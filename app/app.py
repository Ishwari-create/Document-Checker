"""
SD Scrutiny Desk - web front end for the Security Deposit FDR checker.

    python app/app.py            (then open http://localhost:8501)

Screens
  /              Officer queue: every received FDR with the system's finding
  /check/<id>    Scrutiny view: receipt with evidence boxes, findings, officer decision
  /upload        Check a new receipt against an application
  /precheck      Institute self-check before submitting (nothing is recorded)
  /fool          Edit a clean receipt and watch the checker catch the change
  /evaluation    Accuracy on the synthetic test set
  /audit         Every automated check and officer decision
"""

from __future__ import annotations

import base64
import csv
import io
import json
import random
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, Response, abort, redirect, render_template, request, url_for
from pdf2image import convert_from_bytes

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.deficiency import generate_deficiency_letter          # noqa: E402
from src.pipeline import load_applications, run_check          # noqa: E402
from src.registry import IssuerConnector, Ledger               # noqa: E402
from src.rule_engine import inr, load_pack, required_amount    # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

APPS = load_applications()
PACK = load_pack()
ISSUER = IssuerConnector()
LEDGER = Ledger()                         # data/ledger.sqlite3
DOCS = ROOT / "data" / "test_documents"
LABELS = {r["doc_id"]: r for r in csv.DictReader(open(ROOT / "data" / "labels.csv"))}
CASES: dict = {}                          # case_id -> case (in memory for the prototype)
PAGE_CACHE: dict = {}

STATUS_ORDER = {"FAIL": 0, "UNCERTAIN": 1, "PASS": 2, "NA": 3, "EXEMPT": 4}
OVERALL_TEXT = {"PASS": "No deficiency found", "FAIL": "Deficiency found", "UNCERTAIN": "Needs officer review",
                "EXEMPT": "Not required"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def page_image(sha: str, pdf: bytes) -> str:
    if sha not in PAGE_CACHE:
        img = convert_from_bytes(pdf, dpi=110, first_page=1, last_page=1)[0]
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=82)
        PAGE_CACHE[sha] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    return PAGE_CACHE[sha]


def make_case(case_id: str, pdf: bytes, app_rec: dict, received: date, origin: str, record: bool = True,
              actor: str = "system") -> dict:
    out = run_check(pdf, app_rec, submitted_on=received, issuer=ISSUER, ledger=LEDGER if record else None,
                    actor=actor, record=record)
    out["results"].sort(key=lambda r: (STATUS_ORDER.get(r["status"], 9), int(r["rule_id"][1:])))
    req, basis = required_amount({r["id"]: r for r in PACK["rules"]}["R4"], app_rec)
    case = {"id": case_id, "pdf": pdf, "app": app_rec, "received": received, "origin": origin,
            "required": req, "required_basis": basis, "decision": None, **out}
    CASES[case_id] = case
    return case


def sample_case(doc_id: str) -> dict:
    if doc_id not in CASES:
        lab = LABELS[doc_id]
        make_case(doc_id, (DOCS / lab["file"]).read_bytes(), APPS[lab["app_id"]],
                  date.fromisoformat(lab["submitted_on"]), origin="sample")
    return CASES[doc_id]


def boxes_for(case: dict) -> list:
    """Evidence boxes in PDF points, one per field, tagged with the rules that use it."""
    loc = case["extraction"]["locations"]
    by_field: dict = {}
    for r in case["results"]:
        for f in r.get("fields", []):
            if f in loc:
                by_field.setdefault(f, []).append(r)
    out = []
    for f, rules in by_field.items():
        worst = min(rules, key=lambda r: STATUS_ORDER.get(r["status"], 9))
        x0, top, x1, bottom = loc[f]["bbox"]
        out.append({"field": f, "rules": " ".join(r["rule_id"] for r in rules), "status": worst["status"],
                    "x": x0 - 3, "y": top - 3, "w": x1 - x0 + 6, "h": bottom - top + 6})
    return out


@app.template_filter("inr")
def _inr(x):
    return inr(x) if x is not None else "-"


@app.template_filter("dmy")
def _dmy(s):
    if not s:
        return "-"
    if isinstance(s, (date, datetime)):
        return s.strftime("%d %b %Y")
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return s


@app.context_processor
def _globals():
    return {"OVERALL_TEXT": OVERALL_TEXT, "rules_version": PACK.get("version")}


# ---------------------------------------------------------------------------
# Officer screens
# ---------------------------------------------------------------------------
@app.route("/")
def queue():
    cases = [sample_case(d) for d in sorted(LABELS)]
    cases += [c for c in CASES.values() if c["origin"] == "upload"]
    order = {"FAIL": 1, "UNCERTAIN": 0, "PASS": 2, "EXEMPT": 3}
    cases.sort(key=lambda c: (c["decision"] is not None, order.get(c["overall"], 9), c["id"]))
    counts = {k: sum(1 for c in cases if c["overall"] == k) for k in order}
    return render_template("queue.html", cases=cases, counts=counts, pending=sum(c["decision"] is None for c in cases))


@app.route("/check/<case_id>")
def check(case_id):
    case = CASES.get(case_id) or (sample_case(case_id) if case_id in LABELS else None)
    if case is None:
        abort(404)
    pages = case["extraction"]["pages"] or [{"width": 595, "height": 842}]
    return render_template("check.html", c=case, page=pages[0], img=page_image(case["sha256"], case["pdf"]),
                           boxes=boxes_for(case), history=LEDGER.history(case["app"].get("app_id"), 12),
                           label=LABELS.get(case_id))


@app.route("/check/<case_id>/decide", methods=["POST"])
def decide(case_id):
    case = CASES.get(case_id) or abort(404)
    officer = request.form.get("officer", "").strip() or "Scrutiny Officer"
    action = request.form["action"]
    agreed, overrides = [], []
    for r in case["results"]:
        if r["status"] in ("FAIL", "UNCERTAIN"):
            choice = request.form.get(f"v_{r['rule_id']}", "agree")
            note = request.form.get(f"n_{r['rule_id']}", "").strip()
            if choice == "agree" and r["status"] == "FAIL":
                agreed.append(r["rule_id"])
            elif choice == "deficient":
                agreed.append(r["rule_id"])
            if choice in ("disagree", "deficient") or note:
                overrides.append({"rule": r["rule_id"], "system": r["status"], "officer": choice, "note": note})
    if action == "accept" and agreed:
        return render_check_error(case, "Findings marked as deficiencies remain. Mark them 'not a deficiency' "
                                        "with a reason, or prepare a deficiency letter instead.")
    if any(o["officer"] == "disagree" and not o["note"] for o in overrides):
        return render_check_error(case, "Give a reason for every finding you overrule. It is kept in the audit trail.")
    case["decision"] = {"action": action, "officer": officer, "agreed": agreed, "overrides": overrides,
                        "at": datetime.now().isoformat(timespec="seconds")}
    LEDGER.log(officer, f"officer_{action}", case["app"].get("app_id", "?"), case["sha256"],
               case["rules_version"], action, case["decision"])
    if action == "letter":
        return redirect(url_for("letter", case_id=case_id))
    return redirect(url_for("check", case_id=case_id))


def render_check_error(case, msg):
    pages = case["extraction"]["pages"] or [{"width": 595, "height": 842}]
    return render_template("check.html", c=case, page=pages[0], img=page_image(case["sha256"], case["pdf"]),
                           boxes=boxes_for(case), history=LEDGER.history(case["app"].get("app_id"), 12),
                           label=LABELS.get(case["id"]), error=msg), 400


@app.route("/check/<case_id>/letter")
def letter(case_id):
    case = CASES.get(case_id) or abort(404)
    d = case.get("decision") or {}
    text = generate_deficiency_letter(case["extraction"]["fields"], case["results"], case["app"],
                                      officer_name=d.get("officer"), confirmed_rule_ids=d.get("agreed"))
    if request.args.get("download"):
        return Response(text, mimetype="text/plain",
                        headers={"Content-Disposition": f"attachment; filename=deficiency_{case_id}.txt"})
    return render_template("letter.html", c=case, text=text)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        f = request.files.get("pdf")
        if not f or not f.filename:
            return render_template("upload.html", apps=APPS, error="Choose a PDF of the receipt.", today=date.today())
        app_rec = APPS[request.form["app_id"]]
        received = date.fromisoformat(request.form.get("received") or date.today().isoformat())
        cid = "U" + uuid.uuid4().hex[:6].upper()
        make_case(cid, f.read(), app_rec, received, origin="upload")
        return redirect(url_for("check", case_id=cid))
    return render_template("upload.html", apps=APPS, today=date.today())


# ---------------------------------------------------------------------------
# Institute self-check
# ---------------------------------------------------------------------------
@app.route("/precheck", methods=["GET", "POST"])
def precheck():
    result = None
    if request.method == "POST":
        f = request.files.get("pdf")
        app_rec = APPS.get(request.form.get("app_id"))
        sample = request.form.get("sample")
        pdf = (DOCS / LABELS[sample]["file"]).read_bytes() if sample in LABELS else (f.read() if f else b"")
        if not pdf or not app_rec:
            return render_template("precheck.html", apps=APPS, samples=LABELS, error="Pick your application and a receipt.")
        cid = "P" + uuid.uuid4().hex[:6].upper()
        planned = request.form.get("received")
        if not planned:
            app_rec = {**app_rec, "loa_date": None}     # no date given: skip the 15-day check
        # Nothing is written to the ledger: a self-check is private to the institute.
        result = make_case(cid, pdf, app_rec, date.fromisoformat(planned) if planned else date.today(),
                           "precheck", record=False)
        CASES.pop(cid, None)
        result["img"] = page_image(result["sha256"], pdf)
        result["boxes"] = boxes_for(result)
    return render_template("precheck.html", apps=APPS, samples=LABELS, r=result)


# ---------------------------------------------------------------------------
# Try to fool it
# ---------------------------------------------------------------------------
TRICKS = {
    "amount": "Overwrite the amount in figures (words left as printed)",
    "beneficiary": "Make it payable to the college instead of AICTE",
    "tenure": "Shorten the deposit to 8 years",
    "bank": "Move the deposit to a co-operative bank",
    "depositor": "Put a different institute's name as depositor",
    "postdate": "Post-date the deposit by a month",
}


@app.route("/fool", methods=["GET", "POST"])
def fool():
    specs = json.loads((DOCS / "specs.json").read_text())
    clean = [k for k, v in specs.items() if v["defect"] == "none" and not v["scanned"]]
    if request.method == "GET":
        return render_template("fool.html", tricks=TRICKS, clean=clean, specs=specs)

    from tools.generate_test_docs import in_words, render_pdf   # reuse the generator's drawing code
    base_id = request.form.get("base") or random.choice(clean)
    trick = request.form.get("trick") or random.choice(list(TRICKS))
    d = dict(specs[base_id])
    for k in ("issue", "maturity", "submitted"):
        d[k] = date.fromisoformat(d[k])
    if trick == "amount":
        d["amount"] = d["amount"] + 1000000           # +10 lakh in figures only
    elif trick == "beneficiary":
        d["beneficiary"] = f"The Principal, {APPS[d['app_id']]['institute_name']}"
    elif trick == "tenure":
        d["months"] = 96; d["maturity"] = d["issue"].replace(year=d["issue"].year + 8)
    elif trick == "bank":
        d["bank_key"] = "COOP"; d["bank"] = "Shree Sahyadri Sahakari Bank Ltd. (Co-operative)"
    elif trick == "depositor":
        other = random.choice([a for a in APPS.values() if a["app_id"] != d["app_id"]])
        d["depositor"] = other["institute_name"]
    elif trick == "postdate":
        d["issue"] = d["submitted"] + timedelta(days=30)
        d["maturity"] = d["issue"].replace(year=d["issue"].year + 10)
    pdf = render_pdf(d)
    cid = "F" + uuid.uuid4().hex[:6].upper()
    case = make_case(cid, pdf, APPS[d["app_id"]], d["submitted"], origin="fool", record=False)
    case["trick"] = TRICKS[trick]
    case["base"] = base_id
    return redirect(url_for("check", case_id=cid))


# ---------------------------------------------------------------------------
# Evidence and audit
# ---------------------------------------------------------------------------
@app.route("/evaluation")
def evaluation():
    path = ROOT / "reports" / "evaluation.json"
    if not path.exists():
        return render_template("evaluation.html", ev=None)
    hold = {}
    for k in ("holdout", "holdout2"):
        hp = ROOT / "reports" / f"evaluation_{k}.json"
        if hp.exists():
            hold[k] = json.loads(hp.read_text())["summary"]
    return render_template("evaluation.html", ev=json.loads(path.read_text()), hold=hold)


@app.route("/audit")
def audit():
    rows = LEDGER.history(limit=200)
    for r in rows:
        r["detail"] = json.loads(r["detail"]) if r["detail"] else None
    return render_template("audit.html", rows=rows)


@app.route("/rules")
def rules():
    return render_template("rules.html", pack=PACK)


@app.route("/sample/<doc_id>.pdf")
def sample_pdf(doc_id):
    case = CASES.get(doc_id) or (sample_case(doc_id) if doc_id in LABELS else None)
    if not case:
        abort(404)
    return Response(case["pdf"], mimetype="application/pdf")


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8501)), debug=False)
