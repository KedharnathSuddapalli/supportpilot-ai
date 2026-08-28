"""
Loads accounts.json / tickets.json and joins them for the TAM brief tool.

Join strategy: ticket.account_id frequently does NOT match any account_id
in accounts.json (only ~4 of 484 unique ticket account_ids do, verified
against the actual starter dataset) - but ticket.company matches an
account's company name 100% of the time. So we join primarily on
account_id (fast path, works when present) and fall back to company name
(reliable path) rather than silently dropping most of a customer's
ticket history.

"Last 90 days" reference point: this is a static synthetic dataset whose
tickets all fall between 2026-02-20 and 2026-05-22. Anchoring the 90-day
window to the real wall-clock date would return zero tickets for every
account. Instead we anchor "now" to the most recent ticket timestamp in
the dataset, which is a reproducible stand-in for "today" and is
documented here so it's not a silent/surprising choice.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import config


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@lru_cache(maxsize=1)
def load_accounts() -> list[dict]:
    with open(config.ACCOUNTS_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_tickets() -> list[dict]:
    with open(config.TICKETS_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_reference_now() -> datetime:
    """The simulated 'today' for 90-day windowing - see module docstring."""
    tickets = load_tickets()
    return max(_parse_iso(t["created_at"]) for t in tickets)


def get_account(account_id: str) -> dict | None:
    for acc in load_accounts():
        if acc["account_id"] == account_id:
            return acc
    return None


def get_recent_tickets_for_account(account_id: str, days: int = 90) -> list[dict]:
    """Tickets for this account in the last `days` days (anchored to the
    dataset's simulated 'now'), newest first. Joins on account_id OR
    company name (see module docstring) and de-duplicates by ticket_id."""
    account = get_account(account_id)
    if account is None:
        return []

    company = account["company"]
    cutoff = get_reference_now() - timedelta(days=days)

    seen_ids: set[str] = set()
    matched: list[dict] = []
    for t in load_tickets():
        if t.get("account_id") != account_id and t.get("company") != company:
            continue
        if _parse_iso(t["created_at"]) < cutoff:
            continue
        if t["ticket_id"] in seen_ids:
            continue
        seen_ids.add(t["ticket_id"])
        matched.append(t)

    matched.sort(key=lambda t: t["created_at"], reverse=True)
    return matched
