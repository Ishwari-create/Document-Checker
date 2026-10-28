"""
Held-out set: 8 receipts in a fourth layout ("Malabar Rural Bank" style) that
was written AFTER the extractor and rules were frozen, with label wording the
extractor has never seen. Nothing in src/ was tuned on these files.

    python tools/generate_holdout.py && python tools/evaluate.py --holdout
"""
import csv, io, json, random, sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.generate_test_docs import APPS, add_years, in_words, inr, rasterise, required_amount, watermark  # noqa

SECOND = "--set2" in sys.argv
# Set 1 was made once, scored once, and then used to improve the extractor, so it is no longer unseen.
# Set 2 was created after that change and is scored once without any further tuning.
OUT = ROOT / "data" / ("holdout2" if SECOND else "holdout")
rng = random.Random(77 if SECOND else 7)
BANK = "Ganga Valley Bank" if SECOND else "Malabar Coast Bank"   # fictional, listed as demo banks


def draw(d):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    w, h = A4
    c.setFont("Courier-Bold", 15); c.drawString(48, h - 58, BANK + " Limited")
    c.setFont("Courier", 9); c.drawString(48, h - 72, f"{d['branch']} Br. / IFS Code {d['ifsc']}")
    c.setFont("Courier-Bold", 12); c.drawString(48, h - 104, "DEPOSIT RECEIPT (NON-NEGOTIABLE)")
    c.setFont("Courier", 10)
    y = h - 135
    rows = [("Deposit Receipt Number", d["fdr_no"]),
                 ("Name(s) of Depositor(s)", d["depositor"]),
                 ("Payable to", d["beneficiary"]),
                 ("Principal Amount INR", inr(d["amount"])),
                 ("Rupees", d["words"].replace("Rupees ", "")),
                 ("Date of Commencement", d["issue"].strftime("%d.%m.%Y")),
                 ("Date of Maturity", d["maturity"].strftime("%d.%m.%Y")),
                 ("Tenor", f"{d['months'] // 12} years")]
    if SECOND:
        rows = [("STDR No", d["fdr_no"]), ("Name", d["depositor"]), ("Joint Holder / Lien", d["beneficiary"]),
                ("Amount Deposited", "Rs " + inr(d["amount"]) + "/-"), ("In Words", d["words"]),
                ("Deposit Date", d["issue"].strftime("%d %b %Y")), ("Maturity On", d["maturity"].strftime("%d %b %Y")),
                ("Period", f"{d['months']} months")]
        c.setFont("Helvetica", 10)
    for k, v in rows:
        c.drawString(48, y, f"{k:<24}: {v}" if not SECOND else f"{k} - {v}")
        y -= 20
    c.drawString(w - 220, 120, "Branch Manager")
    watermark(c, w, h)
    c.showPage(); c.save()
    return buf.getvalue()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = [("1-SYN-2026-0103", "none", False), ("1-SYN-2026-0105", "none", True), ("1-SYN-2026-0106", "none", False),
            ("1-SYN-2026-0109", "none", False), ("1-SYN-2026-0110", "short_tenure", False),
            ("1-SYN-2026-0101", "wrong_beneficiary", True), ("1-SYN-2026-0111", "short_amount", False),
            ("1-SYN-2026-0104", "name_mismatch", False)] if SECOND else [("1-SYN-2026-0101", "none", False), ("1-SYN-2026-0104", "none", False), ("1-SYN-2026-0107", "none", True),
            ("1-SYN-2026-0111", "none", False), ("1-SYN-2026-0102", "short_tenure", False),
            ("1-SYN-2026-0108", "wrong_beneficiary", False), ("1-SYN-2026-0110", "short_amount", True),
            ("1-SYN-2026-0112", "name_mismatch", False)]
    rows, recs = [], {}
    for i, (app_id, defect, scan) in enumerate(plan, 1):
        a = APPS[app_id]
        loa = date.fromisoformat(a["loa_date"])
        issue = loa + timedelta(days=rng.randint(3, 7))
        d = {"app_id": app_id, "branch": rng.choice(["Patna", "Varanasi", "Haridwar"] if SECOND else ["Kochi", "Kozhikode", "Thrissur"]),
             "ifsc": f"{'GVBK' if SECOND else 'MLCB'}0{rng.randint(100000, 999999)}", "fdr_no": f"{rng.randint(10**11, 10**12 - 1)}",
             "depositor": a["institute_name"], "beneficiary": "Member Secretary, AICTE",
             "amount": required_amount(a), "issue": issue, "months": 120, "maturity": add_years(issue, 10),
             "submitted": issue + timedelta(days=3)}
        fail = ""
        if defect == "short_tenure":
            d["months"], d["maturity"], fail = 84, add_years(issue, 7), "R3"
        if defect == "wrong_beneficiary":
            d["beneficiary"], fail = "Chairman, " + a["trust"], "R1"
        if defect == "short_amount":
            d["amount"], fail = d["amount"] - 300000, "R4"
        if defect == "name_mismatch":
            d["depositor"], fail = "Konark Agro Industries", "R5"
        d["words"] = in_words(d["amount"])
        pdf = draw(d)
        if scan:
            pdf = rasterise(pdf, seed=100 + i)
        doc_id = f"FDR-{'J' if SECOND else 'H'}{i:02d}"
        (OUT / f"{doc_id}.pdf").write_bytes(pdf)
        rows.append({"doc_id": doc_id, "file": f"{doc_id}.pdf", "app_id": app_id, "scanned": int(scan), "layout": "H",
                     "defect_type": defect, "expected_fail_rules": fail,
                     "expected_overall": "PASS" if defect == "none" else "FAIL",
                     "submitted_on": d["submitted"].isoformat(), "note": "held-out layout",
                     "true_fdr_no": d["fdr_no"], "true_amount": d["amount"], "true_issue": d["issue"].isoformat(),
                     "true_maturity": d["maturity"].isoformat(), "true_depositor": d["depositor"]})
        recs[d["fdr_no"]] = {"bank": BANK, "amount": float(d["amount"]), "issue_date": d["issue"].isoformat(),
                             "maturity_date": d["maturity"].isoformat(), "depositor_name": d["depositor"]}
    with open(OUT / "labels.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    (OUT / "bank_confirmations.json").write_text(json.dumps(
        {"connected_banks": [BANK], "records": recs}, indent=1))
    print(f"wrote {len(rows)} held-out documents")


if __name__ == "__main__":
    main()
