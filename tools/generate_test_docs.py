"""
Builds the synthetic test set: 24 FDR PDFs + labels.csv + the mock bank
confirmation records used by the issuer check.

- 10 correct documents, 14 with exactly one planted defect (2 x 7 defect types)
- 4 of the 24 are rasterised with noise and a slight skew, to test scanned input
- 3 different receipt layouts from 3 fictional banks, so the extractor is not
  tuned to one template
- Every page carries "SAMPLE - TEST DATA"; all institutes, banks, IFSC codes and
  FDR numbers are fictional

Run:  python tools/generate_test_docs.py
"""

from __future__ import annotations

import csv
import io
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageFilter
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.render import render_pages  # noqa: E402
OUT = ROOT / "data" / "test_documents"
APPS = {a["app_id"]: a for a in json.loads((ROOT / "data" / "applications.json").read_text())["applications"]}
rng = random.Random(26261)

BANKS = {
    "DNB": {"name": "Deccan National Bank", "ifsc_prefix": "DNBK", "layout": "A"},
    "BUB": {"name": "Bharat Union Bank", "ifsc_prefix": "BUBL", "layout": "B"},
    "KCB": {"name": "Konkan Commercial Bank", "ifsc_prefix": "KONC", "layout": "C"},
    "COOP": {"name": "Shree Sahyadri Sahakari Bank Ltd. (Co-operative)", "ifsc_prefix": "SSSB", "layout": "A"},
    "NBFC": {"name": "Sunrise Finance & Investments Ltd.", "ifsc_prefix": "SFIL", "layout": "B"},
}
BRANCHES = ["Shivajinagar", "Civil Lines", "MG Road", "Station Road", "Main", "Collectorate", "Market Yard"]

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
       "sixteen seventeen eighteen nineteen".split()
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}


def two_digit(n: int) -> str:
    if n < 20:
        return ONES[n]
    return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])


def in_words(amount: int) -> str:
    parts = []
    crore, amount = divmod(amount, 10_000_000)
    lakh, amount = divmod(amount, 100_000)
    thousand, amount = divmod(amount, 1000)
    hundred, rest = divmod(amount, 100)
    if crore: parts.append(two_digit(crore) + " crore")
    if lakh: parts.append(two_digit(lakh) + " lakh")
    if thousand: parts.append(two_digit(thousand) + " thousand")
    if hundred: parts.append(ONES[hundred] + " hundred")
    if rest: parts.append(two_digit(rest))
    return "Rupees " + " ".join(parts).title() + " Only"


def inr(amount: float) -> str:
    s = f"{int(amount)}"
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:]); head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail]) + ".00" if groups else tail + ".00"


def required_amount(app: dict) -> int:
    table = {"Engineering & Technology": (3500000, 2800000)}
    total = 0
    for p in app["programmes"]:
        g, s = table.get(p, (1500000, 1200000))
        total += s if app["special_category"] else g
    return total


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def watermark(c: canvas.Canvas, w: float, h: float):
    c.saveState()
    c.setFillColor(Color(0.85, 0.2, 0.2, alpha=0.18))
    c.setFont("Helvetica-Bold", 54)
    c.translate(w / 2, h / 2)
    c.rotate(32)
    c.drawCentredString(0, 0, "SAMPLE - TEST DATA")
    c.restoreState()
    c.setFont("Helvetica", 7)
    c.setFillColor(Color(0.6, 0.1, 0.1))
    c.drawString(36, 20, "SAMPLE - TEST DATA  |  Synthetic receipt generated for SIH 2026 prototype testing. "
                         "Not a financial instrument. All names are fictional.")
    c.setFillColor(black)


def layout_a(c, d, w, h):
    """Classic single-column receipt."""
    c.setFont("Helvetica-Bold", 17); c.drawString(50, h - 60, d["bank"])
    c.setFont("Helvetica", 9)
    c.drawString(50, h - 76, f"Branch: {d['branch']}")
    c.drawString(330, h - 76, f"IFSC: {d['ifsc']}")
    c.line(50, h - 86, w - 50, h - 86)
    c.setFont("Helvetica-Bold", 13); c.drawCentredString(w / 2, h - 110, "FIXED DEPOSIT RECEIPT")
    c.setFont("Helvetica", 10)
    rows = [
        ("FDR No.", d["fdr_no"]),
        ("Name of Depositor", d["depositor"]),
        ("In favour of", d["beneficiary"]),
        ("Deposit Amount", f"Rs. {inr(d['amount'])}"),
        ("Amount in words", d["words"]),
        ("Date of Deposit", d["issue"].strftime("%d/%m/%Y")),
        ("Period", f"{d['months']} Months"),
        ("Maturity Date", d["maturity"].strftime("%d/%m/%Y")),
        ("Rate of Interest", f"{d['rate']:.2f}% p.a."),
    ]
    y = h - 145
    for k, v in rows:
        c.drawString(60, y, f"{k} : {v}")
        y -= 22
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(60, y - 6, "Not transferable. Premature withdrawal only with written consent of the lien holder.")
    c.setFont("Helvetica", 9)
    c.drawString(w - 200, 90, "Authorised Signatory")
    c.rect(w - 210, 105, 150, 45)


def layout_b(c, d, w, h):
    """Two-column table: label cell and value cell."""
    c.setFillColor(Color(0.12, 0.25, 0.45)); c.rect(0, h - 70, w, 70, fill=1, stroke=0)
    c.setFillColor(Color(1, 1, 1)); c.setFont("Helvetica-Bold", 18); c.drawString(40, h - 45, d["bank"])
    c.setFont("Helvetica", 9); c.drawString(40, h - 60, "Head Office: Synthetic Towers, Example City")
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 12); c.drawString(40, h - 100, "TERM DEPOSIT ADVICE")
    c.setFont("Helvetica", 9); c.drawString(40, h - 115, f"Issuing Branch : {d['branch']}    IFSC Code : {d['ifsc']}")
    rows = [
        ("Receipt No", d["fdr_no"]),
        ("Account Holder", d["depositor"]),
        ("Lien marked in favour of", d["beneficiary"]),
        ("Principal (Rs.)", inr(d["amount"])),
        ("", f"({d['words']})"),
        ("Value Date", d["issue"].strftime("%d-%m-%Y")),
        ("Tenure", f"{d['months'] // 12} Years"),
        ("Due Date", d["maturity"].strftime("%d-%m-%Y")),
        ("Maturity Value (Rs.)", inr(d["amount"] * (1 + d["rate"] / 100) ** (d["months"] / 12))),
    ]
    y = h - 150
    c.setFont("Helvetica", 10)
    for k, v in rows:
        c.setStrokeColor(Color(0.75, 0.75, 0.75))
        c.line(40, y - 6, w - 40, y - 6)
        if k:
            c.setFont("Helvetica-Bold", 10); c.drawString(45, y, k)
        c.setFont("Helvetica", 10); c.drawString(230, y, v)
        y -= 24
    c.setFont("Helvetica", 8)
    c.drawString(45, y - 10, "This advice is computer generated. Original receipt held by the lien holder.")
    c.drawString(w - 190, 80, "For the Bank - Branch Manager")


def layout_c(c, d, w, h):
    """Landscape certificate with two fields per row."""
    c.setStrokeColor(Color(0.4, 0.3, 0.1)); c.setLineWidth(3); c.rect(25, 25, w - 50, h - 50)
    c.setLineWidth(1); c.setStrokeColor(black)
    c.setFont("Times-Bold", 20); c.drawCentredString(w / 2, h - 65, d["bank"].upper())
    c.setFont("Times-Roman", 10); c.drawCentredString(w / 2, h - 80, f"{d['branch']} Branch  |  IFSC {d['ifsc']}")
    c.setFont("Times-Bold", 14); c.drawCentredString(w / 2, h - 105, "Term Deposit Certificate")
    c.setFont("Times-Roman", 11)
    left, right, y = 60, w / 2 + 40, h - 140
    pairs = [
        (f"TD A/c No: {d['fdr_no']}", f"Opened on: {d['issue'].strftime('%d-%b-%Y')}"),
        (f"Depositor: {d['depositor']}", None),
        (f"Favouring: {d['beneficiary']}", None),
        (f"Amount: Rs. {inr(d['amount'])}", f"Matures on: {d['maturity'].strftime('%d-%b-%Y')}"),
        (f"Sum of Rupees: {d['words'].replace('Rupees ', '')}", None),
        (f"Term: {d['months']} months", f"Interest: {d['rate']:.2f}% compounded quarterly"),
    ]
    for l_txt, r_txt in pairs:
        c.drawString(left, y, l_txt)
        if r_txt:
            c.drawString(right, y, r_txt)
        y -= 24
    c.drawString(w - 230, 70, "Manager / Authorised Officer")


def render_pdf(d: dict) -> bytes:
    buf = io.BytesIO()
    layout = BANKS[d["bank_key"]]["layout"]
    size = landscape(A4) if layout == "C" else A4
    c = canvas.Canvas(buf, pagesize=size, invariant=1)
    c.setTitle(f"FDR {d['fdr_no']} (synthetic)")
    c.setAuthor(d["bank"])
    w, h = size
    {"A": layout_a, "B": layout_b, "C": layout_c}[layout](c, d, w, h)
    watermark(c, w, h)
    c.showPage(); c.save()
    return buf.getvalue()


def rasterise(pdf_bytes: bytes, seed: int) -> bytes:
    """Simulate a photocopy scan: 150 dpi, grey, slight skew, blur and speckle."""
    r = random.Random(seed)
    img = render_pages(pdf_bytes, 150, last_page=1)[0].convert("L")
    img = img.rotate(r.uniform(-1.2, 1.2), expand=False, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(img.width * img.height // 220):
        x, y = r.randrange(img.width), r.randrange(img.height)
        px[x, y] = r.choice((0, 90, 200))
    out = io.BytesIO()
    img.save(out, "PDF", resolution=150)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Test set definition
# ---------------------------------------------------------------------------
def base_doc(app_id: str, bank_key: str, n: int, depositor: str = None) -> dict:
    app = APPS[app_id]
    loa = date.fromisoformat(app["loa_date"])
    issue = loa + timedelta(days=rng.randint(3, 7))
    amount = required_amount(app)
    prefix = BANKS[bank_key]["ifsc_prefix"]
    return {
        "app_id": app_id,
        "bank_key": bank_key,
        "bank": BANKS[bank_key]["name"],
        "branch": rng.choice(BRANCHES),
        "ifsc": f"{prefix}0{rng.randint(100000, 999999)}",
        "fdr_no": f"{prefix[:2]}{rng.randint(10, 99)}{2026}{n:04d}{rng.randint(10, 99)}",
        "depositor": depositor or app["institute_name"],
        "beneficiary": rng.choice([
            "Member Secretary, AICTE, New Delhi",
            "Member Secretary, All India Council for Technical Education",
            f"Member Secretary, AICTE jointly with {app['trust']}",
        ]),
        "amount": amount,
        "words": in_words(amount),
        "issue": issue,
        "months": 120,
        "maturity": add_years(issue, 10),
        "rate": rng.choice([6.5, 6.75, 7.0, 7.1]),
        "submitted": issue + timedelta(days=rng.randint(2, 6)),
    }


def build_set():
    docs = []
    n = 0

    def add(doc, defect="none", fail_rules="", scanned=False, note=""):
        nonlocal n
        doc.update(defect=defect, fail_rules=fail_rules, scanned=scanned, note=note)
        docs.append(doc)

    # --- 10 correct documents -------------------------------------------------
    clean_plan = [
        ("1-SYN-2026-0101", "DNB", None, False),
        ("1-SYN-2026-0102", "BUB", "Narmada Education Trust", False),
        ("1-SYN-2026-0103", "KCB", None, True),
        ("1-SYN-2026-0104", "DNB", None, False),
        ("1-SYN-2026-0105", "BUB", None, False),
        ("1-SYN-2026-0106", "KCB", "Brahmaputra Kala Nyas", False),
        ("1-SYN-2026-0107", "DNB", None, True),
        ("1-SYN-2026-0108", "BUB", None, False),
        ("1-SYN-2026-0109", "KCB", "Shivalik College of Engg.", False),
        ("1-SYN-2026-0110", "DNB", None, False),
    ]
    for app_id, bank, dep, scan in clean_plan:
        n += 1
        add(base_doc(app_id, bank, n, dep), scanned=scan)

    # --- D1 wrong beneficiary --------------------------------------------------
    n += 1; d = base_doc("1-SYN-2026-0109", "DNB", n)
    d["beneficiary"] = "The Principal, Shivalik College of Engineering"
    add(d, "wrong_beneficiary", "R1", note="Drawn in favour of the college itself")
    n += 1; d = base_doc("1-SYN-2026-0111", "BUB", n)
    d["beneficiary"] = "Secretary, Aravalli Shiksha Nyas"
    add(d, "wrong_beneficiary", "R1", scanned=True, note="Drawn in favour of the trust secretary")

    # --- D2 ineligible bank ------------------------------------------------------
    n += 1; d = base_doc("1-SYN-2026-0112", "COOP", n)
    add(d, "ineligible_bank", "R2", note="Co-operative bank")
    n += 1; d = base_doc("1-SYN-2026-0107", "NBFC", n)
    add(d, "ineligible_bank", "R2", note="NBFC, not a bank")

    # --- D3 short tenure ---------------------------------------------------------
    n += 1; d = base_doc("1-SYN-2026-0102", "KCB", n)
    d["months"] = 96; d["maturity"] = add_years(d["issue"], 8)
    add(d, "short_tenure", "R3", note="8 years: follows the older instruction, not the 10-year SD period")
    n += 1; d = base_doc("1-SYN-2026-0106", "DNB", n)
    d["months"] = 60; d["maturity"] = add_years(d["issue"], 5)
    add(d, "short_tenure", "R3", note="5 years")

    # --- D4 insufficient amount -------------------------------------------------
    n += 1; d = base_doc("1-SYN-2026-0105", "KCB", n)
    d["amount"] = 3500000; d["words"] = in_words(d["amount"])
    add(d, "short_amount", "R4", note="Two programmes (Engg + Mgmt) need 50 L; FDR covers only Engg (35 L)")
    n += 1; d = base_doc("1-SYN-2026-0104", "BUB", n)
    d["amount"] = 2500000; d["words"] = in_words(d["amount"])
    add(d, "short_amount", "R4", note="Women's college slab is 28 L; FDR is 25 L")

    # --- D5 depositor does not match the applicant ------------------------------
    n += 1; d = base_doc("1-SYN-2026-0108", "DNB", n, depositor="Sai Krupa Hospitality Services Pvt. Ltd.")
    add(d, "name_mismatch", "R5", note="Deposit made by an unrelated company")
    n += 1; d = base_doc("1-SYN-2026-0110", "BUB", n, depositor="Mahanadi Institute of Pharmacy")
    add(d, "name_mismatch", "R5", scanned=True, note="Different institute's name")

    # --- D6 invalid dates ---------------------------------------------------------
    n += 1; d = base_doc("1-SYN-2026-0103", "DNB", n)
    d["issue"] = d["submitted"] + timedelta(days=40); d["maturity"] = add_years(d["issue"], 10)
    add(d, "invalid_dates", "R6", note="Deposit date is after the date of submission (post-dated)")
    n += 1; d = base_doc("1-SYN-2026-0112", "KCB", n)
    d["issue"] = date(2014, 6, 12); d["maturity"] = add_years(d["issue"], 10)
    d["months"] = 120
    add(d, "invalid_dates", "R6", note="Old FDR of 2014 that matured in 2024, re-submitted")

    # --- D7 altered receipt ---------------------------------------------------------
    n += 1; d = base_doc("1-SYN-2026-0101", "BUB", n)
    d["words"] = in_words(2500000)   # figures say 35 L, words still say 25 L
    add(d, "altered", "R8;R9", note="Figures overwritten to 35 L; words still read 25 L; bank record says 25 L")
    n += 1; d = base_doc("1-SYN-2026-0109", "DNB", n)
    d["issuer_override"] = {"amount": 350000.0}
    add(d, "altered", "R9", note="Receipt is internally consistent, but the bank's record shows Rs. 3,50,000")

    return docs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.pdf"):
        old.unlink()
    docs = build_set()
    order = list(range(len(docs)))
    rng.shuffle(order)          # file numbers do not reveal which are defective

    labels, confirmations, specs = [], {}, {}
    for file_no, idx in enumerate(order, start=1):
        d = docs[idx]
        doc_id = f"FDR-T{file_no:02d}"
        pdf = render_pdf(d)
        if d["scanned"]:
            pdf = rasterise(pdf, seed=file_no)
        fname = f"{doc_id}.pdf"
        (OUT / fname).write_bytes(pdf)

        specs[doc_id] = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}
        expected = "PASS" if d["defect"] == "none" else "FAIL"
        labels.append({
            "doc_id": doc_id, "file": fname, "app_id": d["app_id"], "scanned": int(d["scanned"]),
            "layout": BANKS[d["bank_key"]]["layout"], "defect_type": d["defect"],
            "expected_fail_rules": d["fail_rules"], "expected_overall": expected,
            "submitted_on": d["submitted"].isoformat(), "note": d["note"],
            "true_fdr_no": d["fdr_no"], "true_amount": d["amount"],
            "true_issue": d["issue"].isoformat(), "true_maturity": d["maturity"].isoformat(),
            "true_depositor": d["depositor"],
        })
        # Mock bank records: only banks "connected" to the verification service
        if d["bank_key"] in ("DNB", "BUB", "KCB"):
            rec = {"bank": d["bank"], "amount": float(d["amount"]),
                   "issue_date": d["issue"].isoformat(), "maturity_date": d["maturity"].isoformat(),
                   "depositor_name": d["depositor"], "lien": "Member Secretary, AICTE"
                   if "Member Secretary" in d["beneficiary"] else d["beneficiary"]}
            if d["defect"] == "altered" and d["fail_rules"].startswith("R8"):
                rec["amount"] = 2500000.0          # bank knows the true (unaltered) amount
            rec.update(d.get("issuer_override", {}))
            confirmations[d["fdr_no"]] = rec

    with open(ROOT / "data" / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(labels[0].keys()))
        w.writeheader(); w.writerows(labels)

    (ROOT / "data" / "bank_confirmations.json").write_text(json.dumps({
        "_note": "SYNTHETIC records standing in for a bank FDR-confirmation service. "
                 "Only Deccan National, Bharat Union and Konkan Commercial are 'connected'.",
        "connected_banks": ["Deccan National Bank", "Bharat Union Bank", "Konkan Commercial Bank"],
        "records": confirmations,
    }, indent=2))
    (OUT / "specs.json").write_text(json.dumps(specs, indent=1))   # used by the "try to fool it" screen
    print(f"wrote {len(labels)} documents to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
