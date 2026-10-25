"""
Synthetic Test Document Generator for AICTE Document Scrutiny
Generates 24 clearly labeled synthetic FDR PDFs:
- 10 clean passing documents
- 14 with planted defects (2 for each of 7 defect categories)
- Every page is watermarked: SAMPLE - TEST DATA
- Produces data/labels.csv recording the ground truth for evaluation
"""

import csv
import os
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

DATA_DIR = Path(__file__).parent.parent / "data"
TEST_DOCS_DIR = DATA_DIR / "test_documents"
LABELS_FILE = DATA_DIR / "labels.csv"


def draw_fdr_pdf(
    filepath: Path,
    fdr_number: str,
    bank_name: str,
    branch: str,
    institute_name: str,
    beneficiary_name: str,
    amount: float,
    issue_date: str,
    maturity_date: str,
    tenure_years: float,
    watermark_note: str = "SAMPLE - TEST DATA",
    extra_text: str = ""
):
    """Draw a professional FDR receipt using ReportLab canvas."""
    c = canvas.Canvas(str(filepath), pagesize=letter)
    width, height = letter

    # Outer border
    c.setLineWidth(2)
    c.setStrokeColor(colors.HexColor("#1A365D"))
    c.rect(30, 30, width - 60, height - 60)

    # Inner decorative border
    c.setLineWidth(0.75)
    c.rect(36, 36, width - 72, height - 72)

    # Watermark / Banner
    c.setFillColor(colors.HexColor("#C53030"))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2.0, height - 60, f"*** {watermark_note} ***")

    # Bank Header
    c.setFillColor(colors.HexColor("#1A365D"))
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2.0, height - 90, bank_name.upper())

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawCentredString(width / 2.0, height - 105, f"Branch: {branch}")

    # Title
    c.setFillColor(colors.HexColor("#2B6CB0"))
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2.0, height - 135, "FIXED DEPOSIT RECEIPT / TERM DEPOSIT ADVICE")

    c.setStrokeColor(colors.HexColor("#CBD5E0"))
    c.setLineWidth(1)
    c.line(50, height - 145, width - 50, height - 145)

    # FDR Details Grid
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)

    y = height - 180
    row_height = 28

    items = [
        ("FDR / Account No.:", fdr_number, "Deposit Amount:", f"INR {amount:,.2f}"),
        ("Date of Issue:", issue_date, "Date of Maturity:", maturity_date),
        ("Tenure:", f"{tenure_years} Years (96 Months)", "Auto Renewal:", "YES (Roll-over mandated)"),
        ("Depositor / Institute:", institute_name, "", ""),
        ("In Favour Of / Beneficiary:", beneficiary_name, "", "")
    ]

    for left_label, left_val, right_label, right_val in items:
        # Left column
        c.setFont("Helvetica-Bold", 10)
        c.drawString(60, y, left_label)
        c.setFont("Helvetica", 10)
        c.drawString(220, y, left_val)

        # Right column (if exists)
        if right_label:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(340, y, right_label)
            c.setFont("Helvetica", 10)
            c.drawString(450, y, right_val)

        y -= row_height

    # Terms & Conditions Box
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setFillColor(colors.HexColor("#F7FAFC"))
    c.rect(50, y - 90, width - 100, 90, fill=1, stroke=1)

    c.setFillColor(colors.HexColor("#2D3748"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(60, y - 20, "TERMS & CONDITIONS MANDATED BY REGULATORY AUTHORITY:")
    c.setFont("Helvetica", 8)
    c.drawString(60, y - 35, "1. This Fixed Deposit Receipt is held under lien as security deposit towards AICTE regulatory norms.")
    c.drawString(60, y - 50, "2. Premature liquidation or encashment is strictly prohibited without prior written sanction.")
    c.drawString(60, y - 65, "3. Joint discharge or AICTE sole discharge required upon maturity as per Approval Process Handbook.")

    if extra_text:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.red)
        c.drawString(60, y - 80, extra_text)

    # Signatures
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(80, 80, "_________________________")
    c.drawString(80, 65, "Authorized Bank Signatory")

    c.drawString(width - 200, 80, "_________________________")
    c.drawString(width - 200, 65, "Branch Manager / Seal")

    c.save()


def generate_all_test_documents():
    """Build the full 24 synthetic test suite + labels.csv."""
    TEST_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    labels = []

    # Reference standard application profile
    default_app = {
        "institute": "Apex Institute of Technology",
        "category": "Technical",
        "required_amount": 1500000.0
    }

    # 1. Ten Clean Compliant Documents
    banks = [
        "State Bank of India", "Punjab National Bank", "Bank of Baroda",
        "Canara Bank", "Union Bank of India", "HDFC Bank",
        "ICICI Bank", "Axis Bank", "Bank of India", "Kotak Mahindra Bank"
    ]
    for i in range(1, 11):
        filename = f"fdr_test_{i:02d}_clean.pdf"
        filepath = TEST_DOCS_DIR / filename
        draw_fdr_pdf(
            filepath=filepath,
            fdr_number=f"FDR-2026-CLN{i:03d}",
            bank_name=banks[i - 1],
            branch=f"Central Branch #{i}, New Delhi",
            institute_name="Apex Institute of Technology",
            beneficiary_name="Member Secretary, AICTE",
            amount=1500000.0 + (i * 50000.0),
            issue_date="2026-05-10",
            maturity_date="2034-05-10",
            tenure_years=8.0
        )
        labels.append({
            "filename": filename,
            "true_verdict": "PASS",
            "defect_type": "NONE",
            "failed_rule": "NONE",
            "institute_name": default_app["institute"],
            "category": default_app["category"],
            "required_amount": default_app["required_amount"],
            "is_scanned": "false"
        })

    # 2. Planted Defects (14 documents, 2 for each of 7 defect rules)
    defects = [
        # R1: Wrong Beneficiary
        (11, "r1_wrong_beneficiary_1", "R1", "In favour of Principal, ABC College", {
            "beneficiary_name": "Principal, Apex College"
        }),
        (12, "r1_wrong_beneficiary_2", "R1", "Beneficiary named as Chairman of Society", {
            "beneficiary_name": "Chairman, Apex Educational Trust"
        }),

        # R2: Unapproved / Non-Scheduled Bank
        (13, "r2_unapproved_bank_1", "R2", "Issued by unapproved Cooperative Credit Society", {
            "bank_name": "Adarsh Gramin Sahakari Sanstha",
            "branch": "Rural Block #4"
        }),
        (14, "r2_unapproved_bank_2", "R2", "Issued by unauthorized local finance firm", {
            "bank_name": "FastTrack Nidhi Limited",
            "branch": "Main Market"
        }),

        # R3: Short Tenure (< 8 Years)
        (15, "r3_short_tenure_3yr", "R3", "Tenure is 3 years instead of mandatory 8 years", {
            "issue_date": "2026-05-10",
            "maturity_date": "2029-05-10",
            "tenure_years": 3.0
        }),
        (16, "r3_short_tenure_5yr", "R3", "Tenure is 5 years instead of mandatory 8 years", {
            "issue_date": "2026-05-10",
            "maturity_date": "2031-05-10",
            "tenure_years": 5.0
        }),

        # R4: Amount Deficit
        (17, "r4_insufficient_amt_5L", "R4", "Deposit amount is only 5 Lakhs (deficit 10L)", {
            "amount": 500000.0
        }),
        (18, "r4_insufficient_amt_10L", "R4", "Deposit amount is only 10 Lakhs (deficit 5L)", {
            "amount": 1000000.0
        }),

        # R5: Institute Identity Mismatch
        (19, "r5_institute_mismatch_1", "R5", "Institute name differs completely from application", {
            "institute_name": "Shri Ram Murti Institute of Management"
        }),
        (20, "r5_institute_mismatch_2", "R5", "Trust name provided instead of approved college", {
            "institute_name": "Navodaya Charitable Welfare Society"
        }),

        # R6: Inconsistent Date Logic
        (21, "r6_future_issue_date", "R6", "Issue date set in future (year 2035)", {
            "issue_date": "2035-01-01",
            "maturity_date": "2043-01-01",
            "tenure_years": 8.0
        }),
        (22, "r6_matured_deposit", "R6", "Deposit is already past its maturity date", {
            "issue_date": "2012-01-01",
            "maturity_date": "2020-01-01",
            "tenure_years": 8.0
        }),

        # R7: Integrity / Suspicious Watermark
        (23, "r7_tamper_void_stamp", "R7", "Document marked as VOID / SPECIMEN", {
            "extra_text": "VOID - SPECIMEN CANCELLED INSTRUMENT"
        }),
        (24, "r7_tamper_sample_copy", "R7", "Document marked as DO NOT USE FOR APPROVAL", {
            "extra_text": "SAMPLE DOCUMENT DO NOT USE"
        }),
    ]

    for doc_num, tag, failed_rule, desc, overrides in defects:
        filename = f"fdr_test_{doc_num:02d}_{tag}.pdf"
        filepath = TEST_DOCS_DIR / filename

        base_params = {
            "fdr_number": f"FDR-2026-DEF{doc_num:03d}",
            "bank_name": "State Bank of India",
            "branch": "New Delhi Main Branch",
            "institute_name": "Apex Institute of Technology",
            "beneficiary_name": "Member Secretary, AICTE",
            "amount": 1500000.0,
            "issue_date": "2026-05-10",
            "maturity_date": "2034-05-10",
            "tenure_years": 8.0,
            "extra_text": ""
        }
        base_params.update(overrides)

        draw_fdr_pdf(
            filepath=filepath,
            fdr_number=base_params["fdr_number"],
            bank_name=base_params["bank_name"],
            branch=base_params["branch"],
            institute_name=base_params["institute_name"],
            beneficiary_name=base_params["beneficiary_name"],
            amount=base_params["amount"],
            issue_date=base_params["issue_date"],
            maturity_date=base_params["maturity_date"],
            tenure_years=base_params["tenure_years"],
            extra_text=base_params["extra_text"]
        )

        labels.append({
            "filename": filename,
            "true_verdict": "FAIL" if failed_rule != "R7" else "UNCERTAIN",
            "defect_type": desc,
            "failed_rule": failed_rule,
            "institute_name": default_app["institute"],
            "category": default_app["category"],
            "required_amount": default_app["required_amount"],
            "is_scanned": "false"
        })

    # Write labels.csv
    with open(LABELS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "filename", "true_verdict", "defect_type", "failed_rule",
            "institute_name", "category", "required_amount", "is_scanned"
        ])
        writer.writeheader()
        writer.writerows(labels)

    print(f"Generated 24 test documents in {TEST_DOCS_DIR}")
    print(f"Wrote labels ground truth to {LABELS_FILE}")


if __name__ == "__main__":
    generate_all_test_documents()
