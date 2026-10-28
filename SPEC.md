# Specification: AICTE Document Checker (SIH26261 - Project A)

## 1. User Story (3 Lines)
1. An AICTE scrutiny officer or institute applicant uploads a PDF copy of a Fixed Deposit Receipt (FDR) submitted for institutional approval or compliance.
2. The automated engine extracts key financial and institutional fields, validates them against AICTE Approval Process Handbook (APH) clauses via rules, and pinpoints exact evidence.
3. The system generates an immediate verdict (Pass / Fail / Uncertain) per clause, flags deficiencies with official handbook citations, and creates a ready-to-issue deficiency letter if non-compliant.

---

## 2. System Architecture & Screens
- **Backend Core (`A-1`)**:
  - `src/extractor.py`: Deterministic text extraction from PDF with bounding text snippet capture, plus AI vision fallback.
  - `src/rule_engine.py`: Handbook rules loader (`rules.yaml`) running checks (R1–R7) returning structured JSON results.
  - `src/deficiency.py`: Automated clause-cited deficiency letter generator.
  - `tests/test_rules.py`: Comprehensive test suite verifying all 7 rules.
- **Frontend & Evaluation (`A-2`)**:
  - Streamlit Scrutiny Dashboard: PDF upload, side-by-side document preview with visual flags, rule status table (Pass/Fail/Uncertain with clause tags), and officer action queue.
  - Applicant Pre-Check screen: Self-service validation before formal submission.
  - "Try to Fool It" defect injection demo.
  - Evaluation against 24 synthetic test documents (`labels.csv`).

---

## 3. Data Schema & Extracted Fields

| Field Name | Type | Description | Example |
|---|---|---|---|
| `fdr_number` | `str` | FDR / Term Deposit Account Number | `"FDR-2026-98172"` |
| `bank_name` | `str` | Issuing Bank Name | `"State Bank of India"` |
| `branch` | `str` | Branch Name / IFSC | `"New Delhi Main Branch (SBIN0000691)"` |
| `institute_name` | `str` | Depositor / College Name | `"Apex Institute of Technology"` |
| `beneficiary_name` | `str` | Named Beneficiary / In Favour Of | `"Member Secretary, AICTE"` |
| `amount` | `float` | Fixed deposit principal amount (INR) | `1500000.00` |
| `issue_date` | `str` (YYYY-MM-DD) | Date of deposit creation | `"2026-05-10"` |
| `maturity_date` | `str` (YYYY-MM-DD) | Date of deposit maturity | `"2034-05-10"` |
| `tenure_years` | `float` | Tenure calculated from dates | `8.0` |
| `auto_renew` | `bool` | Auto-renewal clause presence | `True` |

---

## 4. Rule Set & Handbook Clause Mapping

| Rule ID | Name | What it checks | AICTE APH Clause | Severity | Output States |
|---|---|---|---|---|---|
| **R1** | **Beneficiary Check** | FDR must be in favour of "Member Secretary, AICTE" or joint with AICTE | Clause 4.1.2 (Security Deposit) | FATAL | PASS / FAIL / UNCERTAIN |
| **R2** | **Approved Bank Check** | Must be issued by Nationalised or Scheduled Commercial Bank | Clause 4.1.2 / RBI 2nd Schedule | FATAL | PASS / FAIL / UNCERTAIN |
| **R3** | **Tenure Check** | Tenure must be at least 8 years (Maturity Date - Issue Date >= 8 years) | Clause 4.1.3 (Tenure of FDR) | FATAL | PASS / FAIL / UNCERTAIN |
| **R4** | **Amount Threshold** | Amount meets requirement for institute category (e.g. ₹15,00,000 for Technical) | Clause 4.1.4 (Prescribed Deposit) | FATAL | PASS / FAIL / UNCERTAIN |
| **R5** | **Name Consistency** | FDR institute name matches AICTE portal application data (fuzzy match >= 85%) | Clause 2.3.1 (Identity Verification) | FATAL | PASS / FAIL / UNCERTAIN |
| **R6** | **Date Logic Check** | Issue date <= today, Maturity > Issue date, valid non-expired range | Clause 4.1.5 (Validity & Integrity) | WARNING | PASS / FAIL / UNCERTAIN |
| **R7** | **Tamper / Integrity** | Flags suspicious digital artifacts, inconsistent font encodings, or missing bank seals | Clause 1.4 (Fraud Prevention) | WARNING | PASS / UNCERTAIN |

---

## 5. Interface Contract for A-2 (Streamlit Front-End)

The backend exposes simple, high-level functions that A-2 can call directly in Streamlit:

```python
from src.extractor import extract_fdr_fields
from src.rule_engine import check_document
from src.deficiency import generate_deficiency_letter

# 1. Extraction from uploaded file (filepath or bytes)
extracted_data = extract_fdr_fields(pdf_path_or_bytes)
# extracted_data -> { "fields": {...}, "raw_text": "...", "confidence": 0.95 }

# 2. Rule evaluation
application_context = {
    "institute_name": "Apex Institute of Technology",
    "category": "Technical",
    "required_amount": 1500000.00
}
rule_results = check_document(extracted_data["fields"], application_context)
# rule_results -> list of RuleVerdict objects:
# [
#   {
#     "rule_id": "R1",
#     "name": "Beneficiary Check",
#     "status": "PASS",  # "PASS" | "FAIL" | "UNCERTAIN"
#     "clause": "Clause 4.1.2",
#     "evidence": "In favour of: Member Secretary, AICTE",
#     "reasoning": "Beneficiary strictly matches designated AICTE authority."
#   }, ...
# ]

# 3. Generate deficiency letter if any FATAL rule failed
if any(r["status"] == "FAIL" for r in rule_results):
    letter_text = generate_deficiency_letter(extracted_data["fields"], rule_results, application_context)
```

---

## 6. Synthetic Test Set & Evaluation Plan
- 24 synthetic PDFs to be generated in `data/test_documents/` with stamp: `SAMPLE - TEST DATA`.
- 10 clean passing documents.
- 14 planted defect documents (2 defects for each of 7 defect categories).
- 4 rasterised/noisy scans to test OCR/scan fallback.
- `data/labels.csv` contains ground-truth labels for automated evaluation metrics (precision, recall, false-alarm rate).

---

## 7. Changes on `feature/a2-frontend` (28 Oct 2026)

This section supersedes sections 3-5 where they differ.

- **Rules.** Now R0-R10, all in `config/rules.yaml` with real sources (docs/RULE_SOURCES.md). The clause numbers in section 4 above could not be traced to any AICTE text and are retired. Tenure is 10 years per the 2024-27 guidelines (to confirm). R7 "tamper" is replaced by R8 (figures vs words) and R9 (issuer confirmation); R10 detects reuse; R7 is now the 15-day submission check with penalty.
- **Statuses.** PASS / FAIL / UNCERTAIN / NA, plus EXEMPT for government institutes. Each verdict also carries `problem`, `ps_status` (the brief's vocabulary), `fix`, `fields` (for evidence boxes), `source` and `verified_source`.
- **Fields.** `institute_name` is now `depositor_name` (old key still filled). New: `ifsc`, `amount_words`, `amount_in_words_value`, `tenure_text`. `extract_fdr_fields` also returns `locations` (page + box per field), `pages`, `method` (text-layer / ocr) and `read_quality`.
- **API.** `check_document(fields, application, raw_text, submitted_on=, issuer=, ledger=, sha256=)`; the A-1 short context `{institute_name, category, required_amount}` still works. `src/pipeline.run_check()` does read + check + log in one call.
- **Front end.** Flask instead of Streamlit (Streamlit could not be installed in the build environment, and a plain web app deploys anywhere with Docker). Screens listed in README.
