"""
Field Extraction Module for AICTE Fixed Deposit Receipts (FDR)
Supports:
1. Native PDF text extraction (via pypdf / pdfplumber)
2. Streamlit BytesIO / File-like input or file path string
3. Pattern-based field parsing for Indian Banking FDR layouts
4. Offline cache fallback for deterministic zero-latency demo runs
"""

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Attempt imports for pdf extractors with graceful fallback
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


DATE_PATTERNS = [
    r"(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4})",       # DD/MM/YYYY or DD-MM-YYYY
    r"(\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})",       # YYYY/MM/DD
    r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4})" # 10 May 2026
]

def parse_date_str(date_str: str) -> Optional[datetime]:
    """Parse flexible date strings to standard datetime object."""
    if not date_str:
        return None
    cleaned = date_str.strip().replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d %b %Y", "%d %B %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def extract_raw_text(pdf_source: Union[str, Path, bytes, io.BytesIO]) -> str:
    """Extract plain text from PDF path or bytes."""
    # Convert path or bytes into BytesIO if bytes
    stream: io.BytesIO
    if isinstance(pdf_source, (str, Path)):
        path = Path(pdf_source)
        if not path.exists():
            return ""
        with open(path, "rb") as f:
            stream = io.BytesIO(f.read())
    elif isinstance(pdf_source, bytes):
        stream = io.BytesIO(pdf_source)
    elif isinstance(pdf_source, io.BytesIO):
        stream = pdf_source
        stream.seek(0)
    else:
        try:
            # Handle Streamlit UploadedFile
            stream = io.BytesIO(pdf_source.read())
        except Exception:
            return ""

    text = ""
    # Method 1: pypdf
    if PYPDF_AVAILABLE:
        try:
            reader = pypdf.PdfReader(stream)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception:
            pass

    # Method 2: pdfplumber if pypdf got nothing
    if not text.strip() and PDFPLUMBER_AVAILABLE:
        try:
            stream.seek(0)
            with pdfplumber.open(stream) as pdf:
                for page in pdf.pages:
                    p_text = page.extract_text()
                    if p_text:
                        text += p_text + "\n"
        except Exception:
            pass

    return text.strip()


def parse_fdr_fields_from_text(raw_text: str) -> Dict[str, Any]:
    """
    Regex & pattern parser tuned for AICTE Fixed Deposit Receipt layouts.
    """
    fields: Dict[str, Any] = {
        "fdr_number": None,
        "bank_name": None,
        "branch": None,
        "institute_name": None,
        "beneficiary_name": None,
        "amount": None,
        "issue_date": None,
        "maturity_date": None,
        "tenure_years": None,
        "auto_renew": False
    }

    if not raw_text:
        return fields

    # 1. FDR / Account Number
    fdr_match = re.search(r"(?:FDR\s*(?:No\.?|Number)|Fixed\s*Deposit\s*No\.?|Receipt\s*No\.?|A\/C\s*No\.?)\s*[:\-]?\s*([A-Za-z0-9\/\-_]+)", raw_text, re.IGNORECASE)
    if fdr_match:
        fields["fdr_number"] = fdr_match.group(1).strip()

    # 2. Bank Name
    known_banks = [
        "State Bank of India", "Punjab National Bank", "Bank of Baroda", "Canara Bank",
        "Union Bank of India", "Bank of India", "Indian Bank", "Central Bank of India",
        "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank", "Bank of Maharashtra"
    ]
    for bank in known_banks:
        if re.search(rf"\b{re.escape(bank)}\b", raw_text, re.IGNORECASE):
            fields["bank_name"] = bank
            break
    if not fields["bank_name"]:
        bank_match = re.search(r"([A-Za-z\s]+Bank(?: of [A-Za-z]+)?)", raw_text, re.IGNORECASE)
        if bank_match:
            fields["bank_name"] = bank_match.group(1).strip()

    # 3. Branch
    branch_match = re.search(r"(?:Branch|Branch\s*Name|IFSC(?:\s*Code)?)\s*[:\-]?\s*([A-Za-z0-9\s,\-\.]+?)(?=\n|$|Date|FDR)", raw_text, re.IGNORECASE)
    if branch_match:
        fields["branch"] = branch_match.group(1).strip()

    # 4. Beneficiary ("In favour of")
    ben_match = re.search(r"(?:In\s*favour\s*of|Beneficiary|Payable\s*to|Favouring)\s*[:\-]?\s*([^\n\r]+)", raw_text, re.IGNORECASE)
    if ben_match:
        fields["beneficiary_name"] = ben_match.group(1).strip()
    elif "member secretary" in raw_text.lower() and "aicte" in raw_text.lower():
        fields["beneficiary_name"] = "Member Secretary, AICTE"

    # 5. Institute / Depositor
    inst_match = re.search(r"(?:Depositor|Institute(?:\s*Name)?|Account\s*Holder|In\s*the\s*name\s*of|M\/s\.?)\s*[:\-]?\s*([^\n\r]+)", raw_text, re.IGNORECASE)
    if inst_match:
        fields["institute_name"] = inst_match.group(1).strip()

    # 6. Amount
    amt_match = re.search(r"(?:Amount|Principal|Deposit\s*Amount|Rs\.?|INR)\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)", raw_text, re.IGNORECASE)
    if amt_match:
        val_str = amt_match.group(1).replace(",", "").strip()
        try:
            fields["amount"] = float(val_str)
        except ValueError:
            pass

    # 7. Dates (Issue Date & Maturity Date)
    issue_match = re.search(r"(?:Date\s*of\s*Issue|Issue\s*Date|Issued\s*on|Date\s*of\s*Deposit|Deposit\s*Date)\s*[:\-]?\s*([A-Za-z0-9\/\-\.\s,]+?)(?=\n|$|Maturity|Tenure)", raw_text, re.IGNORECASE)
    if issue_match:
        raw_issue = issue_match.group(1).strip()
        for pat in DATE_PATTERNS:
            sub = re.search(pat, raw_issue)
            if sub:
                dt = parse_date_str(sub.group(1))
                if dt:
                    fields["issue_date"] = dt.strftime("%Y-%m-%d")
                    break

    mat_match = re.search(r"(?:Date\s*of\s*Maturity|Maturity\s*Date|Due\s*Date|Valid\s*upto)\s*[:\-]?\s*([A-Za-z0-9\/\-\.\s,]+?)(?=\n|$|Tenure|Amount)", raw_text, re.IGNORECASE)
    if mat_match:
        raw_mat = mat_match.group(1).strip()
        for pat in DATE_PATTERNS:
            sub = re.search(pat, raw_mat)
            if sub:
                dt = parse_date_str(sub.group(1))
                if dt:
                    fields["maturity_date"] = dt.strftime("%Y-%m-%d")
                    break

    # 8. Calculate Tenure if dates found
    if fields["issue_date"] and fields["maturity_date"]:
        try:
            d1 = datetime.strptime(fields["issue_date"], "%Y-%m-%d")
            d2 = datetime.strptime(fields["maturity_date"], "%Y-%m-%d")
            days = (d2 - d1).days
            fields["tenure_years"] = round(days / 365.25, 2)
        except Exception:
            pass

    # 9. Auto-renew flag
    if re.search(r"auto[\s\-]renew|automatic\s*renewal|roll[\s\-]over", raw_text, re.IGNORECASE):
        fields["auto_renew"] = True

    return fields


def extract_fdr_fields(
    pdf_source: Union[str, Path, bytes, io.BytesIO],
    precomputed_cache: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    High-level extraction entrypoint for A-2 (Streamlit).
    Returns dict with fields, raw_text, is_scanned flag, and extraction confidence.
    """
    if precomputed_cache:
        return {
            "fields": precomputed_cache,
            "raw_text": precomputed_cache.get("raw_text", ""),
            "is_scanned": False,
            "confidence": 1.0,
            "source": "cache"
        }

    raw_text = extract_raw_text(pdf_source)
    is_scanned = len(raw_text.strip()) < 30

    fields = parse_fdr_fields_from_text(raw_text)

    # Estimate field completeness confidence
    extracted_keys = [k for k, v in fields.items() if v is not None]
    key_fields = ["fdr_number", "bank_name", "beneficiary_name", "amount", "issue_date", "maturity_date"]
    present_keys = [k for k in key_fields if fields.get(k) is not None]
    confidence = round(len(present_keys) / len(key_fields), 2)

    return {
        "fields": fields,
        "raw_text": raw_text,
        "is_scanned": is_scanned,
        "confidence": confidence,
        "source": "text_extracted"
    }
