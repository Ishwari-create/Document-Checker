"""
One call that runs the whole check:

  read -> decide document type -> extract fields (labels, then ML fallback)
  -> authenticity checks -> rule pack for that type -> ledger + audit log
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extractor import extract_document
from .registry import IssuerConnector, Ledger, sha256_of
from .render import ocr_status
from .rule_engine import _v, check_document, get_overall_verdict, rules_version

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
    # bank QR disagrees with what OCR read: likely an OCR misreading, unless the scan itself shows a pasted region
    qr_doubt = by.get("A3", {}).get("status") == "UNCERTAIN" and by.get("A4", {}).get("status") != "FAIL"
    if by.get("R8", {}).get("status") != "FAIL" and not qr_doubt:
        return
    for rid in AMOUNT_RULES:
        r = by.get(rid)
        if r and r["status"] == "FAIL" and (rid != "R9" or set(r["fields"]) <= {"fdr_number", "amount"}):
            r["status"] = "UNCERTAIN"
            r["ps_status"] = "Manual review required"
            r["reasoning"] += " (Scanned copy: the amount may have been misread, so an officer must compare it with the original.)"


ABSENCE_RULES = {"F1", "F2", "F6"}


def _scan_absence_safety(results: List[Dict[str, Any]]) -> None:
    """On a scan, 'not found' may only mean OCR missed a line, so a rule that fails
    because something is absent goes to an officer instead of failing the document."""
    for r in results:
        if r["rule_id"] in ABSENCE_RULES and r["status"] == "FAIL" and ("No " in r["evidence"] or "Missing" in r["evidence"]):
            r["status"] = "UNCERTAIN"
            r["ps_status"] = "Manual review required"
            r["reasoning"] += " (Scanned copy: the text may have been missed by OCR, so an officer must look at the original.)"


def _ocr_missing_reason(results: List[Dict[str, Any]]) -> None:
    """A scan on a computer without Tesseract: say why every rule is unsure."""
    for r in results:
        if r["status"] == "UNCERTAIN":
            r["reasoning"] = ("This is a scanned copy and the OCR engine (Tesseract) is not installed, so the "
                              "text could not be read. An officer must check this point on the original.")
            r["ps_status"] = "Manual review required"


def _ml_marks(results: List[Dict[str, Any]], fields: Dict[str, Any], scanned: bool = False) -> None:
    """Say which findings rest on values the ML extractor found, and never let a
    low-confidence ML value fail a document on its own."""
    ml = fields.get("_ml_filled") or {}
    low = set(fields.get("_ml_low_confidence") or [])
    for r in results:
        used = [f for f in r.get("fields", []) if f in ml]
        if not used:
            continue
        r["ml_fields"] = {f: ml[f] for f in used}
        note = "; ".join(f"{f.replace('_', ' ')} found by the ML extractor (confidence {ml[f]['confidence']:.0%}, "
                         f"label read as '{ml[f]['label_seen']}')" for f in used)
        r["evidence"] += f"  [{note}]"
        if r["status"] == "FAIL" and (set(used) & low or scanned):
            r["status"] = "UNCERTAIN"
            r["ps_status"] = "Manual review required"
            r["reasoning"] += (" The value was found by the ML extractor" + (" on a scanned copy" if scanned else " with low confidence")
                               + ", so an officer must confirm it.")


DT_CFG = {"id": "D0", "name": "Document type recognised", "problem": "Not a supported document",
          "clause": "Pre-check before any rule pack", "severity": "FATAL", "source": "PS", "verified": True}


def run_check(pdf_bytes: bytes, application: Dict[str, Any], *, submitted_on: Optional[date] = None,
              issuer: Optional[IssuerConnector] = None, ledger: Optional[Ledger] = None,
              actor: str = "system", record: bool = True, expect: Optional[str] = None,
              use_ml: bool = True, authenticity: bool = True) -> Dict[str, Any]:
    """
    expect: 'fdr' or 'fire_noc' when the upload slot says what the document should be;
            a different detected type then becomes a finding.
    """
    sha = sha256_of(pdf_bytes)
    ext = extract_document(pdf_bytes)
    dt = ext["doc_type"]
    sub = submitted_on or date.today()

    # ---- D0: what is this document?
    if dt["type"] is None:
        if ext["method"] == "ocr-missing":
            d0 = _v(DT_CFG, "UNCERTAIN", "Scanned copy; no text could be read.",
                    "The OCR engine is not installed, so the document type could not be decided. "
                    "An officer must look at it.", fix="Install Tesseract OCR or check the document by hand.")
        else:
            d0 = _v(DT_CFG, "FAIL", "No FDR, Fire NOC or affidavit wording found in the document.",
                    "This is not a Security Deposit FDR, Fire NOC or affidavit, so no rule pack can be run.",
                    fix="Upload the Fixed Deposit Receipt (or Fire NOC) itself, not a covering letter or another document.")
        results = [d0]
        version = "doc-type"
    else:
        d0 = _v(DT_CFG, "PASS", f"Recognised as: {dt['name']} (matched: {', '.join(dt['matched'][:3])})",
                "Document type decided before running its rule pack.")
        if expect and expect != dt["type"]:
            d0 = _v(DT_CFG, "FAIL", f"Expected {expect.upper()}, but this is a {dt['name']}.",
                    "The document uploaded in this slot is a different type.", fix="Upload the correct document.")
        if dt["type"] == "fire_noc":
            from .noc_rules import check_fire_noc, noc_rules_version
            results = [d0] + check_fire_noc(ext["fields"], application, submitted_on=sub)
            version = noc_rules_version()
        elif dt["type"] == "affidavit":
            from .affidavit_rules import affidavit_rules_version, check_affidavit
            results = [d0] + check_affidavit(ext["fields"], application, submitted_on=sub)
            version = affidavit_rules_version()
        else:
            if use_ml:
                from .ml_extractor import fill_missing_fields
                fill_missing_fields(ext)
            results = [d0] + check_document(ext["fields"], application, ext["raw_text"], submitted_on=sub,
                                            issuer=issuer, ledger=ledger, sha256=sha)
            _ml_marks(results, ext["fields"], scanned=ext["method"] == "ocr")
            version = rules_version()
        if authenticity:
            from .authenticity import authenticity_checks
            results += authenticity_checks(pdf_bytes, ext)

    if ext["method"] == "ocr":
        _scan_safety(results)
        _scan_absence_safety(results)
    if ext["method"] == "ocr-missing":
        _ocr_missing_reason(results)

    overall = get_overall_verdict(results)
    # A poor scan never gets a clean PASS on its own word.
    if overall == "PASS" and ext["method"] == "ocr" and ext["read_quality"] < 0.75:
        overall = "UNCERTAIN"
    if ledger is not None and record:
        f = ext["fields"]
        ledger.record_submission(application.get("app_id", "?"), f.get("fdr_number") or f.get("noc_number"),
                                 f.get("bank_name") or f.get("issuing_authority"), sha)
        ledger.log(actor, "automated_check", application.get("app_id", "?"), sha, version, overall,
                   {r["rule_id"]: r["status"] for r in results})
    ext.pop("bytes", None)
    return {"sha256": sha, "extraction": ext, "results": results, "overall": overall,
            "rules_version": version, "doc_type": dt, "ocr": ocr_status()}
