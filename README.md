# Skill-Router

**Give an agent a task in plain English; get back the right service and a call it can run right now.**

**Live app → [skill-router.onrender.com](https://skill-router.onrender.com)** — open it in your browser and search. No signup, no API key. ([SKILL.md](https://raw.githubusercontent.com/SwasthikaDev/skill-router/main/SKILL.md) · [API docs](https://skill-router.onrender.com/docs))

The NANDA skills registry already lists dozens of agent services (currency
conversion, identity checks, data redaction, and so on). But there is no way for an
agent to *find* the right one at run time — it has to already know the service exists
and already know how to call it. Skill-Router closes that gap.

Send `POST /find` with a need like `"convert 100 USD to EUR"`. Skill-Router scores
that need against every service in the live
[registry](https://nandatown.projectnanda.org/skills) and returns the best matches.
For the top match it also returns a **call plan**: the HTTP method, the URL, a
paste-ready `curl`, and — when your need already contains the values — the URL with
the placeholders filled in, so the call runs as-is. One request in, an executable
call out.

This is the same job DNS does for hosts and a search engine does for web pages:
turn a name or a need into an address you can actually use. The agent web did not
have this layer yet.

Built for NANDAHack (Step 2). Agent-facing docs: [`SKILL.md`](./SKILL.md).

![Skill-Router landing page and live search](docs/screenshot.png)

## Why it matters (scale and importance)

- **It removes hardcoded integrations.** Without a discovery layer, every agent has to
  be pre-wired to every service it might call. That is an N-agents × M-services
  problem: adding a service means updating agents. With Skill-Router, an agent calls
  one endpoint (`/find`) and can reach any service in the registry, so new services
  become usable without touching the agent.
- **It composes the registry.** This is the same pattern as the NandaHack demo, where
  one service uses another as a backend: Skill-Router is how an agent locates that
  other service at run time instead of having its URL baked in.
- **The agent does the lookup, not a human.** The input is a plain-language need and
  the output is a runnable call, so an autonomous agent can go from intent to action
  without anyone picking from a list.

## How it works

1. `POST /find` with a plain-language `need`. No auth, no setup.
2. Deterministic scoring over the live registry returns the best skills, each with
   why it matched.
3. Each result carries a call plan: method, URL, a paste-ready `curl`, and a link to
   that skill's own SKILL.md. When the need already contains the values (like
   "convert 100 USD to EUR"), Skill-Router fills the endpoint placeholders and marks
   the call `ready_to_run`.

## System design

```
agent --"I need X"--> POST /find --> matcher (deterministic, IDF-weighted)
                                       |
                    live NANDA registry (cached) + bundled snapshot fallback
                                       |
                          ranked skills + synthesized call plan --> agent runs it
```

- **Deterministic matcher, no LLM in the hot path.** IDF-weighted scoring over
  name/description/tags/endpoints with light synonym expansion. Same `need` always
  returns the same ranking, so an agent can verify and retry. No API key to expire,
  no rate limit, no model latency.
- **Never goes dark.** Reads the live registry but ships with a bundled snapshot
  ([`data/registry_snapshot.json`](data/registry_snapshot.json)), so it still answers
  if upstream is down — the failure mode that marks other entries unreachable.
- **Call synthesis** ([`app/synth.py`](app/synth.py)) fills endpoint placeholders
  from the need, so the returned call is runnable as-is.
- **Self-correcting errors.** Every error response says how to fix the call.

## How it scales

- **Registry cache is thread-safe with an in-lock re-check**, so a burst of first
  requests triggers exactly one upstream fetch (no thundering herd), and the index is
  warmed at startup so the first request is never a cold, racing load.
- **Matching is linear per query** and sub-millisecond at hundreds to thousands of
  skills; at millions you would drop in an inverted index behind the same interface.
- **Stateless and horizontally scalable** — every instance holds its own read-only
  cache, so you can run one or many behind a load balancer with no coordination.

## Compared to existing systems

| System | Finds | Gap for agents |
|---|---|---|
| DNS | hosts by name | you must already know the name |
| API gateways / service mesh | pre-registered routes | routes are configured by humans |
| Search engines | documents by keywords | returns pages, not runnable calls |
| **Skill-Router** | **services by intent** | **returns the service *and* the call** |

## Run it locally

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS -X POST http://127.0.0.1:8000/find \
  -H 'Content-Type: application/json' \
  -d '{"need": "convert 100 USD to EUR", "top_k": 3}'
```

Open `http://127.0.0.1:8000/` for the landing page and live search, or `/docs` for
the API docs.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/find` | Search skills by natural-language need. |
| GET | `/skills` | List every indexed skill. |
| GET | `/skill/{id}` | Full detail and call plan for one skill. |
| POST | `/refresh` | Reload the registry from upstream. |
| GET | `/health` | Liveness and indexed-skill count. |
| GET | `/skill.md` | The agent-facing SKILL.md. |

## Tests

```bash
pip install pytest
pytest -q      # 18 tests: matching, call synthesis, errors, endpoints
```

The tests force the bundled snapshot, so they run offline with no network.

## Deploy

Live on Render at https://skill-router.onrender.com. `render.yaml` and a `Procfile`
are included for one-click redeploys elsewhere.

## Layout

```
app/
  main.py       FastAPI app, routes, call-plan builder
  registry.py   live-registry loader with snapshot fallback (thread-safe)
  matching.py   deterministic IDF-weighted relevance scoring, no external deps
  synth.py      fills endpoint placeholders from the need
  static/       landing page and live search UI
data/
  registry_snapshot.json   offline fallback copy of the registry
tests/
  test_skill_router.py
SKILL.md        agent-facing documentation
```
