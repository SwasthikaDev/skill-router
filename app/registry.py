"""Load and normalize the NANDA skills registry.

Strategy for maximum uptime (the evaluator pings us live):
  1. Try the live registry API with a short timeout.
  2. On any failure, fall back to the bundled snapshot that ships with the app.
The service therefore NEVER goes dark, even if the upstream registry is down.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

LIVE_URL = "https://nandatown.projectnanda.org/api/skills"
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "registry_snapshot.json"
CACHE_TTL_SECONDS = 300  # re-pull the live registry at most once every 5 minutes

_ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+(\S+)", re.IGNORECASE)


def _coerce_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("skills", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def parse_endpoints(raw: str | None) -> list[dict[str, str]]:
    """Turn the free-text `endpoints` field into structured {method, url} entries."""
    if not raw:
        return []
    out: list[dict[str, str]] = []
    for line in re.split(r"[\r\n]+", raw):
        line = line.strip()
        if not line:
            continue
        m = _ENDPOINT_RE.search(line)
        if m:
            out.append({"method": m.group(1).upper(), "url": m.group(2)})
        elif line.startswith(("http://", "https://")):
            out.append({"method": "GET", "url": line})
    return out


def normalize(record: dict) -> dict:
    """Normalize one registry record and precompute a lowercase search blob."""
    endpoints = parse_endpoints(record.get("endpoints"))
    tags = record.get("tags") or ""
    tag_list = [t.strip() for t in re.split(r"[,\s]+", tags) if t.strip()]
    name = record.get("name") or ""
    description = record.get("description") or ""
    blob = " ".join(
        [name, name, description, " ".join(tag_list), " ".join(tag_list),
         " ".join(e["url"] for e in endpoints)]
    ).lower()
    return {
        "id": record.get("id"),
        "name": name,
        "author": record.get("author"),
        "description": description,
        "tags": tag_list,
        "source_type": record.get("source_type"),
        "source_url": record.get("source_url"),
        "skill_md_url": record.get("source_url"),
        "endpoints": endpoints,
        "reachable": record.get("reachable"),
        "created_at": record.get("created_at"),
        "_blob": blob,
    }


def _dedupe(records: list[dict]) -> list[dict]:
    """Collapse duplicate re-submissions (same name + source_url), keeping the newest."""
    best: dict[tuple, dict] = {}
    for r in records:
        key = ((r.get("name") or "").strip().lower(), (r.get("source_url") or "").strip().lower())
        prev = best.get(key)
        if prev is None or (r.get("created_at") or "") > (prev.get("created_at") or ""):
            best[key] = r
    return list(best.values())


class Registry:
    def __init__(self) -> None:
        self._skills: list[dict] = []
        self._loaded_at: float = 0.0
        self._source: str = "uninitialized"
        self._lock = threading.Lock()

    def _load_snapshot(self) -> list[dict]:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            return _coerce_list(json.load(f))

    def _load_live(self) -> list[dict]:
        resp = httpx.get(LIVE_URL, timeout=6.0, follow_redirects=True)
        resp.raise_for_status()
        return _coerce_list(resp.json())

    def refresh(self, force: bool = False) -> dict:
        """(Re)load the registry. Live first, snapshot on failure.

        Thread-safe. The lock plus the in-lock re-check means that when many
        requests arrive at once with a stale cache, only one of them reloads
        while the rest wait and reuse the fresh result (no thundering herd). The
        new list is built fully and then published in a single assignment, so a
        concurrent reader never sees a half-updated registry.
        """
        now = time.monotonic()
        if not force and self._skills and (now - self._loaded_at) < CACHE_TTL_SECONDS:
            return self.status()
        with self._lock:
            now = time.monotonic()
            if not force and self._skills and (now - self._loaded_at) < CACHE_TTL_SECONDS:
                return self.status()
            try:
                raw = self._load_live()
                source = "live"
            except Exception:
                raw = self._load_snapshot()
                source = "snapshot"
            if not raw:  # live returned empty, prefer snapshot
                raw = self._load_snapshot()
                source = "snapshot"
            new_skills = [normalize(r) for r in _dedupe(raw)]
            self._skills = new_skills  # atomic publish
            self._loaded_at = now
            self._source = source
            return self.status()

    def ensure_loaded(self) -> None:
        if not self._skills:
            self.refresh(force=False)

    @property
    def skills(self) -> list[dict]:
        self.ensure_loaded()
        return self._skills

    def get(self, skill_id: str) -> dict | None:
        self.ensure_loaded()
        for s in self._skills:
            if s["id"] == skill_id:
                return s
        return None

    def status(self) -> dict:
        return {"source": self._source, "count": len(self._skills)}


registry = Registry()
