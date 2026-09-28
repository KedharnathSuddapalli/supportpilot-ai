"""
TAM account health brief pipeline.

Prompt chain (two LLM calls, not one):
  1. Risk extraction - given the account's last-90-day tickets, the LLM
     proposes candidate churn/escalation risk flags, each with a quote.
  2. Quote validation (pure code, no LLM) - every proposed quote is
     checked against the real ticket text; anything that isn't an exact
     substring is dropped. This is what makes the "justify each flag
     with a direct quote" requirement a guarantee rather than a hope.
  3. Synthesis - given the account record + the *validated* risk flags,
     the LLM writes the executive summary and talking points. It never
     sees rejected/unverifiable flags, so it can't echo a hallucinated
     quote into the final brief.

Determinism: results are cached by a hash of (account, tickets,
prompt_version, model) - see cache.py. A repeat call for unchanged
inputs returns the cached brief unchanged, rather than re-querying the
LLM and risking wording drift.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from openai import OpenAI

from . import config
from . import cache as brief_cache
from .accounts_data import get_account, get_recent_tickets_for_account
from .prompts import (
    BRIEF_PROMPT_VERSION,
    RISK_EXTRACTION_SYSTEM_PROMPT,
    BRIEF_SYNTHESIS_SYSTEM_PROMPT,
    build_risk_extraction_message,
    build_synthesis_message,
)
from .schemas import AccountBrief, RiskFlag

EMIT_RISK_FLAGS_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_risk_flags",
        "description": "Emit the list of churn-risk / escalation-risk flagged tickets.",
        "parameters": {
            "type": "object",
            "properties": {
                "risk_flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {"type": "string"},
                            "quote": {"type": "string"},
                            "risk_type": {"type": "string"},
                            "severity": {"type": "string", "enum": ["High", "Medium", "Low"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["ticket_id", "quote", "risk_type", "severity", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["risk_flags"],
            "additionalProperties": False,
        },
    },
}

EMIT_BRIEF_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_brief",
        "description": "Emit the executive summary and recommended talking points for a QBR brief.",
        "parameters": {
            "type": "object",
            "properties": {
                "executive_summary": {"type": "string"},
                "recommended_talking_points": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["executive_summary", "recommended_talking_points"],
            "additionalProperties": False,
        },
    },
}


def _get_client() -> OpenAI:
    if not config.GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL)


def _call_tool(client: OpenAI, system_prompt: str, user_message: str, tool: dict, tool_name: str) -> dict:
    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        max_tokens=config.MODEL_MAX_TOKENS,
        temperature=config.MODEL_TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((t for t in tool_calls if t.function.name == tool_name), None)
    if tool_call is None:
        raise RuntimeError(f"Model did not return the expected {tool_name} tool call: {message}")
    return json.loads(tool_call.function.arguments)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _validate_quote(quote: str, ticket: dict) -> bool:
    """A quote is valid only if it's an exact (whitespace-normalised,
    case-insensitive) substring of that ticket's subject+body. This is
    the guardrail against LLM-hallucinated quotes."""
    haystack = _normalize(f"{ticket.get('subject', '')} {ticket.get('body', '')}")
    needle = _normalize(quote)
    return bool(needle) and needle in haystack


def _extract_and_validate_risk_flags(client: OpenAI, tickets: list[dict]) -> list[RiskFlag]:
    if not tickets:
        return []

    tickets_by_id = {t["ticket_id"]: t for t in tickets}
    user_message = build_risk_extraction_message(tickets)
    result = _call_tool(
        client, RISK_EXTRACTION_SYSTEM_PROMPT, user_message, EMIT_RISK_FLAGS_TOOL, "emit_risk_flags"
    )

    validated: list[RiskFlag] = []
    for rf in result.get("risk_flags", []):
        ticket = tickets_by_id.get(rf.get("ticket_id"))
        if ticket is None:
            continue  # LLM referenced a ticket_id that wasn't in the input - drop it
        if not _validate_quote(rf.get("quote", ""), ticket):
            continue  # unverifiable / hallucinated quote - drop it
        validated.append(RiskFlag(**rf))
    return validated


def generate_account_brief(
    account_id: str,
    *,
    client: OpenAI | None = None,
    force_refresh: bool = False,
) -> AccountBrief:
    """Generate (or retrieve a cached) TAM account health brief.

    Raises ValueError if the account_id doesn't exist in accounts.json.
    """
    account = get_account(account_id)
    if account is None:
        raise ValueError(f"No account found with account_id={account_id!r}")

    tickets = get_recent_tickets_for_account(account_id, days=90)

    input_hash = brief_cache.compute_input_hash(account, tickets, BRIEF_PROMPT_VERSION, config.MODEL_NAME)

    if not force_refresh:
        cached = brief_cache.get_cached_brief(account_id, input_hash)
        if cached is not None:
            return AccountBrief(**{**cached, "cache_hit": True})

    client = client or _get_client()

    risk_flags = _extract_and_validate_risk_flags(client, tickets)

    synthesis_message = build_synthesis_message(
        account, [rf.model_dump() for rf in risk_flags], ticket_count=len(tickets)
    )
    synthesis_result = _call_tool(
        client, BRIEF_SYNTHESIS_SYSTEM_PROMPT, synthesis_message, EMIT_BRIEF_TOOL, "emit_brief"
    )

    brief = AccountBrief(
        account_id=account["account_id"],
        company=account["company"],
        executive_summary=synthesis_result["executive_summary"],
        open_risks=risk_flags,
        account_level_notes=account.get("escalation_notes") or [],
        recommended_talking_points=synthesis_result["recommended_talking_points"],
        prompt_version=BRIEF_PROMPT_VERSION,
        model=config.MODEL_NAME,
        input_hash=input_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
        cache_hit=False,
    )

    brief_cache.save_brief_to_cache(account_id, input_hash, brief.model_dump())
    return brief
