"""
Rule Engine for AICTE Fixed Deposit Receipt Verification
Loads rules from config/rules.yaml and checks all 7 compliance rules.
Returns a list of RuleVerdict dicts ready to be consumed by A-2 (Streamlit).
"""

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from rapidfuzz import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    try:
        from difflib import SequenceMatcher
        FUZZY_AVAILABLE = False
    except ImportError:
        FUZZY_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
CONFIG_DIR = Path(__file__).parent.parent / "config"
DATA_DIR = Path(__file__).parent.parent / "data"
RULES_FILE = CONFIG_DIR / "rules.yaml"
BANKS_FILE = DATA_DIR / "scheduled_banks.json"

AICTE_BENEFICIARY_KEYWORDS = {"member secretary", "aicte"}


# ─────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────
@dataclass
class RuleVerdict:
    rule_id: str
    name: str
    clause: str
    severity: str          # "FATAL" | "WARNING"
    status: str            # "PASS" | "FAIL" | "UNCERTAIN"
    evidence: str          # Exact text snippet from document
    reasoning: str         # Human-readable explanation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────
def load_rules_config() -> List[Dict[str, Any]]:
    """Load rules from config/rules.yaml."""
    if not YAML_AVAILABLE or not RULES_FILE.exists():
        return []
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rules", [])


def load_approved_banks() -> List[str]:
    """Load list of AICTE-approved banks from data/scheduled_banks.json."""
    if not BANKS_FILE.exists():
        return []
    with open(BANKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    banks = [b.lower() for b in data.get("banks", [])]
    aliases = {k.lower(): v.lower() for k, v in data.get("aliases", {}).items()}
    banks += list(aliases.keys())
    return banks


# ─────────────────────────────────────────────────────────────
# Fuzzy Matching Helper
# ─────────────────────────────────────────────────────────────
def fuzzy_ratio(a: str, b: str) -> float:
    """Return string similarity score 0-100."""
    if not a or not b:
        return 0.0
    if FUZZY_AVAILABLE:
        return fuzz.token_set_ratio(a.lower(), b.lower())
    else:
        # stdlib fallback
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


# ─────────────────────────────────────────────────────────────
# Individual Rule Checks
# ─────────────────────────────────────────────────────────────
def _check_r1_beneficiary(fields: Dict[str, Any], rule_cfg: Dict[str, Any]) -> RuleVerdict:
    """R1: FDR must be in favour of Member Secretary, AICTE."""
    beneficiary = (fields.get("beneficiary_name") or "").strip()
    
    if not beneficiary:
        return RuleVerdict(
            rule_id="R1", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence="Beneficiary field not found in document.",
            reasoning="Cannot determine beneficiary — field was not extracted. Manual verification required."
        )

    ben_lower = beneficiary.lower()
    has_aicte = "aicte" in ben_lower
    has_member_sec = "member secretary" in ben_lower or "ms." in ben_lower

    if has_aicte and has_member_sec:
        return RuleVerdict(
            rule_id="R1", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="PASS",
            evidence=f"In favour of: {beneficiary}",
            reasoning="Beneficiary correctly identifies Member Secretary, AICTE."
        )
    elif has_aicte:
        return RuleVerdict(
            rule_id="R1", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=f"In favour of: {beneficiary}",
            reasoning="AICTE mentioned but 'Member Secretary' designation not explicitly present. Manual review advised."
        )
    else:
        return RuleVerdict(
            rule_id="R1", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="FAIL",
            evidence=f"In favour of: {beneficiary}",
            reasoning=rule_cfg["rejection_message"]
        )


def _check_r2_bank(fields: Dict[str, Any], rule_cfg: Dict[str, Any], approved_banks: List[str]) -> RuleVerdict:
    """R2: Issuing bank must be a nationalised/scheduled commercial bank."""
    bank_name = (fields.get("bank_name") or "").strip().lower()

    if not bank_name:
        return RuleVerdict(
            rule_id="R2", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence="Bank name not found.",
            reasoning="Bank name could not be extracted. Manual verification required."
        )

    for approved in approved_banks:
        if approved in bank_name or bank_name in approved:
            return RuleVerdict(
                rule_id="R2", name=rule_cfg["name"], clause=rule_cfg["clause"],
                severity=rule_cfg["severity"], status="PASS",
                evidence=f"Issuing Bank: {fields['bank_name']}",
                reasoning=f"Bank '{fields['bank_name']}' is on the RBI Scheduled Bank list."
            )

    # Fuzzy match as uncertain threshold
    best_score = max((fuzzy_ratio(bank_name, a) for a in approved_banks), default=0)
    if best_score >= 80:
        return RuleVerdict(
            rule_id="R2", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=f"Issuing Bank: {fields['bank_name']} (similarity {best_score:.0f}%)",
            reasoning="Bank name is a close but not exact match to approved list. Manual verification recommended."
        )

    return RuleVerdict(
        rule_id="R2", name=rule_cfg["name"], clause=rule_cfg["clause"],
        severity=rule_cfg["severity"], status="FAIL",
        evidence=f"Issuing Bank: {fields.get('bank_name', 'Unknown')}",
        reasoning=rule_cfg["rejection_message"]
    )


def _check_r3_tenure(fields: Dict[str, Any], rule_cfg: Dict[str, Any]) -> RuleVerdict:
    """R3: FDR tenure must be >= 8 years."""
    tenure = fields.get("tenure_years")
    issue_date = fields.get("issue_date")
    maturity_date = fields.get("maturity_date")
    min_years = rule_cfg.get("minimum_tenure_years", 8.0)
    tolerance_days = rule_cfg.get("tolerance_days", 15)
    min_days = min_years * 365.25 - tolerance_days

    if tenure is None:
        if not issue_date or not maturity_date:
            return RuleVerdict(
                rule_id="R3", name=rule_cfg["name"], clause=rule_cfg["clause"],
                severity=rule_cfg["severity"], status="UNCERTAIN",
                evidence="Dates not found in document.",
                reasoning="Issue and/or maturity dates missing — tenure cannot be computed."
            )
        try:
            d1 = datetime.strptime(issue_date, "%Y-%m-%d")
            d2 = datetime.strptime(maturity_date, "%Y-%m-%d")
            tenure = round((d2 - d1).days / 365.25, 2)
        except Exception:
            return RuleVerdict(
                rule_id="R3", name=rule_cfg["name"], clause=rule_cfg["clause"],
                severity=rule_cfg["severity"], status="UNCERTAIN",
                evidence=f"Issue: {issue_date}, Maturity: {maturity_date}",
                reasoning="Date parsing error — tenure could not be computed."
            )

    evidence = f"Issue: {issue_date or 'N/A'} → Maturity: {maturity_date or 'N/A'} = {tenure} years"
    if tenure >= min_years - (tolerance_days / 365.25):
        return RuleVerdict(
            rule_id="R3", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="PASS",
            evidence=evidence,
            reasoning=f"Tenure of {tenure} years meets minimum requirement of {min_years} years."
        )
    else:
        return RuleVerdict(
            rule_id="R3", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="FAIL",
            evidence=evidence,
            reasoning=f"{rule_cfg['rejection_message']} Detected tenure: {tenure} years (required: {min_years})."
        )


def _check_r4_amount(fields: Dict[str, Any], rule_cfg: Dict[str, Any], app_ctx: Dict[str, Any]) -> RuleVerdict:
    """R4: FDR amount must meet prescribed threshold for category."""
    amount = fields.get("amount")
    category = app_ctx.get("category", "Technical")
    thresholds = rule_cfg.get("category_thresholds", {})
    required = app_ctx.get("required_amount") or thresholds.get(category, rule_cfg.get("default_required_amount", 1500000.0))

    if amount is None:
        return RuleVerdict(
            rule_id="R4", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence="Amount not found in document.",
            reasoning="Deposit amount could not be extracted. Manual verification required."
        )

    evidence = f"Extracted Amount: ₹{amount:,.2f} | Required: ₹{required:,.2f} (Category: {category})"
    if amount >= required:
        return RuleVerdict(
            rule_id="R4", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="PASS",
            evidence=evidence,
            reasoning=f"Deposit amount ₹{amount:,.2f} meets minimum requirement of ₹{required:,.2f}."
        )
    else:
        return RuleVerdict(
            rule_id="R4", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="FAIL",
            evidence=evidence,
            reasoning=f"{rule_cfg['rejection_message']} Shortfall: ₹{required - amount:,.2f}."
        )


def _check_r5_institute_name(fields: Dict[str, Any], rule_cfg: Dict[str, Any], app_ctx: Dict[str, Any]) -> RuleVerdict:
    """R5: Institute name on FDR must fuzzy-match AICTE portal data."""
    fdr_institute = (fields.get("institute_name") or "").strip()
    app_institute = (app_ctx.get("institute_name") or "").strip()
    threshold = rule_cfg.get("match_threshold", 85.0)

    if not fdr_institute:
        return RuleVerdict(
            rule_id="R5", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence="Institute name not found in FDR.",
            reasoning="Institute/depositor name could not be extracted from the document."
        )
    if not app_institute:
        return RuleVerdict(
            rule_id="R5", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=f"FDR Institute: {fdr_institute}",
            reasoning="No reference institute name provided in application context for comparison."
        )

    score = fuzzy_ratio(fdr_institute, app_institute)
    evidence = f"FDR: '{fdr_institute}' vs Portal: '{app_institute}' (similarity: {score:.0f}%)"

    if score >= threshold:
        return RuleVerdict(
            rule_id="R5", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="PASS",
            evidence=evidence,
            reasoning=f"Institute name matches at {score:.0f}% — above {threshold:.0f}% threshold."
        )
    elif score >= 70:
        return RuleVerdict(
            rule_id="R5", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=evidence,
            reasoning=f"Partial name match ({score:.0f}%). Could be abbreviation or minor variation. Manual review advised."
        )
    else:
        return RuleVerdict(
            rule_id="R5", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="FAIL",
            evidence=evidence,
            reasoning=f"{rule_cfg['rejection_message']} Similarity: {score:.0f}% (required: ≥{threshold:.0f}%)."
        )


def _check_r6_date_logic(fields: Dict[str, Any], rule_cfg: Dict[str, Any]) -> RuleVerdict:
    """R6: Validate date logic — issue ≤ today, maturity > issue, not pre-matured."""
    issue_str = fields.get("issue_date")
    mat_str = fields.get("maturity_date")
    today = datetime.today()

    if not issue_str or not mat_str:
        return RuleVerdict(
            rule_id="R6", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=f"Issue: {issue_str or 'missing'}, Maturity: {mat_str or 'missing'}",
            reasoning="Dates missing — date logic cannot be validated."
        )

    try:
        issue_dt = datetime.strptime(issue_str, "%Y-%m-%d")
        mat_dt = datetime.strptime(mat_str, "%Y-%m-%d")
    except ValueError:
        return RuleVerdict(
            rule_id="R6", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=f"Issue: {issue_str}, Maturity: {mat_str}",
            reasoning="Date format invalid — could not parse for logic checks."
        )

    issues = []
    if issue_dt > today:
        issues.append(f"Issue date {issue_str} is in the future.")
    if mat_dt <= issue_dt:
        issues.append(f"Maturity date {mat_str} is not after issue date {issue_str}.")
    if mat_dt < today:
        issues.append(f"FDR has already matured (maturity: {mat_str}).")

    evidence = f"Issue: {issue_str}, Maturity: {mat_str}, Checked: {today.strftime('%Y-%m-%d')}"

    if not issues:
        return RuleVerdict(
            rule_id="R6", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="PASS",
            evidence=evidence,
            reasoning="All date checks passed. Issue date is valid, maturity is future and after issue."
        )
    else:
        return RuleVerdict(
            rule_id="R6", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="FAIL",
            evidence=evidence,
            reasoning=" | ".join(issues)
        )


def _check_r7_integrity(fields: Dict[str, Any], raw_text: str, rule_cfg: Dict[str, Any]) -> RuleVerdict:
    """R7: Basic document integrity check — flags suspicious text patterns."""
    suspicious_patterns = [
        r"copy\s*of\s*copy",
        r"do\s*not\s*use",
        r"cancelled",
        r"specimen",
        r"sample\s*document",
        r"void",
        r"for\s*testing",
        r"invalid",
    ]
    flags = []
    for pat in suspicious_patterns:
        if re.search(pat, raw_text, re.IGNORECASE):
            flags.append(pat.replace(r"\s*", " ").replace(r"\b", "").strip())

    # Very short or empty text = likely scanned / low quality
    if len(raw_text.strip()) < 100:
        flags.append("Extracted text is abnormally short — possible scanned image or corrupted PDF.")

    if not flags:
        return RuleVerdict(
            rule_id="R7", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="PASS",
            evidence="No suspicious watermarks, void marks, or integrity issues detected in document text.",
            reasoning="Document passed basic integrity checks."
        )
    else:
        return RuleVerdict(
            rule_id="R7", name=rule_cfg["name"], clause=rule_cfg["clause"],
            severity=rule_cfg["severity"], status="UNCERTAIN",
            evidence=f"Flags detected: {', '.join(flags)}",
            reasoning=f"{rule_cfg['rejection_message']} Human review strongly recommended."
        )


# ─────────────────────────────────────────────────────────────
# Main Public API
# ─────────────────────────────────────────────────────────────
def check_document(
    fields: Dict[str, Any],
    application_context: Dict[str, Any],
    raw_text: str = ""
) -> List[Dict[str, Any]]:
    """
    Run all 7 AICTE compliance rules against extracted FDR fields.

    Args:
        fields: Output of extract_fdr_fields()["fields"]
        application_context: {
            "institute_name": str,
            "category": str,         # Technical / Management / etc.
            "required_amount": float  # Optional override
        }
        raw_text: Raw extracted text for integrity checks (R7)

    Returns:
        List of RuleVerdict dicts (JSON-serialisable)
    """
    rules_config = load_rules_config()
    approved_banks = load_approved_banks()

    # Build rule lookup
    rule_map = {r["id"]: r for r in rules_config}

    results = [
        _check_r1_beneficiary(fields, rule_map.get("R1", {"id": "R1", "name": "Beneficiary Verification",
            "clause": "AICTE APH Clause 4.1.2", "severity": "FATAL",
            "rejection_message": "FDR not in favour of Member Secretary, AICTE."})),

        _check_r2_bank(fields, rule_map.get("R2", {"id": "R2", "name": "Approved Bank Verification",
            "clause": "AICTE APH Clause 4.1.2", "severity": "FATAL",
            "rejection_message": "Bank not in approved list."}), approved_banks),

        _check_r3_tenure(fields, rule_map.get("R3", {"id": "R3", "name": "Tenure Compliance",
            "clause": "AICTE APH Clause 4.1.3", "severity": "FATAL",
            "minimum_tenure_years": 8.0, "tolerance_days": 15,
            "rejection_message": "Tenure less than 8 years."})),

        _check_r4_amount(fields, rule_map.get("R4", {"id": "R4", "name": "Prescribed Security Amount",
            "clause": "AICTE APH Clause 4.1.4", "severity": "FATAL",
            "default_required_amount": 1500000.0, "category_thresholds": {},
            "rejection_message": "Amount below threshold."}), application_context),

        _check_r5_institute_name(fields, rule_map.get("R5", {"id": "R5", "name": "Institute Identity Match",
            "clause": "AICTE APH Clause 2.3.1", "severity": "FATAL",
            "match_threshold": 85.0,
            "rejection_message": "Institute name mismatch."}), application_context),

        _check_r6_date_logic(fields, rule_map.get("R6", {"id": "R6", "name": "Date Logic & Validity",
            "clause": "AICTE APH Clause 4.1.5", "severity": "WARNING",
            "rejection_message": "Invalid date logic."})),

        _check_r7_integrity(fields, raw_text, rule_map.get("R7", {"id": "R7", "name": "Document Integrity",
            "clause": "AICTE APH Clause 1.4", "severity": "WARNING",
            "rejection_message": "Integrity anomaly detected."})),
    ]

    return [r.to_dict() for r in results]


def get_overall_verdict(rule_results: List[Dict[str, Any]]) -> str:
    """
    Compute overall document verdict from rule results.
    Returns: "PASS" | "FAIL" | "UNCERTAIN"
    """
    statuses = [r["status"] for r in rule_results]
    fatal_rules = [r for r in rule_results if r["severity"] == "FATAL"]
    fatal_statuses = [r["status"] for r in fatal_rules]

    if "FAIL" in fatal_statuses:
        return "FAIL"
    if "UNCERTAIN" in statuses:
        return "UNCERTAIN"
    return "PASS"
