"""Web app: sign-in, role limits, officer correction, portal API."""
import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "labels.csv").exists(), reason="generate test docs first")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app as web
    from src.registry import Ledger
    monkeypatch.setattr(web, "LEDGER", Ledger(db_path=None))
    web.CASES.clear()
    return web.app.test_client()


def login(c, user, pw):
    return c.post("/login", data={"username": user, "password": pw})


def test_needs_sign_in(client):
    assert client.get("/").status_code == 302


def test_institute_cannot_open_officer_queue(client):
    login(client, "sahyadri", "inst123")
    assert client.get("/").status_code == 403
    assert client.get("/precheck").status_code == 200


def test_officer_correction_reruns_rules(client):
    lab = {l["doc_id"]: l for l in csv.DictReader(open(ROOT / "data" / "labels.csv"))}
    clean = next(k for k, v in lab.items() if v["defect_type"] == "none" and v["scanned"] == "0")
    login(client, "officer", "officer123")
    assert client.get(f"/check/{clean}").status_code == 200
    r = client.post(f"/check/{clean}/correct", data={"field": "amount", "value": "100000"}, follow_redirects=True)
    assert b"Amount short" in r.data


def test_api_requires_token_and_returns_findings(client):
    lab = next(csv.DictReader(open(ROOT / "data" / "labels.csv")))
    assert client.post("/api/v1/check").status_code == 401
    with open(ROOT / "data" / "test_documents" / lab["file"], "rb") as f:
        r = client.post("/api/v1/check", headers={"Authorization": "Bearer demo-portal-token"},
                        data={"pdf": (f, "x.pdf"), "app_id": lab["app_id"], "received": lab["submitted_on"]})
    assert r.status_code == 200 and r.json["overall"] in ("PASS", "FAIL", "UNCERTAIN") and r.json["findings"]
