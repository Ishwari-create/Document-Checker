"""Rule pack 2: Fire Safety No Objection Certificate (config/fire_noc_rules.yaml)."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .rule_engine import _d, _v, name_similarity

RULES_FILE = Path(__file__).resolve().parent.parent / "config" / "fire_noc_rules.yaml"


def load_noc_pack() -> Dict[str, Any]:
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


def _pin(s: Optional[str]) -> Optional[str]:
    m = re.search(r"\b(\d{6})\b", s or "")
    return m.group(1) if m else None


def n1_authority(f, cfg, ctx, env):
    a = (f.get("issuing_authority") or "").strip()
    if not a:
        return _v(cfg, "UNCERTAIN", "Issuing office not found.", "Could not read who issued the NOC.",
                  ["issuing_authority"], cfg["fix_hint"])
    if any(re.search(p, a, re.I) for p in cfg["authority_patterns"]):
        return _v(cfg, "PASS", f"Issued by: {a}", "Issued by a fire service authority.", ["issuing_authority"])
    return _v(cfg, "FAIL", f"Issued by: {a}", "The issuing office is not a fire service authority.",
              ["issuing_authority"], cfg["fix_hint"])


def n2_validity(f, cfg, ctx, env):
    issue, until, sub = _d(f.get("issue_date")), _d(f.get("valid_upto")), env["submitted_on"]
    if not until:
        return _v(cfg, "UNCERTAIN", "Validity date not found.", "Could not read the 'valid up to' date.",
                  ["valid_upto"], cfg["fix_hint"])
    ev = f"Issued {issue:%d-%m-%Y}, valid up to {until:%d-%m-%Y}, submitted {sub:%d-%m-%Y}" if issue else \
        f"Valid up to {until:%d-%m-%Y}, submitted {sub:%d-%m-%Y}"
    if until < sub:
        return _v(cfg, "FAIL", ev, f"The NOC expired {(sub - until).days} days before submission.",
                  ["valid_upto"], cfg["fix_hint"], ps_status="Expired")
    if issue and issue > sub:
        return _v(cfg, "FAIL", ev, "The issue date is after the submission date.", ["issue_date"], cfg["fix_hint"])
    left = (until - sub).days
    if left < cfg.get("warn_days", 90):
        return _v(cfg, "UNCERTAIN", ev, f"Valid, but expires in {left} days; renewal will be due soon.",
                  ["valid_upto"], cfg["fix_hint"], severity="WARNING")
    return _v(cfg, "PASS", ev, f"Valid for {left} more days.", ["valid_upto"])


def n3_institute(f, cfg, ctx, env):
    n = (f.get("institute_name") or "").strip()
    ref = ctx.get("institute_name")
    if not n:
        return _v(cfg, "UNCERTAIN", "Institute name not found on the NOC.", "Could not read who the NOC is issued to.",
                  ["institute_name"], cfg["fix_hint"])
    sc = name_similarity(n, ref)
    ev = f"NOC: '{n}'  |  Portal: '{ref}'  ({sc:.0f}% similar)"
    if sc >= cfg["pass_score"]:
        return _v(cfg, "PASS", ev, "Issued to the applicant institute.", ["institute_name"])
    if sc >= cfg["review_score"]:
        return _v(cfg, "UNCERTAIN", ev, "Names are close but not the same.", ["institute_name"], cfg["fix_hint"])
    return _v(cfg, "FAIL", ev, "The NOC names a different institute.", ["institute_name"], cfg["fix_hint"])


def n4_premises(f, cfg, ctx, env):
    a = (f.get("address") or "").strip()
    if not a:
        return _v(cfg, "UNCERTAIN", "Premises address not found.", "Could not read the premises address.",
                  ["address"], cfg["fix_hint"])
    p1, p2 = _pin(a), ctx.get("pincode") or _pin(ctx.get("address"))
    ev = f"NOC premises: '{a}'  |  Application: '{ctx.get('address', '-')}'"
    if p1 and p2:
        if p1 == p2:
            return _v(cfg, "PASS", ev, f"Same PIN code ({p1}).", ["address"])
        return _v(cfg, "FAIL", ev, f"PIN code on the NOC ({p1}) differs from the campus PIN ({p2}).", ["address"],
                  cfg["fix_hint"])
    return _v(cfg, "UNCERTAIN", ev, "PIN code missing; officer to compare the address.", ["address"], cfg["fix_hint"])


FUNCS = {"N1": n1_authority, "N2": n2_validity, "N3": n3_institute, "N4": n4_premises}


def check_fire_noc(fields: Dict[str, Any], application: Dict[str, Any], *,
                   submitted_on: Optional[date] = None) -> List[Dict[str, Any]]:
    pack = load_noc_pack()
    env = {"submitted_on": submitted_on or date.today()}
    out = []
    for cfg in pack["rules"]:
        v = FUNCS[cfg["id"]](fields, cfg, application, env)
        v["source"] = pack["sources"].get(cfg.get("source", ""), cfg.get("source", ""))
        out.append(v)
    return out


def noc_rules_version() -> str:
    return str(load_noc_pack().get("version"))
