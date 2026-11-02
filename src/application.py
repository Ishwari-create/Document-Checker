"""
Whole-application review: the scrutiny officer decides on an application, not on a
single file. This puts every document of one application together:

  * which required documents are still missing,
  * the latest finding on each document received,
  * checks that compare documents with each other (X1-X4), which no single
    document can show: one institute, one campus, one trust, and dates that fit.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .rule_engine import _d, _v, name_similarity

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "application_rules.yaml"


@lru_cache(maxsize=1)
def load_application_rules() -> Dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _pin(s: Optional[str]) -> Optional[str]:
    m = re.search(r"\b(\d{6})\b", s or "")
    return m.group(1) if m else None


def required_documents(app: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for d in load_application_rules()["documents"]:
        exempt = app.get("institution_type") in d.get("not_required_for", [])
        out.append({**d, "required": not exempt})
    return out


def latest_by_type(cases: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for c in sorted(cases, key=lambda c: (str(c["received"]), c["id"])):
        t = (c.get("doc_type") or {}).get("type") or "fdr"
        out[t] = c
    return out


def consistency_checks(app: Dict[str, Any], docs: Dict[str, dict], photos: List[dict],
                       submitted_on: Optional[date] = None) -> List[Dict[str, Any]]:
    cfg = {c["id"]: c for c in load_application_rules()["consistency"]}
    f = {t: c["extraction"]["fields"] for t, c in docs.items()}
    res = []

    # X1 one institute
    c = cfg["X1"]
    names = [(lbl, n) for lbl, n in (("FDR depositor", f.get("fdr", {}).get("depositor_name")),
                                     ("Fire NOC", f.get("fire_noc", {}).get("institute_name")),
                                     ("Affidavit", f.get("affidavit", {}).get("institute_name"))) if n]
    if len(names) < 2:
        res.append(_v(c, "NA", "Fewer than two documents carry an institute name yet.", "Nothing to compare."))
    else:
        worst = min(((a, b, name_similarity(na, nb)) for i, (a, na) in enumerate(names) for b, nb in names[i + 1:]),
                    key=lambda t: t[2])
        trust = app.get("trust")
        ev = "; ".join(f"{lbl}: '{n}'" for lbl, n in names)
        # An FDR made out by the trust is fine: compare it with the trust name instead.
        if worst[2] < c["pass_score"] and "FDR depositor" in (worst[0], worst[1]) and \
                name_similarity(f["fdr"].get("depositor_name"), trust) >= c["pass_score"]:
            rest = [(l, n) for l, n in names if l != "FDR depositor"]
            worst = (rest[0][0], rest[-1][0], name_similarity(rest[0][1], rest[-1][1])) if len(rest) > 1 else ("", "", 100)
        if worst[2] >= c["pass_score"]:
            res.append(_v(c, "PASS", ev, "All documents name the same institute (or its trust)."))
        else:
            res.append(_v(c, "FAIL", ev, f"{worst[0]} and {worst[1]} name different institutes ({worst[2]:.0f}% similar).",
                          fix=c["fix_hint"]))

    # X2 one campus
    c = cfg["X2"]
    ev, bad, seen = [], [], 0
    pin = app.get("pincode") or _pin(app.get("address"))
    noc_pin = _pin(f.get("fire_noc", {}).get("address"))
    if noc_pin:
        seen += 1
        ev.append(f"Fire NOC PIN {noc_pin}")
        if pin and noc_pin != pin:
            bad.append(f"Fire NOC premises PIN {noc_pin} is not the campus PIN {pin}")
    for p in photos:
        p2 = next((r for r in p["results"] if r["rule_id"] == "P2"), None)
        if p2 and p2["status"] in ("PASS", "FAIL"):
            seen += 1
            if p2["status"] == "FAIL":
                bad.append(f"photo '{p['room']}' taken away from the campus")
    if photos:
        ev.append(f"{sum(1 for p in photos for r in p['results'] if r['rule_id'] == 'P2' and r['status'] == 'PASS')} of "
                  f"{len(photos)} photos geo-tagged at the campus")
    if seen == 0:
        res.append(_v(c, "NA", "No Fire NOC or geo-tagged photo yet.", "Nothing to compare."))
    elif bad:
        res.append(_v(c, "FAIL", "; ".join(ev), "; ".join(bad).capitalize() + ".", fix=c["fix_hint"]))
    else:
        res.append(_v(c, "PASS", "; ".join(ev) + f"; application PIN {pin}", "All location evidence points to one campus."))

    # X3 one trust
    c = cfg["X3"]
    trust = app.get("trust")
    aff_trust = f.get("affidavit", {}).get("trust_name")
    dep = f.get("fdr", {}).get("depositor_name")
    if not aff_trust:
        res.append(_v(c, "NA", "No affidavit read yet.", "Nothing to compare."))
    else:
        sc = name_similarity(aff_trust, trust)
        ev = f"Affidavit sworn for '{aff_trust}'; portal trust '{trust}'" + (f"; FDR depositor '{dep}'" if dep else "")
        if sc >= c["pass_score"]:
            res.append(_v(c, "PASS", ev + f" ({sc:.0f}% similar)", "The same trust stands behind the documents."))
        else:
            res.append(_v(c, "FAIL", ev + f" ({sc:.0f}% similar)", "The affidavit is sworn for a different trust.",
                          fix=c["fix_hint"]))

    # X4 Fire NOC covers the academic year
    c = cfg["X4"]
    until = _d(f.get("fire_noc", {}).get("valid_upto"))
    if not until:
        res.append(_v(c, "NA", "No Fire NOC validity date yet.", "Nothing to compare."))
    else:
        sub = submitted_on or docs["fire_noc"]["received"]
        sm, sd = map(int, c["year_starts"].split("-"))
        em, ed = map(int, c["year_ends"].split("-"))
        start = date(sub.year, sm, sd)
        end = date(start.year + 1, em, ed)
        ev = f"Fire NOC valid up to {until:%d-%m-%Y}; academic year {start:%d-%m-%Y} to {end:%d-%m-%Y}"
        if until < start:
            res.append(_v(c, "FAIL", ev, "The NOC expires before the academic year begins.", fix=c["fix_hint"],
                          severity="FATAL"))
        elif until < end:
            res.append(_v(c, "UNCERTAIN", ev, f"The NOC lapses {(end - until).days} days before the year ends; "
                          "renewal will be due mid-year.", fix=c["fix_hint"]))
        else:
            res.append(_v(c, "PASS", ev, "Covers the whole academic year."))
    for r in res:
        r["source"] = "Whole-application check"
    return res


def review_application(app: Dict[str, Any], cases: List[dict], photos: List[dict]) -> Dict[str, Any]:
    docs = latest_by_type(cases)
    from .photos import load_photo_pack
    need_rooms = load_photo_pack()["required_rooms"]
    checklist = []
    for d in required_documents(app):
        if d["id"] == "photos":
            have = {p["room"] for p in photos}
            missing_rooms = [r for r in need_rooms if r not in have]
            worst = min((p["overall"] for p in photos), key=lambda s: {"FAIL": 0, "UNCERTAIN": 1}.get(s, 2), default=None)
            checklist.append({**d, "present": bool(photos), "complete": not missing_rooms, "missing_rooms": missing_rooms,
                              "overall": worst, "count": len(photos)})
        else:
            c = docs.get(d["id"])
            checklist.append({**d, "present": c is not None, "complete": c is not None, "case": c,
                              "overall": c["overall"] if c else None})
    xs = consistency_checks(app, docs, photos)
    missing = [d for d in checklist if d["required"] and not d["complete"]]
    open_points = sum(1 for d in checklist if d.get("overall") in ("FAIL", "UNCERTAIN")) + \
        sum(1 for x in xs if x["status"] in ("FAIL", "UNCERTAIN"))
    deficient = any(d.get("overall") == "FAIL" for d in checklist) or any(x["status"] == "FAIL" for x in xs)
    if missing:
        status, text = "INCOMPLETE", f"{len(missing)} required document{'s' if len(missing) > 1 else ''} missing"
    elif deficient:
        status, text = "FAIL", "Deficiencies found"
    elif open_points:
        status, text = "UNCERTAIN", "Points for an officer"
    else:
        status, text = "PASS", "Complete, no deficiency found"
    return {"checklist": checklist, "consistency": xs, "missing": missing, "status": status, "status_text": text,
            "open_points": open_points, "docs": docs}


def application_letter(app: Dict[str, Any], review: Dict[str, Any], photos: List[dict],
                       officer: Optional[str] = None, draft: bool = True) -> str:
    """One consolidated letter for the whole application, the way a Regional Office writes it."""
    from datetime import datetime
    today = datetime.today()
    L = []
    if draft:
        L += ["DRAFT - generated for officer review. Not issued until approved by the Regional Office.", ""]
    L += [f"Ref: APP/{app.get('app_id')}/{today:%Y%m%d}", f"Date: {today:%d %B %Y}", "", "To", "The Principal / Director",
          app.get("institute_name", ""), f"Application No.: {app.get('app_id')}", "",
          "Subject: Deficiencies in the documents submitted with your application for approval", "", "Sir / Madam,", "",
          "The documents submitted with your application have been scrutinised. The following points need to be "
          "rectified:", ""]
    n = 0
    sections = []
    if review["missing"]:
        items = []
        for d in review["missing"]:
            extra = f" (missing: {', '.join(d['missing_rooms'])})" if d.get("missing_rooms") and d.get("present") else ""
            items.append(f"{d['name']} not submitted{extra}.")
        sections.append(("Documents not submitted", [(i, "", "") for i in items]))
    for d in review["checklist"]:
        c = d.get("case")
        if not c:
            continue
        dec = c.get("decision") or {}
        keep = set(dec["agreed"]) if dec.get("agreed") is not None and dec.get("action") else None
        rows = [r for r in c["results"] if (r["rule_id"] in keep if keep is not None else r["status"] == "FAIL")
                and r["rule_id"] != "D0" or (r["rule_id"] == "D0" and r["status"] == "FAIL")]
        if rows:
            sections.append((d["name"], [(f"{r.get('problem') or r['name']}  [{r['rule_id']}; {r['clause']}]",
                                          r["evidence"], r.get("fix") or r["reasoning"]) for r in rows]))
    prow = [(f"{r.get('problem')} - {p['room']}  [{r['rule_id']}]", r["evidence"], r.get("fix"))
            for p in photos for r in p["results"] if r["status"] == "FAIL"]
    if prow:
        sections.append(("Infrastructure photographs", prow))
    xrow = [(f"{x['problem']}  [{x['rule_id']}]", x["evidence"], x.get("fix")) for x in review["consistency"]
            if x["status"] == "FAIL"]
    if xrow:
        sections.append(("Between documents", xrow))
    if not sections:
        L += ["  No deficiency has been confirmed.", ""]
    for title, rows in sections:
        L += [f"{title}:"]
        for head, found, fix in rows:
            n += 1
            L += [f"  {n}. {head}"]
            if found:
                L += [f"     Found: {found}"]
            if fix:
                L += [f"     Required action: {fix}"]
        L += [""]
    L += ["Please submit the rectified documents through the portal within the time allowed by the Regional Office.", "",
          "Yours faithfully,", "", officer or "Scrutiny Officer", "Regional Office", ""]
    return "\n".join(L)
