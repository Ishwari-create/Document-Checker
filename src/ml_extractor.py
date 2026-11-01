"""
Machine-learning field extractor: the fallback for receipts whose wording the
label matcher has never seen ("Maturity On", "Joint Holder / Lien", "Name - ...").

How it works
  1. Every printed cell is turned into candidate (context, value) pairs:
       "Label : value" in one cell, a label cell with the value to its right,
       or a label with the value on the line below.
  2. Each candidate is described by the label text (character n-grams, so OCR
     noise and new phrasings still look similar), the value's type (date,
     amount, name, account number) and its position on the page.
  3. A logistic-regression model trained on labelled receipts says which field,
     if any, the candidate is. tools/train_field_model.py trains it; the model
     file is models/field_model.joblib (a few hundred KB, runs offline on CPU).
  4. It only fills fields the label matcher left empty. Dates are checked for
     order (deposit before maturity). Low-confidence values are marked so that a
     failure based on them goes to an officer instead of becoming a deficiency.

The rules never change: they check whatever was extracted, by either method.
"""
from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .extractor import _IFSC_RE, parse_amount, parse_date, words_to_number

ROOT = Path(__file__).resolve().parent.parent
MODEL_FILE = ROOT / "models" / "field_model.joblib"
FIELDS = ["fdr_number", "amount", "issue_date", "maturity_date", "depositor_name", "beneficiary_name", "amount_words"]
LOW_CONFIDENCE = 0.7
MIN_CONFIDENCE = 0.45
_SEP = re.compile(r"\s*(?::|–|—|\s-\s)\s*")


def value_type(v: str) -> Optional[str]:
    t = v.strip()
    if not t or len(t) > 90:
        return None
    if parse_date(t) and len(re.sub(r"[\d\s/.,\-a-zA-Z]", "", t)) < 3 and re.search(r"\d{4}", t):
        return "date"
    if re.fullmatch(r"[A-Z]{0,5}\d{8,18}[A-Z0-9]*", t.replace(" ", "")) and not _IFSC_RE.fullmatch(t):
        return "id"
    if re.match(r"^\(?\s*(rupees\s+)?[a-z ]+\bonly\)?$", t, re.I) and words_to_number(t):
        return "words"
    a = parse_amount(t)
    if a and a >= 1000 and not re.search(r"[a-z]{4,}", t, re.I) and not re.search(r"\d{4}-\d", t):
        return "amount"
    if len(re.findall(r"[A-Za-z]{2,}", t)) >= 2 and not re.search(r"\d{3,}", t):
        return "text"
    return None


def candidates(segments: List[dict], pages: List[dict]) -> List[dict]:
    out = []
    H = pages[0]["height"] if pages else 842

    def add(ctx, val, seg, how):
        vt = value_type(val)
        if vt:
            out.append({"context": ctx.strip(" :.-").lower(), "value": val.strip(" :.-()"), "type": vt, "how": how,
                        "page": seg["page"], "bbox": seg["bbox"], "y": seg["bbox"][1] / H})

    for i, s in enumerate(segments):
        text = s["text"]
        parts = _SEP.split(text, maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            add(parts[0], parts[1], s, "same-cell")
        # value to the right on the same row
        mid = (s["bbox"][1] + s["bbox"][3]) / 2
        right = [t for t in segments if t["page"] == s["page"] and t["bbox"][0] > s["bbox"][2]
                 and abs((t["bbox"][1] + t["bbox"][3]) / 2 - mid) < 6]
        if right:
            r = min(right, key=lambda t: t["bbox"][0])
            add(text, r["text"], r, "right")
        # value on the line below, roughly aligned
        below = [t for t in segments if t["page"] == s["page"] and 0 < t["bbox"][1] - s["bbox"][1] < 28
                 and abs(t["bbox"][0] - s["bbox"][0]) < 50]
        if below and len(text) < 40:
            b = min(below, key=lambda t: t["bbox"][1])
            add(text, b["text"], b, "below")
        # a bare value with no label (e.g. "(Rupees Twelve Lakh Only)")
        add("", text, s, "bare")
    return out


def features(c: dict) -> str:
    """One text string per candidate; the vectorizer turns it into char n-grams plus marker tokens."""
    v = c["value"].lower()
    marks = [f"__type_{c['type']}", f"__how_{c['how']}", f"__y{int(c['y'] * 5)}"]
    if re.search(r"secretary|aicte|council", v):
        marks.append("__val_aicte")
    if re.search(r"college|institute|school|university|academy", v):
        marks.append("__val_inst")
    if re.search(r"\bbank\b|ltd|limited", v):
        marks.append("__val_bank")
    return f"{c['context']} || {' '.join(marks)}"


def context_part(s: str) -> str:
    return s.split("||")[0]


def marker_tokens(s: str) -> List[str]:
    return s.split("||")[1].split()


def parsed(field: str, value: str):
    if field in ("issue_date", "maturity_date"):
        return parse_date(value)
    if field == "amount":
        return parse_amount(value)
    if field == "fdr_number":
        return value.replace(" ", "").strip(".,;")
    return re.sub(r"\s{2,}", " ", value).strip()


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_FILE.exists():
        return None
    import joblib
    return joblib.load(MODEL_FILE)


TYPE_OK = {"fdr_number": {"id"}, "amount": {"amount"}, "issue_date": {"date"}, "maturity_date": {"date"},
           "depositor_name": {"text"}, "beneficiary_name": {"text"}, "amount_words": {"words"}}


def predict(segments: List[dict], pages: List[dict]) -> Dict[str, Tuple[Any, float, dict]]:
    """Best candidate per field: {field: (value, confidence, candidate)}"""
    model = load_model()
    cands = candidates(segments, pages)
    if model is None or not cands:
        return {}
    probs = model.predict_proba([features(c) for c in cands])
    classes = list(model.classes_)
    best: Dict[str, Tuple[Any, float, dict]] = {}
    for c, p in zip(cands, probs):
        for f in FIELDS:
            if f not in classes or c["type"] not in TYPE_OK[f]:
                continue
            conf = float(p[classes.index(f)])
            val = parsed(f, c["value"])
            if val in (None, "") or conf < MIN_CONFIDENCE:
                continue
            if f not in best or conf > best[f][1]:
                best[f] = (val, conf, c)
    # two dates: the earlier is the deposit date
    if "issue_date" in best and "maturity_date" in best and best["issue_date"][0] > best["maturity_date"][0]:
        best["issue_date"], best["maturity_date"] = best["maturity_date"], best["issue_date"]
    return best


def fill_missing_fields(ext: Dict[str, Any]) -> List[str]:
    """Fill the fields the label matcher missed. Returns the fields filled."""
    f, loc = ext["fields"], ext.setdefault("locations", {})
    missing = [k for k in FIELDS if f.get(k) in (None, "")]
    if not missing or not ext.get("segments"):
        return []
    best = predict(ext["segments"], ext["pages"])
    filled, info = [], {}
    for k in missing:
        if k not in best:
            continue
        val, conf, c = best[k]
        if k == "maturity_date" and f.get("issue_date") and val <= f["issue_date"]:
            continue
        if k == "issue_date" and f.get("maturity_date") and val >= f["maturity_date"]:
            continue
        f[k] = val
        loc[k] = {"page": c["page"], "bbox": c["bbox"]}
        info[k] = {"confidence": round(conf, 2), "label_seen": c["context"] or "(no label)"}
        filled.append(k)
    if "amount_words" in filled:
        f["amount_in_words_value"] = words_to_number(f["amount_words"])
    if "depositor_name" in filled:
        f["institute_name"] = f["depositor_name"]
    if f.get("issue_date") and f.get("maturity_date"):
        d1, d2 = (datetime.strptime(f[x], "%Y-%m-%d") for x in ("issue_date", "maturity_date"))
        f["tenure_years"] = round((d2 - d1).days / 365.25, 2)
    f["_ml_filled"] = info
    f["_ml_low_confidence"] = [k for k, v in info.items() if v["confidence"] < LOW_CONFIDENCE]
    ext["missing"] = [k for k in ext.get("missing", []) if k not in filled]
    return filled
