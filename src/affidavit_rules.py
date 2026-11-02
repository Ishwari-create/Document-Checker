"""Rule pack 3: Affidavit by the Trust / Society (config/affidavit_rules.yaml)."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .rule_engine import _d, _v, name_similarity

RULES_FILE = Path(__file__).resolve().parent.parent / "config" / "affidavit_rules.yaml"


def load_affidavit_pack() -> Dict[str, Any]:
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


def f1_stamp(f, cfg, ctx, env):
    v = f.get("stamp_value")
    if not f.get("stamp_paper"):
        return _v(cfg, "FAIL" if f.get("_text_ok") else "UNCERTAIN", "No mention of non-judicial stamp paper.",
                  "The affidavit does not say it is on stamp paper.", ["stamp_value"], cfg["fix_hint"])
    if v is None:
        return _v(cfg, "UNCERTAIN", "Stamp paper mentioned, value not readable.", "Officer to check the stamp value.",
                  ["stamp_value"], cfg["fix_hint"])
    need = cfg["min_stamp_value"]
    if v < need:
        return _v(cfg, "FAIL", f"Stamp paper of Rs. {v:,.0f}; required at least Rs. {need:,.0f}.",
                  "Stamp value below the minimum.", ["stamp_value"], cfg["fix_hint"])
    return _v(cfg, "PASS", f"Non-judicial stamp paper of Rs. {v:,.0f}.", "Stamp value meets the minimum.", ["stamp_value"])


def f2_attested(f, cfg, ctx, env):
    a = f.get("attested_by")
    if a and any(re.search(p, a, re.I) for p in cfg["attest_patterns"]):
        reg = f.get("attestor_reg")
        ev = f"Attested by: {a}" + (f", Reg. No. {reg}" if reg else "")
        if not reg:
            return _v(cfg, "UNCERTAIN", ev, "Attestation found, but no registration number is printed.",
                      ["attested_by"], cfg["fix_hint"])
        return _v(cfg, "PASS", ev, "Sworn before an authorised attesting officer.", ["attested_by"])
    return _v(cfg, "FAIL" if f.get("_text_ok") else "UNCERTAIN", "No Notary / Magistrate attestation found.",
              "An affidavit is only valid when sworn before an authorised officer.", ["attested_by"], cfg["fix_hint"])


def f3_deponent(f, cfg, ctx, env):
    who, desig, org = f.get("deponent_name"), f.get("deponent_designation") or "", f.get("trust_name") or ""
    if not who:
        return _v(cfg, "UNCERTAIN", "Deponent not found.", "Could not read who swore the affidavit.",
                  ["deponent_name"], cfg["fix_hint"])
    ev = f"Deponent: {who}, {desig or 'designation not stated'} of '{org or '-'}'  |  Portal trust: '{ctx.get('trust', '-')}'"
    if not any(re.search(p, desig, re.I) for p in cfg["designations"]):
        return _v(cfg, "FAIL", ev, "The deponent is not the Chairman / President / Secretary.", ["deponent_name"],
                  cfg["fix_hint"])
    sc = name_similarity(org, ctx.get("trust"))
    if sc >= cfg["pass_score"]:
        return _v(cfg, "PASS", ev + f" ({sc:.0f}% similar)", "Sworn by an office-bearer of the applicant trust.",
                  ["deponent_name"])
    if sc >= cfg["review_score"]:
        return _v(cfg, "UNCERTAIN", ev + f" ({sc:.0f}% similar)", "Trust names are close but not the same.",
                  ["deponent_name"], cfg["fix_hint"])
    return _v(cfg, "FAIL", ev + f" ({sc:.0f}% similar)", "The deponent belongs to a different trust.",
              ["deponent_name"], cfg["fix_hint"])


def f4_institute(f, cfg, ctx, env):
    n = f.get("institute_name")
    if not n:
        return _v(cfg, "UNCERTAIN", "Institute name not found.", "Could not read which institute the affidavit is for.",
                  ["institute_name"], cfg["fix_hint"])
    sc = name_similarity(n, ctx.get("institute_name"))
    ev = f"Affidavit: '{n}'  |  Portal: '{ctx.get('institute_name')}'  ({sc:.0f}% similar)"
    if sc >= cfg["pass_score"]:
        return _v(cfg, "PASS", ev, "Names the applicant institute.", ["institute_name"])
    if sc >= cfg["review_score"]:
        return _v(cfg, "UNCERTAIN", ev, "Names are close but not the same.", ["institute_name"], cfg["fix_hint"])
    return _v(cfg, "FAIL", ev, "The affidavit names a different institute.", ["institute_name"], cfg["fix_hint"])


def f5_date(f, cfg, ctx, env):
    d, sub = _d(f.get("executed_on")), env["submitted_on"]
    if not d:
        return _v(cfg, "UNCERTAIN", "Date of execution not found.", "Could not read when it was sworn.",
                  ["executed_on"], cfg["fix_hint"])
    ev = f"Sworn on {d:%d-%m-%Y}, submitted {sub:%d-%m-%Y}"
    if d > sub:
        return _v(cfg, "FAIL", ev, "Dated after the submission date.", ["executed_on"], cfg["fix_hint"])
    age = (sub - d).days
    if age > cfg["max_age_days"]:
        return _v(cfg, "FAIL", ev, f"Sworn {age} days before submission; older than {cfg['max_age_days']} days.",
                  ["executed_on"], cfg["fix_hint"])
    return _v(cfg, "PASS", ev, f"Sworn {age} days before submission.", ["executed_on"])


def f6_undertakings(f, cfg, ctx, env):
    text = f.get("_body", "")
    if not f.get("_text_ok"):
        return _v(cfg, "UNCERTAIN", "Text not readable.", "Officer to read the undertakings.", [], cfg["fix_hint"])
    missing = [k for k, pats in cfg["undertakings"].items() if not any(re.search(p, text, re.I | re.S) for p in pats)]
    names = {"truth": "information is true and correct", "liability": "liable to action / withdrawal of approval",
             "compliance": "will abide by AICTE norms"}
    if missing:
        return _v(cfg, "FAIL", "Missing: " + "; ".join(names.get(m, m) for m in missing),
                  "A paragraph of the prescribed format has been left out.", [], cfg["fix_hint"])
    return _v(cfg, "PASS", "Found: " + "; ".join(names.values()), "All required undertakings are present.")


FUNCS = {"F1": f1_stamp, "F2": f2_attested, "F3": f3_deponent, "F4": f4_institute, "F5": f5_date, "F6": f6_undertakings}


def check_affidavit(fields: Dict[str, Any], application: Dict[str, Any], *,
                    submitted_on: Optional[date] = None) -> List[Dict[str, Any]]:
    pack = load_affidavit_pack()
    env = {"submitted_on": submitted_on or date.today()}
    out = []
    for cfg in pack["rules"]:
        v = FUNCS[cfg["id"]](fields, cfg, application, env)
        v["source"] = pack["sources"].get(cfg.get("source", ""), cfg.get("source", ""))
        out.append(v)
    return out


def affidavit_rules_version() -> str:
    return str(load_affidavit_pack().get("version"))
