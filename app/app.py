"""
SD Scrutiny Desk - web front end for the Security Deposit FDR checker.

    python app/app.py            (then open http://localhost:8501)

Screens
  /dashboard     Officer dashboard: workload, deficiency trends, expiry alerts, measured time per file
  /application/<id>  Whole application: missing documents, cross-document checks, photos, one letter
  /study         Time study: manual vs assisted scrutiny, timed, to measure the time saved
  /              Officer queue: every received document with the system's finding
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
import statistics
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import functools
import os

import yaml
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.render import ocr_status, preview_page                # noqa: E402
from src.deficiency import generate_deficiency_letter          # noqa: E402
from src.pipeline import load_applications, run_check          # noqa: E402
from src.registry import CaseStore, IssuerConnector, Ledger    # noqa: E402
from src.rule_engine import check_document, get_overall_verdict, inr, load_pack, required_amount  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
DEFAULT_SECRET, DEFAULT_TOKEN = "change-me-before-deploying", "demo-portal-token"
app.secret_key = os.environ.get("SECRET_KEY", DEFAULT_SECRET)
USERS = {u["username"]: u for u in yaml.safe_load((ROOT / "config" / "users.yaml").read_text())["users"]}
API_TOKEN = os.environ.get("API_TOKEN", DEFAULT_TOKEN)
PRODUCTION = os.environ.get("APP_ENV", "").lower() == "production"
if PRODUCTION and (app.secret_key == DEFAULT_SECRET or API_TOKEN == DEFAULT_TOKEN):
    raise SystemExit("Refusing to start: APP_ENV=production but SECRET_KEY or API_TOKEN is still the default. "
                     "Set both environment variables to long random values.")

# Who may open what. Anything not listed needs any signed-in user.
ROLE_ACCESS = {
    "queue": {"officer"}, "check": {"officer"}, "decide": {"officer"}, "correct": {"officer"},
    "letter": {"officer"}, "letter_pdf": {"officer"}, "upload": {"officer"}, "sample_pdf": {"officer"},
    "email_letter": {"officer"}, "outbox": {"officer"}, "inbox": {"officer"}, "inbox_events": {"officer"},
    "audit": {"officer", "auditor"}, "dashboard": {"officer", "auditor"}, "application": {"officer"},
    "application_letter": {"officer"}, "add_photo": {"officer"}, "photo_img": {"officer"},
    "study": {"officer"}, "study_next": {"officer"}, "study_submit": {"officer"},
}
PUBLIC = {"login", "logout", "static", "api_check", "api_rules", "api_photo"}
HOME = {"officer": "dashboard", "auditor": "dashboard", "institute": "precheck"}


@app.before_request
def _auth():
    g.user = USERS.get(session.get("user"))
    if request.endpoint in PUBLIC or request.endpoint is None:
        return None
    if g.user is None:
        return redirect(url_for("login", next=request.path))
    allowed = ROLE_ACCESS.get(request.endpoint)
    if allowed and g.user["role"] not in allowed:
        return render_template("denied.html"), 403
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = USERS.get(request.form.get("username", "").strip())
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session["user"] = u["username"]
            nxt = request.args.get("next")
            return redirect(nxt if nxt and nxt.startswith("/") else url_for(HOME[u["role"]]))
        error = "Username or password is wrong."
    return render_template("login.html", error=error, users=USERS.values())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

APPS = load_applications()
PACK = load_pack()
ISSUER = IssuerConnector()
LEDGER = Ledger()                         # data/ledger.sqlite3
DOCS = ROOT / "data" / "test_documents"
LABELS = {r["doc_id"]: r for r in csv.DictReader(open(ROOT / "data" / "labels.csv"))}
CASES = CaseStore()                       # cases survive a restart (data/ledger.sqlite3)
PAGE_CACHE: dict = {}

# Sample documents of every type, shown in the queue: doc_id -> (path, label row)
SAMPLES = {d: (DOCS / r["file"], r) for d, r in LABELS.items()}
for _folder in ("fire_noc", "affidavits"):
    _lab = ROOT / "data" / _folder / "labels.csv"
    if _lab.exists():
        SAMPLES.update({r["doc_id"]: (ROOT / "data" / _folder / r["file"], r) for r in csv.DictReader(open(_lab))})

from src.photos import PhotoStore, check_photo, load_photo_pack, thumbnail   # noqa: E402
PHOTOS = PhotoStore()


def ensure_sample_photos():
    """Load the synthetic infrastructure photos once (in order, so the reused one meets its original)."""
    lab = ROOT / "data" / "photos" / "labels.csv"
    if not lab.exists() or PHOTOS.conn.execute("SELECT 1 FROM photos WHERE origin='sample' LIMIT 1").fetchone():
        return
    for r in csv.DictReader(open(lab)):
        data = (ROOT / "data" / "photos" / r["file"]).read_bytes()
        out = check_photo(data, APPS[r["app_id"]], r["room"], submitted_on=date.fromisoformat(r["submitted_on"]),
                          store=PHOTOS, photo_id=r["photo_id"])
        PHOTOS.add({"id": r["photo_id"], "app_id": r["app_id"], "room": r["room"], "meta": out["meta"],
                    "results": out["results"], "overall": out["overall"], "image": data,
                    "submitted_on": r["submitted_on"], "origin": "sample"})

STATUS_ORDER = {"FAIL": 0, "UNCERTAIN": 1, "PASS": 2, "NA": 3, "EXEMPT": 4}
RULE_ORDER = ["D0", "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "N1", "N2", "N3", "N4",
              "F1", "F2", "F3", "F4", "F5", "F6", "A1", "A2", "A3", "A4"]


def finding_key(r):
    return (STATUS_ORDER.get(r["status"], 9), RULE_ORDER.index(r["rule_id"]) if r["rule_id"] in RULE_ORDER else 99)
OVERALL_TEXT = {"PASS": "No deficiency found", "FAIL": "Deficiency found", "UNCERTAIN": "Needs officer review",
                "EXEMPT": "Not required", "NA": "Not applicable"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def page_image(sha: str, pdf: bytes) -> str:
    if sha not in PAGE_CACHE:
        img = preview_page(pdf, 110)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=82)
        PAGE_CACHE[sha] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    return PAGE_CACHE[sha]


def make_case(case_id: str, pdf: bytes, app_rec: dict, received: date, origin: str, record: bool = True,
              actor: str = "system") -> dict:
    t0 = time.perf_counter()
    out = run_check(pdf, app_rec, submitted_on=received, issuer=ISSUER, ledger=LEDGER if record else None,
                    actor=actor, record=record)
    out["system_seconds"] = round(time.perf_counter() - t0, 2)
    out["results"].sort(key=finding_key)
    req, basis = required_amount({r["id"]: r for r in PACK["rules"]}["R4"], app_rec)
    case = {"id": case_id, "pdf": pdf, "app": app_rec, "received": received, "origin": origin,
            "required": req, "required_basis": basis, "decision": None, **out}
    CASES[case_id] = case
    return case


def sample_case(doc_id: str) -> dict:
    if doc_id not in CASES:
        path, lab = SAMPLES[doc_id]
        make_case(doc_id, path.read_bytes(), APPS[lab["app_id"]],
                  date.fromisoformat(lab["submitted_on"]), origin="sample")
    return CASES[doc_id]


def all_cases() -> list:
    return [sample_case(d) for d in sorted(SAMPLES)] + [c for c in CASES.values() if c["origin"] in ("upload", "inbox")]


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
    return inr(x) if isinstance(x, (int, float)) else "-"


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
    return {"OVERALL_TEXT": OVERALL_TEXT, "rules_version": PACK.get("version"), "user": g.get("user"),
            "ocr": ocr_status(), "apps_known": APPS}


# ---------------------------------------------------------------------------
# Officer screens
# ---------------------------------------------------------------------------
@app.route("/")
def queue():
    cases = all_cases()
    kind = request.args.get("type")
    if kind:
        cases = [c for c in cases if ((c.get("doc_type") or {}).get("type") or "fdr") == kind]
    order = {"FAIL": 1, "UNCERTAIN": 0, "PASS": 2, "EXEMPT": 3}
    cases.sort(key=lambda c: (c["decision"] is not None, order.get(c["overall"], 9), c["id"]))
    counts = {k: sum(1 for c in cases if c["overall"] == k) for k in order}
    return render_template("queue.html", cases=cases, counts=counts, pending=sum(c["decision"] is None for c in cases),
                           kind=kind)


@app.route("/check/<case_id>")
def check(case_id):
    case = CASES.get(case_id) or (sample_case(case_id) if case_id in SAMPLES else None)
    if case is None:
        abort(404)
    if g.user["role"] == "officer" and not case.get("opened_at") and not case.get("decision"):
        case["opened_at"] = datetime.now().isoformat(timespec="seconds")      # for officer time per file
        CASES.save(case)
    pages = case["extraction"]["pages"] or [{"width": 595, "height": 842}]
    return render_template("check.html", c=case, page=pages[0], img=page_image(case["sha256"], case["pdf"]),
                           boxes=boxes_for(case), history=LEDGER.history(case["app"].get("app_id"), 12),
                           label=SAMPLES.get(case_id, (None, None))[1], correctable=CORRECTABLE)


@app.route("/check/<case_id>/decide", methods=["POST"])
def decide(case_id):
    case = CASES.get(case_id) or abort(404)
    officer = g.user["name"]
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
    now = datetime.now()
    case["decision"] = {"action": action, "officer": officer, "agreed": agreed, "overrides": overrides,
                        "at": now.isoformat(timespec="seconds")}
    if case.get("opened_at"):
        secs = (now - datetime.fromisoformat(case["opened_at"])).total_seconds()
        case["decision"]["officer_seconds"] = round(secs) if secs < 3 * 3600 else None   # ignore files left open
    CASES.save(case)
    LEDGER.log(officer, f"officer_{action}", case["app"].get("app_id", "?"), case["sha256"],
               case["rules_version"], action, case["decision"])
    if action == "letter":
        return redirect(url_for("letter", case_id=case_id))
    return redirect(url_for("check", case_id=case_id))


def render_check_error(case, msg):
    pages = case["extraction"]["pages"] or [{"width": 595, "height": 842}]
    return render_template("check.html", c=case, page=pages[0], img=page_image(case["sha256"], case["pdf"]),
                           boxes=boxes_for(case), history=LEDGER.history(case["app"].get("app_id"), 12),
                           label=SAMPLES.get(case["id"], (None, None))[1], error=msg, correctable=CORRECTABLE), 400


@app.route("/check/<case_id>/letter")
def letter(case_id):
    case = CASES.get(case_id) or abort(404)
    text = letter_text(case)
    if request.args.get("download"):
        return Response(text, mimetype="text/plain",
                        headers={"Content-Disposition": f"attachment; filename=deficiency_{case_id}.txt"})
    return render_template("letter.html", c=case, text=text)


CORRECTABLE = {"fdr_number": "FDR number", "bank_name": "Bank", "depositor_name": "Depositor",
               "beneficiary_name": "In favour of", "amount": "Amount (Rs.)", "issue_date": "Deposit date (YYYY-MM-DD)",
               "maturity_date": "Maturity date (YYYY-MM-DD)"}


@app.route("/check/<case_id>/correct", methods=["POST"])
def correct(case_id):
    """Officer fixes a value the machine misread; the rules run again on the corrected values."""
    case = CASES.get(case_id) or abort(404)
    field, value = request.form.get("field"), request.form.get("value", "").strip()
    if field not in CORRECTABLE or not value:
        return render_check_error(case, "Choose the field and type the value as printed on the original.")
    f = dict(case["extraction"]["fields"])
    old = f.get(field)
    try:
        if field == "amount":
            value = float(value.replace(",", "").replace("Rs.", "").strip())
            f["amount_in_words_value"] = f.get("amount_in_words_value")
        elif field in ("issue_date", "maturity_date"):
            value = datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return render_check_error(case, f"'{value}' is not a valid {CORRECTABLE[field].lower()}.")
    f[field] = value
    f.pop("_fdr_number_guessed", None) if field == "fdr_number" else None
    if field == "depositor_name":
        f["institute_name"] = value
    if f.get("issue_date") and f.get("maturity_date"):
        d1, d2 = (datetime.strptime(f[k], "%Y-%m-%d") for k in ("issue_date", "maturity_date"))
        f["tenure_years"] = round((d2 - d1).days / 365.25, 2)
    results = check_document(f, case["app"], submitted_on=case["received"], issuer=ISSUER, ledger=LEDGER,
                             sha256=case["sha256"])
    results.sort(key=finding_key)
    case["extraction"]["fields"] = f
    case["results"] = results
    case["overall"] = get_overall_verdict(results)
    case.setdefault("corrections", []).append({"field": CORRECTABLE[field], "old": old, "new": value,
                                               "by": g.user["name"], "at": datetime.now().isoformat(timespec="seconds")})
    CASES.save(case)
    LEDGER.log(g.user["name"], "officer_correction", case["app"].get("app_id", "?"), case["sha256"],
               case["rules_version"], case["overall"], {"field": field, "old": old, "new": value})
    return redirect(url_for("check", case_id=case_id))


def letter_text(case: dict, draft: bool = True) -> str:
    d = case.get("decision") or {}
    return generate_deficiency_letter(case["extraction"]["fields"], case["results"], case["app"],
                                      officer_name=d.get("officer"), confirmed_rule_ids=d.get("agreed"), draft=draft,
                                      document_label=(case.get("doc_type") or {}).get("name"))


def letter_pdf_bytes(case: dict, draft: bool = True) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    text = letter_text(case, draft)
    buf = io.BytesIO()
    style = ParagraphStyle("b", fontName="Times-Roman", fontSize=11, leading=15)
    head = ParagraphStyle("h", parent=style, fontName="Times-Bold", textColor="#A8231A")
    story = []
    for line in text.split("\n"):
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lead = len(line) - len(line.lstrip(" "))
        story.append(Paragraph(esc.strip() or "&nbsp;", head if line.startswith("DRAFT") else
                               ParagraphStyle("i", parent=style, leftIndent=lead * 3)))
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=60, rightMargin=60, topMargin=60, bottomMargin=60,
                      title=f"Deficiency letter {case['id']}").build(story)
    return buf.getvalue()


@app.route("/check/<case_id>/letter.pdf")
def letter_pdf(case_id):
    case = CASES.get(case_id) or abort(404)
    return Response(letter_pdf_bytes(case), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=deficiency_{case_id}.pdf"})


@app.route("/check/<case_id>/email", methods=["POST"])
def email_letter(case_id):
    """Officer approves and sends the letter: the PDF goes to the institute straight away."""
    from src.mailer import send_letter
    case = CASES.get(case_id) or abort(404)
    if not (case.get("decision") or {}).get("action") == "letter":
        abort(400)
    to = request.form.get("to", "").strip() or case["app"].get("contact_email", "")
    if "@" not in to:
        return render_template("letter.html", c=case, text=letter_text(case), error="Enter the institute's email address.")
    inst = case["app"].get("institute_name", "the institute")
    body = (f"Dear Principal / Director,\n\nPlease find attached the deficiency letter for application "
            f"{case['app'].get('app_id')} ({inst}) regarding the document submitted to AICTE. Kindly rectify the "
            f"points listed and resubmit through the portal.\n\nRegards,\n{g.user['name']}\nRegional Office, AICTE")
    res = send_letter(to, f"Deficiency in submitted document - {case['app'].get('app_id')}", body,
                      letter_pdf_bytes(case, draft=False), f"deficiency_{case_id}.pdf")
    case["email"] = {**res, "by": g.user["name"]}
    CASES.save(case)
    LEDGER.log(g.user["name"], "letter_emailed" if res["status"] == "sent" else "letter_saved_to_outbox",
               case["app"].get("app_id", "?"), case["sha256"], case["rules_version"], res["status"], {"to": to})
    return redirect(url_for("letter", case_id=case_id))


@app.route("/outbox")
def outbox():
    rows = [c for c in CASES.values() if c.get("email")]
    rows.sort(key=lambda c: c["email"]["at"], reverse=True)
    from src.mailer import smtp_configured
    return render_template("outbox.html", rows=rows, smtp=smtp_configured())


# ---------------------------------------------------------------------------
# Live inbox: drop a PDF into a folder, see the result in seconds
# ---------------------------------------------------------------------------
def _inbox_handler(path, data, sub):
    from src.extractor import extract_document
    from src.rule_engine import name_similarity
    app_rec, how = None, ""
    if sub and sub in APPS:
        app_rec, how = APPS[sub], f"folder {sub}"
    ext = extract_document(data)
    if ext["doc_type"]["type"] is None:
        why = ("scanned copy, and the OCR engine is not installed" if ext["method"] == "ocr-missing"
               else "no Fixed Deposit Receipt, Fire NOC or affidavit wording found")
        return {"error": f"Not a supported document ({why}). Nothing was checked."}
    if app_rec is None:
        f = ext["fields"]
        name = f.get("depositor_name") or f.get("institute_name")
        if name:
            scored = sorted(((max(name_similarity(name, a["institute_name"]), name_similarity(name, a.get("trust"))), a)
                             for a in APPS.values()), key=lambda t: -t[0])
            if scored[0][0] >= 75:
                app_rec, how = scored[0][1], f"name on document ({scored[0][0]:.0f}% match)"
    if app_rec is None and INBOX.settings.get("default_app") in APPS:
        app_rec, how = APPS[INBOX.settings["default_app"]], "default application"
    if app_rec is None:
        return {"error": "Could not tell which application this belongs to. Choose a default application, "
                         "or put the file in a folder named after the application number."}
    cid = "I" + uuid.uuid4().hex[:6].upper()
    case = make_case(cid, data, app_rec, INBOX.received_date(), origin="inbox")
    case["inbox_file"] = path.name
    CASES.save(case)
    return {"case": cid, "institute": app_rec["institute_name"], "matched": how, "overall": case["overall"],
            "overall_text": OVERALL_TEXT.get(case["overall"], case["overall"]),
            "doc_type": case["doc_type"]["name"] if case.get("doc_type") else "",
            "points": [r.get("problem") or r["name"] for r in case["results"] if r["status"] in ("FAIL", "UNCERTAIN")][:3]}


from src.inbox import INBOX_DIR, InboxWatcher   # noqa: E402
INBOX = InboxWatcher(INBOX_DIR, _inbox_handler)


@app.route("/inbox", methods=["GET", "POST"])
def inbox():
    INBOX.start()
    if request.method == "POST":
        INBOX.settings["default_app"] = request.form.get("default_app") or None
        INBOX.settings["received"] = request.form.get("received") or None
        return redirect(url_for("inbox"))
    return render_template("inbox.html", folder=str(INBOX_DIR.resolve()), apps=APPS, settings=INBOX.settings,
                           events=INBOX.recent())


@app.route("/inbox/events")
def inbox_events():
    return jsonify({"running": INBOX.running(), "events": INBOX.recent()})


# ---------------------------------------------------------------------------
# API for the AICTE portal
# ---------------------------------------------------------------------------
def _api_auth():
    return request.headers.get("Authorization", "") == f"Bearer {API_TOKEN}"


@app.route("/api/v1/check", methods=["POST"])
def api_check():
    """POST multipart: pdf (file), app_id, received (YYYY-MM-DD, optional).
    Or JSON-free: the portal sends the application record as form field 'application' (JSON)."""
    if not _api_auth():
        return jsonify({"error": "missing or wrong bearer token"}), 401
    f = request.files.get("pdf")
    if not f:
        return jsonify({"error": "field 'pdf' is required"}), 400
    if request.form.get("application"):
        app_rec = json.loads(request.form["application"])
    elif request.form.get("app_id") in APPS:
        app_rec = APPS[request.form["app_id"]]
    else:
        return jsonify({"error": "send 'app_id' of a known application or the 'application' record as JSON"}), 400
    received = date.fromisoformat(request.form["received"]) if request.form.get("received") else date.today()
    out = run_check(f.read(), app_rec, submitted_on=received, issuer=ISSUER, ledger=LEDGER, actor="portal-api")
    ext = out["extraction"]
    return jsonify({
        "app_id": app_rec.get("app_id"), "overall": out["overall"], "sha256": out["sha256"],
        "rules_version": out["rules_version"], "read_method": ext["method"], "read_quality": ext["read_quality"],
        "fields": {k: v for k, v in ext["fields"].items() if not k.startswith("_")},
        "evidence_locations": ext["locations"],
        "findings": [{k: r[k] for k in ("rule_id", "name", "problem", "status", "ps_status", "severity", "clause",
                                        "evidence", "reasoning", "fix")} for r in out["results"]],
        "note": "Decision support only. A FAIL is a point for an officer, not a rejection.",
    })


@app.route("/api/v1/rules")
def api_rules():
    return jsonify(PACK)


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
        if g.user["role"] == "institute":
            app_rec = APPS.get(g.user.get("app_id"))
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
    apps = APPS if g.user["role"] != "institute" else {g.user["app_id"]: APPS[g.user["app_id"]]}
    return render_template("precheck.html", apps=apps, samples=LABELS, r=result)


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
    CASES.save(case)
    return redirect(url_for("check", case_id=cid))


# ---------------------------------------------------------------------------
# Evidence and audit
# ---------------------------------------------------------------------------
@app.route("/evaluation")
def evaluation():
    rep = ROOT / "reports"
    load = lambda k: json.loads((rep / f"{k}.json").read_text()) if (rep / f"{k}.json").exists() else None
    ev = load("evaluation")
    unseen = []
    for k, name in (("holdout", "Unseen layout 1"), ("holdout2", "Unseen layout 2 (never used for tuning)")):
        before, after = load(f"evaluation_{k}_noml"), load(f"evaluation_{k}")
        if before and after:
            unseen.append({"name": name, "before": before["summary"], "after": after["summary"]})
    return render_template("evaluation.html", ev=ev, unseen=unseen, noc=load("evaluation_noc"),
                           aff=load("evaluation_affidavit"), photos=load("evaluation_photos"), study=study_summary())


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
    case = CASES.get(doc_id) or (sample_case(doc_id) if doc_id in SAMPLES else None)
    if not case:
        abort(404)
    return Response(case["pdf"], mimetype="application/pdf")

# ---------------------------------------------------------------------------
# Whole application: every document together, missing ones, cross-document checks
# ---------------------------------------------------------------------------
from src.application import application_letter, review_application   # noqa: E402


def app_review(app_id: str):
    ensure_sample_photos()
    cases = [c for c in all_cases() if c["app"].get("app_id") == app_id]
    photos = PHOTOS.for_app(app_id)
    return cases, photos, review_application(APPS[app_id], cases, photos)


@app.route("/application/<app_id>")
def application(app_id):
    if app_id not in APPS:
        abort(404)
    cases, photos, rv = app_review(app_id)
    return render_template("application.html", a=APPS[app_id], rv=rv, cases=sorted(cases, key=lambda c: c["id"]),
                           photos=photos, rooms=load_photo_pack()["rooms"], today=date.today(),
                           error=request.args.get("error"))


@app.route("/application/<app_id>/photo", methods=["POST"])
def add_photo(app_id):
    if app_id not in APPS:
        abort(404)
    files = [f for f in request.files.getlist("photo") if f and f.filename]
    if not files:
        return redirect(url_for("application", app_id=app_id, error="Choose one or more photographs (JPEG)."))
    room = request.form.get("room") or "Other"
    received = date.fromisoformat(request.form.get("received") or date.today().isoformat())
    for f in files:
        data = f.read()
        pid = "PH" + uuid.uuid4().hex[:6].upper()
        try:
            out = check_photo(data, APPS[app_id], room, submitted_on=received, store=PHOTOS, photo_id=pid)
        except Exception:
            return redirect(url_for("application", app_id=app_id, error=f"'{f.filename}' is not a readable image."))
        PHOTOS.add({"id": pid, "app_id": app_id, "room": room, "meta": out["meta"], "results": out["results"],
                    "overall": out["overall"], "image": data, "submitted_on": received.isoformat(), "origin": "upload"})
        LEDGER.log(g.user["name"], "photo_check", app_id, out["meta"]["sha256"], out["rules_version"], out["overall"],
                   {r["rule_id"]: r["status"] for r in out["results"]})
    return redirect(url_for("application", app_id=app_id) + "#photos")


@app.route("/photo/<pid>.jpg")
def photo_img(pid):
    p = PHOTOS.get(pid) or abort(404)
    return Response(thumbnail(p["image"], int(request.args.get("w", 360))), mimetype="image/jpeg")


@app.route("/application/<app_id>/letter", endpoint="application_letter")
def application_letter_view(app_id):
    if app_id not in APPS:
        abort(404)
    _, photos, rv = app_review(app_id)
    text = application_letter(APPS[app_id], rv, photos, officer=g.user["name"])
    if request.args.get("download"):
        return Response(text, mimetype="text/plain",
                        headers={"Content-Disposition": f"attachment; filename=deficiency_{app_id}.txt"})
    return render_template("app_letter.html", a=APPS[app_id], text=text, rv=rv)



# ---------------------------------------------------------------------------
# Dashboard: workload, trends, alerts, measured time
# ---------------------------------------------------------------------------
def _days(a, b):
    return (a - b).days


@app.route("/dashboard")
def dashboard():
    from src.rule_engine import _d
    ensure_sample_photos()
    as_of = date.fromisoformat(request.args["as_of"]) if request.args.get("as_of") else date.today()
    cases = all_cases()
    photos = PHOTOS.all()
    kinds = {"fdr": "Security Deposit FDR", "fire_noc": "Fire NOC", "affidavit": "Affidavit"}
    by_kind = {k: [c for c in cases if ((c.get("doc_type") or {}).get("type") or "fdr") == k] for k in kinds}

    # deficiency types: count every FAIL by its problem label
    trend: dict = {}
    for c in cases:
        for r in c["results"]:
            if r["status"] == "FAIL":
                trend[(r["rule_id"], r.get("problem") or r["name"])] = trend.get((r["rule_id"], r.get("problem") or r["name"]), 0) + 1
    for p in photos:
        for r in p["results"]:
            if r["status"] == "FAIL":
                trend[(r["rule_id"], r["problem"])] = trend.get((r["rule_id"], r["problem"]), 0) + 1
    trend = sorted(trend.items(), key=lambda t: -t[1])[:10]

    # alerts
    alerts = []
    for c in by_kind["fire_noc"]:
        until = _d(c["extraction"]["fields"].get("valid_upto"))
        if until and _days(until, as_of) <= 90:
            alerts.append({"level": "FAIL" if until < as_of else "UNCERTAIN", "case": c,
                           "text": (f"Fire NOC expired on {until:%d %b %Y}" if until < as_of else
                                    f"Fire NOC expires on {until:%d %b %Y} ({_days(until, as_of)} days)"),
                           "sort": _days(until, as_of)})
    sd_years = next((r.get("minimum_tenure_years") for r in PACK["rules"] if r["id"] == "R3"), 10) or 10
    for c in by_kind["fdr"]:
        f = c["extraction"]["fields"]
        mat, iss = _d(f.get("maturity_date")), _d(f.get("issue_date"))
        if c["overall"] == "EXEMPT" or not mat:
            continue
        if _days(mat, as_of) <= 180:
            alerts.append({"level": "FAIL" if mat < as_of else "UNCERTAIN", "case": c, "sort": _days(mat, as_of),
                           "text": f"FDR {'matured' if mat < as_of else 'matures'} on {mat:%d %b %Y}: Security Deposit must be renewed"})
        elif iss and (mat - iss).days < sd_years * 365 - 5:
            alerts.append({"level": "UNCERTAIN", "case": c, "sort": _days(mat, as_of),
                           "text": f"FDR matures on {mat:%d %b %Y}, before the {sd_years}-year Security Deposit period ends: renewal reminder needed"})
    for c in cases:
        e = c.get("email")
        if e and e.get("at"):
            sent = datetime.fromisoformat(e["at"]).date()
            if _days(as_of, sent) > 30:
                alerts.append({"level": "UNCERTAIN", "case": c, "sort": -_days(as_of, sent),
                               "text": f"Deficiency letter sent {sent:%d %b %Y}; no corrected document received in {_days(as_of, sent)} days"})
    alerts.sort(key=lambda a: a["sort"])

    # applications
    apps_rows = []
    for app_id, a in APPS.items():
        cs = [c for c in cases if c["app"].get("app_id") == app_id]
        ps = [p for p in photos if p["app_id"] == app_id]
        rv = review_application(a, cs, ps)
        apps_rows.append({"a": a, "rv": rv, "docs": len(cs) + len(ps)})
    order = {"FAIL": 0, "INCOMPLETE": 1, "UNCERTAIN": 2, "PASS": 3}
    apps_rows.sort(key=lambda r: (order.get(r["rv"]["status"], 9), r["a"]["app_id"]))
    states: dict = {}
    for r in apps_rows:
        s = states.setdefault(r["a"]["state"], {"apps": 0, "def": 0})
        s["apps"] += 1
        s["def"] += r["rv"]["status"] in ("FAIL", "INCOMPLETE")

    decided = [c["decision"]["officer_seconds"] for c in cases if c.get("decision") and c["decision"].get("officer_seconds")]
    sys_t = [c["system_seconds"] for c in cases if c.get("system_seconds")]
    kpi = {"documents": len(cases) + len(photos), "pending": sum(1 for c in cases if not c.get("decision")),
           "deficient": sum(1 for c in cases if c["overall"] == "FAIL") + sum(1 for p in photos if p["overall"] == "FAIL"),
           "review": sum(1 for c in cases if c["overall"] == "UNCERTAIN") + sum(1 for p in photos if p["overall"] == "UNCERTAIN"),
           "officer_median": round(statistics.median(decided) / 60, 1) if decided else None, "decided": len(decided),
           "system_median": round(statistics.median(sys_t), 1) if sys_t else None}
    return render_template("dashboard.html", kpi=kpi, trend=trend, alerts=alerts[:15], n_alerts=len(alerts),
                           apps_rows=apps_rows, states=sorted(states.items()), by_kind={k: len(v) for k, v in by_kind.items()},
                           kinds=kinds, n_photos=len(photos), as_of=as_of, study=study_summary())


# ---------------------------------------------------------------------------
# Time study: the same files checked by hand and with the desk, timed
# ---------------------------------------------------------------------------
import sqlite3   # noqa: E402

STUDY_DB = sqlite3.connect(str(ROOT / "data" / "ledger.sqlite3"), check_same_thread=False)
STUDY_DB.execute("CREATE TABLE IF NOT EXISTS study (id INTEGER PRIMARY KEY, at TEXT, user TEXT, mode TEXT, doc_id TEXT, "
                 "seconds REAL, marked TEXT, truth TEXT)")
STUDY_DB.commit()
STUDY_RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "A1", "A2", "A3", "A4"]


def study_summary() -> dict:
    rows = STUDY_DB.execute("SELECT mode, seconds, marked, truth FROM study").fetchall()
    out = {}
    for mode in ("manual", "assisted"):
        rs = [r for r in rows if r[0] == mode]
        if not rs:
            continue
        planted = sum(len(json.loads(t)) for _, _, _, t in rs)
        caught = sum(len(set(json.loads(m)) & set(json.loads(t))) for _, _, m, t in rs)
        false = sum(len(set(json.loads(m)) - set(json.loads(t))) for _, _, m, t in rs)
        secs = [s for _, s, _, _ in rs]
        out[mode] = {"files": len(rs), "mean_min": round(statistics.mean(secs) / 60, 1),
                     "median_min": round(statistics.median(secs) / 60, 1),
                     "caught": f"{caught}/{planted}", "recall": round(caught / planted, 2) if planted else None,
                     "false_marks": false}
    if "manual" in out and "assisted" in out and out["manual"]["mean_min"]:
        out["saved_pct"] = round(100 * (1 - out["assisted"]["mean_min"] / out["manual"]["mean_min"]))
    return out


@app.route("/study")
def study():
    rows = STUDY_DB.execute("SELECT at, user, mode, doc_id, seconds, marked, truth FROM study ORDER BY id DESC LIMIT 40").fetchall()
    return render_template("study.html", s=study_summary(), rows=[
        {"at": r[0], "user": r[1], "mode": r[2], "doc": r[3], "min": round(r[4] / 60, 1),
         "marked": json.loads(r[5]), "truth": json.loads(r[6])} for r in rows], last=session.pop("study_last", None))


@app.route("/study/next")
def study_next():
    mode = request.args.get("mode", "manual")
    done = {r[0] for r in STUDY_DB.execute("SELECT doc_id FROM study WHERE user=? AND mode=?", (g.user["username"], mode))}
    pool = [d for d in sorted(LABELS) if d not in done] or sorted(LABELS)
    doc = random.Random(f"{g.user['username']}{mode}{len(done)}").choice(pool)
    case = sample_case(doc)
    session["study"] = {"doc": doc, "mode": mode, "start": time.time()}
    problems = {r["id"]: r.get("problem") or r["name"] for r in PACK["rules"] if r["id"] in STUDY_RULES}
    problems.update({"A1": "Edited after issue", "A2": "Values in a different font / printed over",
                     "A3": "QR code does not match", "A4": "Pasted patch in a scan"})
    pages = case["extraction"]["pages"] or [{"width": 595, "height": 842}]
    return render_template("study_doc.html", c=case, mode=mode, img=page_image(case["sha256"], case["pdf"]), page=pages[0],
                           problems=problems, n_done=len(done),
                           system_fail={r["rule_id"] for r in case["results"] if r["status"] == "FAIL"})


@app.route("/study/submit", methods=["POST"])
def study_submit():
    st = session.pop("study", None)
    if not st:
        return redirect(url_for("study"))
    secs = time.time() - st["start"]
    marked = sorted(set(request.form.getlist("rule")) & set(STUDY_RULES))
    truth = [x for x in LABELS[st["doc"]]["expected_fail_rules"].split(";") if x in STUDY_RULES]
    STUDY_DB.execute("INSERT INTO study (at, user, mode, doc_id, seconds, marked, truth) VALUES (?,?,?,?,?,?,?)",
                     (datetime.now().isoformat(timespec="seconds"), g.user["username"], st["mode"], st["doc"], secs,
                      json.dumps(marked), json.dumps(truth)))
    STUDY_DB.commit()
    session["study_last"] = {"doc": st["doc"], "mode": st["mode"], "min": round(secs / 60, 1),
                             "missed": sorted(set(truth) - set(marked)), "extra": sorted(set(marked) - set(truth)),
                             "truth": truth}
    if request.form.get("again"):
        return redirect(url_for("study_next", mode=st["mode"]))
    return redirect(url_for("study"))


@app.route("/api/v1/photo", methods=["POST"])
def api_photo():
    """POST multipart: photo (JPEG), app_id, room, received (optional). Bearer token as for /api/v1/check."""
    if not _api_auth():
        return jsonify({"error": "missing or wrong bearer token"}), 401
    f, app_id = request.files.get("photo"), request.form.get("app_id")
    if not f or app_id not in APPS:
        return jsonify({"error": "send 'photo' and the 'app_id' of a known application"}), 400
    received = date.fromisoformat(request.form["received"]) if request.form.get("received") else date.today()
    data = f.read()
    pid = "PH" + uuid.uuid4().hex[:6].upper()
    out = check_photo(data, APPS[app_id], request.form.get("room", "Other"), submitted_on=received, store=PHOTOS, photo_id=pid)
    PHOTOS.add({"id": pid, "app_id": app_id, "room": request.form.get("room", "Other"), "meta": out["meta"],
                "results": out["results"], "overall": out["overall"], "image": data, "submitted_on": received.isoformat(),
                "origin": "api"})
    return jsonify({"photo_id": pid, "overall": out["overall"], "rules_version": out["rules_version"],
                    "metadata": {k: out["meta"][k] for k in ("taken", "lat", "lon", "make", "model", "software")},
                    "findings": [{k: r[k] for k in ("rule_id", "name", "status", "evidence", "reasoning", "fix")}
                                 for r in out["results"]],
                    "note": "Decision support only. A FAIL is a point for an officer, not a rejection."})


if __name__ == "__main__":
    import os
    INBOX.start()
    print(f" * Live inbox: drop PDFs into {INBOX_DIR.resolve()}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8501)), debug=False)
