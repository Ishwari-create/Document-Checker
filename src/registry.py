"""
Things the checker must look up outside the document itself:

  IssuerConnector  asks the issuing bank whether the FDR exists and matches.
                   Here it reads data/bank_confirmations.json (synthetic). In
                   production this is where a bank API, an NeSL/e-BG style
                   registry or a signed branch confirmation would plug in; the
                   rule engine only sees the status it returns.

  Ledger           remembers every submitted FDR (number + file hash) so the
                   same deposit cannot back two applications, and keeps the
                   audit trail of every check and every officer decision.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIRMATIONS_FILE = ROOT / "data" / "bank_confirmations.json"
DEFAULT_DB = ROOT / "data" / "ledger.sqlite3"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").lower().replace(".", " ").replace(",", " ").split())


class IssuerConnector:
    """Mock bank confirmation service. Status vocabulary follows the SIH26261 brief."""

    def __init__(self, path: Path = CONFIRMATIONS_FILE):
        data = json.loads(path.read_text()) if path.exists() else {}
        self.connected = [_norm(b) for b in data.get("connected_banks", [])]
        self.records: Dict[str, dict] = data.get("records", {})

    def confirm(self, bank_name: Optional[str], fdr_number: Optional[str]) -> Dict[str, Any]:
        checked_at = datetime.now().isoformat(timespec="seconds")
        base = {"source": "Bank confirmation service (synthetic mock)", "checked_at": checked_at}
        bank = _norm(bank_name)
        if not bank or not any(c in bank or bank in c for c in self.connected):
            return {**base, "status": "source_unavailable", "record": None,
                    "detail": f"'{bank_name or 'unknown bank'}' is not connected to the confirmation service."}
        if not fdr_number:
            return {**base, "status": "verification_pending", "record": None,
                    "detail": "FDR number could not be read, so the bank could not be asked."}
        rec = self.records.get(fdr_number)
        if rec is None:
            return {**base, "status": "not_found", "record": None,
                    "detail": f"Bank has no deposit numbered {fdr_number}."}
        return {**base, "status": "found", "record": rec, "detail": "Record returned by the bank."}


class Ledger:
    def __init__(self, db_path: Optional[Path] = DEFAULT_DB):
        self.conn = sqlite3.connect(str(db_path) if db_path else ":memory:", check_same_thread=False)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY, app_id TEXT, fdr_number TEXT, bank TEXT,
                sha256 TEXT, submitted_at TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, app_id TEXT,
                sha256 TEXT, rules_version TEXT, outcome TEXT, detail TEXT);
        """)

    # -- duplicates ---------------------------------------------------------
    def find_reuse(self, app_id: str, fdr_number: Optional[str], bank: Optional[str], sha: str) -> List[dict]:
        rows = self.conn.execute(
            "SELECT app_id, fdr_number, bank, sha256, submitted_at FROM submissions "
            "WHERE app_id != ? AND (sha256 = ? OR (fdr_number = ? AND fdr_number IS NOT NULL))",
            (app_id, sha, fdr_number)).fetchall()
        out = []
        for a, f, b, h, t in rows:
            if h == sha or _norm(b) == _norm(bank) or not bank:
                out.append({"app_id": a, "fdr_number": f, "same_file": h == sha, "submitted_at": t})
        return out

    def record_submission(self, app_id: str, fdr_number: Optional[str], bank: Optional[str], sha: str):
        exists = self.conn.execute("SELECT 1 FROM submissions WHERE app_id=? AND sha256=?", (app_id, sha)).fetchone()
        if not exists:
            self.conn.execute("INSERT INTO submissions (app_id, fdr_number, bank, sha256, submitted_at) "
                              "VALUES (?,?,?,?,?)", (app_id, fdr_number, bank, sha,
                                                    datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()

    # -- audit trail -----------------------------------------------------------
    def log(self, actor: str, action: str, app_id: str, sha: str, rules_version: str,
            outcome: str, detail: Any = None):
        self.conn.execute(
            "INSERT INTO audit (at, actor, action, app_id, sha256, rules_version, outcome, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), actor, action, app_id, sha, rules_version,
             outcome, json.dumps(detail, default=str) if detail is not None else None))
        self.conn.commit()

    def history(self, app_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        q = "SELECT at, actor, action, app_id, sha256, rules_version, outcome, detail FROM audit"
        args: tuple = ()
        if app_id:
            q += " WHERE app_id = ?"
            args = (app_id,)
        q += " ORDER BY id DESC LIMIT ?"
        cols = ["at", "actor", "action", "app_id", "sha256", "rules_version", "outcome", "detail"]
        return [dict(zip(cols, r)) for r in self.conn.execute(q, args + (limit,)).fetchall()]
