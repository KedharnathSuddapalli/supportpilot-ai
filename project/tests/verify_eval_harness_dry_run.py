"""
Dry-run check of the eval harness's own logic (scoring, case dispatch,
report assembly) using mocked LLM responses - so we can verify the
harness is correct WITHOUT a live Groq call. Not a graded deliverable;
delete freely. The real eval_report.json/.md should be produced by
actually running `python3 tests/run_eval.py` with a working GROQ_API_KEY.
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schemas import TriageOutput, AccountBrief, RiskFlag
from tests import judges, run_eval
from tests.eval_cases import TASK1_CASES, TASK2_CASES


def fake_triage_ticket(ticket):
    """Heuristic fake classifier - good enough to make standard cases
    pass and adversarial cases behave sensibly, purely to exercise the
    harness's scoring logic end-to-end."""
    text = f"{ticket.get('subject','')} {ticket.get('body','')}".lower()
    if "invoice" in text or "billing" in text or "charge" in text:
        cat, urg = "Billing", "P4"
    elif "feature request" in text or "would love to see" in text or "roadmap" in text:
        cat, urg = "Feature Request", "P4"
    elif "how do i" in text or "how to" in text or "documentation" in text:
        cat, urg = "How-To", "P4"
    elif "sso" in text:
        cat, urg = "Integration", "P2"
    elif "webhook" in text or "not being delivered" in text:
        cat, urg = "Data Loss", "P1"
    elif len(text.strip()) < 30:
        cat, urg = "Bug", "P3"  # minimal-info adversarial case
    else:
        cat, urg = "Bug", "P3"

    kb_match = None
    if "sso" in text:
        from src.schemas import KBMatch
        kb_match = KBMatch(doc_path="troubleshooting/authentication-sso.md", section="SSO",
                            score=0.7, snippet="mock snippet")

    return TriageOutput(
        product_area="Mock Area",
        issue_category=cat,
        urgency_tier=urg,
        reasoning="This is uncertain / ambiguous based on limited detail." if len(text.strip()) < 40
                  else "Mock reasoning grounded in ticket content for dry-run purposes.",
        matched_kb_doc=kb_match,
        recommended_team="Mock Team",
        draft_response="Could you share more detail so we can help?" if len(text.strip()) < 40
                        else "Thanks for reaching out, mock draft response addressing the issue.",
        model="mock-model",
    )


def fake_generate_account_brief(account_id, *, client=None, force_refresh=False):
    from src.accounts_data import get_account, get_recent_tickets_for_account
    account = get_account(account_id)
    if account is None:
        raise ValueError(f"No account found with account_id={account_id!r}")
    tickets = get_recent_tickets_for_account(account_id)

    risks = []
    if tickets and account.get("escalation_notes"):
        t0 = tickets[0]
        risks.append(RiskFlag(
            ticket_id=t0["ticket_id"], quote=t0["body"][:30], risk_type="Escalation risk",
            severity="High", reason="mock reason",
        ))

    return AccountBrief(
        account_id=account["account_id"],
        company=account["company"],
        executive_summary=f"Mock summary for {account['company']} with health_status={account['health_status']} "
                           f"and {len(tickets)} recent tickets, for dry-run verification purposes only.",
        open_risks=risks,
        account_level_notes=account.get("escalation_notes") or [],
        recommended_talking_points=["Mock talking point one.", "Mock talking point two."],
        model="mock-model",
        input_hash="mockhash",
        generated_at="2026-01-01T00:00:00+00:00",
        cache_hit=False,
    )


def fake_llm_judge(client, context, output, rubric):
    return judges.CheckResult("llm_judge", True, 0.85, "mock judge: looks reasonable")


def main():
    with patch("tests.run_eval.triage_ticket", side_effect=fake_triage_ticket), \
         patch("tests.run_eval.generate_account_brief", side_effect=fake_generate_account_brief), \
         patch("tests.run_eval.judges.llm_judge", side_effect=fake_llm_judge), \
         patch("tests.run_eval.get_triage_client", return_value=MagicMock()):

        client = run_eval.get_triage_client()

        print("=== Task 1 dry run ===")
        for case in TASK1_CASES:
            r = run_eval.run_task1_case(case, client)
            print(f"{r['id']}: passed={r['passed']} quality={r['quality_score']}")
            assert "checks" in r and len(r["checks"]) > 0

        print("\n=== Task 2 dry run ===")
        for case in TASK2_CASES:
            r = run_eval.run_task2_case(case, client)
            print(f"{r['id']}: passed={r['passed']} quality={r['quality_score']}")
            assert "checks" in r and len(r["checks"]) > 0

        print("\nDry run completed without exceptions - harness plumbing verified.")


if __name__ == "__main__":
    main()
