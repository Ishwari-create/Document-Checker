"""
Tests for the second round of features: document type check, Fire NOC rule pack,
authenticity checks, ML field extractor, email letters, live inbox, case storage,
OCR status and the production start-up guard.

    pytest -q
"""
import csv
import email
import io
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pipeline import load_applications, run_check      # noqa: E402
from src.registry import CaseStore, IssuerConnector, Ledger  # noqa: E402

APPS = load_applications()
DOCS = ROOT / "data" / "test_documents"
need_docs = pytest.mark.skipif(not (ROOT / "data" / "labels.csv").exists(), reason="generate test docs first")


def labels(path):
    return {l["doc_id"]: l for l in csv.DictReader(open(path))}


def check(doc_id, base=DOCS, label_file=ROOT / "data" / "labels.csv", issuer=None, **kw):
    lab = labels(label_file)[doc_id]
    out = run_check((base / lab["file"]).read_bytes(), APPS[lab["app_id"]],
                    submitted_on=date.fromisoformat(lab["submitted_on"]),
                    issuer=issuer or IssuerConnector(), ledger=Ledger(db_path=None), **kw)
    return out, {r["rule_id"]: r["status"] for r in out["results"]}


def minutes_pdf() -> bytes:
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b)
    c.drawString(72, 720, "Minutes of the governing body meeting held on 12 May 2026")
    c.drawString(72, 700, "Agenda: annual budget, library books, sports day.")
    c.save()
    return b.getvalue()


# --- document type -----------------------------------------------------------------------
@need_docs
def test_fdr_is_recognised_before_rules_run():
    out, st = check("FDR-T08")
    assert out["doc_type"]["type"] == "fdr" and st["D0"] == "PASS"


def test_other_document_is_rejected_with_one_clear_finding():
    out = run_check(minutes_pdf(), APPS["1-SYN-2026-0101"], submitted_on=date(2026, 5, 1))
    assert [r["rule_id"] for r in out["results"]] == ["D0"]
    assert out["results"][0]["status"] == "FAIL" and out["overall"] == "FAIL"


@need_docs
def test_wrong_document_in_a_slot_is_flagged():
    _, st = check("FDR-T08", expect="fire_noc")
    assert st["D0"] == "FAIL"


# --- Fire NOC pack -----------------------------------------------------------------------
NOC = ROOT / "data" / "fire_noc"


@pytest.mark.skipif(not (NOC / "labels.csv").exists(), reason="run tools/generate_noc_docs.py")
@pytest.mark.parametrize("doc_id", sorted(labels(NOC / "labels.csv")) if (NOC / "labels.csv").exists() else [])
def test_fire_noc_pack(doc_id):
    lab = labels(NOC / "labels.csv")[doc_id]
    out, st = check(doc_id, base=NOC, label_file=NOC / "labels.csv")
    assert out["doc_type"]["type"] == "fire_noc"
    for rid in filter(None, lab["expected_fail_rules"].split(";")):
        assert st[rid] == "FAIL", (doc_id, rid, st)
    if lab["expected_overall"] == "PASS":
        assert out["overall"] == "PASS", st


# --- authenticity ------------------------------------------------------------------------
@need_docs
def test_pdf_edited_after_issue_is_caught():
    _, st = check("FDR-T25")
    assert st["A1"] == "FAIL"          # incremental save by a PDF editor
    assert st["A2"] == "FAIL"          # new figures in a font used nowhere else / printed over old text
    assert st["A3"] == "FAIL"          # bank's QR still has the true amount


@need_docs
def test_pasted_patch_in_scan_is_caught():
    _, st = check("FDR-T26")
    assert st["A4"] == "FAIL"


@need_docs
def test_clean_receipt_passes_authenticity():
    _, st = check("FDR-T08")
    assert st["A1"] == "PASS" and st["A2"] == "PASS" and st["A3"] in ("PASS", "NA") and st["A4"] == "NA"


# --- ML extractor ------------------------------------------------------------------------
H2 = ROOT / "data" / "holdout2"


@pytest.mark.skipif(not (ROOT / "models" / "field_model.joblib").exists() or not (H2 / "labels.csv").exists(),
                    reason="train the model and generate the held-out set first")
def test_ml_fills_fields_the_label_matcher_misses():
    lab = labels(H2 / "labels.csv")["FDR-J01"]
    issuer = IssuerConnector(H2 / "bank_confirmations.json")
    off, _ = check("FDR-J01", base=H2, label_file=H2 / "labels.csv", issuer=issuer, use_ml=False)
    on, _ = check("FDR-J01", base=H2, label_file=H2 / "labels.csv", issuer=issuer, use_ml=True)
    assert off["extraction"]["fields"]["depositor_name"] is None
    assert on["extraction"]["fields"]["depositor_name"] == lab["true_depositor"]
    assert on["extraction"]["fields"]["maturity_date"] == lab["true_maturity"]
    assert "depositor_name" in on["extraction"]["fields"]["_ml_filled"]


# --- email -------------------------------------------------------------------------------
def test_letter_saved_to_outbox_without_smtp(tmp_path, monkeypatch):
    from src import mailer
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path)
    res = mailer.send_letter("principal@x.example.in", "Deficiency", "body", b"%PDF-1.4 test", "letter.pdf")
    assert res["status"] == "saved"
    msg = email.message_from_bytes(Path(res["where"]).read_bytes())
    assert msg["To"] == "principal@x.example.in"
    assert [p.get_filename() for p in msg.walk() if p.get_filename()] == ["letter.pdf"]


def test_letter_sent_through_smtp_when_configured(monkeypatch):
    from src import mailer
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.append((host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): pass
        def login(self, u, p): pass
        def send_message(self, msg): sent.append(msg["To"])

    monkeypatch.setenv("SMTP_HOST", "smtp.example.in")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    res = mailer.send_letter("principal@x.example.in", "Deficiency", "body", b"%PDF", "letter.pdf")
    assert res["status"] == "sent" and sent == [("smtp.example.in", 587), "principal@x.example.in"]


# --- live inbox --------------------------------------------------------------------------
def test_inbox_checks_a_dropped_file(tmp_path):
    from src.inbox import InboxWatcher
    seen = []
    w = InboxWatcher(tmp_path, lambda p, data, sub: seen.append((p.name, sub, len(data))) or {"case": "X"})
    w.start()
    (tmp_path / "1-SYN-2026-0101").mkdir()
    (tmp_path / "1-SYN-2026-0101" / "receipt.pdf").write_bytes(minutes_pdf())
    for _ in range(30):
        if w.recent():
            break
        time.sleep(0.2)
    assert seen and seen[0][:2] == ("receipt.pdf", "1-SYN-2026-0101")
    assert w.recent()[0]["file"] == "receipt.pdf"


# --- case storage ------------------------------------------------------------------------
def test_cases_survive_a_restart(tmp_path):
    db = tmp_path / "cases.sqlite3"
    a = CaseStore(db)
    a["C1"] = {"origin": "upload", "app": {"app_id": "A"}, "received": date(2026, 5, 1), "pdf": b"%PDF",
               "overall": "FAIL", "results": [{"rule_id": "R4", "status": "FAIL"}]}
    b = CaseStore(db)
    case = b["C1"]
    assert case["overall"] == "FAIL" and case["pdf"] == b"%PDF" and case["received"] == date(2026, 5, 1)


# --- OCR status and production guard --------------------------------------------------------
def test_ocr_missing_is_reported(monkeypatch):
    import pytesseract
    from src import render
    render.ocr_status.cache_clear()
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: (_ for _ in ()).throw(OSError("not found")))
    st = render.ocr_status()
    render.ocr_status.cache_clear()
    assert st["available"] is False and "not installed" in st["message"]


def test_production_refuses_default_secrets():
    env = {**os.environ, "APP_ENV": "production"}
    env.pop("SECRET_KEY", None)
    env.pop("API_TOKEN", None)
    p = subprocess.run([sys.executable, "-c", "import app.app"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert p.returncode != 0 and "Refusing to start" in (p.stderr + p.stdout)
