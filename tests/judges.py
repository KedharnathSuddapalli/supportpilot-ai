"""
Scoring primitives for the eval harness.

Two kinds of checks, deliberately kept separate so a report can show
which failures are "hard" (deterministic, unambiguous) vs "soft"
(quality judgment calls):

- Rule-based checks: pure code, no LLM call, binary or simple pass/fail.
  Cheap, deterministic, zero flakiness. Used for schema/format/safety
  guarantees (valid enum values, verbatim quotes, no crash, etc.)

- LLM-as-judge: for things with no fixed right answer (does this draft
  response actually address the issue? is this summary grounded in the
  data?). Runs at temperature=0 with a forced tool call so the judge's
  own output is structured and as reproducible as the underlying model
  allows.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from openai import OpenAI

from src import config


@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float  # 0.0-1.0
    detail: str = ""


# --- Rule-based checks ----------------------------------------------------

def check_enum_value(name: str, value, allowed: list) -> CheckResult:
    ok = value in allowed
    return CheckResult(name, ok, 1.0 if ok else 0.0,
                        f"value={value!r}, allowed={allowed}" if not ok else "")


def check_nonempty(name: str, value: str, min_len: int = 1) -> CheckResult:
    ok = bool(value) and len(value.strip()) >= min_len
    return CheckResult(name, ok, 1.0 if ok else 0.0,
                        "" if ok else f"got {value!r}, need len>={min_len}")


def check_exact_match(name: str, actual, expected) -> CheckResult:
    ok = actual == expected
    return CheckResult(name, ok, 1.0 if ok else 0.0,
                        "" if ok else f"expected {expected!r}, got {actual!r}")


def check_substring(name: str, haystack: str, needle: str) -> CheckResult:
    ok = needle.lower() in (haystack or "").lower()
    return CheckResult(name, ok, 1.0 if ok else 0.0,
                        "" if ok else f"{needle!r} not found in {haystack!r}")


def check_min_count(name: str, items: list, minimum: int) -> CheckResult:
    ok = len(items) >= minimum
    return CheckResult(name, ok, 1.0 if ok else 0.0,
                        "" if ok else f"got {len(items)} items, need >= {minimum}")


def check_quotes_verbatim(name: str, risk_flags: list[dict], tickets_by_id: dict) -> CheckResult:
    """Re-validates that every risk flag's quote is an exact substring of
    its cited ticket - the same guardrail logic used in production,
    re-run here as an independent eval check rather than trusted blindly."""
    from src.account_brief import _validate_quote

    if not risk_flags:
        return CheckResult(name, True, 1.0, "no risk flags to validate")

    bad = []
    for rf in risk_flags:
        ticket = tickets_by_id.get(rf["ticket_id"])
        if ticket is None or not _validate_quote(rf["quote"], ticket):
            bad.append(rf["ticket_id"])
    ok = not bad
    return CheckResult(name, ok, 1.0 if ok else 0.0,
                        "" if ok else f"unverifiable quotes for tickets: {bad}")


def check_no_exception(name: str, fn, *args, **kwargs) -> tuple[CheckResult, object | None]:
    try:
        result = fn(*args, **kwargs)
        return CheckResult(name, True, 1.0, ""), result
    except Exception as e:
        return CheckResult(name, False, 0.0, f"{type(e).__name__}: {e}"), None


def check_raises(name: str, fn, exc_type, *args, **kwargs) -> CheckResult:
    try:
        fn(*args, **kwargs)
        return CheckResult(name, False, 0.0, f"expected {exc_type.__name__} but no exception was raised")
    except exc_type as e:
        return CheckResult(name, True, 1.0, f"correctly raised {exc_type.__name__}: {e}")
    except Exception as e:
        return CheckResult(name, False, 0.0, f"wrong exception type: {type(e).__name__}: {e}")


def check_latency(name: str, elapsed_seconds: float, max_seconds: float) -> CheckResult:
    ok = elapsed_seconds <= max_seconds
    return CheckResult(name, ok, 1.0 if ok else max(0.0, 1 - (elapsed_seconds - max_seconds) / max_seconds),
                        f"{elapsed_seconds:.3f}s (limit {max_seconds}s)")


# --- LLM-as-judge ----------------------------------------------------------

JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_judgment",
        "description": "Emit a quality judgment for the given output against the given rubric.",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {"type": "number", "description": "Quality score from 0.0 (fails rubric) to 1.0 (fully meets rubric)"},
                "passed": {"type": "boolean", "description": "true if score meets a reasonable bar for production use"},
                "reasoning": {"type": "string", "description": "1-2 sentence justification"},
            },
            "required": ["score", "passed", "reasoning"],
            "additionalProperties": False,
        },
    },
}

JUDGE_SYSTEM_PROMPT = """You are a strict but fair QA reviewer for an AI support-ticket triage and \
account-briefing system. You will be given: the original input, the system's output, and a rubric. \
Score how well the output satisfies the rubric, from 0.0 (completely fails) to 1.0 (fully satisfies). \
Be skeptical of generic, vague, or hedge-everything output - it should score lower than specific, \
grounded, correct output. You must call the `emit_judgment` tool exactly once."""


def llm_judge(client: OpenAI, context: str, output: str, rubric: str) -> CheckResult:
    user_message = f"INPUT/CONTEXT:\n{context}\n\nSYSTEM OUTPUT TO EVALUATE:\n{output}\n\nRUBRIC:\n{rubric}"
    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        max_tokens=300,
        temperature=0,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        tools=[JUDGE_TOOL],
        tool_choice={"type": "function", "function": {"name": "emit_judgment"}},
    )
    message = response.choices[0].message
    tool_call = next((t for t in (message.tool_calls or []) if t.function.name == "emit_judgment"), None)
    if tool_call is None:
        return CheckResult("llm_judge", False, 0.0, "judge model did not return a tool call")
    result = json.loads(tool_call.function.arguments)
    return CheckResult("llm_judge", bool(result["passed"]), float(result["score"]), result["reasoning"])
