"""
Synthetic infrastructure photographs for the photo check: drawn rooms (classroom,
laboratory, library) with camera EXIF (date, GPS, make/model). 15 correct photos
and 5 with one problem each: old, taken in another city, reused from another
application (resized and re-saved), edited in Photoshop, forwarded (no EXIF).
Every image carries a SAMPLE - TEST DATA stamp.

    python tools/generate_photos.py
"""
import csv
import io
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "photos"
APPS = {a["app_id"]: a for a in json.loads((ROOT / "data" / "applications.json").read_text())["applications"]}
W, H = 960, 640


def font(size):
    for f in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def room(kind: str, seed: int) -> Image.Image:
    r = random.Random(seed)
    wall = tuple(r.randint(185, 235) for _ in range(3))
    img = Image.new("RGB", (W, H), wall)
    d = ImageDraw.Draw(img)
    hz = int(H * r.uniform(0.42, 0.5))                       # horizon
    vx = W // 2 + r.randint(-120, 120)                       # vanishing point
    floor = tuple(r.randint(110, 170) for _ in range(3))
    d.polygon([(0, H), (W, H), (W, hz + 60), (0, hz + 60)], fill=floor)
    d.polygon([(0, 0), (vx - 260, hz - 160), (vx - 260, hz + 60), (0, H)], fill=tuple(max(0, c - 25) for c in wall))
    d.polygon([(W, 0), (vx + 260, hz - 160), (vx + 260, hz + 60), (W, H)], fill=tuple(max(0, c - 15) for c in wall))
    d.rectangle([vx - 260, hz - 160, vx + 260, hz + 60], fill=wall)
    for i in range(r.randint(2, 4)):                          # windows on the left wall
        x = 40 + i * 70
        d.polygon([(x, 120 + i * 12), (x + 45, 140 + i * 14), (x + 45, 330 - i * 6), (x, 360 - i * 8)], fill=(205, 225, 240))
    if kind == "Classroom":
        d.rectangle([vx - 170, hz - 120, vx + 170, hz - 10], fill=(30, 60, 45), outline=(120, 90, 60), width=6)
        for row in range(5):
            y = hz + 80 + row * 55
            s = 0.55 + row * 0.18
            for col in range(-2, 3):
                cx = vx + int(col * 150 * s)
                d.rectangle([cx - 55 * s, y, cx + 55 * s, y + 16 * s], fill=(140, 95, 55))
                d.rectangle([cx - 50 * s, y + 16 * s, cx - 44 * s, y + 40 * s], fill=(70, 70, 70))
                d.rectangle([cx + 44 * s, y + 16 * s, cx + 50 * s, y + 40 * s], fill=(70, 70, 70))
    elif kind == "Laboratory":
        for row in range(4):
            y = hz + 70 + row * 70
            s = 0.6 + row * 0.22
            d.rectangle([vx - 330 * s, y, vx + 330 * s, y + 22 * s], fill=(225, 225, 220), outline=(90, 90, 90))
            for col in range(-3, 4):
                cx = vx + int(col * 90 * s)
                d.rectangle([cx - 26 * s, y - 42 * s, cx + 26 * s, y - 6 * s], fill=(25, 25, 30))
                d.rectangle([cx - 22 * s, y - 38 * s, cx + 22 * s, y - 10 * s], fill=(60, 110, 170))
    else:  # Library
        for i in range(5):
            x0 = vx - 250 + i * 100
            d.rectangle([x0, hz - 150, x0 + 90, hz + 55], fill=(110, 75, 45))
            for sh in range(5):
                y = hz - 145 + sh * 40
                x = x0 + 4
                while x < x0 + 86:
                    bw = r.randint(5, 11)
                    d.rectangle([x, y, x + bw, y + 34], fill=tuple(r.randint(40, 220) for _ in range(3)))
                    x += bw + 1
        d.rectangle([vx - 200, hz + 160, vx + 200, hz + 190], fill=(150, 105, 60))
    z = r.uniform(0.78, 1.0)                                   # camera position: zoom, shift, mirror
    cw, ch = int(W * z), int(H * z)
    x0, y0 = r.randint(0, W - cw), r.randint(0, H - ch)
    img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H)).rotate(r.uniform(-3, 3), fillcolor=wall)
    if r.random() < 0.5:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    a = np.asarray(img, dtype=np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    light = 1.08 - 0.25 * (((xx - W * r.uniform(0.3, 0.7)) / W) ** 2 + ((yy - H * 0.3) / H) ** 2)
    a = a * light[..., None] + np.random.default_rng(seed).normal(0, 6, a.shape)
    img = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    d = ImageDraw.Draw(img)
    d.rectangle([10, H - 34, 330, H - 8], fill=(160, 30, 30))
    d.text((18, H - 31), "SAMPLE - TEST DATA", fill="white", font=font(18))
    return img


def to_dms(x):
    x = abs(x); d = int(x); m = int((x - d) * 60); s = round(((x - d) * 60 - m) * 60, 2)
    return (float(d), float(m), float(s))


def jpeg(img, taken=None, lat=None, lon=None, make="SAMPLE", model="Test Camera 12MP", software=None, exif=True):
    ex = Image.Exif()
    if exif:
        if make: ex[0x010F] = make
        if model: ex[0x0110] = model
        if software: ex[0x0131] = software
        if taken: ex.get_ifd(0x8769)[0x9003] = taken.strftime("%Y:%m:%d %H:%M:%S")
        if lat is not None:
            g = ex.get_ifd(0x8825)
            g[1], g[2], g[3], g[4] = ("N" if lat >= 0 else "S"), to_dms(lat), ("E" if lon >= 0 else "W"), to_dms(lon)
    b = io.BytesIO()
    img.save(b, "JPEG", quality=88, exif=ex if exif else b"")
    return b.getvalue()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    r = random.Random(77)
    rows, imgs = [], {}
    clean_apps = ["1-SYN-2026-0101", "1-SYN-2026-0103", "1-SYN-2026-0106", "1-SYN-2026-0110", "1-SYN-2026-0102"]
    defects = {("1-SYN-2026-0102", "Laboratory"): "old", ("1-SYN-2026-0105", "Laboratory"): "far",
               ("1-SYN-2026-0111", "Library"): "reused", ("1-SYN-2026-0108", "Classroom"): "edited",
               ("1-SYN-2026-0107", "Classroom"): "forwarded"}
    order = clean_apps + ["1-SYN-2026-0105", "1-SYN-2026-0111", "1-SYN-2026-0108", "1-SYN-2026-0107"]
    n = 0
    for app_id in order:
        a = APPS[app_id]
        sub = date.fromisoformat(a["loa_date"]) + timedelta(days=10)
        rooms = ["Classroom", "Laboratory", "Library"] if app_id in clean_apps else \
            [k[1] for k in defects if k[0] == app_id]
        for kind in rooms:
            n += 1
            defect = defects.get((app_id, kind), "none")
            img = room(kind, seed=int(app_id[-4:]) * 31 + n * 977)
            taken = datetime.combine(sub - timedelta(days=r.randint(10, 60)), datetime.min.time()) + timedelta(hours=r.randint(9, 16), minutes=r.randint(0, 59))
            lat = a["campus_lat"] + r.uniform(-0.002, 0.002); lon = a["campus_lon"] + r.uniform(-0.002, 0.002)
            kw = dict(taken=taken, lat=lat, lon=lon)
            fail = ""
            if defect == "old":
                kw["taken"] = taken - timedelta(days=700); fail = "P1"
            elif defect == "far":
                kw["lat"], kw["lon"] = 19.0760, 72.8777; fail = "P2"           # Mumbai, not Bhopal
            elif defect == "reused":
                src = imgs[("1-SYN-2026-0101", "Library")]
                img = src.resize((800, 533)).crop((8, 6, 792, 527)); fail = "P3"
            elif defect == "edited":
                kw["software"] = "Adobe Photoshop 25.1 (Windows)"; fail = ""
            elif defect == "forwarded":
                kw = dict(exif=False); fail = ""
            imgs[(app_id, kind)] = img
            pid = f"PH-{n:02d}"
            (OUT / f"{pid}.jpg").write_bytes(jpeg(img, **kw))
            review = {"edited": "P4", "forwarded": "P1;P2;P4"}.get(defect, "")
            rows.append({"photo_id": pid, "file": f"{pid}.jpg", "app_id": app_id, "room": kind, "defect_type": defect,
                         "expected_fail_rules": fail, "expected_review_rules": review,
                         "expected_overall": "FAIL" if fail else ("UNCERTAIN" if review else "PASS"),
                         "submitted_on": sub.isoformat()})
    with open(OUT / "labels.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    print(f"wrote {len(rows)} photos")


if __name__ == "__main__":
    main()
