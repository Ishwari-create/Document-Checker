"""
Turns PDF pages into images (for the receipt preview and for OCR).

Uses Poppler (pdf2image) when it is installed, otherwise pypdfium2, which comes
with pdfplumber and needs nothing installed on the computer. So the app runs on
a Windows laptop with only `pip install -r requirements.txt`.
"""
from __future__ import annotations

import io
import shutil
from typing import List, Optional

from PIL import Image


def _poppler_available() -> bool:
    return shutil.which("pdftoppm") is not None


def render_pages(data: bytes, dpi: int, last_page: Optional[int] = None) -> List[Image.Image]:
    if _poppler_available():
        try:
            from pdf2image import convert_from_bytes
            kw = {"first_page": 1, "last_page": last_page} if last_page else {}
            return convert_from_bytes(data, dpi=dpi, **kw)
        except Exception:
            pass
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    n = len(pdf) if not last_page else min(last_page, len(pdf))
    out = [pdf[i].render(scale=dpi / 72).to_pil().convert("RGB") for i in range(n)]
    pdf.close()
    return out


def ocr_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
