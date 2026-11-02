"""
Tests for the third round: affidavit rule pack, infrastructure photo check,
whole-application review (missing documents, cross-document checks, one letter),
dashboard, time study, photo API and the redaction tool.

    pytest -q
"""
import csv
import io
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pipeline import load_applications, run_check   # noqa: E402
from src.photos import PhotoStore, check_photo, read_photo   # noqa: E402

APPS = load_applications()
AFF, PH, NOC = ROOT / "data" / "affidavits", ROOT / "data" / "photos", ROOT / "data" / "fire_noc"


def labels(path, key="doc_id"):
    return {l[key]: l for l in csv.DictReader(open(path))} if path.exists() else {}


# --- affidavit pack ---------------------------------------------------------------------
@pytest.mark.parametrize("doc_id", sorted(labels(AFF / "labels.csv")))
def test_affidavit_pack(doc_id):
    lab = labels(AFF / "labels.csv")[doc_id]
    out = run_check((AFF / lab["file"]).read_bytes(), APPS[lab["app_id"]],
                    submitted_on=date.fromisoformat(lab["submitted_on"]))
    st = {r["rule_id"]: r["status"] for r in out["results"]}
    assert out["doc_type"]["type"] == "affidavit"
    for rid in filter(None, lab["expected_fail_rules"].split(";")):
        assert st[rid] == "FAIL", (doc_id, st)
    assert out["overall"] == lab["expected_overall"], (doc_id, st)


def test_missing_text_on_a_scan_goes_to_officer_not_fail():
    from src.pipeline import _scan_absence_safety
    r = [{"rule_id": "F2", "status": "FAIL", "evidence": "No Notary / Magistrate attestation found.", "reasoning": "x",
          "ps_status": "Deficiency"}]
    _scan_absence_safety(r)
    assert r[0]["status"] == "UNCERTAIN"


# --- photos -----------------------------------------------------------------------------
def run_photo_set():
    store, out = PhotoStore(None), {}
    for lab in csv.DictReader(open(PH / "labels.csv")):
        data = (PH / lab["file"]).read_bytes()
        res = check_photo(data, APPS[lab["app_id"]], lab["room"], submitted_on=date.fromisoformat(lab["submitted_on"]),
                          store=store, photo_id=lab["photo_id"])
        store.add({"id": lab["photo_id"], "app_id": lab["app_id"], "room": lab["room"], "meta": res["meta"],
                   "results": res["results"], "overall": res["overall"], "image": data, "submitted_on": lab["submitted_on"]})
        out[lab["photo_id"]] = (lab, res)
    return out


@pytest.mark.skipif(not (PH / "labels.csv").exists(), reason="run tools/generate_photos.py")
def test_photo_set_matches_labels():
    for pid, (lab, res) in run_photo_set().items():
        st = {r["rule_id"]: r["status"] for r in res["results"]}
        assert res["overall"] == lab["expected_overall"], (pid, st)
        for rid in filter(None, lab["expected_fail_rules"].split(";")):
            assert st[rid] == "FAIL"
        for rid in filter(None, lab["expected_review_rules"].split(";")):
            assert st[rid] == "UNCERTAIN"


@pytest.mark.skipif(not (PH / "labels.csv").exists(), reason="run tools/generate_photos.py")
def test_reused_photo_caught_even_after_resize_and_recompress():
    from PIL import Image
    store = PhotoStore(None)
    a = APPS["1-SYN-2026-0101"]
    data = (PH / "PH-01.jpg").read_bytes()
    res = check_photo(data, a, "Classroom", submitted_on=date(2026, 5, 2), store=store, photo_id="X1")
    store.add({"id": "X1", "app_id": a["app_id"], "room": "Classroom", "meta": res["meta"], "results": res["results"],
               "overall": res["overall"], "image": data, "submitted_on": "2026-05-02"})
    b = io.BytesIO()
    Image.open(io.BytesIO(data)).resize((640, 427)).save(b, "JPEG", quality=60)
    res2 = check_photo(b.getvalue(), APPS["1-SYN-2026-0105"], "Classroom", submitted_on=date(2026, 5, 2), store=store)
    assert {r["rule_id"]: r["status"] for r in res2["results"]}["P3"] == "FAIL"


def test_gps_and_date_are_read_from_exif():
    m = read_photo((PH / "PH-01.jpg").read_bytes())
    assert m["taken"] and abs(m["lat"] - APPS["1-SYN-2026-0101"]["campus_lat"]) < 0.01


# --- whole application ------------------------------------------------------------------
def _case(path, app_id, sub):
    out = run_check(Path(path).read_bytes(), APPS[app_id], submitted_on=date.fromisoformat(sub))
    return {"id": Path(path).stem, "received": date.fromisoformat(sub), "decision": None, **out}


def test_application_reports_missing_documents():
    from src.application import review_application
    rv = review_application(APPS["1-SYN-2026-0104"], [], [])
    assert rv["status"] == "INCOMPLETE" and {d["id"] for d in rv["missing"]} == {"fdr", "fire_noc", "affidavit", "photos"}


def test_government_institute_needs_no_security_deposit():
    from src.application import review_application
    rv = review_application(APPS["1-SYN-2026-0113"], [], [])
    assert "fdr" not in {d["id"] for d in rv["missing"]}


def test_wrong_premises_noc_breaks_cross_document_check():
    from src.application import review_application
    lab = labels(NOC / "labels.csv")["NOC-T07"]          # wrong premises
    assert lab["defect_type"] == "wrong_premises"
    rv = review_application(APPS[lab["app_id"]], [_case(NOC / lab["file"], lab["app_id"], lab["submitted_on"])], [])
    assert {x["rule_id"]: x["status"] for x in rv["consistency"]}["X2"] == "FAIL"


def test_one_letter_lists_missing_documents_and_deficiencies():
    from src.application import application_letter, review_application
    lab = labels(AFF / "labels.csv")["AFF-T06"]          # low stamp
    a = APPS[lab["app_id"]]
    rv = review_application(a, [_case(AFF / lab["file"], lab["app_id"], lab["submitted_on"])], [])
    text = application_letter(a, rv, [])
    assert "Fire Safety NOC not submitted" in text and "F1" in text and "Stamp paper" in text


# --- web screens ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from app.app import app
    c = app.test_client()
    c.post("/login", data={"username": "officer", "password": "officer123"})
    return c


def test_dashboard_application_and_study_pages(client):
    for url in ("/dashboard", "/application/1-SYN-2026-0101", "/application/1-SYN-2026-0101/letter", "/study"):
        assert client.get(url).status_code == 200, url
    assert b"Alerts" in client.get("/dashboard").data


def test_time_study_records_time_and_marks(client):
    from app.app import STUDY_DB
    before = STUDY_DB.execute("SELECT COUNT(*) FROM study").fetchone()[0]
    assert client.get("/study/next?mode=manual").status_code == 200
    assert client.post("/study/submit", data={"rule": ["R4"]}).status_code == 302
    assert STUDY_DB.execute("SELECT COUNT(*) FROM study").fetchone()[0] == before + 1
    STUDY_DB.execute("DELETE FROM study WHERE id = (SELECT MAX(id) FROM study)"); STUDY_DB.commit()


def test_photo_api(client):
    from app.app import API_TOKEN, PHOTOS
    r = client.post("/api/v1/photo", headers={"Authorization": f"Bearer {API_TOKEN}"},
                    data={"app_id": "1-SYN-2026-0105", "room": "Library", "received": "2026-05-05",
                          "photo": (io.BytesIO((PH / "PH-03.jpg").read_bytes()), "lib.jpg")},
                    content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200 and {f["rule_id"]: f["status"] for f in j["findings"]}["P3"] == "FAIL"
    PHOTOS.conn.execute("DELETE FROM photos WHERE id=?", (j["photo_id"],)); PHOTOS.conn.commit()


# --- redaction --------------------------------------------------------------------------
def test_redaction_removes_fdr_number_but_keeps_the_rest_readable():
    from src.render import ocr_status
    if not ocr_status()["available"]:
        pytest.skip("needs Tesseract")
    from src.extractor import extract_document
    from tools.redact import redact
    e = extract_document(redact((ROOT / "data" / "test_documents" / "FDR-T08.pdf").read_bytes()))
    assert e["fields"]["fdr_number"] is None and e["fields"]["amount"]
