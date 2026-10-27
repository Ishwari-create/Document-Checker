"""
Rule engine for the Security Deposit FDR.

All thresholds, amounts and clause references live in config/rules.yaml; this
file only holds the logic. Each rule returns one verdict:

    PASS       the document satisfies the rule
    FAIL       the document breaks the rule (with the evidence that shows it)
    UNCERTAIN  the machine cannot decide; an officer must look
    NA         the rule does not apply to this case (or its input is unavailable)

The engine never takes an adverse decision by itself: FAIL produces a draft
deficiency, which an officer has to confirm (see app/ and registry.Ledger).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = ROOT / "config" / "rules.yaml"
BANKS_FILE = ROOT / "data" / "scheduled_banks.json"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def load_pack(path: Path = RULES_FILE) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rules_config() -> List[Dict[str, Any]]:      # kept for A-1's original API
    return load_pack()["rules"]


def load_banks(include_demo: bool = True) -> Dict[str, str]:
    """normalised name -> display label"""
    data = json.loads(BANKS_FILE.read_text(encoding="utf-8"))
    out = {_norm_bank(b): b for b in data.get("banks", [])}
    for alias, full in data.get("aliases", {}).items():
        out[_norm_bank(alias)] = full
    if include_demo:
        for b in data.get("synthetic_demo_banks", {}).get("banks", []):
            out[_norm_bank(b)] = f"{b} (synthetic demo bank)"
    return out


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
_ABBREV = {
    "engg": "engineering", "engg.": "engineering", "eng": "engineering", "inst": "institute",
    "instt": "institute", "tech": "technology", "mgmt": "management", "mgt": "management",
    "coll": "college", "clg": "college", "univ": "university", "pharm": "pharmacy",
    "sci": "sciences", "&": "and", "edu": "education", "soc": "society",
}
_DROP = {"the", "of", "m/s", "ms", "and", "for"}


def norm_name(s: Optional[str]) -> List[str]:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9/ ]", " ", s)
    toks = [_ABBREV.get(t, t) for t in s.split()]
    return [t for t in toks if t not in _DROP]


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    """0-100. Average of a token-set and a token-sort comparison, so that a
    short name that is merely contained in a long one does not score 100."""
    ta, tb = norm_name(a), norm_name(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    inter = " ".join(sorted(sa & sb))
    da = " ".join(sorted(sa - sb))
    db = " ".join(sorted(sb - sa))
    t1, t2 = f"{inter} {da}".strip(), f"{inter} {db}".strip()
    r = lambda x, y: SequenceMatcher(None, x, y).ratio()
    token_set = max(r(inter, t1) if inter else 0, r(inter, t2) if inter else 0, r(t1, t2))
    token_sort = r(" ".join(sorted(ta)), " ".join(sorted(tb)))
    coverage = len(sa & sb) / max(len(sa), len(sb))      # share of words the two names have in common
    return round(100 * (token_set + token_sort) / 2 * (0.6 + 0.4 * coverage), 1)


def _norm_bank(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(the|ltd|limited|branch)\b", " ", s)
    return " ".join(s.split())


def _d(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def inr(x: float) -> str:
    """Indian digit grouping: 3500000 -> 35,00,000"""
    s = f"{int(round(x))}"
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:]); head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def _months_from_text(t: Optional[str]) -> Optional[int]:
    if not t:
        return None
    m = re.search(r"(\d{1,3})\s*(month|year|yr)", t, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n if m.group(2).lower().startswith("month") else n * 12


# ---------------------------------------------------------------------------
# Verdict builder
# ---------------------------------------------------------------------------
def _v(cfg: dict, status: str, evidence: str, reasoning: str, fields: List[str] = (),
       fix: str = "", ps_status: Optional[str] = None, severity: Optional[str] = None,
       sources: Dict[str, str] = None) -> Dict[str, Any]:
    default_ps = {"PASS": "Verified", "FAIL": "Deficiency", "UNCERTAIN": "Manual review required",
                  "NA": "Not applicable", "EXEMPT": "Not applicable"}[status]
    return {
        "rule_id": cfg["id"], "name": cfg["name"], "clause": cfg.get("clause", ""),
        "severity": severity or cfg.get("severity", "FATAL"), "status": status,
        "ps_status": ps_status or default_ps,
        "evidence": evidence, "reasoning": reasoning,
        "fix": fix if status in ("FAIL", "UNCERTAIN") else "",
        "fields": list(fields),
        "source": (sources or {}).get(cfg.get("source", ""), cfg.get("source", "")),
        "verified_source": bool(cfg.get("verified", False)),
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def r1_beneficiary(f, cfg, ctx, env):
    ben = (f.get("beneficiary_name") or "").strip()
    if not ben:
        return _v(cfg, "UNCERTAIN", "No 'in favour of' line found on the receipt.",
                  "Payee could not be read; officer to check.", ["beneficiary_name"], cfg["fix_hint"])
    low = ben.lower()
    if any(re.search(p, low) for p in cfg["accept_patterns"]):
        return _v(cfg, "PASS", f"In favour of: {ben}", "Payee is Member Secretary, AICTE.", ["beneficiary_name"])
    mentions_aicte = bool(re.search(r"aicte|council\s*for\s*technical", low))
    mentions_ms = "member" in low
    if mentions_aicte or (mentions_ms and "secretary" not in low):
        return _v(cfg, "UNCERTAIN", f"In favour of: {ben}",
                  "Payee mentions AICTE but 'Member Secretary' is not clearly readable.",
                  ["beneficiary_name"], cfg["fix_hint"])
    return _v(cfg, "FAIL", f"In favour of: {ben}",
              "The deposit is payable to someone other than Member Secretary, AICTE, so AICTE "
              "cannot encash or hold a lien on it.", ["beneficiary_name"], cfg["fix_hint"])


def r2_bank(f, cfg, ctx, env):
    bank = (f.get("bank_name") or "").strip()
    if not bank:
        return _v(cfg, "UNCERTAIN", "Issuing bank not identified.", "Bank name could not be read.",
                  ["bank_name"], cfg["fix_hint"])
    low = bank.lower()
    bad = [m for m in cfg["ineligible_markers"] if re.search(rf"\b{re.escape(m)}\b", low)]
    if bad:
        return _v(cfg, "FAIL", f"Issuing institution: {bank}",
                  f"Identified as a non-scheduled-commercial lender (marker: '{bad[0]}').",
                  ["bank_name"], cfg["fix_hint"])
    banks = env["banks"]
    key = _norm_bank(bank)
    if key in banks:
        return _v(cfg, "PASS", f"Issuing bank: {banks[key]}", "Bank is on the accepted list.", ["bank_name"])
    best = max(banks, key=lambda b: SequenceMatcher(None, key, b).ratio())
    score = SequenceMatcher(None, key, best).ratio() * 100
    if score >= 92:
        return _v(cfg, "PASS", f"Issuing bank: {bank} (read as {banks[best]}, {score:.0f}% match)",
                  "Bank matches the accepted list allowing for scan errors.", ["bank_name"])
    return _v(cfg, "UNCERTAIN", f"Issuing bank: {bank}",
              "Bank not found in the scheduled bank list held by the system; officer to verify "
              "against the current RBI Second Schedule.", ["bank_name"], cfg["fix_hint"])


def r3_tenure(f, cfg, ctx, env):
    years = int(cfg["minimum_tenure_years"])
    tol = int(cfg.get("tolerance_days", 0))
    fix = cfg["fix_hint"].format(min_years=years)
    issue, mat = _d(f.get("issue_date")), _d(f.get("maturity_date"))
    if issue and mat:
        need = _add_years(issue, years)
        months = (mat.year - issue.year) * 12 + mat.month - issue.month
        ev = f"Deposit {issue:%d-%m-%Y} to maturity {mat:%d-%m-%Y} = {months} months"
        if mat >= need - timedelta(days=tol):
            return _v(cfg, "PASS", ev, f"Covers the {years}-year period.", ["issue_date", "maturity_date"])
        return _v(cfg, "FAIL", ev, f"Matures on {mat:%d-%m-%Y}; it must run until at least {need:%d-%m-%Y} "
                  f"({years} years).", ["issue_date", "maturity_date"], fix)
    months = _months_from_text(f.get("tenure_text"))
    if months is not None:
        ev = f"Printed period: {f.get('tenure_text')} (dates unreadable)"
        if months >= years * 12:
            return _v(cfg, "UNCERTAIN", ev, "Printed period is sufficient but dates could not be read to confirm.",
                      ["tenure_text"], fix)
        return _v(cfg, "FAIL", ev, f"Printed period is {months} months; {years * 12} required.", ["tenure_text"], fix)
    return _v(cfg, "UNCERTAIN", "Deposit and maturity dates not found.", "Tenure cannot be computed.",
              ["issue_date", "maturity_date"], fix)


def required_amount(cfg: dict, ctx: dict) -> (float, str):
    if ctx.get("required_amount"):
        return float(ctx["required_amount"]), "as entered"
    table = cfg["amount_table"]
    progs = ctx.get("programmes") or ([ctx["category"]] if ctx.get("category") else [])
    slab = "special" if ctx.get("special_category") else "general"
    total, parts = 0.0, []
    for p in progs:
        key = p if p in table else ("Engineering & Technology" if p == "Technical" else None)
        if key is None:
            continue
        amt = table[key][slab]
        total += amt
        parts.append(f"{key} {inr(amt)}")
    basis = " + ".join(parts) + (" (minority/women/NE slab)" if slab == "special" else "")
    return total, basis


def r4_amount(f, cfg, ctx, env):
    amt = f.get("amount")
    req, basis = required_amount(cfg, ctx)
    if not req:
        return _v(cfg, "NA", "Programme list not available.", "Required amount cannot be computed.", ["amount"])
    if amt is None:
        return _v(cfg, "UNCERTAIN", f"Required: Rs. {inr(req)} ({basis})", "Deposit amount could not be read.",
                  ["amount"], cfg["fix_hint"].format(shortfall="?", required=inr(req)))
    ev = f"Deposit Rs. {inr(amt)} vs required Rs. {inr(req)} ({basis})"
    if amt + 0.5 >= req:
        return _v(cfg, "PASS", ev, "Amount is sufficient.", ["amount"])
    return _v(cfg, "FAIL", ev, f"Short by Rs. {inr(req - amt)}.", ["amount"],
              cfg["fix_hint"].format(shortfall=inr(req - amt), required=inr(req)))


def r5_depositor(f, cfg, ctx, env):
    dep = (f.get("depositor_name") or f.get("institute_name") or "").strip()
    names = [n for n in (ctx.get("institute_name"), ctx.get("trust")) if n]
    if not dep:
        return _v(cfg, "UNCERTAIN", "Depositor name not found on the receipt.", "Depositor could not be read.",
                  ["depositor_name"], cfg["fix_hint"])
    if not names:
        return _v(cfg, "NA", f"Depositor: {dep}", "No application record to compare with.", ["depositor_name"])
    scored = sorted(((name_similarity(dep, n), n) for n in names), reverse=True)
    score, best = scored[0]
    ev = f"Receipt: '{dep}'  |  Portal: '{best}'  ({score:.0f}% similar)"
    if score >= cfg["pass_score"]:
        return _v(cfg, "PASS", ev, "Depositor is the applicant institute or its trust.", ["depositor_name"])
    if score >= cfg["review_score"]:
        return _v(cfg, "UNCERTAIN", ev, "Names are close but not the same; could be an abbreviation.",
                  ["depositor_name"], cfg["fix_hint"])
    return _v(cfg, "FAIL", ev, "Depositor is not the applicant institute or its registered trust/society.",
              ["depositor_name"], cfg["fix_hint"])


def r6_dates(f, cfg, ctx, env):
    issue, mat = _d(f.get("issue_date")), _d(f.get("maturity_date"))
    as_of = env["as_of"]
    if not issue or not mat:
        return _v(cfg, "UNCERTAIN", f"Deposit: {f.get('issue_date') or 'not read'}, maturity: "
                  f"{f.get('maturity_date') or 'not read'}", "Dates missing.", ["issue_date", "maturity_date"],
                  cfg["fix_hint"])
    ev = f"Deposit {issue:%d-%m-%Y}, maturity {mat:%d-%m-%Y}, received {as_of:%d-%m-%Y}"
    if mat <= issue:
        return _v(cfg, "FAIL", ev, "Maturity date is not after the deposit date.", ["issue_date", "maturity_date"],
                  cfg["fix_hint"])
    if issue > as_of:
        return _v(cfg, "FAIL", ev, f"Deposit date is {(issue - as_of).days} days after the date the receipt "
                  "was received (post-dated receipt).", ["issue_date"], cfg["fix_hint"])
    if mat <= as_of:
        return _v(cfg, "FAIL", ev, "The deposit had already matured when it was submitted.",
                  ["maturity_date"], cfg["fix_hint"], ps_status="Expired")
    return _v(cfg, "PASS", ev, "Dates are consistent.", ["issue_date", "maturity_date"])


def r7_timeliness(f, cfg, ctx, env):
    loa, sub = _d(ctx.get("loa_date")), env.get("submitted_on")
    if not loa or not sub:
        return _v(cfg, "NA", "Letter of Approval date or receipt date not available.",
                  "Timeliness not checked.")
    days = (sub - loa).days
    ev = f"LoA {loa:%d-%m-%Y}, FDR received {sub:%d-%m-%Y} ({days} days)"
    if days <= cfg["days_allowed"]:
        return _v(cfg, "PASS", ev, f"Within {cfg['days_allowed']} days.")
    sd, _ = required_amount(env["pack_rules"]["R4"], ctx)
    for slab in cfg["penalty_slabs"]:
        mm, dd = map(int, slab["until"].split("-"))
        if sub <= date(loa.year, mm, dd):
            pen = sd * slab["percent"] / 100
            return _v(cfg, "FAIL", ev, f"Late by {days - cfg['days_allowed']} days; penalty of "
                      f"{slab['percent']}% applies.", [],
                      cfg["fix_hint"].format(percent=slab["percent"], penalty=inr(pen)))
    return _v(cfg, "FAIL", ev, f"Received after 31 July {loa.year}; approval is liable to be withdrawn "
              "under cl. 6.2(f).", [], "Refer to the Regional Officer: the penalty window has closed.",
              severity="FATAL")


def r8_words(f, cfg, ctx, env):
    amt, words_val = f.get("amount"), f.get("amount_in_words_value")
    if amt is None or words_val is None:
        return _v(cfg, "NA", "Amount in words not printed or not readable.", "Cross-check not possible.",
                  ["amount_words"])
    ev = f"Figures Rs. {inr(amt)}  |  Words: '{f.get('amount_words')}' = Rs. {inr(words_val)}"
    if abs(amt - words_val) < 1:
        return _v(cfg, "PASS", ev, "Figures and words agree.", ["amount", "amount_words"])
    return _v(cfg, "FAIL", ev, "Figures and words disagree: a common sign that the receipt was altered "
              "after issue.", ["amount", "amount_words"], cfg["fix_hint"], ps_status="Mismatch detected")


def r9_issuer(f, cfg, ctx, env):
    issuer = env.get("issuer")
    if issuer is None:
        return _v(cfg, "NA", "No bank connection configured.", "Issuer check skipped.")
    res = issuer.confirm(f.get("bank_name"), f.get("fdr_number"))
    env["issuer_result"] = res
    stamp = f"{res['source']}, checked {res['checked_at']}"
    if res["status"] == "source_unavailable":
        return _v(cfg, "UNCERTAIN", f"{res['detail']} ({stamp})", "Officer to obtain written branch confirmation.",
                  ["bank_name"], cfg["fix_hint"], ps_status="Source unavailable")
    if res["status"] == "verification_pending":
        return _v(cfg, "UNCERTAIN", f"{res['detail']} ({stamp})", "Bank could not be asked.", ["fdr_number"],
                  cfg["fix_hint"], ps_status="Verification pending")
    if res["status"] == "not_found":
        if f.get("_fdr_number_guessed"):
            return _v(cfg, "UNCERTAIN", f"{res['detail']} ({stamp})",
                      "FDR number was read from a poor scan and may be wrong.", ["fdr_number"], cfg["fix_hint"],
                      ps_status="Manual review required")
        return _v(cfg, "FAIL", f"{res['detail']} ({stamp})", "The bank has no such deposit.", ["fdr_number"],
                  cfg["fix_hint"], ps_status="Mismatch detected")
    rec, diffs, hl = res["record"], [], ["fdr_number"]
    if f.get("amount") is not None and abs(float(rec["amount"]) - f["amount"]) >= 1:
        diffs.append(f"amount: receipt Rs. {inr(f['amount'])}, bank Rs. {inr(rec['amount'])}"); hl.append("amount")
    if f.get("maturity_date") and rec.get("maturity_date") != f["maturity_date"]:
        diffs.append(f"maturity: receipt {f['maturity_date']}, bank {rec['maturity_date']}"); hl.append("maturity_date")
    if f.get("depositor_name") and name_similarity(f["depositor_name"], rec.get("depositor_name")) < 88:
        diffs.append(f"depositor: receipt '{f['depositor_name']}', bank '{rec['depositor_name']}'")
        hl.append("depositor_name")
    if diffs:
        return _v(cfg, "FAIL", "; ".join(diffs) + f" ({stamp})",
                  "The bank's own record disagrees with the receipt.", hl, cfg["fix_hint"],
                  ps_status="Mismatch detected")
    return _v(cfg, "PASS", f"Bank confirms deposit {f.get('fdr_number')} for Rs. {inr(rec['amount'])}, "
              f"maturing {rec['maturity_date']} ({stamp})", "Verified with the issuing bank.", ["fdr_number"],
              ps_status="Verified with issuer")


def r10_reuse(f, cfg, ctx, env):
    ledger = env.get("ledger")
    if ledger is None or not ctx.get("app_id"):
        return _v(cfg, "NA", "Submission ledger not connected.", "Reuse check skipped.")
    hits = ledger.find_reuse(ctx["app_id"], f.get("fdr_number"), f.get("bank_name"), env.get("sha256") or "")
    if not hits:
        return _v(cfg, "PASS", f"FDR {f.get('fdr_number') or '(number unread)'} and file hash not seen in any "
                  "other application.", "No reuse found.", ["fdr_number"])
    h = hits[0]
    how = "the identical file" if h["same_file"] else f"the same FDR number {h['fdr_number']}"
    return _v(cfg, "FAIL", f"{how} was submitted for application {h['app_id']} on {h['submitted_at']}",
              "One deposit is being used to back two applications.", ["fdr_number"], cfg["fix_hint"],
              ps_status="Duplicate detected")


RULE_FUNCS = {"R1": r1_beneficiary, "R2": r2_bank, "R3": r3_tenure, "R4": r4_amount, "R5": r5_depositor,
              "R6": r6_dates, "R7": r7_timeliness, "R8": r8_words, "R9": r9_issuer, "R10": r10_reuse}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check_document(fields: Dict[str, Any], application_context: Dict[str, Any], raw_text: str = "", *,
                   as_of: Optional[date] = None, submitted_on: Optional[date] = None, issuer=None,
                   ledger=None, sha256: Optional[str] = None, pack: Optional[dict] = None,
                   include_demo_banks: bool = True) -> List[Dict[str, Any]]:
    """
    fields              extract_fdr_fields(...)["fields"]
    application_context the applicant's portal record: institute_name, trust, institution_type,
                        special_category, programmes, loa_date, app_id
                        (A-1's short form {institute_name, category, required_amount} still works)
    submitted_on        date the receipt reached AICTE (defaults to today)
    issuer, ledger      registry.IssuerConnector / registry.Ledger; omit to skip R9 / R10
    """
    pack = pack or load_pack()
    ctx = dict(application_context or {})
    sub = submitted_on or _d(ctx.get("submitted_on")) or date.today()
    env = {"as_of": as_of or sub, "submitted_on": sub, "issuer": issuer, "ledger": ledger, "sha256": sha256,
           "banks": load_banks(include_demo_banks), "pack_rules": {r["id"]: r for r in pack["rules"]},
           "sources": pack.get("sources", {})}

    itype = ctx.get("institution_type")
    exempt = itype in pack.get("exempt_institution_types", [])
    applic = {"id": "R0", "name": "Security Deposit applicable", "clause": "Guidelines 2024-27 cl. 6.2(f), 6.6(c)",
              "severity": "FATAL", "source": "REG2024", "verified": True}
    if exempt:
        return [_v(applic, "EXEMPT", f"Institution type: {itype}",
                   "Government / Government-aided institutions are exempt from the Security Deposit.",
                   sources=env["sources"])]

    results = []
    if itype:
        results.append(_v(applic, "PASS", f"Institution type: {itype}", "Security Deposit is required.",
                          sources=env["sources"]))
    for cfg in pack["rules"]:
        fn = RULE_FUNCS.get(cfg["id"])
        if fn:
            v = fn(fields, cfg, ctx, env)
            v["source"] = env["sources"].get(cfg.get("source", ""), cfg.get("source", ""))
            results.append(v)
    return results


def get_overall_verdict(rule_results: List[Dict[str, Any]]) -> str:
    """PASS | FAIL | UNCERTAIN | EXEMPT"""
    if any(r["status"] == "EXEMPT" for r in rule_results):
        return "EXEMPT"
    if any(r["status"] == "FAIL" and r["severity"] == "FATAL" for r in rule_results):
        return "FAIL"
    if any(r["status"] == "UNCERTAIN" or (r["status"] == "FAIL") for r in rule_results):
        return "UNCERTAIN"
    return "PASS"


def rules_version() -> str:
    return str(load_pack().get("version", "unversioned"))
