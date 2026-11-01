"""
Turning PDF pages into images, and finding out what OCR this computer has.

- Page previews use pdfplumber's own renderer (pypdfium2, installed with pip),
  so the scrutiny screen works on any laptop with no system install.
- OCR uses Poppler for rendering when it is installed (slightly sharper text),
  otherwise the same pdfplumber renderer.
- `ocr_status()` says whether Tesseract is installed and which languages it
  has, so the app can tell the user instead of quietly sending scans to review.
"""
from __future__ import annotations

import io
import shutil
from functools import lru_cache
from typing import Dict, List, Optional

from PIL import Image


def preview_page(data: bytes, resolution: int = 110, page: int = 0) -> Image.Image:
    """One page as an image, for the screen. Needs nothing but pip packages."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return pdf.pages[page].to_image(resolution=resolution).original.convert("RGB")


def render_pages(data: bytes, dpi: int, last_page: Optional[int] = None) -> List[Image.Image]:
    """All pages (or the first `last_page`) as images, for OCR and scan forensics."""
    if shutil.which("pdftoppm"):
        try:
            from pdf2image import convert_from_bytes
            kw = {"first_page": 1, "last_page": last_page} if last_page else {}
            return convert_from_bytes(data, dpi=dpi, **kw)
        except Exception:
            pass
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = pdf.pages if not last_page else pdf.pages[:last_page]
        for p in pages:
            out.append(p.to_image(resolution=dpi).original.convert("RGB"))
    return out


@lru_cache(maxsize=1)
def ocr_status() -> Dict[str, object]:
    """{'available': bool, 'version': str, 'languages': [...], 'lang': 'eng+hin', 'message': str}"""
    try:
        import pytesseract
        version = str(pytesseract.get_tesseract_version())
        langs = [l for l in pytesseract.get_languages(config="") if l not in ("osd",)]
    except Exception:
        return {"available": False, "version": "", "languages": [], "lang": "",
                "message": "OCR engine (Tesseract) is not installed on this computer, so scanned "
                           "receipts cannot be read and will go to an officer for review."}
    msg = "" if "hin" in langs else "Hindi OCR data is not installed; scans are read in English only."
    return {"available": True, "version": version, "languages": langs, "lang": "eng" if "eng" in langs else (langs[0] if langs else "eng"),
            "hindi": "hin" in langs, "message": msg}


def ocr_lang_for(img) -> str:
    """English by default; English + Hindi when the page is in Devanagari script.
    Running Hindi on English pages makes English OCR worse, so the script is detected first."""
    st = ocr_status()
    if not st.get("hindi"):
        return st["lang"] or "eng"
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img, config="--psm 0")
        if "Devanagari" in osd:
            return "hin+eng"
    except Exception:
        pass
    return "eng"


def ocr_available() -> bool:
    return bool(ocr_status()["available"])
