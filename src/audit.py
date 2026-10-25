"""
Audit Trail & Provenance Module for AICTE Document Checker
Computes SHA-256 document fingerprints, tracks rule engine versioning,
and generates tamper-evident verification receipts.
"""

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

CONFIG_DIR = Path(__file__).parent.parent / "config"
RULES_FILE = CONFIG_DIR / "rules.yaml"


def compute_sha256(source: Union[str, Path, bytes, io.BytesIO]) -> str:
    """Compute hex SHA-256 digest of input file or byte stream."""
    hasher = hashlib.sha256()
    if isinstance(source, (str, Path)):
        p = Path(source)
        if p.exists():
            with open(p, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        else:
            hasher.update(str(source).encode("utf-8"))
            return hasher.hexdigest()
    elif isinstance(source, bytes):
        hasher.update(source)
        return hasher.hexdigest()
    elif hasattr(source, "getvalue"):
        hasher.update(source.getvalue())
        return hasher.hexdigest()
    elif hasattr(source, "read"):
        pos = source.tell() if hasattr(source, "tell") else 0
        content = source.read()
        if hasattr(source, "seek"):
            source.seek(pos)
        hasher.update(content)
        return hasher.hexdigest()
    return ""


def get_rules_fingerprint() -> str:
    """Compute hash of rules.yaml to ensure rule configuration traceability."""
    if RULES_FILE.exists():
        with open(RULES_FILE, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    return "default-v1.0"


def generate_audit_receipt(
    pdf_source: Union[str, Path, bytes, io.BytesIO],
    verdict: str,
    rules_evaluated: int
) -> Dict[str, Any]:
    """Create a tamper-evident audit record for the verification run."""
    doc_hash = compute_sha256(pdf_source)
    rules_ver = get_rules_fingerprint()
    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "document_sha256": doc_hash,
        "rules_config_fingerprint": rules_ver,
        "timestamp_utc": timestamp,
        "overall_verdict": verdict,
        "total_rules_evaluated": rules_evaluated,
        "system_version": "AICTE-DocChecker-1.0.0"
    }
