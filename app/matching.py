"""Deterministic, dependency-free relevance scoring.

No external LLM/embedding service is required, so the matcher can never fail or
rate-limit at grade time. Scoring blends:
  * IDF-weighted term overlap (rare words count for more),
  * exact tag hits (a strong signal of intent),
  * whole-phrase bonus (the query appears verbatim in name/description).
Given identical input the output is always identical -> easy for an agent to verify.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "the", "to", "for", "of", "and", "or", "i", "my", "me", "we",
    "need", "want", "that", "can", "with", "how", "do", "does", "is", "are",
    "be", "some", "any", "please", "find", "service", "agent", "agents", "api",
    "use", "using", "call", "give", "get", "help", "let", "lets", "would",
    "should", "which", "this", "it", "on", "in", "at", "by", "from", "as",
    "before", "after", "another", "other", "so", "own", "its", "their",
}

# Light synonym expansion so natural-language needs map onto registry vocabulary.
SYNONYMS = {
    "money": ["payment", "pay", "escrow", "credits"],
    "pay": ["payment", "escrow", "credits"],
    "payment": ["pay", "escrow", "credits"],
    "identity": ["did", "credential", "identity", "ed25519"],
    "verify": ["verification", "attestation", "conformance", "proof"],
    "trust": ["reputation", "trust", "conformance"],
    "reputation": ["trust", "reputation"],
    "memory": ["memory", "state", "recall", "precedent"],
    "remember": ["memory", "state", "recall"],
    "privacy": ["privacy", "redact", "pii", "encryption", "disclosure"],
    "redact": ["privacy", "pii", "redact"],
    "negotiate": ["negotiation", "bargaining", "pareto", "offer"],
    "negotiation": ["negotiate", "bargaining", "pareto"],
    "currency": ["currency", "exchange", "forex", "convert"],
    "convert": ["conversion", "currency", "exchange"],
    "auth": ["auth", "token", "capability", "access", "authorization"],
    "token": ["auth", "capability", "access"],
    "discover": ["discovery", "registry", "lookup", "find"],
    "coordinate": ["coordination", "contract", "auction", "consensus"],
    "price": ["pricing", "cost", "price"],
    "pricing": ["price", "cost"],
    "human": ["human", "escalation", "approval"],
    "captcha": ["captcha", "badge", "proof"],
    "medical": ["clinical", "medical", "hospital", "discharge"],
    "clinical": ["medical", "hospital", "discharge"],
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def expand(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for t in tokens:
        out.extend(SYNONYMS.get(t, []))
    return out


def build_idf(skills: list[dict]) -> dict[str, float]:
    n = max(len(skills), 1)
    df: Counter[str] = Counter()
    for s in skills:
        for tok in set(tokenize(s["_blob"])):
            df[tok] += 1
    return {tok: math.log((n + 1) / (c + 0.5)) + 1.0 for tok, c in df.items()}


def score_skill(query_tokens: list[str], skill: dict, idf: dict[str, float]) -> tuple[float, list[str]]:
    blob = skill["_blob"]
    blob_tokens = set(tokenize(blob))
    tag_tokens = {t.lower() for tag in skill["tags"] for t in tokenize(tag)}
    matched: list[str] = []
    score = 0.0
    for tok in query_tokens:
        w = idf.get(tok, 1.0)
        if tok in tag_tokens:
            score += 2.2 * w
            matched.append(tok)
        elif tok in blob_tokens:
            score += 1.0 * w
            matched.append(tok)
    return score, sorted(set(matched))


def rank(need: str, skills: list[dict], idf: dict[str, float], top_k: int = 3) -> list[dict]:
    raw_tokens = tokenize(need)
    query_tokens = list(dict.fromkeys(expand(raw_tokens)))  # dedupe, keep order
    need_lower = need.lower().strip()
    results: list[dict] = []
    for s in skills:
        score, matched = score_skill(query_tokens, s, idf)
        if len(need_lower) >= 4 and need_lower in s["_blob"]:
            score += 5.0  # verbatim phrase bonus
        if score <= 0:
            continue
        results.append({"skill": s, "score": round(score, 3), "matched_terms": matched})
    results.sort(key=lambda r: (-r["score"], r["skill"]["name"].lower()))
    # Normalize to a 0-1 confidence for readability.
    if results:
        top = results[0]["score"]
        for r in results:
            r["confidence"] = round(min(1.0, r["score"] / (top + 1e-9)), 3)
    return results[:top_k]
