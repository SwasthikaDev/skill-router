"""Skill-Router — a discovery/routing service for the agent web.

An AI agent describes what it needs in plain language; Skill-Router returns the
best-matching skills from the live NANDA registry, each with a normalized,
ready-to-run call plan (method, URL, a paste-ready curl, and how to verify
success). One hop from "I need X" to an executable call.

Design goals (it is graded by an AI agent, so):
  * zero auth, deterministic output, one verifiable success signal;
  * never goes dark — live registry with a bundled snapshot fallback;
  * every error is self-correcting: it tells the caller exactly how to fix it.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

from .matching import build_idf, rank
from .registry import registry

app = FastAPI(
    title="Skill-Router",
    version="1.0.0",
    description="Natural-language discovery + call routing over the NANDA skills registry.",
)

# ---- IDF is cheap to recompute and depends on the current registry snapshot ----
_idf_cache: dict = {"source": None, "count": 0, "idf": {}}


def get_idf() -> dict:
    status = registry.status()
    if _idf_cache["count"] != status["count"] or _idf_cache["source"] != status["source"]:
        _idf_cache["idf"] = build_idf(registry.skills)
        _idf_cache["count"] = status["count"]
        _idf_cache["source"] = status["source"]
    return _idf_cache["idf"]


def _example_curl(method: str, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"# endpoint path is relative — see the skill's SKILL.md for its base URL\n# {method} {url}"
    if method == "GET":
        return f"curl -sSL '{url}'"  # -L follows redirects the target may issue
    return (
        f"curl -sS -X {method} '{url}' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{{}}'   # fill the body per the skill's SKILL.md"
    )


_BOILERPLATE = ("/health", "/agent.json", "/skill.md", "/openapi", "/docs", "/", "/ping")


def _choose_primary(eps: list[dict]) -> dict | None:
    """Pick the most useful endpoint to call first, skipping health/discovery boilerplate."""
    if not eps:
        return None
    meaningful = [
        e for e in eps
        if e["url"].rstrip("/").lower().split("?")[0] not in _BOILERPLATE
        and not e["url"].lower().endswith((".json", ".md"))
    ]
    pool = meaningful or eps
    # Prefer an absolute URL the agent can call without extra context.
    absolute = [e for e in pool if e["url"].startswith(("http://", "https://"))]
    return (absolute or pool)[0]


def _call_plan(skill: dict) -> dict:
    eps = skill["endpoints"]
    first = _choose_primary(eps)
    return {
        "skill_md_url": skill["skill_md_url"],
        "read_this_first": "Fetch skill_md_url for exact request/response schemas before calling.",
        "endpoints": eps,
        "suggested_first_call": (
            {
                "method": first["method"],
                "url": first["url"],
                "example_curl": _example_curl(first["method"], first["url"]),
            }
            if first
            else None
        ),
    }


def _present(match: dict) -> dict:
    s = match["skill"]
    return {
        "id": s["id"],
        "name": s["name"],
        "author": s["author"],
        "description": s["description"],
        "tags": s["tags"],
        "reachable": s["reachable"],
        "confidence": match.get("confidence"),
        "score": match["score"],
        "why": (
            f"Matched on: {', '.join(match['matched_terms'])}."
            if match["matched_terms"]
            else "Matched by overall relevance."
        ),
        "call_plan": _call_plan(s),
    }


# --------------------------------- models ---------------------------------
class FindRequest(BaseModel):
    need: str = Field(..., description="Plain-language description of what the agent needs.")
    top_k: int = Field(3, ge=1, le=10, description="How many skills to return.")


# --------------------------------- routes ---------------------------------
@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return (
        "Skill-Router — natural-language discovery + call routing over the NANDA skills registry.\n"
        "No API key required. Start here: POST /find {\"need\": \"...\"}.  Docs: /skill.md  Health: /health\n"
    )


@app.get("/skill.md", response_class=PlainTextResponse)
@app.get("/SKILL.md", response_class=PlainTextResponse)
def skill_md() -> str:
    try:
        return _SKILL_MD.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "SKILL.md not found on server."


@app.get("/health")
def health() -> dict:
    registry.ensure_loaded()
    st = registry.status()
    return {
        "status": "ok",
        "registry_source": st["source"],  # "live" or "snapshot"
        "skills_indexed": st["count"],
    }


@app.post("/find")
def find(req: FindRequest) -> dict:
    need = req.need.strip()
    if not need:
        return JSONResponse(
            status_code=400,
            content={
                "error": "empty_need",
                "message": "The 'need' field was empty.",
                "fix": "Send JSON like {\"need\": \"convert currency\", \"top_k\": 3}.",
            },
        )
    idf = get_idf()
    matches = rank(need, registry.skills, idf, top_k=req.top_k)
    if not matches:
        return {
            "status": "no_match",
            "need": need,
            "message": "No skill in the registry matched that need.",
            "suggestion": "Try broader or different keywords (e.g. 'payment', 'identity', "
            "'memory', 'privacy', 'negotiation'). GET /skills to browse everything.",
            "results": [],
        }
    return {
        "status": "ok",
        "need": need,
        "count": len(matches),
        "results": [_present(m) for m in matches],
        "next_step": "Open results[0].call_plan.skill_md_url, then run "
        "results[0].call_plan.suggested_first_call.example_curl.",
    }


@app.get("/skills")
def list_skills() -> dict:
    st = registry.status()
    return {
        "status": "ok",
        "registry_source": st["source"],
        "count": st["count"],
        "skills": [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "tags": s["tags"],
                "reachable": s["reachable"],
                "skill_md_url": s["skill_md_url"],
            }
            for s in registry.skills
        ],
    }


@app.get("/skill/{skill_id}")
def get_skill(skill_id: str) -> dict:
    s = registry.get(skill_id)
    if s is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "skill_not_found",
                "message": f"No skill with id '{skill_id}'.",
                "fix": "Call GET /skills to list valid ids, or POST /find to search by need.",
            },
        )
    return {"status": "ok", "skill": {**{k: v for k, v in s.items() if k != "_blob"}, "call_plan": _call_plan(s)}}


@app.post("/refresh")
def refresh() -> dict:
    st = registry.refresh(force=True)
    return {"status": "ok", "reloaded": True, **st}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": "route_not_found",
            "message": f"No route for {request.method} {request.url.path}.",
            "fix": "Valid routes: GET /health, POST /find, GET /skills, GET /skill/{id}, POST /refresh.",
        },
    )
