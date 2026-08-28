"""
Not part of the Task 3 eval harness - this is a quick internal sanity
check to validate the triage_ticket() plumbing (retrieval -> tool call ->
schema assembly) without requiring network access to huggingface.co or a
live OpenAI API key. Safe to delete once real end-to-end runs work.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval import Chunk
from src.triage import triage_ticket


def fake_kb_match(*args, **kwargs):
    return [
        (Chunk(
            doc_path="troubleshooting/authentication-sso.md",
            heading_path="Troubleshooting: Authentication & SSO > New Users Cannot Authenticate via SSO",
            text="Symptom: Existing users log in fine; new joiners get an error. Most common cause: "
                 "The new user's IDP group has not been mapped to a product role.",
        ), 0.71),
    ]


def fake_openai_response():
    tool_call = MagicMock()
    tool_call.function.name = "emit_triage"
    tool_call.function.arguments = json.dumps({
        "product_area": "SSO Configuration",
        "issue_category": "Bug",
        "urgency_tier": "P2",
        "reasoning": "New hires cannot authenticate via SSO, blocking onboarding for multiple users; "
                     "existing users unaffected so it is not fully business-stopping.",
        "recommended_team": "Technical Support - Tier 2",
        "draft_response": "Thanks for reaching out - this looks like new users are missing an IDP "
                           "group-to-role mapping. Could you confirm the IDP group name for the "
                           "affected new hires? In the meantime, check Settings > SSO > Group Mapping "
                           "on your end. We'll follow up shortly.",
    })

    message = MagicMock()
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def main():
    with patch("src.triage.get_retriever") as mock_get_retriever, \
         patch("src.triage._get_client") as mock_get_client:

        mock_retriever = MagicMock()
        mock_retriever.search.side_effect = fake_kb_match
        mock_get_retriever.return_value = mock_retriever

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_openai_response()
        mock_get_client.return_value = mock_client

        ticket = {
            "subject": "New hires can't log in via SSO",
            "body": "We onboarded 5 new engineers this week and none of them can authenticate via "
                    "SSO. Existing employees have no issues. Getting a generic error on the login page.",
            "company": "Acme Corp",
            "plan_tier": "Enterprise",
        }

        result = triage_ticket(ticket)
        print(result.model_dump_json(indent=2))

        assert result.issue_category == "Bug"
        assert result.urgency_tier == "P2"
        # routing fallback should have overridden to the deterministic mapping for "Bug"
        assert result.recommended_team == "Technical Support - Tier 2"
        assert result.matched_kb_doc is not None
        assert result.matched_kb_doc.doc_path == "troubleshooting/authentication-sso.md"
        print("\nSmoke test passed.")


if __name__ == "__main__":
    main()
