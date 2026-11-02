"""
Field extraction for Fixed Deposit Receipts.

Works on both digital PDFs (text layer read with pdfplumber) and scanned PDFs
(page rendered and read with Tesseract OCR). Every extracted field keeps the
page and box it came from, so the screen can draw a box around the evidence
instead of asking the officer to trust a number.

Public entry point: extract_fdr_fields(source) -> dict (see bottom of file).
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import ImageFilter, ImageOps

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:  # pragma: no cover
    PDFPLUMBER_AVAILABLE = False

from .render import ocr_available, ocr_lang_for, ocr_status, render_pages

try:
    import pytesseract
    OCR_AVAILABLE = ocr_available()       # needs the Tesseract program, not just the Python package
except ImportError:  # pragma: no cover
    OCR_AVAILABLE = False

OCR_DPI = 300
MIN_TEXT_CHARS = 40      # below this a page is treated as a scan
SEGMENT_GAP_PT = 28      # horizontal gap that splits one printed row into two cells

PdfSource = Union[str, Path, bytes, io.BytesIO, Any]


# ---------------------------------------------------------------------------
# 1. Reading the page into "segments" (one printed cell of text + its box)
# ---------------------------------------------------------------------------
def _to_bytes(src: PdfSource) -> bytes:
    if isinstance(src, (str, Path)):
        p = Path(src)
        return p.read_bytes() if p.exists() else b""
    if isinstance(src, bytes):
        return src
    if hasattr(src, "getvalue"):
        return src.getvalue()
    if hasattr(src, "read"):
        try:
            src.seek(0)
        except Exception:
            pass
        return src.read()
    return b""


def _split_rows(rows: List[List[dict]], page_no: int) -> List[dict]:
    """Split each printed row into cells wherever there is a wide horizontal gap."""
    out = []
    for row in rows:
        row = sorted(row, key=lambda w: w["x0"])
        cells, current = [], [row[0]]
        for w in row[1:]:
            if w["x0"] - current[-1]["x1"] > SEGMENT_GAP_PT:
                cells.append(current)
                current = [w]
            else:
                current.append(w)
        cells.append(current)
        for cell in cells:
            text = " ".join(w["text"] for w in cell).strip()
            if text:
                out.append({
                    "text": text, "page": page_no,
                    "bbox": [min(w["x0"] for w in cell), min(w["top"] for w in cell),
                             max(w["x1"] for w in cell), max(w["bottom"] for w in cell)],
                })
    return out


def _rows_to_segments(words: List[dict], page_no: int, row_tol: float) -> List[dict]:
    """Group words into rows by vertical position (digital PDFs), then split into cells."""
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: List[List[dict]] = []
    for w in words:
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= row_tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return _split_rows(rows, page_no)


def _cid(c) -> tuple:
    return (round(c["x0"], 2), round(c["top"], 2), c["text"], c.get("fontname"))


def hidden_char_ids(chars: List[dict]) -> set:
    """Characters covered by text drawn later on the same line (an edit pasted over the original).

    Characters are grouped into runs (consecutive in drawing order, same font, same line).
    When a later run sits on top of an earlier run, the earlier characters under it are hidden."""
    runs: List[dict] = []
    for i, c in enumerate(chars):
        if not c["text"].strip():
            continue
        r = runs[-1] if runs else None
        if r and r["font"] == c.get("fontname") and abs(r["top"] - c["top"]) < 2 and c["x0"] >= r["x1"] - 1:
            r["chars"].append(c); r["x1"] = c["x1"]; r["end"] = i
        else:
            runs.append({"font": c.get("fontname"), "top": c["top"], "bottom": c["bottom"], "x0": c["x0"],
                         "x1": c["x1"], "chars": [c], "start": i, "end": i})
    hidden = set()
    spaces = [(i, c) for i, c in enumerate(chars) if not c["text"].strip()]
    for later in runs:
        for i, c in spaces:            # spaces of the old text would split the new words
            if i < later["start"] and abs(c["top"] - later["top"]) < 2 and later["x0"] <= (c["x0"] + c["x1"]) / 2 <= later["x1"]:
                hidden.add(_cid(c))
    for k, later in enumerate(runs):
        for earlier in runs[:k]:
            if abs(earlier["top"] - later["top"]) > 0.6 * (later["bottom"] - later["top"]):
                continue
            ox = min(earlier["x1"], later["x1"]) - max(earlier["x0"], later["x0"])
            if ox <= 2:
                continue
            for c in earlier["chars"]:
                mid = (c["x0"] + c["x1"]) / 2
                if later["x0"] - 0.5 <= mid <= later["x1"] + 0.5:
                    hidden.add(_cid(c))
    return hidden


def _segments_from_text_layer(data: bytes) -> Tuple[List[dict], List[dict]]:
    segments, pages = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            pages.append({"page": i, "width": float(page.width), "height": float(page.height)})
            # Diagonal watermarks ("SAMPLE", "COPY") are rotated text; ignore them.
            def _horizontal(o):
                if o.get("object_type") != "char":
                    return True
                m = o.get("matrix") or (1, 0, 0, 1, 0, 0)
                return o.get("upright", True) and abs(m[1]) < 0.05 and abs(m[2]) < 0.05
            upright = page.filter(_horizontal)
            # Text drawn later covers text drawn earlier (an edit pasted over the original).
            # Read what a person sees: drop characters hidden under a later one.
            hidden = hidden_char_ids(upright.chars)
            if hidden:
                upright = upright.filter(lambda o: o.get("object_type") != "char" or _cid(o) not in hidden)
            words = upright.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)
            segments += _rows_to_segments(words, i, row_tol=3)
    return segments, pages


def _segments_from_ocr(data: bytes) -> Tuple[List[dict], List[dict], float]:
    segments, pages, confs = [], [], []
    scale = 72.0 / OCR_DPI
    for i, img in enumerate(render_pages(data, OCR_DPI)):
        pages.append({"page": i, "width": img.width * scale, "height": img.height * scale})
        # Photocopies carry speckle; a median filter removes dots without eating strokes.
        clean = ImageOps.autocontrast(img.convert("L").filter(ImageFilter.MedianFilter(3)))
        d = pytesseract.image_to_data(clean, lang=ocr_lang_for(clean), output_type=pytesseract.Output.DICT, config="--psm 4")
        words = []
        for k, txt in enumerate(d["text"]):
            txt = (txt or "").strip()
            conf = float(d["conf"][k]) if str(d["conf"][k]) not in ("-1", "") else -1
            if not txt or conf < 0:
                continue
            # Drop specks read as punctuation ("'", "~", "ae") unless OCR is sure.
            if len(re.sub(r"[^A-Za-z0-9]", "", txt)) < 2 and conf < 85:
                continue
            confs.append(conf)
            x, y, w, h = d["left"][k], d["top"][k], d["width"][k], d["height"][k]
            key = (d["block_num"][k], d["par_num"][k], d["line_num"][k])
            words.append({"text": txt, "x0": x * scale, "x1": (x + w) * scale,
                          "top": y * scale, "bottom": (y + h) * scale, "line": key})
        # Tesseract already knows which words share a printed line, even on a skewed scan.
        lines: Dict[tuple, List[dict]] = {}
        for w in words:
            lines.setdefault(w["line"], []).append(w)
        rows = sorted(lines.values(), key=lambda r: min(w["top"] for w in r))
        segments += _split_rows(rows, i)
    mean_conf = sum(confs) / len(confs) / 100 if confs else 0.0
    return segments, pages, mean_conf


def read_document(src: PdfSource) -> Dict[str, Any]:
    """Return segments, page sizes, the method used and a read-quality score."""
    data = _to_bytes(src)
    if not data:
        return {"segments": [], "pages": [], "method": "none", "read_quality": 0.0, "bytes": b""}

    segments, pages = ([], [])
    if PDFPLUMBER_AVAILABLE:
        try:
            segments, pages = _segments_from_text_layer(data)
        except Exception:
            segments, pages = [], []

    chars = sum(len(s["text"]) for s in segments)
    if chars >= MIN_TEXT_CHARS:
        return {"segments": segments, "pages": pages, "method": "text-layer",
                "read_quality": 1.0, "bytes": data}

    if OCR_AVAILABLE:
        try:
            segments, pages, q = _segments_from_ocr(data)
            return {"segments": segments, "pages": pages, "method": "ocr",
                    "read_quality": round(q, 2), "bytes": data}
        except Exception:
            pass
    return {"segments": segments, "pages": pages, "method": "unreadable" if OCR_AVAILABLE else "ocr-missing",
            "read_quality": 0.0, "bytes": data}


# ---------------------------------------------------------------------------
# 2. Value parsers
# ---------------------------------------------------------------------------
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_RE = re.compile(
    rf"(\d{{1,2}}\s*[-/.,]\s*\d{{1,2}}\s*[-/.,]\s*\d{{4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|\d{{1,2}}[\s-]*(?:{_MONTHS})[a-z]*[\s,-]*\d{{4}})",
    re.IGNORECASE,
)


def parse_date(text: str) -> Optional[str]:
    """Find the first date in text and return it as YYYY-MM-DD (Indian day-first order)."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1)).strip()
    raw = re.sub(r"\s*([-/.,])\s*", r"\1", raw)
    raw = re.sub(r"^(\d{1,2})[-/.,](\d{1,2})[-/.,](\d{4})$", r"\1/\2/\3", raw)
    raw = raw.replace("Sept", "Sep").replace("sept", "sep")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y",
                "%d %b %Y", "%d %B %Y", "%d-%B-%Y", "%d %b, %Y", "%d %B, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_amount(text: str) -> Optional[float]:
    """Read an Indian-format figure such as 'Rs. 35,00,000.00' or '₹ 15,00,000/-'."""
    if not text:
        return None
    t = text.replace("O", "0").replace("o", "0") if re.search(r"\d", text) else text
    m = re.search(r"(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{4,}(?:\.\d{1,2})?)", t)
    if not m:
        return None
    try:
        return float(re.sub(r"[,\s]", "", m.group(1)))
    except ValueError:
        return None


_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000,
           "lac": 100_000, "lacs": 100_000, "crore": 10_000_000, "crores": 10_000_000}


def words_to_number(text: str) -> Optional[float]:
    """'Rupees Thirty Five Lakh Fifty Thousand Only' -> 3550000.0"""
    if not text:
        return None
    tokens = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    total, current, seen = 0, 0, False
    for tok in tokens:
        if tok in _UNITS:
            current += _UNITS[tok]; seen = True
        elif tok in _TENS:
            current += _TENS[tok]; seen = True
        elif tok == "hundred":
            current = max(current, 1) * 100; seen = True
        elif tok in _SCALES:
            total += max(current, 1) * _SCALES[tok]; current = 0; seen = True
    return float(total + current) if seen else None


# ---------------------------------------------------------------------------
# 3. Label-anchored field finding
# Order matters: the first pattern that matches the start of a cell wins.
LABELS_FILE = Path(__file__).resolve().parent.parent / "config" / "field_labels.yaml"


def _load_labels() -> List[Tuple[str, str]]:
    import yaml
    data = yaml.safe_load(LABELS_FILE.read_text(encoding="utf-8"))
    return [(e["field"], e["pattern"]) for e in data["fields"]]


# Order matters: the first pattern that matches the start of a cell wins.
LABELS: List[Tuple[str, str]] = _load_labels()
# Scans turn spaces into dots or quotes ("Receipt.No_", "Name:of Depositor"),
# so any run of non-letters is accepted between the words of a label.
def compile_labels(labels: List[Tuple[str, str]]):
    return [(f, re.compile(r"^[\W_]*" + p.replace(r"\s*", r"[\W_]*") + r"(?![a-z])[\W_]*", re.IGNORECASE))
            for f, p in labels]


def load_labels_file(name: str) -> List[Tuple[str, str]]:
    import yaml
    data = yaml.safe_load((LABELS_FILE.parent / name).read_text(encoding="utf-8"))
    return [(e["field"], e["pattern"]) for e in data["fields"]]


_LABEL_RES = compile_labels(LABELS)
_BANK_WORDS = re.compile(r"\b(bank|co-?operative|credit\s+society|sahakari|finance|nidhi|investments)\b", re.I)
_IFSC_RE = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")


def _value_after_label(seg_idx: int, segs: List[dict], rest: str) -> Tuple[str, dict]:
    """Value is the rest of the cell, else the next cell on the same row, else the cell below."""
    seg = segs[seg_idx]
    if rest.strip():
        return rest.strip(), seg
    y = seg["bbox"][1]
    mid = (seg["bbox"][1] + seg["bbox"][3]) / 2
    half = max(4.0, (seg["bbox"][3] - seg["bbox"][1]) * 0.75)
    same_row = [s for s in segs if s["page"] == seg["page"]
                and abs((s["bbox"][1] + s["bbox"][3]) / 2 - mid) < half
                and s["bbox"][0] > seg["bbox"][2]]
    if same_row:
        nxt = min(same_row, key=lambda s: s["bbox"][0])
        return nxt["text"], nxt
    below = [s for s in segs if s["page"] == seg["page"] and 0 < s["bbox"][1] - y < 30
             and abs(s["bbox"][0] - seg["bbox"][0]) < 60]
    if below:
        nxt = min(below, key=lambda s: s["bbox"][1])
        return nxt["text"], nxt
    return "", seg


def parse_fields(segments: List[dict], pages: List[dict]) -> Tuple[Dict[str, Any], Dict[str, dict]]:
    fields: Dict[str, Any] = {
        "fdr_number": None, "bank_name": None, "branch": None, "ifsc": None,
        "depositor_name": None, "beneficiary_name": None, "amount": None,
        "amount_words": None, "amount_in_words_value": None, "issue_date": None,
        "maturity_date": None, "tenure_years": None, "tenure_text": None,
    }
    where: Dict[str, dict] = {}

    def put(field: str, value: Any, seg: dict):
        if value in (None, "") or fields.get(field) is not None:
            return
        fields[field] = value
        where[field] = {"page": seg["page"], "bbox": seg["bbox"]}

    for i, seg in enumerate(segments):
        text = re.sub(r"\((e?s)\)", r"\1", seg["text"])          # "Name(s) of Depositor(s)" -> "Names of Depositors"
        for field, rx in _LABEL_RES:
            m = rx.match(text)
            if not m:
                continue
            rest = text[m.end():]
            if len(re.findall(r"[A-Za-z]{3,}", rest)) == 0 and not re.search(r"\d{2}", rest):
                rest = ""                                      # only noise after the label: look at the next cell/line
            value, vseg = _value_after_label(i, segments, rest)
            if field in ("issue_date", "maturity_date", "amount"):
                parser = parse_amount if field == "amount" else parse_date
                parsed = parser(value)
                if parsed is None and rest.strip():
                    # e.g. "Principal (Rs.)" leaves "(Rs.)" behind; the figure is in the next cell
                    value, vseg = _value_after_label(i, segments, "")
                    parsed = parser(value)
                put(field, parsed, vseg)
            elif field == "amount_words":
                put(field, value.strip("() "), vseg)
            elif field == "maturity_amount":
                pass
            else:
                put(field, re.sub(r"\s{2,}", " ", value).strip(" :-"), vseg)
            break

        # "Rupees ... Only" printed without a label
        if fields["amount_words"] is None and re.match(r"^\(?\s*rupees\b.*\bonly\b", text, re.I):
            put("amount_words", text.strip("() "), seg)

        if fields["ifsc"] is None:
            m = _IFSC_RE.search(text)
            if m:
                put("ifsc", m.group(1), seg)

    # Bank name: the first bank-like heading in the top third of page 1
    top_limit = (pages[0]["height"] if pages else 842) * 0.33
    for seg in segments:
        if seg["page"] == 0 and seg["bbox"][1] < top_limit and _BANK_WORDS.search(seg["text"]) \
                and not re.search(r"favou?r|payable|ifsc|branch\s*:", seg["text"], re.I):
            put("bank_name", seg["text"].strip(), seg)
            break

    # Fallback for scans where the label itself was misread ("FOR No." for "FDR No."):
    # take a long account-number-like token that is not the IFSC.
    if fields["fdr_number"] is None:
        for seg in segments:
            for tok in re.findall(r"\b[A-Z]{0,4}\d{9,18}\b", seg["text"]):
                if not _IFSC_RE.fullmatch(tok):
                    put("fdr_number", tok, seg)
                    fields["_fdr_number_guessed"] = True
                    break
            if fields["fdr_number"]:
                break

    if fields["bank_name"]:
        fields["bank_name"] = fields["bank_name"].strip(" _-—'‘\"“.,|")

    if fields["amount_words"]:
        fields["amount_in_words_value"] = words_to_number(fields["amount_words"])
    if fields["amount"] is None and fields["amount_in_words_value"]:
        fields["amount"] = fields["amount_in_words_value"]
        fields["_amount_from_words"] = True
        if "amount_words" in where:
            where["amount"] = where["amount_words"]

    if fields["fdr_number"]:
        fields["fdr_number"] = fields["fdr_number"].split()[0].strip(".,;")

    if fields["issue_date"] and fields["maturity_date"]:
        d1 = datetime.strptime(fields["issue_date"], "%Y-%m-%d")
        d2 = datetime.strptime(fields["maturity_date"], "%Y-%m-%d")
        fields["tenure_years"] = round((d2 - d1).days / 365.25, 2)

    # Back-compat with A-1's field name
    fields["institute_name"] = fields["depositor_name"]
    return fields, where


KEY_FIELDS = ["fdr_number", "bank_name", "depositor_name", "beneficiary_name",
              "amount", "issue_date", "maturity_date"]


def extract_fdr_fields(source: PdfSource, precomputed_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns:
      fields        dict of extracted values (None when not found)
      locations     {field: {"page": int, "bbox": [x0, top, x1, bottom]}} in PDF points
      pages         [{"page", "width", "height"}]
      raw_text      all text, one cell per line
      method        "text-layer" | "ocr" | "unreadable" | "cache"
      read_quality  1.0 for text PDFs, mean OCR confidence for scans
      confidence    share of key fields found (0-1)
      missing       key fields not found
    """
    if precomputed_cache:
        return {**precomputed_cache, "method": "cache"}

    doc = read_document(source)
    fields, where = parse_fields(doc["segments"], doc["pages"])
    present = [k for k in KEY_FIELDS if fields.get(k) is not None]
    return {
        "fields": fields,
        "locations": where,
        "pages": doc["pages"],
        "raw_text": "\n".join(s["text"] for s in doc["segments"]),
        "method": doc["method"],
        "is_scanned": doc["method"] == "ocr",
        "read_quality": doc["read_quality"],
        "confidence": round(len(present) / len(KEY_FIELDS), 2),
        "missing": [k for k in KEY_FIELDS if k not in present],
    }


# ---------------------------------------------------------------------------
# 4. Any supported document: read once, decide the type, parse with its labels
# ---------------------------------------------------------------------------
def parse_noc_fields(segments: List[dict], pages: List[dict]) -> Tuple[Dict[str, Any], Dict[str, dict]]:
    label_res = compile_labels(load_labels_file("fire_noc_labels.yaml"))
    fields: Dict[str, Any] = {"noc_number": None, "issuing_authority": None, "institute_name": None,
                              "address": None, "issue_date": None, "valid_upto": None, "buildings": None}
    where: Dict[str, dict] = {}

    def put(field, value, seg):
        if value in (None, "") or fields.get(field) is not None:
            return
        fields[field] = value
        where[field] = {"page": seg["page"], "bbox": seg["bbox"]}

    for i, seg in enumerate(segments):
        text = seg["text"]
        for field, rx in label_res:
            m = rx.match(text)
            if not m:
                continue
            value, vseg = _value_after_label(i, segments, text[m.end():])
            if field in ("issue_date", "valid_upto"):
                put(field, parse_date(value), vseg)
            else:
                put(field, re.sub(r"\s{2,}", " ", value).strip(" :-"), vseg)
            break
    # The issuing office is the letterhead: the top lines of page 1 that name an office
    if fields["issuing_authority"] is None:
        top = (pages[0]["height"] if pages else 842) * 0.3
        head = [s for s in segments if s["page"] == 0 and s["bbox"][1] < top
                and re.search(r"office|officer|department|services|brigade|corporation|panchayat|authority", s["text"], re.I)]
        if head:
            put("issuing_authority", " ".join(s["text"] for s in head[:2]), head[0])
    return fields, where


NOC_KEY_FIELDS = ["noc_number", "issuing_authority", "institute_name", "address", "issue_date", "valid_upto"]

_TITLE = r"(?:shri|smt\.?|sri|dr\.?|mr\.?|ms\.?|mrs\.?|prof\.?|kum\.?)"
_DESIG = (r"(chairman|chairperson|president|secretary|managing\s*trustee|trustee|treasurer|member|principal|"
          r"director|registrar|manager)")


def parse_affidavit_fields(segments: List[dict], pages: List[dict]) -> Tuple[Dict[str, Any], Dict[str, dict]]:
    """Affidavits are prose, not label: value tables, so the fields come from sentence patterns."""
    raw = " ".join(s["text"] for s in segments)
    flat = re.sub(r"\s+", " ", raw)
    f: Dict[str, Any] = {"stamp_paper": False, "stamp_value": None, "deponent_name": None,
                         "deponent_designation": None, "trust_name": None, "institute_name": None,
                         "executed_on": None, "attested_by": None, "attestor_reg": None,
                         "_body": flat, "_text_ok": len(flat) > 200}
    where: Dict[str, dict] = {}

    def locate(field, needle):
        needle = (needle or "").strip().lower()[:18]
        for seg in segments:
            if needle and needle in re.sub(r"\s+", " ", seg["text"]).lower():
                where[field] = {"page": seg["page"], "bbox": seg["bbox"]}
                return

    if re.search(r"non[\s-]*judicial|stamp\s*paper|e-?stamp", flat, re.I):
        f["stamp_paper"] = True
        top = (pages[0]["height"] if pages else 842) * 0.3
        head = " ".join(s["text"] for s in segments if s["page"] == 0 and s["bbox"][1] < top)
        m = (re.search(r"(?:rs\.?|inr|\u20b9)\s*([\d,]{1,7})", head, re.I)
             or re.search(r"stamp\s*paper\s*(?:of|worth|for)?\s*(?:rs\.?|inr|\u20b9)\s*([\d,]{1,7})", flat, re.I))
        if m:
            f["stamp_value"] = float(m.group(1).replace(",", ""))
            locate("stamp_value", m.group(0))
    m = re.search(r"(?:\bI\s*[,.]\s*|\baffidavit\s+(?:I\s*[,.]?\s*)?)" + _TITLE + r"?\s*([A-Z][A-Za-z. ]{2,60}?),(.{0,160}?)\b" + _DESIG +
                  r"\s+of\s+(?:the\s+)?([^,;]{4,90})", flat, re.I)
    if m:
        f["deponent_name"] = m.group(1).strip()
        f["deponent_designation"] = re.sub(r"\s+", " ", m.group(3)).title()
        f["trust_name"] = m.group(4).strip(" .")
        locate("deponent_name", m.group(1))
    m = re.search(r"(?:running|which\s*runs|managing|in\s*respect\s*of|sponsoring\s*body\s*of)\s+(?:the\s+)?"
                  r"([A-Z][^,;]{4,90}?)(?:,|;|\s+do\s+hereby|\s+hereby|\s+situated)", flat)
    if m:
        f["institute_name"] = m.group(1).strip(" .")
        locate("institute_name", m.group(1))
    m = re.search(r"(?:verified|sworn|solemnly\s*affirmed|affirmed)\s+(?:at|before)[^.]{0,40}?\bon\b\s*(?:this\s*)?(.{6,30})",
                  flat, re.I) or re.search(r"\bdate[d]?\s*[:\-]?\s*(.{6,20})", flat, re.I)
    if m:
        f["executed_on"] = parse_date(m.group(1))
        if f["executed_on"]:
            locate("executed_on", m.group(1))
    _att = r"(notary(?:\s*public)?|oath\s*commissioner|(?:executive|first\s*class|judicial)?\s*magistrate)"
    m = (re.search(_att + r"(,?\s*[A-Za-z ]{0,30}?),?\s*(?=reg)", flat, re.I)
         or re.search(_att + r"([^.]{0,40})", flat, re.I))
    if m:
        f["attested_by"] = re.sub(r"\s*reg.*$", "", (m.group(1) + m.group(2)).strip(" ,"), flags=re.I).strip(" ,")
        r = re.search(r"reg(?:istration|n)?\.?\s*no\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,})", flat[m.start():m.start() + 160], re.I)
        f["attestor_reg"] = r.group(1) if r else None
        locate("attested_by", m.group(1))
    return f, where


AFFIDAVIT_KEY_FIELDS = ["stamp_value", "deponent_name", "institute_name", "executed_on", "attested_by"]


def extract_document(source: PdfSource) -> Dict[str, Any]:
    """Like extract_fdr_fields, plus 'doc_type' (see src/doctype.py) and 'bytes'."""
    from .doctype import classify
    doc = read_document(source)
    raw = "\n".join(s["text"] for s in doc["segments"])
    dt = classify(raw)
    if dt["type"] == "fire_noc":
        fields, where = parse_noc_fields(doc["segments"], doc["pages"])
        keys = NOC_KEY_FIELDS
    elif dt["type"] == "affidavit":
        fields, where = parse_affidavit_fields(doc["segments"], doc["pages"])
        keys = AFFIDAVIT_KEY_FIELDS
    else:
        fields, where = parse_fields(doc["segments"], doc["pages"])
        keys = KEY_FIELDS
    present = [k for k in keys if fields.get(k) is not None]
    return {"fields": fields, "locations": where, "pages": doc["pages"], "raw_text": raw,
            "segments": doc["segments"], "method": doc["method"], "is_scanned": doc["method"] in ("ocr", "ocr-missing"),
            "read_quality": doc["read_quality"], "confidence": round(len(present) / len(keys), 2),
            "missing": [k for k in keys if k not in present], "doc_type": dt, "bytes": doc["bytes"]}
