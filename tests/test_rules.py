"""
Unit tests: one PASS and one FAIL (or UNCERTAIN) case per rule, plus the
extractor helpers and the end-to-end pipeline on two generated documents.

    pytest -q
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extractor import parse_amount, parse_date, words_to_number          # noqa: E402
from src.registry import IssuerConnector, Ledger                              # noqa: E402
from src.rule_engine import check_document, get_overall_verdict, name_similarity  # noqa: E402
from src.deficiency import generate_deficiency_letter                         # noqa: E402

SUB = date(2026, 5, 1)


@pytest.fixture
def fields():
    return {
        "fdr_number": "XX1234567890", "bank_name": "State Bank of India",
        "depositor_name": "Apex Institute of Technology", "beneficiary_name": "Member Secretary, AICTE",
        "amount": 3500000.0, "amount_words": "Rupees Thirty Five Lakh Only", "amount_in_words_value": 3500000.0,
        "issue_date": "2026-04-25", "maturity_date": "2036-04-25", "tenure_text": "120 Months",
    }


@pytest.fixture
def app():
    return {"app_id": "A1", "institute_name": "Apex Institute of Technology", "trust": "Apex Education Trust",
            "institution_type": "Private Self-Financing", "special_category": False,
            "programmes": ["Engineering & Technology"], "loa_date": "2026-04-20"}


def run(fields, app, **kw):
    res = check_document(fields, app, submitted_on=kw.pop("sub", SUB), **kw)
    return {r["rule_id"]: r for r in res}, get_overall_verdict(res)


def test_clean_document_passes(fields, app):
    r, overall = run(fields, app)
    assert overall == "PASS", {k: (v["status"], v["reasoning"]) for k, v in r.items() if v["status"] != "PASS"}


def test_government_institution_is_exempt(fields, app):
    _, overall = run(fields, {**app, "institution_type": "Government"})
    assert overall == "EXEMPT"


# R1 ---------------------------------------------------------------------------
@pytest.mark.parametrize("ben,expected", [
    ("Member Secretary, All India Council for Technical Education", "PASS"),
    ("Member Secretary AICTE jointly with Apex Education Trust", "PASS"),
    ("The Principal, Apex Institute of Technology", "FAIL"),
    ("Member Secy, AICTE", "UNCERTAIN"),
    (None, "UNCERTAIN"),
])
def test_r1(fields, app, ben, expected):
    assert run({**fields, "beneficiary_name": ben}, app)[0]["R1"]["status"] == expected


# R2 ---------------------------------------------------------------------------
@pytest.mark.parametrize("bank,expected", [
    ("State Bank of India", "PASS"), ("Central Bank of India", "PASS"), ("HDFC Bank Ltd.", "PASS"),
    ("Shree Ganesh Sahakari Bank (Co-operative)", "FAIL"), ("Sunrise Finance & Investments Ltd.", "FAIL"),
    ("Bank of Indla", "PASS"),                      # OCR error still recognised
    ("Some Unknown Bank", "UNCERTAIN"),
])
def test_r2(fields, app, bank, expected):
    assert run({**fields, "bank_name": bank}, app)[0]["R2"]["status"] == expected


# R3 ---------------------------------------------------------------------------
def test_r3_eight_years_is_short(fields, app):
    assert run({**fields, "maturity_date": "2034-04-25"}, app)[0]["R3"]["status"] == "FAIL"


def test_r3_uses_printed_period_when_dates_missing(fields, app):
    r = run({**fields, "issue_date": None, "maturity_date": None, "tenure_text": "60 Months"}, app)[0]
    assert r["R3"]["status"] == "FAIL"


# R4 ---------------------------------------------------------------------------
def test_r4_sums_programmes(fields, app):
    two = {**app, "programmes": ["Engineering & Technology", "Management"]}
    r = run(fields, two)[0]["R4"]
    assert r["status"] == "FAIL" and "15,00,000" in r["reasoning"]


def test_r4_special_category_slab(fields, app):
    r = run({**fields, "amount": 2800000.0, "amount_in_words_value": 2800000.0},
            {**app, "special_category": True})[0]
    assert r["R4"]["status"] == "PASS"


# R5 ---------------------------------------------------------------------------
@pytest.mark.parametrize("dep,expected", [
    ("Apex Institute of Technology", "PASS"), ("Apex Inst. of Tech.", "PASS"),
    ("Apex Education Trust", "PASS"), ("Sai Krupa Hospitality Services Pvt. Ltd.", "FAIL"),
])
def test_r5(fields, app, dep, expected):
    assert run({**fields, "depositor_name": dep}, app)[0]["R5"]["status"] == expected


def test_name_similarity_not_fooled_by_subset():
    assert name_similarity("College", "Apex College of Engineering") < 70


# R6 ---------------------------------------------------------------------------
def test_r6_post_dated(fields, app):
    assert run({**fields, "issue_date": "2026-06-30", "maturity_date": "2036-06-30"}, app)[0]["R6"]["status"] == "FAIL"


def test_r6_already_matured(fields, app):
    r = run({**fields, "issue_date": "2014-06-12", "maturity_date": "2024-06-12"}, app)[0]["R6"]
    assert r["status"] == "FAIL" and r["ps_status"] == "Expired"


# R7 ---------------------------------------------------------------------------
def test_r7_late_submission_penalty(fields, app):
    r = run(fields, app, sub=date(2026, 5, 20))[0]["R7"]
    assert r["status"] == "FAIL" and "10%" in r["reasoning"] and r["severity"] == "WARNING"


def test_r7_after_july_is_fatal(fields, app):
    r = run(fields, app, sub=date(2026, 8, 5))[0]["R7"]
    assert r["status"] == "FAIL" and r["severity"] == "FATAL"


# R8 ---------------------------------------------------------------------------
def test_r8_figures_vs_words(fields, app):
    r = run({**fields, "amount_in_words_value": 2500000.0}, app)[0]["R8"]
    assert r["status"] == "FAIL"


# R9 / R10 ------------------------------------------------------------------------
def test_r9_source_unavailable_goes_to_review(fields, app):
    r = run(fields, app, issuer=IssuerConnector())[0]["R9"]
    assert r["status"] == "UNCERTAIN" and r["ps_status"] == "Source unavailable"


def test_r10_same_fdr_in_two_applications(fields, app):
    led = Ledger(db_path=None)
    led.record_submission("OTHER-APP", fields["fdr_number"], fields["bank_name"], "abc")
    r = run(fields, app, ledger=led, sha256="def")[0]["R10"]
    assert r["status"] == "FAIL" and "OTHER-APP" in r["evidence"]


# Helpers -------------------------------------------------------------------------
def test_parsers():
    assert parse_amount("Rs. 35,00,000.00") == 3500000.0
    assert parse_date("Opened on: 04-May-2026") == "2026-05-04"
    assert parse_date("Date of Deposit : 15/06/2026") == "2026-06-15"
    assert words_to_number("Rupees Twelve Lakh Fifty Thousand Only") == 1250000
    assert words_to_number("Rupees One Crore Five Lakh Only") == 10500000


def test_letter_lists_failures(fields, app):
    res = check_document({**fields, "amount": 100.0}, app, submitted_on=SUB)
    letter = generate_deficiency_letter(fields, res, app)
    assert "R4" in letter and "DRAFT" in letter.upper()


# End to end on generated documents --------------------------------------------------
@pytest.mark.skipif(not (ROOT / "data" / "labels.csv").exists(), reason="run tools/generate_test_docs.py first")
def test_pipeline_on_two_generated_documents():
    import csv
    from src.pipeline import load_applications, run_check
    apps = load_applications()
    labels = list(csv.DictReader(open(ROOT / "data" / "labels.csv")))
    clean = next(l for l in labels if l["defect_type"] == "none" and l["scanned"] == "0")
    bad = next(l for l in labels if l["defect_type"] == "short_tenure")
    for lab, expected in [(clean, "PASS"), (bad, "FAIL")]:
        pdf = (ROOT / "data" / "test_documents" / lab["file"]).read_bytes()
        out = run_check(pdf, apps[lab["app_id"]], submitted_on=date.fromisoformat(lab["submitted_on"]),
                        issuer=IssuerConnector(), ledger=Ledger(db_path=None))
        assert out["overall"] == expected
