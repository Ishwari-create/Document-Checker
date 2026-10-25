"""
Deficiency Letter Generator for AICTE Document Scrutiny
Generates a formal, clause-cited deficiency letter for non-compliant FDRs.
Consumed by A-2 (Streamlit) to let officers download/print the letter.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


LETTER_HEADER = """AICTE - DEFICIENCY NOTICE
All India Council for Technical Education
Nelson Mandela Marg, Vasant Kunj, New Delhi – 110 070
Phone: 011-29581000 | website: www.aicte-india.org
─────────────────────────────────────────────────────────────────────────
"""

LETTER_FOOTER = """─────────────────────────────────────────────────────────────────────────
NOTE: This notice is system-generated based on automated document analysis.
The institute must resubmit a compliant Fixed Deposit Receipt within 30 days
of the date of this notice. Failure to comply may result in rejection of the
application or withdrawal of approval.

For queries, contact:
Bureau of Planning, Policy & Administration
All India Council for Technical Education
─────────────────────────────────────────────────────────────────────────
"""


def generate_deficiency_letter(
    fields: Dict[str, Any],
    rule_results: List[Dict[str, Any]],
    application_context: Dict[str, Any],
    officer_name: Optional[str] = None,
    reference_number: Optional[str] = None
) -> str:
    """
    Generate a formal deficiency letter for failed/uncertain FATAL rules.

    Args:
        fields: Extracted FDR fields from extractor.py
        rule_results: List of RuleVerdict dicts from rule_engine.py
        application_context: { "institute_name": str, "category": str, ... }
        officer_name: Optional scrutiny officer name
        reference_number: Optional reference/application number

    Returns:
        Formatted deficiency letter as a plain-text string
    """
    today = datetime.today()
    date_str = today.strftime("%d %B %Y")

    institute = application_context.get("institute_name") or fields.get("institute_name") or "Concerned Institute"
    category = application_context.get("category", "Technical")
    ref = reference_number or "AUTO-" + today.strftime("%Y%m%d%H%M")
    officer = officer_name or "Bureau of Planning, Policy & Administration"

    # Filter failing or uncertain FATAL rules
    deficient_rules = [
        r for r in rule_results
        if r["status"] in ("FAIL", "UNCERTAIN") and r["severity"] == "FATAL"
    ]

    # FDR details for salutation
    fdr_number = fields.get("fdr_number") or "N/A"
    bank_name = fields.get("bank_name") or "N/A"

    lines = []
    lines.append(LETTER_HEADER)
    lines.append(f"Reference No: {ref}")
    lines.append(f"Date: {date_str}\n")

    lines.append(f"To,")
    lines.append(f"The Principal/Director,")
    lines.append(f"{institute},")
    lines.append(f"(Category: {category})\n")

    lines.append("Sub: Deficiency in Fixed Deposit Receipt Submitted for AICTE Compliance")
    lines.append(f"       (FDR No.: {fdr_number} | Bank: {bank_name})\n")

    lines.append("Sir/Madam,\n")

    if not deficient_rules:
        lines.append("On scrutiny of the Fixed Deposit Receipt submitted by your institute, "
                     "no critical deficiencies were found. However, the following items require "
                     "manual review and officer attention before final approval:\n")
        uncertain = [r for r in rule_results if r["status"] == "UNCERTAIN"]
        for i, r in enumerate(uncertain, 1):
            lines.append(f"  {i}. [{r['rule_id']}] {r['name']} ({r['clause']})")
            lines.append(f"     Evidence: {r['evidence']}")
            lines.append(f"     Note: {r['reasoning']}\n")
    else:
        lines.append("On scrutiny of the Fixed Deposit Receipt (FDR) submitted by your institute, "
                     "the following deficiencies/non-compliances have been identified in terms "
                     "of the AICTE Approval Process Handbook (APH):\n")

        for i, r in enumerate(deficient_rules, 1):
            status_label = "NON-COMPLIANT" if r["status"] == "FAIL" else "REQUIRES VERIFICATION"
            lines.append(f"  {i}. [{r['rule_id']}] {r['name']}  ── {status_label}")
            lines.append(f"     Handbook Reference: {r['clause']}")
            lines.append(f"     Evidence: {r['evidence']}")
            lines.append(f"     Reason: {r['reasoning']}\n")

    lines.append("You are, therefore, directed to rectify the above deficiencies and submit a "
                 "corrected Fixed Deposit Receipt along with supporting documents within "
                 "30 (thirty) days from the date of this notice.\n")

    lines.append("Failure to submit the required documents within the stipulated time may "
                 "result in rejection of the application or initiation of further action "
                 "as per AICTE norms.\n")

    lines.append("Yours faithfully,\n")
    lines.append(f"{officer}")
    lines.append("All India Council for Technical Education\n")

    # Append all rule statuses as a summary table
    lines.append("─────────────────────────────────────────────────────────────────────────")
    lines.append("AUTOMATED VERIFICATION SUMMARY")
    lines.append(f"{'Rule':<6} {'Name':<35} {'Clause':<25} {'Status'}")
    lines.append("─" * 90)
    for r in rule_results:
        lines.append(f"{r['rule_id']:<6} {r['name']:<35} {r['clause']:<25} {r['status']}")

    lines.append(LETTER_FOOTER)

    return "\n".join(lines)


def get_deficiency_summary(rule_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Returns a short summary dict for dashboard display (A-2 use).
    """
    total = len(rule_results)
    passed = sum(1 for r in rule_results if r["status"] == "PASS")
    failed = sum(1 for r in rule_results if r["status"] == "FAIL")
    uncertain = sum(1 for r in rule_results if r["status"] == "UNCERTAIN")
    fatal_fails = sum(1 for r in rule_results if r["status"] == "FAIL" and r["severity"] == "FATAL")

    return {
        "total_rules": total,
        "passed": passed,
        "failed": failed,
        "uncertain": uncertain,
        "fatal_fails": fatal_fails,
        "overall": "FAIL" if fatal_fails > 0 else ("UNCERTAIN" if uncertain > 0 else "PASS"),
        "needs_letter": fatal_fails > 0 or uncertain > 0
    }
