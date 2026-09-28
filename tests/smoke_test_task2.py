"""
Internal sanity check for Task 2 (account brief pipeline). Two parts:
1. Quote validation tested against REAL ticket data (no mocking needed -
   this is pure string logic).
2. Full two-step chain + caching tested with mocked LLM responses (no
   network / API key required).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.accounts_data import load_accounts, get_recent_tickets_for_account
from src.account_brief import _validate_quote, generate_account_brief
from src import cache as brief_cache


def test_quote_validation_against_real_data():
    accounts = load_accounts()
    acc = accounts[0]
    tickets = get_recent_tickets_for_account(acc["account_id"])
    assert tickets, "expected at least one ticket for the test account"

    t = tickets[0]
    # A real verbatim substring should validate...
    real_quote = t["body"][:40]
    assert _validate_quote(real_quote, t) is True

    # ...but a fabricated quote should not.
    fake_quote = "This sentence absolutely does not appear in the ticket text anywhere."
    assert _validate_quote(fake_quote, t) is False

    print(f"Quote validation check passed against real ticket {t['ticket_id']}.")


def fake_risk_flags_response(tickets):
    # Pick one real ticket and quote it verbatim (valid), plus inject one
    # fabricated flag referencing a real ticket_id but a made-up quote
    # (should be dropped by validation).
    t0 = tickets[0]
    real_snippet = t0["body"][:30]

    call = MagicMock()
    call.function.name = "emit_risk_flags"
    call.function.arguments = json.dumps({
        "risk_flags": [
            {
                "ticket_id": t0["ticket_id"],
                "quote": real_snippet,
                "risk_type": "Escalation risk",
                "severity": "High",
                "reason": "Customer explicitly raised this as a blocking issue.",
            },
            {
                "ticket_id": t0["ticket_id"],
                "quote": "a quote the model made up that is not in the ticket",
                "risk_type": "Negative sentiment",
                "severity": "Medium",
                "reason": "Should be dropped by validation.",
            },
        ]
    })
    message = MagicMock()
    message.tool_calls = [call]
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def fake_synthesis_response():
    call = MagicMock()
    call.function.name = "emit_brief"
    call.function.arguments = json.dumps({
        "executive_summary": "This account shows healthy usage overall with one escalation-worthy "
                              "ticket in the last 90 days. ARR is stable and the primary contact "
                              "remains engaged. No immediate churn signals beyond the one flagged item.",
        "recommended_talking_points": [
            "Follow up on the flagged escalation ticket and confirm resolution status.",
            "Review upcoming renewal date and confirm stakeholder alignment.",
        ],
    })
    message = MagicMock()
    message.tool_calls = [call]
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_full_chain_and_caching():
    accounts = load_accounts()
    acc = accounts[0]
    account_id = acc["account_id"]
    tickets = get_recent_tickets_for_account(account_id)

    # clean any pre-existing cache file for a clean test
    cache_path = brief_cache._cache_path(account_id)
    if cache_path.exists():
        cache_path.unlink()

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        fake_risk_flags_response(tickets),
        fake_synthesis_response(),
    ]

    # --- first call: cache miss, should call the LLM twice ---
    brief1 = generate_account_brief(account_id, client=mock_client)
    assert brief1.cache_hit is False
    assert len(brief1.open_risks) == 1, "the fabricated quote should have been dropped"
    assert brief1.open_risks[0].ticket_id == tickets[0]["ticket_id"]
    assert mock_client.chat.completions.create.call_count == 2
    print(f"First call: cache_hit={brief1.cache_hit}, risk flags={len(brief1.open_risks)} (1 expected, fabricated quote dropped)")

    # --- second call: same inputs, should hit cache, NOT call the LLM again ---
    brief2 = generate_account_brief(account_id, client=mock_client)
    assert brief2.cache_hit is True
    assert brief2.executive_summary == brief1.executive_summary
    assert brief2.generated_at == brief1.generated_at, "cached brief must be byte-identical, including metadata"
    assert mock_client.chat.completions.create.call_count == 2, "LLM should NOT be called again on cache hit"
    print(f"Second call: cache_hit={brief2.cache_hit}, identical output confirmed, LLM not re-invoked.")

    print("\nFull chain + determinism test passed.")


def main():
    test_quote_validation_against_real_data()
    test_full_chain_and_caching()


if __name__ == "__main__":
    main()
