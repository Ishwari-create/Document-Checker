"""
Make a real receipt safe to add to the test set: blacks out account / FDR numbers,
PAN, Aadhaar-like numbers, phone numbers and e-mail addresses, then saves the page
as an image-only PDF (so the hidden text layer cannot leak the numbers either).

    python tools/redact.py real_receipt.pdf data/real/receipt_01.pdf
    python tools/redact.py real_receipt.pdf out.pdf --keep-amount      (default: amounts are kept)

Check the output by eye before sharing it. The checker will then read it with OCR,
exactly like a scanned copy.
"""
import argparse
import io
import re
import sys
from pathlib import Path

from PIL import ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.extractor import read_document   # noqa: E402
from src.render import render_pages        # noqa: E402

SENSITIVE = [r"\b\d{9,18}\b", r"\b[A-Z]{2,5}\d{6,}\b", r"\b[A-Z]{5}\d{4}[A-Z]\b", r"\b\d{4}\s?\d{4}\s?\d{4}\b",
             r"\b[6-9]\d{9}\b", r"[\w.+-]+@[\w-]+\.[\w.]+", r"(?i)(a/?c|account)\s*(no|number)?\.?\s*[:\-]?\s*\S+"]


def redact(pdf: bytes, dpi: int = 150) -> bytes:
    doc = read_document(pdf)
    pages = render_pages(pdf, dpi)
    scale = dpi / 72
    hits = 0
    for i, img in enumerate(pages):
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        for seg in doc["segments"]:
            if seg["page"] != i:
                continue
            if any(re.search(p, seg["text"]) for p in SENSITIVE):
                x0, top, x1, bottom = seg["bbox"]
                d.rectangle([x0 * scale - 2, top * scale - 2, x1 * scale + 2, bottom * scale + 2], fill="black")
                hits += 1
        pages[i] = img
    out = io.BytesIO()
    pages[0].save(out, "PDF", resolution=dpi, save_all=True, append_images=pages[1:])
    print(f"blacked out {hits} line(s); check the result by eye", file=sys.stderr)
    return out.getvalue()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    a = ap.parse_args()
    Path(a.dst).parent.mkdir(parents=True, exist_ok=True)
    Path(a.dst).write_bytes(redact(Path(a.src).read_bytes()))
