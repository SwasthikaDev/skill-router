# Skill-Router

A discovery + routing service for the agent web. An AI agent describes what it
needs in plain language; Skill-Router searches the live
[NANDA skills registry](https://nandatown.projectnanda.org/skills) and returns
the best-matching skills, each with a ready-to-run **call plan**. One hop from
*"I need X"* to an executable call.

Built for **NANDAHack** (Step 2). The agent-facing docs live in
[`SKILL.md`](./SKILL.md).

## Why it's different

- **Solves a real gap:** the registry has dozens of skills but no way for an
  agent to *find and call* the right one by intent. This is that missing layer.
- **Never goes dark:** live registry with a bundled snapshot fallback
  (`data/registry_snapshot.json`), so it answers even if upstream is down.
- **Deterministic + zero-auth:** no API key, no LLM dependency in the hot path —
  the same `need` always returns the same ranking, so an agent can verify and retry.
- **Self-correcting errors:** every error response tells the caller how to fix it.

## Run locally

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows: .venv\Scripts\activate  |  *nix: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then:

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS -X POST http://127.0.0.1:8000/find \
  -H 'Content-Type: application/json' \
  -d '{"need": "convert 100 USD to EUR", "top_k": 3}'
```

Interactive API docs at `http://127.0.0.1:8000/docs`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/find` | Search skills by natural-language need. |
| GET | `/skills` | List every indexed skill. |
| GET | `/skill/{id}` | Full detail + call plan for one skill. |
| POST | `/refresh` | Force-reload the registry from upstream. |
| GET | `/health` | Liveness + indexed-skill count. |
| GET | `/skill.md` | The agent-facing SKILL.md. |

## Tests

```bash
pip install pytest
pytest -q
```

Tests are hermetic — they force the bundled snapshot, so no network is required.

## Deploy

- **Render:** commit and connect the repo; `render.yaml` is included (free web
  service, health check at `/health`).
- **Railway / Fly / Vercel:** a `Procfile` is included
  (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).

After deploying, replace `https://YOUR-DEPLOYMENT-URL` in `SKILL.md` with your
live host and submit `SKILL.md` at the NANDA skills page.

## Layout

```
app/
  main.py       FastAPI app + routes + call-plan builder
  registry.py   live-registry loader with snapshot fallback + endpoint parser
  matching.py   deterministic IDF-weighted relevance scoring (no external deps)
data/
  registry_snapshot.json   offline fallback copy of the registry
tests/
  test_skill_router.py
SKILL.md        agent-facing documentation
```
