"""
Draft deficiency letter for a non-compliant Security Deposit FDR.

The letter is a DRAFT until an officer confirms it in the app; the system never
sends it on its own. Only items the officer has accepted are included when
`confirmed_rule_ids` is passed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _deficient(rule_results: List[Dict[str, Any]], confirmed: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    if confirmed is not None:
        keep = set(confirmed)
        return [r for r in rule_results if r["rule_id"] in keep]
    return [r for r in rule_results if r["status"] == "FAIL"]


def generate_deficiency_letter(fields: Dict[str, Any], rule_results: List[Dict[str, Any]],
                               application_context: Dict[str, Any], officer_name: Optional[str] = None,
                               reference_number: Optional[str] = None,
                               confirmed_rule_ids: Optional[Iterable[str]] = None,
                               draft: bool = True) -> str:
    today = datetime.today()
    inst = application_context.get("institute_name") or fields.get("depositor_name") or "the Institute"
    app_id = application_context.get("app_id", "-")
    ref = reference_number or f"SD/{app_id}/{today:%Y%m%d}"
    items = _deficient(rule_results, confirmed_rule_ids)

    L = []
    if draft:
        L += ["DRAFT - generated for officer review. Not issued until approved by the Regional Office.", ""]
    L += [f"Ref: {ref}", f"Date: {today:%d %B %Y}", "",
          "To", "The Principal / Director", inst, f"Application No.: {app_id}", "",
          "Subject: Deficiencies in the Security Deposit (FDR) submitted with your application", "",
          f"FDR No. {fields.get('fdr_number') or 'not readable'}, issued by {fields.get('bank_name') or 'bank not readable'}.",
          "", "Sir / Madam,", "",
          "The Fixed Deposit Receipt submitted towards the Security Deposit has been scrutinised. "
          "The following points need to be rectified:", ""]
    if not items:
        L += ["  No deficiency has been confirmed.", ""]
    for i, r in enumerate(items, 1):
        L += [f"  {i}. {r['name']}  [{r['rule_id']}; {r['clause']}]",
              f"     Found: {r['evidence']}",
              f"     Required action: {r.get('fix') or r.get('reasoning', '')}", ""]
    L += ["Please submit the rectified FDR (original to the Regional Office, scanned copy on the portal) "
          "along with the affidavit, within the time allowed by the Regional Office.", "",
          "Yours faithfully,", "", officer_name or "Scrutiny Officer", "Regional Office", ""]
    return "\n".join(L)


def get_deficiency_summary(rule_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    fatal = sum(1 for r in rule_results if r["status"] == "FAIL" and r["severity"] == "FATAL")
    unc = sum(1 for r in rule_results if r["status"] == "UNCERTAIN")
    return {
        "total_rules": len(rule_results),
        "passed": sum(1 for r in rule_results if r["status"] == "PASS"),
        "failed": sum(1 for r in rule_results if r["status"] == "FAIL"),
        "uncertain": unc, "fatal_fails": fatal,
        "overall": "FAIL" if fatal else ("UNCERTAIN" if unc else "PASS"),
        "needs_letter": fatal > 0,
    }
