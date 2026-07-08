"""Tests for Skill-Router. Hermetic: the registry is forced to the bundled snapshot."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import registry as reg_mod
from app.matching import build_idf, rank
from app.registry import parse_endpoints, registry
from app.synth import fill_url


@pytest.fixture(autouse=True)
def offline_registry(monkeypatch):
    """Force the registry to load from the bundled snapshot (no network in tests)."""
    def _boom():
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(registry, "_load_live", _boom)
    registry.refresh(force=True)
    assert registry.status()["source"] == "snapshot"
    yield


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


# ---- pure helpers ----
def test_parse_endpoints_methods_and_urls():
    eps = parse_endpoints("POST https://x.com/a\nGET /b\nhttps://x.com/c")
    assert {"method": "POST", "url": "https://x.com/a"} in eps
    assert {"method": "GET", "url": "/b"} in eps
    assert {"method": "GET", "url": "https://x.com/c"} in eps


def test_parse_endpoints_empty():
    assert parse_endpoints(None) == []
    assert parse_endpoints("") == []


def test_matching_ranks_currency_first():
    idf = build_idf(registry.skills)
    res = rank("convert 100 USD to EUR", registry.skills, idf, top_k=3)
    assert res, "expected at least one match"
    assert "currency" in res[0]["skill"]["name"].lower()


def test_matching_is_deterministic():
    idf = build_idf(registry.skills)
    a = rank("verify an agent identity", registry.skills, idf, top_k=5)
    b = rank("verify an agent identity", registry.skills, idf, top_k=5)
    assert [r["skill"]["id"] for r in a] == [r["skill"]["id"] for r in b]


# ---- call synthesis ----
def test_fill_url_currency():
    url = "https://api.example.com/latest?amount={amount}&from={from}&to={to}"
    filled, ok, missing = fill_url("convert 100 USD to EUR", url)
    assert ok is True
    assert missing == []
    assert "amount=100" in filled and "from=USD" in filled and "to=EUR" in filled


def test_fill_url_reports_missing():
    url = "https://api.example.com/x?amount={amount}&mode={mode}"
    filled, ok, missing = fill_url("convert 50 USD", url)
    assert ok is False
    assert "mode" in missing
    assert "amount=50" in filled


def test_fill_url_no_placeholders():
    url = "https://api.example.com/health"
    filled, ok, missing = fill_url("anything", url)
    assert filled == url and ok is True and missing == []


def test_find_synthesizes_runnable_call(client):
    r = client.post("/find", json={"need": "convert 100 USD to EUR", "top_k": 3})
    body = r.json()
    curr = next((x for x in body["results"] if "currency" in x["name"].lower()), None)
    assert curr is not None
    call = curr["call_plan"]["suggested_first_call"]
    assert call["ready_to_run"] is True
    assert "{" not in call["url"]  # no leftover placeholders


# ---- endpoints ----
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["skills_indexed"] > 0


def test_find_ok(client):
    r = client.post("/find", json={"need": "convert currency", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["results"]
    top = body["results"][0]
    assert top["call_plan"]["suggested_first_call"] is not None
    assert "next_step" in body


def test_find_primary_endpoint_skips_boilerplate(client):
    # A skill whose first endpoint is /health should not suggest /health as the call.
    r = client.post("/find", json={"need": "redact pii privacy consent", "top_k": 1})
    body = r.json()
    call = body["results"][0]["call_plan"]["suggested_first_call"]
    assert call["url"].rstrip("/").lower() not in ("/health", "/agent.json")


def test_find_empty_need(client):
    r = client.post("/find", json={"need": "   "})
    assert r.status_code == 400
    assert r.json()["error"] == "empty_need"
    assert "fix" in r.json()


def test_find_no_match(client):
    r = client.post("/find", json={"need": "zzxqq flibberflop nonsense"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_match"
    assert body["results"] == []


def test_find_invalid_body(client):
    r = client.post("/find", json={"top_k": 2})  # missing required 'need'
    assert r.status_code == 422


def test_skill_not_found(client):
    r = client.get("/skill/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"] == "skill_not_found"


def test_skills_list(client):
    r = client.get("/skills")
    assert r.status_code == 200
    assert r.json()["count"] > 0


def test_unknown_route(client):
    r = client.get("/totally/unknown")
    assert r.status_code == 404
    assert r.json()["error"] == "route_not_found"


# ---- reachability-aware ranking ----
def _mk(name: str, reachable, blob: str) -> dict:
    return {
        "id": name, "name": name, "description": "", "tags": [], "reachable": reachable,
        "_blob": blob, "endpoints": [], "skill_md_url": None, "source_url": None,
        "author": None, "created_at": None,
    }


def test_reachable_skill_ranks_above_unreachable():
    live = _mk("live-pay", True, "payment pay money")
    dead = _mk("dead-pay", False, "payment pay money")
    skills = [dead, live]  # dead listed first; reachability should flip them
    idf = build_idf(skills)
    ranked = rank("payment", skills, idf, top_k=2)
    assert ranked[0]["skill"]["name"] == "live-pay"


def test_probe_live_ignores_non_urls():
    from app.main import _probe_live
    assert _probe_live("") is None
    assert _probe_live("/relative/path") is None


def test_find_verify_flag_shape(client):
    r = client.post("/find", json={"need": "convert currency", "top_k": 1, "verify": False})
    body = r.json()
    assert body["verified_live"] is False  # default path unchanged, no probing


def test_skill_md_served(client):
    r = client.get("/skill.md")
    assert r.status_code == 200
    assert "Skill-Router" in r.text
