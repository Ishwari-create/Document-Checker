"""
Infrastructure photo check (rule pack 'photos', config/photo_rules.yaml).

The brief asks for infrastructure evidence to be verified with computer vision. A
photo is checked on what can be measured reliably on a laptop:

  P1  when it was taken           EXIF DateTimeOriginal
  P2  where it was taken          EXIF GPS, distance to the campus point in the application
  P3  whether it was reused       perceptual hash (dHash) against every photo already
                                  submitted by any other application, so a resized or
                                  re-compressed copy is still caught
  P4  whether it came from a camera  editing software tag, missing camera details

A missing tag never fails a photo on its own; it sends it to an officer.
"""
from __future__ import annotations

import io
import json
import math
import sqlite3
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml
from PIL import Image, ImageOps

from .registry import DEFAULT_DB, sha256_of
from .rule_engine import _v

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = ROOT / "config" / "photo_rules.yaml"
EXIF_IFD, GPS_IFD = 0x8769, 0x8825


@lru_cache(maxsize=1)
def load_photo_pack() -> Dict[str, Any]:
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


HASH_SIZE = 16          # 256-bit difference hash


def signature(img: Image.Image) -> np.ndarray:
    """64x64 grey thumbnail, normalised: two copies of one photo correlate above 0.95
    even after resizing, light cropping or re-compression."""
    t = np.asarray(ImageOps.exif_transpose(img).convert("L").resize((64, 64), Image.LANCZOS), dtype=np.float32)
    return (t - t.mean()) / (t.std() + 1e-6)


def dhash(img: Image.Image, size: int = HASH_SIZE) -> int:
    g = ImageOps.exif_transpose(img).convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _deg(v, ref) -> Optional[float]:
    try:
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None
    return -d if ref in ("S", "W") else d


def read_photo(data: bytes) -> Dict[str, Any]:
    img = Image.open(io.BytesIO(data))
    ex = img.getexif()
    sub, gps = ex.get_ifd(EXIF_IFD), ex.get_ifd(GPS_IFD)
    taken = None
    for raw in (sub.get(0x9003), sub.get(0x9004), ex.get(0x0132)):
        try:
            taken = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
            break
        except (TypeError, ValueError):
            continue
    lat = _deg(gps.get(2), gps.get(1)) if gps else None
    lon = _deg(gps.get(4), gps.get(3)) if gps else None
    return {"sha256": sha256_of(data), "width": img.width, "height": img.height, "format": img.format,
            "taken": taken.isoformat(timespec="seconds") if taken else None,
            "lat": lat, "lon": lon, "make": (ex.get(0x010F) or "").strip("\x00 ") or None,
            "model": (ex.get(0x0110) or "").strip("\x00 ") or None,
            "software": (ex.get(0x0131) or "").strip("\x00 ") or None,
            "has_exif": len(ex) > 0, "dhash": format(dhash(img), "064x")}


def km_between(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


class PhotoStore:
    """Every photo submitted, with its hash, so a reused photo is found across applications."""

    def __init__(self, db_path: Optional[Path] = DEFAULT_DB):
        self.conn = sqlite3.connect(str(db_path) if db_path else ":memory:", check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS photos (id TEXT PRIMARY KEY, app_id TEXT, room TEXT, "
                          "sha256 TEXT, dhash TEXT, meta TEXT, results TEXT, overall TEXT, image BLOB, "
                          "submitted_on TEXT, origin TEXT)")
        self.conn.commit()

    def similar(self, dh: str, sig: np.ndarray, max_distance: int, min_corr: float,
                exclude_id: Optional[str] = None) -> List[dict]:
        """Two steps: a fast hash comparison picks candidates, then the thumbnails must
        correlate strongly, so two different rooms that merely look alike are not matched."""
        out = []
        for pid, app_id, room, h, sub in self.conn.execute("SELECT id, app_id, room, dhash, submitted_on FROM photos"):
            if pid == exclude_id:
                continue
            d = hamming(int(dh, 16), int(h, 16))
            if d > max_distance:
                continue
            img = self.conn.execute("SELECT image FROM photos WHERE id=?", (pid,)).fetchone()[0]
            if not img:
                continue
            corr = float((sig * signature(Image.open(io.BytesIO(img)))).mean())
            if corr >= min_corr:
                out.append({"id": pid, "app_id": app_id, "room": room, "distance": d, "corr": corr, "submitted_on": sub})
        return sorted(out, key=lambda r: -r["corr"])

    def add(self, rec: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO photos VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (rec["id"], rec["app_id"], rec["room"], rec["meta"]["sha256"], rec["meta"]["dhash"],
                           json.dumps(rec["meta"]), json.dumps(rec["results"]), rec["overall"], rec["image"],
                           rec["submitted_on"], rec.get("origin", "upload")))
        self.conn.commit()

    def for_app(self, app_id: str) -> List[dict]:
        cols = ["id", "app_id", "room", "meta", "results", "overall", "image", "submitted_on", "origin"]
        rows = self.conn.execute(f"SELECT {', '.join(cols)} FROM photos WHERE app_id=? ORDER BY id", (app_id,)).fetchall()
        return [self._row(dict(zip(cols, r))) for r in rows]

    def all(self) -> List[dict]:
        cols = ["id", "app_id", "room", "meta", "results", "overall", "submitted_on", "origin"]
        return [self._row(dict(zip(cols, r))) for r in self.conn.execute(f"SELECT {', '.join(cols)} FROM photos")]

    def get(self, pid: str) -> Optional[dict]:
        cols = ["id", "app_id", "room", "meta", "results", "overall", "image", "submitted_on", "origin"]
        r = self.conn.execute(f"SELECT {', '.join(cols)} FROM photos WHERE id=?", (pid,)).fetchone()
        return self._row(dict(zip(cols, r))) if r else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

    @staticmethod
    def _row(r: dict) -> dict:
        r["meta"], r["results"] = json.loads(r["meta"]), json.loads(r["results"])
        return r


def check_photo(data: bytes, application: Dict[str, Any], room: str, *, submitted_on: Optional[date] = None,
                store: Optional[PhotoStore] = None, photo_id: Optional[str] = None) -> Dict[str, Any]:
    pack = load_photo_pack()
    cfg = {r["id"]: r for r in pack["rules"]}
    src = pack["sources"]
    sub = submitted_on or date.today()
    m = read_photo(data)
    res = []

    c = cfg["P1"]
    if not m["taken"]:
        res.append(_v(c, "UNCERTAIN", "No date in the photo file.", "The camera date has been removed (often by "
                      "messaging apps or editing), so when it was taken cannot be confirmed.", [], c["fix_hint"], sources=src))
    else:
        t = datetime.fromisoformat(m["taken"]).date()
        age = (sub - t).days
        ev = f"Taken {t:%d-%m-%Y}, submitted {sub:%d-%m-%Y}"
        if age < 0:
            res.append(_v(c, "FAIL", ev, "The photo date is after the submission date.", [], c["fix_hint"], sources=src))
        elif age > c["max_age_days"]:
            res.append(_v(c, "FAIL", ev, f"Taken {age} days before submission; older than {c['max_age_days']} days.",
                          [], c["fix_hint"], sources=src))
        else:
            res.append(_v(c, "PASS", ev, f"Taken {age} days before submission.", sources=src))

    c = cfg["P2"]
    clat, clon = application.get("campus_lat"), application.get("campus_lon")
    if m["lat"] is None or m["lon"] is None:
        res.append(_v(c, "UNCERTAIN", "No location in the photo file.", "The photo is not geo-tagged, so where it was "
                      "taken cannot be confirmed.", [], c["fix_hint"], sources=src))
    elif clat is None:
        res.append(_v(c, "NA", f"Photo location {m['lat']:.4f}, {m['lon']:.4f}", "No campus location in the application.",
                      sources=src))
    else:
        km = km_between(m["lat"], m["lon"], clat, clon)
        ev = f"Photo at {m['lat']:.4f}, {m['lon']:.4f}; campus at {clat:.4f}, {clon:.4f}: {km:.1f} km apart"
        if km <= c["pass_km"]:
            res.append(_v(c, "PASS", ev, "Taken at the campus.", sources=src))
        elif km <= c["review_km"]:
            res.append(_v(c, "UNCERTAIN", ev, "Close to, but not at, the campus point.", [], c["fix_hint"], sources=src))
        else:
            res.append(_v(c, "FAIL", ev, f"Taken {km:.0f} km away from the campus.", [], c["fix_hint"], sources=src))

    c = cfg["P3"]
    sig = signature(Image.open(io.BytesIO(data)))
    hits = store.similar(m["dhash"], sig, c["max_distance"], c["min_correlation"], exclude_id=photo_id) if store else []
    other = [h for h in hits if h["app_id"] != application.get("app_id")]
    same = [h for h in hits if h["app_id"] == application.get("app_id") and h["room"] != room]
    if other:
        h = other[0]
        res.append(_v(c, "FAIL", f"Same picture as application {h['app_id']} ('{h['room']}', submitted {h['submitted_on']}); "
                      f"picture match {h['corr']:.0%}", "This photograph was already submitted by another "
                      "application, even if resized or re-saved.", [], c["fix_hint"], sources=src))
    elif same:
        h = same[0]
        res.append(_v(c, "UNCERTAIN", f"Same picture also uploaded as '{h['room']}' in this application",
                      "One photograph is used for two different rooms.", [], c["fix_hint"], sources=src))
    else:
        n = store.count() if store else 0
        res.append(_v(c, "PASS", f"Compared with {n} photos on record; no match.", "Not seen in any other application.",
                      sources=src))

    c = cfg["P4"]
    sw = (m["software"] or "").lower()
    editor = next((e for e in c["editors"] if e in sw), None)
    if editor:
        res.append(_v(c, "UNCERTAIN", f"Saved by: {m['software']}", "The file was last saved by photo-editing software.",
                      [], c["fix_hint"], sources=src))
    elif not (m["make"] or m["model"]):
        res.append(_v(c, "UNCERTAIN", "No camera make or model in the file.", "May be a screenshot, a download, or a copy "
                      "forwarded through a messaging app.", [], c["fix_hint"], sources=src))
    else:
        res.append(_v(c, "PASS", f"Camera: {' '.join(filter(None, [m['make'], m['model']]))}", "Original camera file.",
                      sources=src))

    for r in res:
        r["fields"] = []
    from .rule_engine import get_overall_verdict
    return {"meta": m, "results": res, "overall": get_overall_verdict(res), "room": room,
            "rules_version": str(pack["version"])}


def thumbnail(data: bytes, width: int = 360) -> bytes:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((width, width))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=80)
    return b.getvalue()
