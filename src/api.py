"""
Verification Check Endpoint & Service API (A-1)
Provides:
1. Pure Python high-level API `verify_fdr()` combining extractor, audit, rules, and deficiency generator
2. Optional FastAPI REST endpoint `/api/check` for remote or microservice integration
3. CLI interface `python -m src.api path/to/fdr.pdf`
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from src.audit import generate_audit_receipt
from src.deficiency import generate_deficiency_letter, get_deficiency_summary
from src.extractor import extract_fdr_fields
from src.rule_engine import check_document, get_overall_verdict


def verify_fdr(
    pdf_source: Union[str, Path, bytes, Any],
    application_context: Optional[Dict[str, Any]] = None,
    officer_name: Optional[str] = None,
    reference_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete end-to-end scrutiny pipeline:
    1. Extract key fields from PDF / stream
    2. Run all 7 AICTE compliance rules
    3. Calculate overall verdict & summary
    4. Generate clause-cited deficiency letter (if needed)
    5. Stamp tamper-evident SHA-256 audit receipt
    """
    ctx = application_context or {
        "institute_name": "Apex Institute of Technology",
        "category": "Technical",
        "required_amount": 1500000.0
    }

    # 1. Extraction
    extraction_result = extract_fdr_fields(pdf_source)
    fields = extraction_result["fields"]
    raw_text = extraction_result["raw_text"]

    # 2. Rule evaluation
    rule_results = check_document(fields, ctx, raw_text=raw_text)

    # 3. Overall verdict & summary metrics
    overall_verdict = get_overall_verdict(rule_results)
    summary = get_deficiency_summary(rule_results)

    # 4. Deficiency letter
    deficiency_letter = None
    if summary["needs_letter"]:
        deficiency_letter = generate_deficiency_letter(
            fields=fields,
            rule_results=rule_results,
            application_context=ctx,
            officer_name=officer_name,
            reference_number=reference_number
        )

    # 5. Audit trail & fingerprinting
    audit = generate_audit_receipt(
        pdf_source=pdf_source,
        verdict=overall_verdict,
        rules_evaluated=len(rule_results)
    )

    return {
        "verdict": overall_verdict,
        "summary": summary,
        "extracted_fields": fields,
        "rule_results": rule_results,
        "deficiency_letter": deficiency_letter,
        "audit": audit,
        "metadata": {
            "is_scanned": extraction_result["is_scanned"],
            "extraction_confidence": extraction_result["confidence"],
            "extraction_source": extraction_result["source"]
        }
    }


# ─────────────────────────────────────────────────────────────
# Optional FastAPI REST App
# ─────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, File, Form, UploadFile
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="AICTE Document Checker API (SIH26261)",
        description="Automated AICTE FDR Verification and Clause Scrutiny Engine",
        version="1.0.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health_check():
        return {"status": "ok", "service": "aicte-docchecker"}

    @app.post("/api/check")
    async def check_endpoint(
        file: UploadFile = File(...),
        institute_name: str = Form("Apex Institute of Technology"),
        category: str = Form("Technical"),
        required_amount: float = Form(1500000.0)
    ):
        contents = await file.read()
        app_ctx = {
            "institute_name": institute_name,
            "category": category,
            "required_amount": required_amount
        }
        return verify_fdr(contents, app_ctx)

except ImportError:
    app = None


# ─────────────────────────────────────────────────────────────
# CLI Entrypoint
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AICTE FDR Document Scrutiny CLI")
    parser.add_argument("pdf_path", type=str, help="Path to FDR PDF file")
    parser.add_argument("--institute", type=str, default="Apex Institute of Technology", help="Reference institute name")
    parser.add_argument("--category", type=str, default="Technical", help="AICTE institute category")
    parser.add_argument("--amount", type=float, default=1500000.0, help="Required security deposit amount")
    args = parser.parse_args()

    result = verify_fdr(
        pdf_source=args.pdf_path,
        application_context={
            "institute_name": args.institute,
            "category": args.category,
            "required_amount": args.amount
        }
    )

    print(f"\n================ VERIFICATION RESULT: {result['verdict']} ================")
    print(f"Document SHA-256: {result['audit']['document_sha256']}")
    print(f"Summary: Passed={result['summary']['passed']}, Failed={result['summary']['failed']}, Uncertain={result['summary']['uncertain']}\n")
    for r in result["rule_results"]:
        status_icon = "✓" if r["status"] == "PASS" else ("✗" if r["status"] == "FAIL" else "?")
        print(f"[{status_icon}] {r['rule_id']}: {r['name']} ({r['clause']}) -> {r['status']}")
        print(f"    Evidence: {r['evidence']}")
        print(f"    Reason: {r['reasoning']}\n")

    if result["deficiency_letter"]:
        print("Deficiency Letter Generated:")
        print(result["deficiency_letter"][:300] + "...\n[Full letter available in result['deficiency_letter']]")
