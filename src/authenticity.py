"""
Document authentication checks. They look at the file itself, not just the words on it.

  A1  Edit history     PDF saved again after it was created (incremental updates),
                       or saved by a PDF editing tool. A digital signature also adds an
                       update, so signed files are reported, not flagged.
  A2  Fonts            A key value (amount, dates, payee, depositor) printed in a font
                       used nowhere else on the receipt: the usual trace of a pasted edit.
  A3  QR / signature   If the bank printed a QR code, its contents must agree with the
                       printed amount, FDR number and maturity date.
  A4  Scan forensics   Paper-grain consistency on scanned copies: a region pasted in
                       from a digital source has no paper grain (or a different
                       compression history) compared with the rest of the page.

All four are "preliminary indicators requiring human verification" (SIH26261), so a
failure here sends the case to an officer; only a QR mismatch is a deficiency by itself.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from .rule_engine import _v, inr

EDITOR_TOOLS = ["pdfescape", "ilovepdf", "smallpdf", "sejda", "pdf-xchange", "foxit phantom", "nitro",
                "acrobat pro", "pdffiller", "pdf candy", "soda pdf", "libreoffice draw", "inkscape",
                "photoshop", "canva", "microsoft print to pdf"]
KEY_FIELDS = ["amount", "amount_words", "issue_date", "maturity_date", "beneficiary_name", "depositor_name",
              "valid_upto", "issue_date", "institute_name"]

CFG = {
    "A1": {"id": "A1", "name": "No edits after the document was issued", "problem": "Edited after issue",
           "clause": "SIH26261: detect manipulation", "severity": "WARNING", "source": "PS", "verified": True},
    "A2": {"id": "A2", "name": "Key values use the document's own fonts", "problem": "Mixed fonts in a key value",
           "clause": "SIH26261: detect manipulation", "severity": "WARNING", "source": "PS", "verified": True},
    "A3": {"id": "A3", "name": "QR code agrees with the printed details", "problem": "QR code disagrees with the receipt",
           "clause": "SIH26261: verify via QR / digital signature", "severity": "FATAL", "source": "PS", "verified": True},
    "A4": {"id": "A4", "name": "No pasted regions in the scan", "problem": "Possible pasted region in the scan",
           "clause": "SIH26261: detect manipulation", "severity": "WARNING", "source": "PS", "verified": True},
}
FIX = {
    "A1": "Ask the institute for the bank's original file, or confirm the details with the issuing branch.",
    "A2": "Compare the flagged value with the original receipt; obtain a fresh receipt from the bank if it differs.",
    "A3": "The bank's QR code does not match the printed values: treat the receipt as altered and confirm with the branch.",
    "A4": "Inspect the highlighted area on the original paper receipt.",
}


# ---------------------------------------------------------------------------
def pdf_history(data: bytes) -> Dict[str, Any]:
    info: Dict[str, Any] = {"updates": max(0, data.count(b"%%EOF") - 1), "producer": "", "creator": "",
                            "created": "", "modified": "", "signed": b"/ByteRange" in data or b"/Sig" in data,
                            "signer": ""}
    try:
        import pikepdf
        with pikepdf.open(io.BytesIO(data)) as pdf:
            di = pdf.docinfo
            for k, key in (("producer", "/Producer"), ("creator", "/Creator"), ("created", "/CreationDate"),
                           ("modified", "/ModDate")):
                if key in di:
                    info[k] = str(di[key])
    except Exception:
        pass
    return info


def a1_edit_history(data: bytes, ext: Dict[str, Any]) -> Dict[str, Any]:
    h = pdf_history(data)
    tool = next((t for t in EDITOR_TOOLS if t in (h["producer"] + " " + h["creator"]).lower()), None)
    meta = f"Producer: {h['producer'] or 'not stated'}; saved {h['updates'] + 1} time(s)"
    if h["signed"]:
        return _v(CFG["A1"], "PASS", meta + "; digitally signed (certificate not verified offline)",
                  "Later saves come from the digital signature.", [])
    if tool and h["updates"] > 0:
        return _v(CFG["A1"], "FAIL", meta + f"; last saved with an editing tool ({tool})",
                  "The file was opened and saved again in a PDF editor after the bank produced it.", [], FIX["A1"],
                  ps_status="Suspected alteration")
    if h["updates"] > 0:
        return _v(CFG["A1"], "FAIL", meta, f"The file was changed {h['updates']} time(s) after it was first saved.",
                  [], FIX["A1"], ps_status="Suspected alteration")
    if tool:
        return _v(CFG["A1"], "UNCERTAIN", meta + f"; made with {tool}",
                  "The file was produced by a general PDF editor, not a banking system.", [], FIX["A1"])
    return _v(CFG["A1"], "PASS", meta, "No changes after the file was created.", [])


# ---------------------------------------------------------------------------
def a2_fonts(data: bytes, ext: Dict[str, Any]) -> Dict[str, Any]:
    if ext.get("method") != "text-layer":
        return _v(CFG["A2"], "NA", "Scanned copy: fonts cannot be read.", "Font check applies to digital PDFs only.")
    import pdfplumber
    from .extractor import hidden_char_ids
    loc = ext.get("locations", {})
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        chars = [c for c in page.chars if c.get("upright", True) and c["text"].strip()
                 and abs((c.get("matrix") or (1, 0, 0, 1))[1]) < 0.05 and c["size"] >= 8]
    covered = len(hidden_char_ids(chars))
    base = lambda f: re.sub(r"^[A-Z]{6}\+", "", f or "").split("-")[0].split(",")[0]
    boxes = {f: loc[f]["bbox"] for f in dict.fromkeys(KEY_FIELDS) if f in loc and loc[f]["page"] == 0}
    def in_box(c, b):
        return c["x0"] >= b[0] - 1 and c["x1"] <= b[2] + 1 and c["top"] >= b[1] - 2 and c["bottom"] <= b[3] + 2
    outside = Counter(base(c["fontname"]) for c in chars if not any(in_box(c, b) for b in boxes.values()))
    flagged = []
    for field, b in boxes.items():
        fonts = Counter(base(c["fontname"]) for c in chars if in_box(c, b))
        flagged += [(field, font) for font, n in fonts.items() if n >= 3 and outside.get(font, 0) == 0]
    if covered >= 5:
        names = ", ".join(sorted({f.replace("_", " ") for f, _ in flagged})) or "a key value"
        return _v(CFG["A2"], "FAIL", f"{covered} characters are printed on top of other text ({names}); "
                  f"fonts: {', '.join(sorted({font for _, font in flagged})) or 'mixed'}",
                  "New text was placed over the original text: the classic trace of an edited receipt.",
                  [f for f, _ in flagged], FIX["A2"], ps_status="Suspected alteration")
    if flagged:
        names = ", ".join(f"{f.replace('_', ' ')} in {font}" for f, font in flagged)
        return _v(CFG["A2"], "FAIL", f"Printed in a font found nowhere else on the receipt: {names}",
                  "A value set in its own font is the usual trace of text pasted over the original.",
                  [f for f, _ in flagged], FIX["A2"], ps_status="Suspected alteration")
    return _v(CFG["A2"], "PASS", "All key values use fonts that appear elsewhere on the receipt; no overwritten text.",
              "No sign of a pasted value.", [])


# ---------------------------------------------------------------------------
def read_qr(data: bytes) -> Optional[str]:
    try:
        import cv2
        import numpy as np
        from .render import render_pages
        img = np.array(render_pages(data, 200, last_page=1)[0].convert("L"))
        det = cv2.QRCodeDetector()
        txt, pts, _ = det.detectAndDecode(img)
        if not txt:
            txt, pts, _ = det.detectAndDecode(cv2.GaussianBlur(img, (3, 3), 0))
        return txt or None
    except Exception:
        return None


def a3_qr(data: bytes, ext: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_qr(data)
    f = ext["fields"]
    if not payload:
        return _v(CFG["A3"], "NA", "No readable QR code on the document.", "QR check not possible.")
    parts = payload.split("|")
    if len(parts) < 4 or parts[0] not in ("FDR", "NOC"):
        return _v(CFG["A3"], "NA", f"QR code found but not in a known format: '{payload[:40]}'", "QR check not possible.")
    if parts[0] == "FDR":
        _, no, amount, maturity = parts[:4]
        diffs = []
        scanned = ext.get("method") == "ocr"
        if f.get("fdr_number") and no != f["fdr_number"]:
            from difflib import SequenceMatcher
            if not (scanned and SequenceMatcher(None, no, f["fdr_number"]).ratio() >= 0.85):
                diffs.append(f"FDR number: printed {f['fdr_number']}, QR {no}")
        if f.get("amount") is not None and abs(float(amount) - f["amount"]) >= 1:
            diffs.append(f"amount: printed Rs. {inr(f['amount'])}, QR Rs. {inr(float(amount))}")
        if f.get("maturity_date") and maturity != f["maturity_date"]:
            diffs.append(f"maturity: printed {f['maturity_date']}, QR {maturity}")
        if diffs and scanned:
            return _v(CFG["A3"], "UNCERTAIN", "; ".join(diffs) + " (printed value read by OCR)",
                      "The QR code disagrees with what OCR read. It may be an OCR misreading or an altered "
                      "scan: an officer must compare with the original.", ["amount", "fdr_number"], FIX["A3"],
                      ps_status="Manual review required", severity="WARNING")
        if diffs:
            hl = [k for k, w in (("fdr_number", "FDR number"), ("amount", "amount"), ("maturity_date", "maturity"))
                  if any(d.startswith(w) for d in diffs)]
            return _v(CFG["A3"], "FAIL", "; ".join(diffs), "The bank's QR code was not changed with the printed values.",
                      hl, FIX["A3"], ps_status="Mismatch detected")
        return _v(CFG["A3"], "PASS", f"QR code matches: FDR {no}, Rs. {inr(float(amount))}, maturity {maturity}",
                  "Printed details agree with the bank's QR code.", ["fdr_number", "amount"],
                  ps_status="Verified with QR")
    return _v(CFG["A3"], "NA", "QR present.", "QR format not checked for this document type.")


# ---------------------------------------------------------------------------
def scan_consistency(data: bytes) -> Optional[Dict[str, Any]]:
    """Paper grain and compression consistency of a scanned page.

    A real scan has the same paper grain everywhere. A region pasted in from a
    digital source is unnaturally flat (no grain) or has a different JPEG history.
    For each 32 px block of blank paper we measure the grain (robust spread of the
    background pixels) and flag blocks far below the page's usual grain."""
    try:
        import numpy as np
        import pikepdf
        from PIL import Image
        with pikepdf.open(io.BytesIO(data)) as pdf:
            page = pdf.pages[0]
            imgs = list((page.get_images() if hasattr(page, "get_images") else page.images).values())
            if not imgs:
                return None
            raw = imgs[0].read_raw_bytes() if imgs[0].Filter == "/DCTDecode" else None
            pil = Image.open(io.BytesIO(raw)) if raw else imgs[0].as_pil_image()
        g = np.asarray(pil.convert("L"), dtype=float)
        B = 32
        rows = []
        for y in range(0, g.shape[0] - B, B):
            for x in range(0, g.shape[1] - B, B):
                blk = g[y:y + B, x:x + B]
                bg = blk[(blk > 150)]
                ink = (blk < 140).mean()
                if bg.size < B * B * 0.5 or ink < 0.02:     # only blocks with text and paper around it
                    continue
                mad = np.median(np.abs(bg - np.median(bg)))
                rows.append((mad, x, y))
        if len(rows) < 30:
            return None
        v = np.array([m for m, _, _ in rows])
        med = np.median(v)
        flat = [(x, y) for m, x, y in rows if m < 0.35 * med]
        return {"blocks": len(rows), "outliers": len(flat), "boxes": flat[:60], "B": B,
                "scale": 72 / 150}
    except Exception:
        return None


def a4_scan_forensics(data: bytes, ext: Dict[str, Any]) -> Dict[str, Any]:
    if ext.get("method") not in ("ocr", "ocr-missing"):
        return _v(CFG["A4"], "NA", "Digital PDF: scan forensics not needed.", "Applies to scanned copies only.")
    r = scan_consistency(data)
    if r is None:
        return _v(CFG["A4"], "NA", "Not enough printed area to analyse.", "Scan forensics not possible.")
    ev = f"{r['outliers']} of {r['blocks']} printed areas lack the paper grain seen on the rest of the page"
    if r["outliers"] >= 4:
        xs = [x for x, _ in r["boxes"]]; ys = [y for _, y in r["boxes"]]
        ext.setdefault("locations", {})["_forensic"] = {"page": 0, "bbox": [min(xs) * r["scale"], min(ys) * r["scale"],
                                                                            (max(xs) + r["B"]) * r["scale"], (max(ys) + r["B"]) * r["scale"]]}
        return _v(CFG["A4"], "FAIL", ev, "Part of the page has no paper grain: it may have been pasted in from a "
                  "digital source.", ["_forensic"], FIX["A4"], ps_status="Suspected alteration")
    return _v(CFG["A4"], "PASS", ev, "Paper grain is consistent across the page.", [])


def authenticity_checks(data: bytes, ext: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for fn in (a1_edit_history, a2_fonts, a3_qr, a4_scan_forensics):
        try:
            out.append(fn(data, ext))
        except Exception as e:   # a forensic check must never break the scrutiny
            rid = fn.__name__[:2].upper()
            out.append(_v(CFG[rid], "NA", f"Check could not run ({type(e).__name__}).", "Skipped."))
    for v in out:
        v["source"] = "SIH26261 problem statement: document authentication"
    return out
