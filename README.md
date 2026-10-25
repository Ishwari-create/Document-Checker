# Document Checker – AICTE FDR Compliance Engine

> **SIH Project A** | Automated AICTE Fixed Deposit Receipt (FDR) Scrutiny System

---

## Project Structure

```
DocCheckerSIH/
├── config/
│   └── rules.yaml              # Rule definitions with AICTE APH clause references
├── data/
│   └── scheduled_banks.json    # RBI-approved Nationalised & Scheduled banks list
├── src/
│   ├── __init__.py
│   ├── extractor.py            # PDF text extraction + FDR field parser
│   ├── rule_engine.py          # 7 AICTE compliance rules engine
│   └── deficiency.py           # Deficiency letter generator
├── tests/
│   └── test_rules.py           # Pytest suite: all rules, PASS/FAIL/UNCERTAIN
├── requirements.txt
├── SPEC.md                     # Full specification & A-2 interface contract
└── README.md
```

---

## Sub-Task Breakdown

| Task | Owner | Branch | Status |
|------|-------|--------|--------|
| **A-1**: Backend core (extractor, rule engine, deficiency letter, tests) | Parag | `main` | ✅ Done |
| **A-2**: Streamlit UI (upload, PDF preview, rule dashboard, download letter) | Team Member | `feature/a2-frontend` | 🔲 To start |

---

## Setup & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## A-2 Quick Start Guide (Frontend Member)

**Create your branch first:**
```bash
git checkout -b feature/a2-frontend
```

**Three functions you need from the backend:**
```python
from src.extractor import extract_fdr_fields
from src.rule_engine import check_document, get_overall_verdict
from src.deficiency import generate_deficiency_letter, get_deficiency_summary

# 1. Extract fields from uploaded PDF
result = extract_fdr_fields(uploaded_file)   # works with Streamlit's UploadedFile
fields = result["fields"]
raw_text = result["raw_text"]
confidence = result["confidence"]

# 2. Run all 7 compliance rules
app_context = {
    "institute_name": "User typed name",
    "category": "Technical",          # or Management, Pharmacy, etc.
    "required_amount": 1500000.0
}
rule_results = check_document(fields, app_context, raw_text)
verdict = get_overall_verdict(rule_results)   # "PASS" | "FAIL" | "UNCERTAIN"

# 3. Generate deficiency letter (if needed)
summary = get_deficiency_summary(rule_results)
if summary["needs_letter"]:
    letter = generate_deficiency_letter(fields, rule_results, app_context)
```

**RuleVerdict dict structure** (each item in `rule_results`):
```python
{
    "rule_id": "R1",               # R1 through R7
    "name": "Beneficiary Verification",
    "clause": "AICTE APH Clause 4.1.2",
    "severity": "FATAL",           # "FATAL" | "WARNING"
    "status": "PASS",              # "PASS" | "FAIL" | "UNCERTAIN"
    "evidence": "In favour of: Member Secretary, AICTE",
    "reasoning": "Beneficiary correctly identifies Member Secretary, AICTE."
}
```

See [`SPEC.md`](./SPEC.md) for the full specification.

---

## Rules Summary

| Rule | What it Checks | APH Clause | Severity |
|------|---------------|------------|----------|
| R1 | FDR beneficiary = Member Secretary, AICTE | 4.1.2 | FATAL |
| R2 | Issuing bank is Nationalised/Scheduled | 4.1.2 / RBI | FATAL |
| R3 | Tenure ≥ 8 years | 4.1.3 | FATAL |
| R4 | Amount ≥ prescribed threshold (₹15L for Technical) | 4.1.4 | FATAL |
| R5 | Institute name matches AICTE portal records | 2.3.1 | FATAL |
| R6 | Valid date logic (issue ≤ today, maturity > issue) | 4.1.5 | WARNING |
| R7 | No tamper indicators / integrity flags | 1.4 | WARNING |
