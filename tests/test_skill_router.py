"""Tests for Skill-Router. Hermetic: the registry is forced to the bundled snapshot."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import registry as reg_mod
from app.matching import build_idf, rank
from app.registry import parse_endpoints, registry


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


def test_skill_md_served(client):
    r = client.get("/skill.md")
    assert r.status_code == 200
    assert "Skill-Router" in r.text
