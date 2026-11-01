"""Decides what kind of document this is before any rules run."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "document_types.yaml"


@lru_cache(maxsize=1)
def document_types() -> List[Dict[str, Any]]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["types"]


def classify(raw_text: str) -> Dict[str, Any]:
    """{'type': 'fdr' | 'fire_noc' | None, 'name': str, 'score': int, 'scores': {...}, 'matched': [...]}"""
    text = (raw_text or "").lower()
    scores, matched = {}, {}
    for t in document_types():
        hit = [p for p in t["keywords"] if re.search(p, text)]
        scores[t["id"]] = sum(t["keywords"][p] for p in hit)
        matched[t["id"]] = hit
    best = max(document_types(), key=lambda t: scores[t["id"]])
    ok = scores[best["id"]] >= best["min_score"]
    return {"type": best["id"] if ok else None, "name": best["name"] if ok else "Unrecognised document",
            "score": scores[best["id"]], "scores": scores, "matched": matched[best["id"]] if ok else []}


def type_info(type_id: str) -> Dict[str, Any]:
    return next(t for t in document_types() if t["id"] == type_id)
