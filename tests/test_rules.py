"""
Test Suite for AICTE Rule Engine (A-1)
Tests all 7 rules with pass, fail, and uncertain scenarios.
Run with: pytest tests/ -v
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.rule_engine import check_document, get_overall_verdict
from src.deficiency import generate_deficiency_letter, get_deficiency_summary


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def good_fields():
    return {
        "fdr_number": "FDR-2026-98172",
        "bank_name": "State Bank of India",
        "branch": "New Delhi Main Branch (SBIN0000691)",
        "institute_name": "Apex Institute of Technology",
        "beneficiary_name": "Member Secretary, AICTE",
        "amount": 1500000.0,
        "issue_date": "2026-05-10",
        "maturity_date": "2034-05-10",
        "tenure_years": 8.0,
        "auto_renew": True,
    }


@pytest.fixture
def good_context():
    return {
        "institute_name": "Apex Institute of Technology",
        "category": "Technical",
        "required_amount": 1500000.0
    }


# ─────────────────────────────────────────────────────────────
# R1: Beneficiary
# ─────────────────────────────────────────────────────────────
class TestR1Beneficiary:
    def test_r1_pass(self, good_fields, good_context):
        results = check_document(good_fields, good_context)
        r1 = next(r for r in results if r["rule_id"] == "R1")
        assert r1["status"] == "PASS", f"Expected PASS, got {r1['status']}: {r1['reasoning']}"

    def test_r1_fail_wrong_beneficiary(self, good_fields, good_context):
        bad = {**good_fields, "beneficiary_name": "Principal, ABC College"}
        results = check_document(bad, good_context)
        r1 = next(r for r in results if r["rule_id"] == "R1")
        assert r1["status"] == "FAIL"

    def test_r1_uncertain_only_aicte(self, good_fields, good_context):
        uncertain = {**good_fields, "beneficiary_name": "AICTE, New Delhi"}
        results = check_document(uncertain, good_context)
        r1 = next(r for r in results if r["rule_id"] == "R1")
        assert r1["status"] in ("UNCERTAIN", "PASS")

    def test_r1_uncertain_missing_field(self, good_fields, good_context):
        missing = {**good_fields, "beneficiary_name": None}
        results = check_document(missing, good_context)
        r1 = next(r for r in results if r["rule_id"] == "R1")
        assert r1["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# R2: Approved Bank
# ─────────────────────────────────────────────────────────────
class TestR2Bank:
    def test_r2_pass_nationalised(self, good_fields, good_context):
        results = check_document(good_fields, good_context)
        r2 = next(r for r in results if r["rule_id"] == "R2")
        assert r2["status"] == "PASS"

    def test_r2_pass_private_scheduled(self, good_fields, good_context):
        hdfc = {**good_fields, "bank_name": "HDFC Bank"}
        results = check_document(hdfc, good_context)
        r2 = next(r for r in results if r["rule_id"] == "R2")
        assert r2["status"] == "PASS"

    def test_r2_fail_unknown_bank(self, good_fields, good_context):
        bad = {**good_fields, "bank_name": "Fake Rural Cooperative Bank"}
        results = check_document(bad, good_context)
        r2 = next(r for r in results if r["rule_id"] == "R2")
        assert r2["status"] in ("FAIL", "UNCERTAIN")

    def test_r2_uncertain_missing(self, good_fields, good_context):
        missing = {**good_fields, "bank_name": None}
        results = check_document(missing, good_context)
        r2 = next(r for r in results if r["rule_id"] == "R2")
        assert r2["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# R3: Tenure
# ─────────────────────────────────────────────────────────────
class TestR3Tenure:
    def test_r3_pass_exactly_8_years(self, good_fields, good_context):
        results = check_document(good_fields, good_context)
        r3 = next(r for r in results if r["rule_id"] == "R3")
        assert r3["status"] == "PASS"

    def test_r3_pass_more_than_8_years(self, good_fields, good_context):
        extended = {**good_fields, "issue_date": "2020-01-01", "maturity_date": "2030-01-01", "tenure_years": 10.0}
        results = check_document(extended, good_context)
        r3 = next(r for r in results if r["rule_id"] == "R3")
        assert r3["status"] == "PASS"

    def test_r3_fail_short_tenure(self, good_fields, good_context):
        short = {**good_fields, "issue_date": "2024-01-01", "maturity_date": "2028-01-01", "tenure_years": 4.0}
        results = check_document(short, good_context)
        r3 = next(r for r in results if r["rule_id"] == "R3")
        assert r3["status"] == "FAIL"

    def test_r3_uncertain_no_dates(self, good_fields, good_context):
        no_dates = {**good_fields, "issue_date": None, "maturity_date": None, "tenure_years": None}
        results = check_document(no_dates, good_context)
        r3 = next(r for r in results if r["rule_id"] == "R3")
        assert r3["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# R4: Amount
# ─────────────────────────────────────────────────────────────
class TestR4Amount:
    def test_r4_pass_exact_amount(self, good_fields, good_context):
        results = check_document(good_fields, good_context)
        r4 = next(r for r in results if r["rule_id"] == "R4")
        assert r4["status"] == "PASS"

    def test_r4_pass_above_threshold(self, good_fields, good_context):
        rich = {**good_fields, "amount": 2000000.0}
        results = check_document(rich, good_context)
        r4 = next(r for r in results if r["rule_id"] == "R4")
        assert r4["status"] == "PASS"

    def test_r4_fail_below_threshold(self, good_fields, good_context):
        poor = {**good_fields, "amount": 500000.0}
        results = check_document(poor, good_context)
        r4 = next(r for r in results if r["rule_id"] == "R4")
        assert r4["status"] == "FAIL"

    def test_r4_uncertain_no_amount(self, good_fields, good_context):
        no_amt = {**good_fields, "amount": None}
        results = check_document(no_amt, good_context)
        r4 = next(r for r in results if r["rule_id"] == "R4")
        assert r4["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# R5: Institute Name Match
# ─────────────────────────────────────────────────────────────
class TestR5InstituteMatch:
    def test_r5_pass_exact_match(self, good_fields, good_context):
        results = check_document(good_fields, good_context)
        r5 = next(r for r in results if r["rule_id"] == "R5")
        assert r5["status"] == "PASS"

    def test_r5_pass_minor_typo(self, good_fields, good_context):
        typo = {**good_fields, "institute_name": "Apex Institute Of Technology"}
        results = check_document(typo, good_context)
        r5 = next(r for r in results if r["rule_id"] == "R5")
        assert r5["status"] == "PASS"

    def test_r5_fail_different_name(self, good_fields, good_context):
        wrong = {**good_fields, "institute_name": "Shri Ram College of Commerce"}
        results = check_document(wrong, good_context)
        r5 = next(r for r in results if r["rule_id"] == "R5")
        assert r5["status"] in ("FAIL", "UNCERTAIN")

    def test_r5_uncertain_missing_field(self, good_fields, good_context):
        missing = {**good_fields, "institute_name": None}
        results = check_document(missing, good_context)
        r5 = next(r for r in results if r["rule_id"] == "R5")
        assert r5["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# R6: Date Logic
# ─────────────────────────────────────────────────────────────
class TestR6DateLogic:
    def test_r6_pass_valid_dates(self, good_fields, good_context):
        results = check_document(good_fields, good_context)
        r6 = next(r for r in results if r["rule_id"] == "R6")
        assert r6["status"] == "PASS"

    def test_r6_fail_future_issue_date(self, good_fields, good_context):
        future = {**good_fields, "issue_date": "2099-01-01", "maturity_date": "2107-01-01"}
        results = check_document(future, good_context)
        r6 = next(r for r in results if r["rule_id"] == "R6")
        assert r6["status"] == "FAIL"

    def test_r6_fail_already_matured(self, good_fields, good_context):
        matured = {**good_fields, "issue_date": "2010-01-01", "maturity_date": "2018-01-01"}
        results = check_document(matured, good_context)
        r6 = next(r for r in results if r["rule_id"] == "R6")
        assert r6["status"] == "FAIL"

    def test_r6_uncertain_no_dates(self, good_fields, good_context):
        no_date = {**good_fields, "issue_date": None, "maturity_date": None}
        results = check_document(no_date, good_context)
        r6 = next(r for r in results if r["rule_id"] == "R6")
        assert r6["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# R7: Document Integrity
# ─────────────────────────────────────────────────────────────
class TestR7Integrity:
    def test_r7_pass_clean_text(self, good_fields, good_context):
        results = check_document(good_fields, good_context, raw_text="Normal FDR document text. " * 20)
        r7 = next(r for r in results if r["rule_id"] == "R7")
        assert r7["status"] == "PASS"

    def test_r7_uncertain_void_stamp(self, good_fields, good_context):
        results = check_document(good_fields, good_context, raw_text="VOID - SAMPLE DOCUMENT FOR TESTING")
        r7 = next(r for r in results if r["rule_id"] == "R7")
        assert r7["status"] == "UNCERTAIN"

    def test_r7_uncertain_empty_text(self, good_fields, good_context):
        results = check_document(good_fields, good_context, raw_text="")
        r7 = next(r for r in results if r["rule_id"] == "R7")
        assert r7["status"] == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────
# Overall Verdict
# ─────────────────────────────────────────────────────────────
class TestOverallVerdict:
    def test_all_pass(self, good_fields, good_context):
        results = check_document(good_fields, good_context, raw_text="Normal FDR text. " * 20)
        verdict = get_overall_verdict(results)
        assert verdict == "PASS"

    def test_fail_on_fatal_fail(self, good_fields, good_context):
        bad = {**good_fields, "amount": 100.0}
        results = check_document(bad, good_context, raw_text="Normal FDR text. " * 20)
        verdict = get_overall_verdict(results)
        assert verdict == "FAIL"

    def test_uncertain_on_missing_data(self, good_fields, good_context):
        missing = {**good_fields, "beneficiary_name": None}
        results = check_document(missing, good_context, raw_text="Normal FDR text. " * 20)
        verdict = get_overall_verdict(results)
        assert verdict in ("UNCERTAIN", "FAIL")


# ─────────────────────────────────────────────────────────────
# Deficiency Letter
# ─────────────────────────────────────────────────────────────
class TestDeficiencyLetter:
    def test_letter_generated_on_fail(self, good_fields, good_context):
        bad_fields = {**good_fields, "amount": 100.0, "beneficiary_name": "Principal, XYZ College"}
        results = check_document(bad_fields, good_context)
        letter = generate_deficiency_letter(bad_fields, results, good_context)
        assert "DEFICIENCY" in letter.upper()
        assert "AICTE" in letter
        assert len(letter) > 200

    def test_summary_dict(self, good_fields, good_context):
        results = check_document(good_fields, good_context, raw_text="Normal text " * 20)
        summary = get_deficiency_summary(results)
        assert "overall" in summary
        assert summary["total_rules"] == 7
