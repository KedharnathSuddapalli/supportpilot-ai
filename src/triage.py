"""
Core triage pipeline: retrieval -> LLM classification -> structured output.

LLM calls go to Groq (OpenAI-compatible API, fast + generous free tier)
via the `openai` SDK pointed at Groq's base URL. Structured output is
enforced via forced tool/function calling rather than asking the model
to "return JSON" in prose - this eliminates the usual parsing failures
(markdown fences, trailing commentary, etc.)
"""
from __future__ import annotations

import json

from openai import OpenAI

from . import config
from .prompts import TRIAGE_SYSTEM_PROMPT, TRIAGE_PROMPT_VERSION, build_user_message
from .retrieval import get_retriever
from .schemas import TicketInput, TriageOutput, KBMatch, CategoryLabel, UrgencyTier

EMIT_TRIAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_triage",
        "description": "Emit the structured triage classification for a support ticket.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_area": {"type": "string"},
                "issue_category": {
                    "type": "string",
                    "enum": ["Bug", "Feature Request", "How-To", "Performance",
                             "Billing", "Integration", "Onboarding", "Data Loss"],
                },
                "urgency_tier": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
                "reasoning": {"type": "string"},
                "recommended_team": {"type": "string"},
                "draft_response": {"type": "string"},
            },
            "required": [
                "product_area", "issue_category", "urgency_tier",
                "reasoning", "recommended_team", "draft_response",
            ],
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


def stream_draft_response(ticket: TicketInput, classification_context: dict, kb_context: str | None,
                           *, client: OpenAI | None = None):
    """Stream the draft first-response message token-by-token (bonus:
    streaming output). This is a separate, additional code path from the
    main triage_ticket() pipeline - it doesn't replace the synchronous
    draft_response already returned by /triage, which stays required and
    unchanged. It's a second LLM call (slight extra cost) purely to
    demonstrate streaming; in a latency-sensitive production version this
    would instead be the *only* generation of draft_response, with
    classification and drafting merged back into one pass.
    """
    client = client or _get_client()
    context_lines = [
        f"Ticket subject: {ticket.subject or '(none)'}",
        f"Ticket body: {ticket.body}",
        f"Classified as: {classification_context.get('issue_category')} / "
        f"{classification_context.get('urgency_tier')} ({classification_context.get('product_area')})",
    ]
    if kb_context:
        context_lines.append(f"Relevant KB excerpt: {kb_context}")
    user_message = "\n".join(context_lines)

    stream = client.chat.completions.create(
        model=config.MODEL_NAME,
        temperature=config.MODEL_TEMPERATURE,
        max_tokens=400,
        stream=True,
        messages=[
            {"role": "system", "content": "You are a support agent assistant. Write ONLY the "
                                           "customer-facing first-response message for this already-"
                                           "classified ticket - 3-6 sentences, professional, no preamble, "
                                           "no markdown headers. Do not promise a specific resolution time."},
            {"role": "user", "content": user_message},
        ],
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def _retrieve_kb_match(ticket: TicketInput) -> KBMatch | None:
    query = f"{ticket.subject}\n{ticket.body}"
    retriever = get_retriever()
    results = retriever.search(query, top_k=config.KB_TOP_K)
    if not results:
        return None
    top_chunk, score = results[0]
    if score < config.KB_MIN_SCORE:
        return None
    return KBMatch(
        doc_path=top_chunk.doc_path,
        section=top_chunk.heading_path,
        score=round(score, 4),
        snippet=top_chunk.text[:500],
    )


def _apply_routing_fallback(category: str, llm_team: str) -> str:
    """Cross-check the LLM's recommended team against a deterministic
    lookup table. If they disagree, prefer the deterministic mapping -
    this guards against a plausible-sounding but wrong team name for a
    category the model should route consistently."""
    expected = config.CATEGORY_TEAM_MAP.get(category, config.DEFAULT_TEAM)
    return expected


def triage_ticket(raw_ticket: str | dict, *, client: OpenAI | None = None) -> TriageOutput:
    """Classify a raw support ticket and produce a structured triage result.

    Args:
        raw_ticket: either a plain-text ticket body, or a dict/JSON object
            with at least `subject` and `body` keys (see TicketInput).
        client: optional pre-built OpenAI client (mainly for tests / reuse
            across many calls without re-authenticating).

    Returns:
        TriageOutput with classification, KB match, routing, and a draft
        first-response message.
    """
    ticket = TicketInput.from_raw(raw_ticket)

    kb_match = _retrieve_kb_match(ticket)
    kb_context = None
    if kb_match:
        kb_context = f"[{kb_match.doc_path} — {kb_match.section}]\n{kb_match.snippet}"

    user_message = build_user_message(ticket.subject, ticket.body, kb_context)

    client = client or _get_client()
    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        max_tokens=config.MODEL_MAX_TOKENS,
        temperature=config.MODEL_TEMPERATURE,
        messages=[
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        tools=[EMIT_TRIAGE_TOOL],
        tool_choice={"type": "function", "function": {"name": "emit_triage"}},
    )

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((t for t in tool_calls if t.function.name == "emit_triage"), None)
    if tool_call is None:
        raise RuntimeError(f"Model did not return the expected emit_triage tool call: {message}")

    result: dict = json.loads(tool_call.function.arguments)

    # Deterministic cross-check on team routing (see _apply_routing_fallback docstring)
    recommended_team = _apply_routing_fallback(result["issue_category"], result["recommended_team"])

    return TriageOutput(
        product_area=result["product_area"],
        issue_category=result["issue_category"],
        urgency_tier=result["urgency_tier"],
        reasoning=result["reasoning"],
        matched_kb_doc=kb_match,
        recommended_team=recommended_team,
        draft_response=result["draft_response"],
        prompt_version=TRIAGE_PROMPT_VERSION,
        model=config.MODEL_NAME,
    )
