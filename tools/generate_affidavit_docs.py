"""
Synthetic trust affidavits for the third rule pack: 5 correct (one of them a scan),
5 with one defect each. Every page is marked SAMPLE - TEST DATA; all people,
trusts and notaries are fictional.

    python tools/generate_affidavit_docs.py
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
from tools.generate_test_docs import rasterise, watermark  # noqa: E402

OUT = ROOT / "data" / "affidavits"
APPS = {a["app_id"]: a for a in json.loads((ROOT / "data" / "applications.json").read_text())["applications"]}
rng = random.Random(2612)
STATES = {"Maharashtra": "Government of Maharashtra", "Gujarat": "Government of Gujarat", "Telangana": "Government of Telangana",
          "Karnataka": "Government of Karnataka", "Madhya Pradesh": "Government of Madhya Pradesh", "Assam": "Government of Assam",
          "Punjab": "Government of Punjab", "Odisha": "Government of Odisha", "Rajasthan": "Government of Rajasthan",
          "Himachal Pradesh": "Government of Himachal Pradesh"}
NAMES = ["Ramesh Vasant Kulkarni", "Hemlata Joshi", "Prakash Rao Deshmukh", "Anita Sharma", "Gurpreet Singh Brar",
         "Bijoy Kumar Das", "Sunita Mohanty", "Mahesh Chandra Purohit", "Kavita Nair", "Arvind Patil"]
WORDS = {100: "ONE HUNDRED RUPEES", 20: "TWENTY RUPEES", 500: "FIVE HUNDRED RUPEES"}


def wrap(c, text, x, y, width, size=11, leading=15):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    line = ""
    for w in text.split():
        if stringWidth(line + " " + w, "Times-Roman", size) > width:
            c.drawString(x, y, line.strip()); y -= leading; line = w
        else:
            line += " " + w
    c.drawString(x, y, line.strip())
    return y - leading


def draw(d) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    w, h = A4
    # stamp paper band
    c.setFillColor(Color(0.93, 0.89, 0.80)); c.rect(40, h - 150, w - 80, 110, fill=1, stroke=0)
    c.setFillColor(black); c.setStrokeColor(Color(0.45, 0.32, 0.18)); c.rect(40, h - 150, w - 80, 110, fill=0)
    if d["stamp"]:
        c.setFont("Helvetica-Bold", 16); c.drawCentredString(w / 2, h - 68, "INDIA NON JUDICIAL")
        c.setFont("Helvetica", 11); c.drawCentredString(w / 2, h - 86, d["govt"] + " (synthetic)")
        c.setFont("Helvetica-Bold", 22); c.drawCentredString(w / 2, h - 114, f"Rs. {d['stamp']}")
        c.setFont("Helvetica", 9); c.drawCentredString(w / 2, h - 132, f"{WORDS[d['stamp']]}   Serial No. {d['serial']}")
    else:
        c.setFont("Helvetica", 11); c.drawCentredString(w / 2, h - 100, "(plain paper)")
    c.setFont("Times-Bold", 15); c.drawCentredString(w / 2, h - 182, "AFFIDAVIT")
    c.setFont("Times-Roman", 11)
    y = h - 210
    y = wrap(c, f"I, {d['title']} {d['name']}, aged {d['age']} years, {d['desig']} of {d['trust']}, {d['city']}, the "
                f"Trust / Society running {d['inst']}, do hereby solemnly affirm and state on oath as under:", 60, y, w - 120)
    y -= 6
    for i, p in enumerate(d["paras"], 1):
        y = wrap(c, f"{i}. {p}", 70, y, w - 140) - 4
    c.setFont("Times-Bold", 11); c.drawString(w - 170, y - 20, "DEPONENT"); c.setFont("Times-Roman", 11)
    y -= 60
    c.setFont("Times-Bold", 11); c.drawString(60, y, "VERIFICATION"); c.setFont("Times-Roman", 11)
    y = wrap(c, f"Verified at {d['city']} on {d['date']:%d/%m/%Y} that the contents of the above paragraphs are true "
                "to my knowledge and nothing material has been concealed.", 60, y - 18, w - 120)
    c.setFont("Times-Bold", 11); c.drawString(w - 170, y - 14, "DEPONENT"); c.setFont("Times-Roman", 11)
    if d["notary"]:
        c.setStrokeColor(Color(0.15, 0.25, 0.6)); c.setFillColor(Color(0.15, 0.25, 0.6))
        c.circle(150, 150, 52); c.circle(150, 150, 40)
        c.setFont("Helvetica-Bold", 8); c.drawCentredString(150, 160, "NOTARY PUBLIC"); c.drawCentredString(150, 148, d["city"].upper())
        c.drawCentredString(150, 136, "(synthetic)")
        c.setFont("Times-Roman", 10)
        c.drawString(220, 160, "Sworn before me")
        c.drawString(220, 146, f"Notary Public, {d['city']}, Reg. No. {d['notary']}")
        c.setFillColor(black)
    watermark(c, w, h)
    c.showPage(); c.save()
    return buf.getvalue()


PARAS = [
    "That the information furnished in the online application to AICTE for the academic year 2026-27 and in the documents "
    "uploaded with it is true and correct to the best of my knowledge and belief.",
    "That the Institute shall abide by the norms, regulations and guidelines of AICTE issued from time to time.",
    "That if any information furnished is found to be false at any stage, the Trust / Society and the Institute shall be "
    "liable for action under the AICTE regulations, including withdrawal of approval.",
    "That the land and buildings on which the Institute runs are owned by / leased to the Trust / Society, and the documents "
    "submitted for them are genuine.",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = [("1-SYN-2026-0101", "none"), ("1-SYN-2026-0103", "none"), ("1-SYN-2026-0106", "none"),
            ("1-SYN-2026-0110", "none"), ("1-SYN-2026-0102", "none_scan"),
            ("1-SYN-2026-0105", "low_stamp"), ("1-SYN-2026-0107", "no_notary"), ("1-SYN-2026-0108", "wrong_deponent"),
            ("1-SYN-2026-0111", "old_date"), ("1-SYN-2026-0109", "missing_undertaking")]
    rows = []
    for i, (app_id, defect) in enumerate(plan, 1):
        a = APPS[app_id]
        city = a["address"].split(",")[-1].strip().rsplit(" ", 1)[0]
        sub = date.fromisoformat(a["loa_date"]) + timedelta(days=10)
        d = {"stamp": 100, "govt": STATES.get(a["state"], "State Government"), "serial": f"{rng.choice('ABCDEFGH')}{rng.randint(100000, 999999)}",
             "title": "Shri", "name": NAMES[i - 1], "age": rng.randint(45, 70), "desig": rng.choice(["Chairman", "Secretary", "President"]),
             "trust": a["trust"], "city": city, "inst": a["institute_name"], "paras": list(PARAS),
             "date": sub - timedelta(days=rng.randint(5, 40)), "notary": f"{rng.randint(100, 9999)}/{rng.randint(2012, 2024)}"}
        if d["name"] in ("Hemlata Joshi", "Anita Sharma", "Sunita Mohanty", "Kavita Nair"):
            d["title"] = "Smt."
        fail = ""
        if defect == "low_stamp":
            d["stamp"] = 20; fail = "F1"
        elif defect == "no_notary":
            d["notary"] = None; fail = "F2"
        elif defect == "wrong_deponent":
            d["desig"] = "Principal"; fail = "F3"
        elif defect == "old_date":
            d["date"] = sub - timedelta(days=400); fail = "F5"
        elif defect == "missing_undertaking":
            d["paras"] = [PARAS[0], PARAS[1], PARAS[3]]; fail = "F6"
        doc_id = f"AFF-T{i:02d}"
        pdf = draw(d)
        if defect == "none_scan":
            pdf = rasterise(pdf, seed=900 + i)
        (OUT / f"{doc_id}.pdf").write_bytes(pdf)
        rows.append({"doc_id": doc_id, "file": f"{doc_id}.pdf", "app_id": app_id, "defect_type": defect,
                     "expected_fail_rules": fail, "expected_overall": "FAIL" if fail else "PASS",
                     "submitted_on": sub.isoformat(), "scanned": defect == "none_scan"})
    with open(OUT / "labels.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    print(f"wrote {len(rows)} affidavits")


if __name__ == "__main__":
    main()
