"""
Synthetic Fire NOCs for the second rule pack: 4 correct, 4 with one defect
(expired, wrong institute, wrong premises, not a fire authority). Every page is
marked SAMPLE - TEST DATA; all offices and names are fictional.

    python tools/generate_noc_docs.py
"""
import csv
import io
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.generate_test_docs import watermark  # noqa: E402

OUT = ROOT / "data" / "fire_noc"
APPS = {a["app_id"]: a for a in json.loads((ROOT / "data" / "applications.json").read_text())["applications"]}
rng = random.Random(2611)


def draw(d) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    w, h = A4
    c.setFont("Times-Bold", 15)
    c.drawCentredString(w / 2, h - 60, d["office1"])
    c.setFont("Times-Roman", 11)
    c.drawCentredString(w / 2, h - 78, d["office2"])
    c.line(50, h - 90, w - 50, h - 90)
    c.setFont("Times-Bold", 14)
    c.drawCentredString(w / 2, h - 120, "FIRE SAFETY NO OBJECTION CERTIFICATE")
    c.setFont("Times-Roman", 11)
    rows = [("NOC No.", d["noc_no"]), ("Date of Issue", d["issue"].strftime("%d/%m/%Y")),
            ("Issued to", d["inst"]), ("Premises", d["addr"]),
            ("Buildings covered", "Academic Block A, Academic Block B, Workshop, Library"),
            ("Valid up to", d["until"].strftime("%d/%m/%Y"))]
    y = h - 160
    for k, v in rows:
        c.drawString(70, y, f"{k} : {v}")
        y -= 24
    c.drawString(70, y - 10, "The premises were inspected and fire safety arrangements were found satisfactory")
    c.drawString(70, y - 26, "under the applicable fire prevention rules, subject to annual renewal.")
    c.drawString(w - 230, 130, d["signatory"])
    watermark(c, w, h)
    c.showPage(); c.save()
    return buf.getvalue()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = [("1-SYN-2026-0101", "none"), ("1-SYN-2026-0103", "none"), ("1-SYN-2026-0106", "none"), ("1-SYN-2026-0110", "none"),
            ("1-SYN-2026-0102", "expired"), ("1-SYN-2026-0105", "wrong_institute"),
            ("1-SYN-2026-0108", "wrong_premises"), ("1-SYN-2026-0111", "not_fire_authority")]
    rows = []
    for i, (app_id, defect) in enumerate(plan, 1):
        a = APPS[app_id]
        city = a["address"].split(",")[-1].strip().rsplit(" ", 1)[0]
        sub = date.fromisoformat(a["loa_date"]) + timedelta(days=10)
        issue = sub - timedelta(days=rng.randint(30, 200))
        d = {"office1": f"OFFICE OF THE CHIEF FIRE OFFICER, {city.upper()}",
             "office2": f"{city} Fire and Emergency Services (synthetic)", "noc_no": f"FNOC/{issue.year}/{rng.randint(1000, 9999)}",
             "issue": issue, "until": issue + timedelta(days=365), "inst": a["institute_name"], "addr": a["address"],
             "signatory": "Chief Fire Officer"}
        fail = ""
        if defect == "expired":
            d["issue"] = sub - timedelta(days=430); d["until"] = d["issue"] + timedelta(days=365); fail = "N2"
        elif defect == "wrong_institute":
            d["inst"] = "Vindhyachal Polytechnic College"; fail = "N3"
        elif defect == "wrong_premises":
            d["addr"] = "MIDC Area, Aurangabad 431001"; fail = "N4"
        elif defect == "not_fire_authority":
            d["office1"] = "OFFICE OF THE GRAM PANCHAYAT, SITAPURA"; d["office2"] = "Village Administration (synthetic)"
            d["signatory"] = "Sarpanch"; fail = "N1"
        doc_id = f"NOC-T{i:02d}"
        (OUT / f"{doc_id}.pdf").write_bytes(draw(d))
        rows.append({"doc_id": doc_id, "file": f"{doc_id}.pdf", "app_id": app_id, "defect_type": defect,
                     "expected_fail_rules": fail, "expected_overall": "PASS" if defect == "none" else "FAIL",
                     "submitted_on": sub.isoformat()})
    with open(OUT / "labels.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    print(f"wrote {len(rows)} Fire NOCs")


if __name__ == "__main__":
    main()
