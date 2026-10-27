"""One call that runs the whole check: read -> extract -> rules -> ledger/audit."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extractor import extract_fdr_fields
from .registry import IssuerConnector, Ledger, sha256_of
from .rule_engine import check_document, get_overall_verdict, rules_version

ROOT = Path(__file__).resolve().parent.parent


def load_applications() -> Dict[str, dict]:
    data = json.loads((ROOT / "data" / "applications.json").read_text())
    return {a["app_id"]: a for a in data["applications"]}


AMOUNT_RULES = {"R4", "R8", "R9"}


def _scan_safety(results: List[Dict[str, Any]]) -> None:
    """On a scan, a disagreement between the amount in figures and in words is more
    often a misread digit than an altered receipt. In that case no amount-based rule
    may fail the document on its own; each goes to the officer instead."""
    by = {r["rule_id"]: r for r in results}
    if by.get("R8", {}).get("status") != "FAIL":
        return
    for rid in AMOUNT_RULES:
        r = by.get(rid)
        if r and r["status"] == "FAIL" and (rid != "R9" or set(r["fields"]) <= {"fdr_number", "amount"}):
            r["status"] = "UNCERTAIN"
            r["ps_status"] = "Manual review required"
            r["reasoning"] += " (Scanned copy: the amount may have been misread, so an officer must compare it with the original.)"


def run_check(pdf_bytes: bytes, application: Dict[str, Any], *, submitted_on: Optional[date] = None,
              issuer: Optional[IssuerConnector] = None, ledger: Optional[Ledger] = None,
              actor: str = "system", record: bool = True) -> Dict[str, Any]:
    sha = sha256_of(pdf_bytes)
    ext = extract_fdr_fields(pdf_bytes)
    f = ext["fields"]
    results = check_document(f, application, ext["raw_text"], submitted_on=submitted_on,
                             issuer=issuer, ledger=ledger, sha256=sha)
    if ext["method"] == "ocr":
        _scan_safety(results)
    overall = get_overall_verdict(results)
    # A poor scan never gets a clean PASS on its own word.
    if overall == "PASS" and ext["method"] == "ocr" and ext["read_quality"] < 0.75:
        overall = "UNCERTAIN"
    version = rules_version()
    if ledger is not None and record:
        ledger.record_submission(application.get("app_id", "?"), f.get("fdr_number"), f.get("bank_name"), sha)
        ledger.log(actor, "automated_check", application.get("app_id", "?"), sha, version, overall,
                   {r["rule_id"]: r["status"] for r in results})
    return {"sha256": sha, "extraction": ext, "results": results, "overall": overall,
            "rules_version": version}
