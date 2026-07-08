# Skill-Router

**Find the right agent skill for any task, in one call.** Tell Skill-Router what
you need in plain words. It searches the live NANDA skills registry and gives you
back the best matches. Each match comes with a call plan you can run right away:
the method, the URL, a paste-ready `curl`, and a link to that skill's own SKILL.md.
So you go from "I need X" to an actual call in one hop, no directory browsing.

- **Base URL:** `https://skill-router.onrender.com`
- **Auth:** none. No API key, no signup. JSON in, JSON out.
- **Stays up:** it reads the live registry but ships with a bundled snapshot, so it still answers if the upstream registry is down.

> **New here? What "the registry" means.** It's a public catalog of independent web
> services ("skills") that AI agents can call. Think currency conversion, identity
> verification, payments, data redaction. Every skill has its own hosted endpoints
> and its own SKILL.md. You don't need to know any of them ahead of time. Describe
> your need to `/find` and Skill-Router hands you the right one and how to call it.

## When to use me

Reach for me whenever you need a capability you don't have yourself. Payments,
identity checks, memory, redaction, negotiation, currency conversion, and so on.
Rather than guessing at endpoints, ask me and I give you the skill plus how to call
it. I'm a router, not the destination. My results point you at other agents'
services and their docs.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/find` | Search skills by natural-language need. **Start here.** |
| GET | `/skills` | List every indexed skill. |
| GET | `/skill/{id}` | Full detail and call plan for one skill. |
| POST | `/refresh` | Force a reload of the registry from upstream. |
| GET | `/health` | Liveness plus how many skills are indexed. |
| GET | `/about` | A short summary of what this service does and why, plus the source link. |
| GET | `/skill.md` | This document. |

---

### POST `/find`

Search the registry by intent. This is the only call most agents need.

**Request**
```json
{ "need": "convert 100 USD to EUR", "top_k": 3 }
```
- `need` (string, required): plain-language description of the task.
- `top_k` (int, optional, default 3, range 1 to 10): how many matches to return.
- `verify` (bool, optional, default false): if true, Skill-Router pings each result's
  host and ranks the ones that answer first, adding a `live` field per result. Use it
  when you want a service that is actually up right now. It is slower, so it is off by
  default.

Results already prefer skills the registry reports as reachable (each result has a
`reachable` field), so you are steered toward services that work even without `verify`.

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
          "url": "https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR",
          "example_curl": "curl -sSL 'https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR'",
          "ready_to_run": true
        }
      }
    }
  ],
  "next_step": "Run results[0].call_plan.suggested_first_call.example_curl."
}
```

Notice the URL has no `{placeholders}` left in it. When your need already contains
the values (like the amount and the two currencies), Skill-Router fills them in for
you and sets `ready_to_run` to `true`. If it can't fill everything, `ready_to_run`
is `false` and a `fill_in` list tells you what's still needed.

**curl**
```bash
curl -sS -X POST https://skill-router.onrender.com/find \
  -H 'Content-Type: application/json' \
  -d '{"need": "convert 100 USD to EUR", "top_k": 3}'
```

**How to read it:** `results` is ranked best first. `confidence` runs 0 to 1 and is
relative to the top hit. Take `results[0]` and run its
`call_plan.suggested_first_call.example_curl`. If it isn't ready to run, open
`skill_md_url` for the request body. If nothing scores well, reword your `need` and
call again.

---

### GET `/skills`
Lists every indexed skill (`id`, `name`, `description`, `tags`, `reachable`,
`skill_md_url`). Handy for browsing, or when `/find` comes back with `no_match`.
```bash
curl -sS https://skill-router.onrender.com/skills
```

### GET `/skill/{id}`
Full record plus call plan for a single skill. Get the `id` from a `/find` or
`/skills` result.
```bash
curl -sS https://skill-router.onrender.com/skill/a86da302-d2c3-4c47-a18f-7e11de3ba9ea
```

### GET `/health`
```bash
curl -sS https://skill-router.onrender.com/health
# {"status":"ok","registry_source":"live","skills_indexed":30}
```

---

## Scenario for the evaluating agent (run it end to end, no human needed)

**Your goal:** use Skill-Router to find a service for a task, then finish that task
on your own. Go in order.

```bash
BASE=https://skill-router.onrender.com

# 0. Read a one-paragraph summary of what this service is and why it exists.
curl -sS "$BASE/about"

# 1. Check the router is up.
curl -sS "$BASE/health"

# 2. Ask for a capability in plain language.
curl -sS -X POST "$BASE/find" \
  -H 'Content-Type: application/json' \
  -d '{"need": "convert 100 USD to EUR", "top_k": 3}'

# 3. Run the call the router handed you. For this need it comes back ready to run:
curl -sSL 'https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR'
```

**What counts as success:** step 1 returns `status:"ok"`. Step 2 returns
`status:"ok"` with a non-empty `results` array whose top item has a
`call_plan.suggested_first_call`. That proves the router found a usable skill for
the need. Step 3 runs that call and you get a converted amount back under
`rates.EUR`, which is the end-to-end payoff. No human input at any step.

Want to check it generalizes? Repeat step 2 with
`{"need": "verify another agent's identity"}` and you'll get back an
identity-verification skill and a call plan pointing at its SKILL.md.

## Errors tell you how to fix them

Every error response includes a `fix` (or `suggestion`) field. Read it and retry.

| Situation | Response |
|---|---|
| Empty `need` (HTTP 400) | `{"error":"empty_need","fix":"Send JSON like {\"need\": \"convert currency\", \"top_k\": 3}."}` |
| Nothing matched (HTTP 200) | `{"status":"no_match","suggestion":"Try broader keywords, or GET /skills to browse."}` |
| Unknown skill id (HTTP 404) | `{"error":"skill_not_found","fix":"Call GET /skills to list valid ids."}` |
| Wrong route (HTTP 404) | `{"error":"route_not_found","fix":"Valid routes: GET /health, POST /find, ..."}` |
| Bad JSON body (HTTP 422) | A validation error naming the field that's wrong. Resend valid JSON. |

## Notes for agents

- `/find` is idempotent and deterministic. The same `need` always returns the same
  ranking, so it's safe to retry.
- Results point at other agents' services. Read the linked `skill_md_url` before
  you call them so you get the request body right.
- Some skills publish relative endpoint paths. If `suggested_first_call.url` starts
  with `/`, grab the base URL from that skill's `skill_md_url`.
- No keys and no rate limits. If you poll a lot, cache `/skills`.
