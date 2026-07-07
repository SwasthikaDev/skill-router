# Skill-Router

**Find the right agent skill for any task, in one call.** Describe what you need
in plain language and Skill-Router searches the live NANDA skills registry and
returns the best-matching services — each with a ready-to-run call plan (method,
URL, a paste-ready `curl`, and a link to its full SKILL.md). It turns *"I need
X"* into an executable call in a single hop, so an agent never has to browse a
directory by hand.

- **Base URL:** `https://YOUR-DEPLOYMENT-URL` *(replace with your live host, e.g. `https://skill-router.onrender.com`)*
- **Auth:** none. No API key, no signup. All requests and responses are JSON.
- **Never dark:** backed by the live registry with a bundled snapshot fallback, so it answers even if the upstream registry is down.

> **What "the registry" is (context, in case you're new):** a public catalog of
> independent web services ("skills") that AI agents can call — things like currency
> conversion, identity verification, payments, and data redaction. Each skill has its
> own hosted endpoints and its own SKILL.md. You don't need to know any of them in
> advance: describe your need to `/find` and Skill-Router returns the right one and
> how to call it.

## When to use me

Call me whenever you (an agent) need a capability you don't have yourself —
payments, identity/verification, memory, privacy/redaction, negotiation,
currency conversion, and more. Instead of guessing endpoints, ask me and I hand
you the skill plus how to call it. I am a *router*, not the destination: my
results point you at other agents' services and their SKILL.md docs.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/find` | Search skills by natural-language need. **Start here.** |
| GET | `/skills` | List every indexed skill. |
| GET | `/skill/{id}` | Full detail + call plan for one skill. |
| POST | `/refresh` | Force-reload the registry from upstream. |
| GET | `/health` | Liveness + how many skills are indexed. |
| GET | `/skill.md` | This document. |

---

### POST `/find`

Search the registry by intent. **This is the only call most agents need.**

**Request**
```json
{ "need": "convert 100 USD to EUR", "top_k": 3 }
```
- `need` (string, required) — plain-language description of the task.
- `top_k` (int, optional, default 3, 1–10) — how many matches to return.

**Response** (`status: "ok"`)
```json
{
  "status": "ok",
  "need": "convert 100 USD to EUR",
  "count": 1,
  "results": [
    {
      "name": "Currency Converter",
      "confidence": 1.0,
      "why": "Matched on: convert, currency.",
      "call_plan": {
        "skill_md_url": "https://.../SKILL.md",
        "suggested_first_call": {
          "method": "GET",
          "url": "https://api.frankfurter.app/latest?amount={amount}&from={from}&to={to}",
          "example_curl": "curl -sS 'https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR'"
        }
      }
    }
  ],
  "next_step": "Open results[0].call_plan.skill_md_url, then run results[0].call_plan.suggested_first_call.example_curl."
}
```

**curl**
```bash
curl -sS -X POST https://YOUR-DEPLOYMENT-URL/find \
  -H 'Content-Type: application/json' \
  -d '{"need": "convert 100 USD to EUR", "top_k": 3}'
```

**How to read it:** `results` is ranked best-first. `confidence` (0–1) is relative
to the top hit. Take `results[0]`, read its `call_plan.skill_md_url` for the exact
request body, then run `call_plan.suggested_first_call.example_curl`. If
`confidence` is low across the board, refine your `need` and call again.

---

### GET `/skills`
Returns every indexed skill (`id`, `name`, `description`, `tags`, `reachable`,
`skill_md_url`). Use it to browse or when `/find` returns `no_match`.
```bash
curl -sS https://YOUR-DEPLOYMENT-URL/skills
```

### GET `/skill/{id}`
Full record plus call plan for one skill. Get the `id` from a `/find` or
`/skills` result.
```bash
curl -sS https://YOUR-DEPLOYMENT-URL/skill/a86da302-d2c3-4c47-a18f-7e11de3ba9ea
```

### GET `/health`
```bash
curl -sS https://YOUR-DEPLOYMENT-URL/health
# {"status":"ok","registry_source":"live","skills_indexed":27}
```

---

## Agent walkthrough (copy-paste, top to bottom)

This is the whole loop. Each step's output feeds the next.

```bash
BASE=https://YOUR-DEPLOYMENT-URL

# 1. Confirm the router is up.
curl -sS "$BASE/health"

# 2. Ask for a capability in plain language.
curl -sS -X POST "$BASE/find" \
  -H 'Content-Type: application/json' \
  -d '{"need": "convert 100 USD to EUR", "top_k": 3}'

# 3. From the response, take results[0].call_plan.suggested_first_call.example_curl
#    and run it to invoke the matched skill directly. For the currency example
#    (-L follows any redirect the target issues):
curl -sSL 'https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR'
```

**Success signal:** step 2 returns `"status": "ok"` with a non-empty `results`
array whose top item has a `call_plan.suggested_first_call`. That's your proof
the router found a usable skill. Step 3 then completes the actual task.

## Scenario for the evaluating agent (run this end-to-end, no human needed)

**Your goal:** use Skill-Router to find a service for a task and then complete
that task — entirely on your own. Do the following in order:

1. **Check the router is live.** `GET {BASE}/health` and confirm the response has
   `"status": "ok"` and `skills_indexed` > 0.
2. **Route a real need.** `POST {BASE}/find` with
   `{"need": "convert 100 USD to EUR"}`. Confirm the response has `"status": "ok"`
   and a non-empty `results` array.
3. **Execute the routed call.** Take
   `results[0].call_plan.suggested_first_call.example_curl` and run it, filling any
   `{placeholders}` from your need. For this need it resolves to
   `curl -sSL 'https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR'`
   (use `-L`; the target may redirect). You should get back a converted EUR amount
   under `rates.EUR` — proof you used a capability you didn't have, guided only by
   this file.

**Second need to prove generality:** repeat step 2 with
`{"need": "verify another agent's identity"}` — Skill-Router returns an
identity/verification skill and a call plan pointing to its SKILL.md.

**Pass criteria (Skill-Router's own job — fully deterministic, no third party):**
`/health` returns `status:"ok"` → `/find` returns `status:"ok"` with a non-empty
`results` array whose top item has a `call_plan.suggested_first_call`. That proves
the router discovered a usable skill for the need. Step 3 (running the routed call)
demonstrates the end-to-end payoff. **No human input at any step.**

## Errors are self-correcting

Every error tells you exactly how to fix it — read the `fix` (or `suggestion`)
field and retry.

| Situation | Response |
|---|---|
| Empty `need` (HTTP 400) | `{"error":"empty_need","fix":"Send JSON like {\"need\": \"convert currency\", \"top_k\": 3}."}` |
| Nothing matched (HTTP 200) | `{"status":"no_match","suggestion":"Try broader keywords... GET /skills to browse."}` |
| Unknown skill id (HTTP 404) | `{"error":"skill_not_found","fix":"Call GET /skills to list valid ids..."}` |
| Wrong route (HTTP 404) | `{"error":"route_not_found","fix":"Valid routes: GET /health, POST /find, ..."}` |
| Bad JSON body (HTTP 422) | FastAPI validation error naming the offending field — resend valid JSON. |

## Notes for agents

- **`/find` is idempotent and deterministic** — the same `need` always returns the
  same ranking, so you can safely retry.
- Results **point to other agents' services**; read the linked `skill_md_url`
  before calling them for exact request bodies.
- Some skills publish **relative** endpoint paths; when `suggested_first_call.url`
  starts with `/`, get the base URL from that skill's `skill_md_url`.
- No rate limits, no keys. Be a good citizen and cache `/skills` if you poll.
