"""
Content-hashed cache for account briefs.

This is what makes Task 2 "bulletproof" deterministic rather than just
"probably deterministic because temperature=0": the first successful
generation for a given (account data + ticket set + prompt_version +
model) is persisted to disk. Any later call with identical inputs
returns the exact cached text - byte-for-byte - instead of making a new
LLM call, so wording can never drift between repeat requests even if the
LLM itself has small run-to-run nondeterminism.

The cache key intentionally includes the full ticket content (not just
ticket_ids) so that an edited ticket, or a newly created one that enters
the 90-day window, correctly invalidates the cache and triggers a fresh
brief - "deterministic for the same input" also implies "changes when
the input changes."
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config

CACHE_DIR = config.ROOT_DIR / "data" / "cache" / "briefs"


def compute_input_hash(account: dict, tickets: list[dict], prompt_version: str, model: str) -> str:
    payload = {
        "account": account,
        "tickets": sorted(tickets, key=lambda t: t["ticket_id"]),
        "prompt_version": prompt_version,
        "model": model,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_path(account_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{account_id}.json"


def get_cached_brief(account_id: str, input_hash: str) -> dict | None:
    path = _cache_path(account_id)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if cached.get("input_hash") != input_hash:
        return None
    return cached.get("brief")


def save_brief_to_cache(account_id: str, input_hash: str, brief: dict) -> None:
    path = _cache_path(account_id)
    path.write_text(json.dumps({"input_hash": input_hash, "brief": brief}, indent=2), encoding="utf-8")
