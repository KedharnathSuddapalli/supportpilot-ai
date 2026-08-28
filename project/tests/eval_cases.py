"""
Eval test case definitions.

Design note on ground truth: tickets.json's own `category` field is NOT
used as ground truth here. Spot-checking it against actual ticket
content shows it's uncorrelated with the real issue (e.g. a clear
invoice/billing question tagged "Bug"; a clear feature request tagged
"Billing"). This is consistent with Task 1's brief of classifying
"without any human labelling" - the dataset's tag is not a trustworthy
label to grade against. Instead, each test case below was hand-picked by
reading the real ticket text, and `expected_category` / `expected_urgency`
reflect what a competent human triager would independently conclude from
the content, not the dataset's tag.
"""

# --- Task 1: ticket triage cases ------------------------------------------

TASK1_CASES = [
    {
        "id": "t1-01-p1-data-loss",
        "description": "Clear P1: webhook delivery failure causing data loss to a downstream system",
        "adversarial": False,
        "ticket": {
            "subject": "Webhook from WorkflowEngine not reaching Snowflake",
            "body": "Our WorkflowEngine webhooks are not being delivered to Snowflake. We've verified "
                    "the endpoint is reachable and the secret is correctly configured.\n\n"
                    "Last successful delivery: earlier today\nFailed deliveries since: 7742\n\n"
                    "Webhook logs attached. Please advise.",
        },
        "expected_category": "Data Loss",
        "expected_urgency": "P1",
        "judge_rubric": "The draft_response should acknowledge this is a critical webhook/data-delivery "
                         "failure and ask for or reference concrete diagnostic detail (e.g. webhook logs, "
                         "endpoint status), not give a generic 'thanks for reaching out, we'll look into it'.",
    },
    {
        "id": "t1-02-billing-invoice-discrepancy",
        "description": "Clear billing question: seat count discrepancy on an invoice",
        "adversarial": False,
        "ticket": {
            "subject": "Billing question about SecureVault invoice",
            "body": "Hi,\n\nI have a question about our latest invoice (Invoice #49829). We were charged "
                    "for 282 seats but only have 275 active users.\n\nCould you clarify the billing logic "
                    "and process a credit if applicable?\n\nAccount: ACC-9375",
        },
        "expected_category": "Billing",
        "expected_urgency": "P4",
        "judge_rubric": "The draft_response should address the seat-count/invoice discrepancy specifically "
                         "and should not treat this as urgent or technical.",
    },
    {
        "id": "t1-03-feature-request-export",
        "description": "Clear feature request: export functionality to a third-party tool",
        "adversarial": False,
        "ticket": {
            "subject": "Feature request: export Key Management data to Jira",
            "body": "Hi team,\n\nWe'd love to see native export functionality from Key Management "
                    "directly to Jira. Currently we're using a manual workaround which takes our team "
                    "hours each week.\n\nUse case: automated client data delivery\n\n"
                    "Would this be on the roadmap? Happy to join a beta.",
        },
        "expected_category": "Feature Request",
        "expected_urgency": "P4",
        "judge_rubric": "The draft_response should acknowledge this as a feature request (not a bug), "
                         "and should not promise a delivery date it can't guarantee.",
    },
    {
        "id": "t1-04-how-to-permissions",
        "description": "Clear how-to / documentation request about configuring permissions",
        "adversarial": False,
        "ticket": {
            "subject": "How do I configure Permissions in CloudSync?",
            "body": "Hi,\n\nI'm trying to set up Permissions for our team but can't find clear "
                    "documentation. Specifically, I need to know:\n\n1. How to assign to team\n"
                    "2. What permissions are required\n3. Whether this integrates with Salesforce\n\n"
                    "We're on the Professional plan. Thanks in advance.",
        },
        "expected_category": "How-To",
        "expected_urgency": "P4",
        "judge_rubric": "The draft_response should be instructional/guidance-oriented, not treat this as "
                         "a bug report.",
    },
    {
        "id": "t1-05-sso-kb-match",
        "description": "SSO new-user authentication failure - should retrieve the authentication-sso.md KB doc",
        "adversarial": False,
        "ticket": {
            "subject": "SSO configuration not working for new users \u2014 CloudSync",
            "body": "We set up SSO for CloudSync last month and it works for existing users, but new "
                    "joiners can't authenticate.\n\nError they see: DEPENDENCY_UNAVAILABLE: downstream "
                    "service unreachable\n\nOur IDP: Salesforce\nPlan: Business\n\n"
                    "Please help \u2014 we have 308 people blocked from accessing the platform.",
        },
        "expected_category": "Integration",
        "expected_urgency": "P2",
        "expected_kb_doc_substring": "authentication-sso",
        "judge_rubric": "The draft_response should reference SSO/authentication troubleshooting relevant "
                         "to new-user access, ideally informed by the retrieved KB content.",
    },
    {
        "id": "t1-06-adversarial-ambiguous",
        "description": "ADVERSARIAL: deliberately ambiguous ticket that could plausibly be Billing OR Bug, "
                        "with almost no diagnostic detail",
        "adversarial": True,
        "ticket": {
            "subject": "Something's wrong since the last charge",
            "body": "Not sure if this is a billing issue or a bug, but something changed after our last "
                    "payment went through and now things look off. Can someone check?",
        },
        # No expected_category/expected_urgency - genuinely ambiguous. We only require the pipeline
        # to degrade gracefully (valid schema, non-generic reasoning) rather than match one "right" answer.
        "judge_rubric": "Given how vague and ambiguous this ticket is, the reasoning should explicitly "
                         "acknowledge the ambiguity/uncertainty rather than confidently asserting a "
                         "specific root cause it has no evidence for, and the draft_response should ask "
                         "a clarifying question rather than guess at a fix.",
    },
    {
        "id": "t1-07-adversarial-minimal",
        "description": "ADVERSARIAL: near-empty ticket body with almost no content",
        "adversarial": True,
        "ticket": {
            "subject": "help",
            "body": "not working",
        },
        "judge_rubric": "Given there is almost no information, the draft_response should ask for more "
                         "detail (what's not working, error messages, steps to reproduce) rather than "
                         "inventing a specific diagnosis it has no basis for.",
    },
]


# --- Task 2: account brief cases -------------------------------------------

TASK2_CASES = [
    {
        "id": "t2-01-at-risk-with-escalation",
        "description": "At-risk account with real escalation_notes and P1 ticket history - should "
                        "surface both ticket-level and account-level risk signals",
        "case_type": "brief",
        "adversarial": False,
        "account_id": "ACC-3336",
        "checks": {"min_talking_points": 2},
        "judge_rubric": "The executive_summary should reflect that this account is At Risk (not "
                         "portray it as simply healthy), and should reference concrete account facts "
                         "(ARR, seat utilization, or escalation context) rather than being generic.",
    },
    {
        "id": "t2-02-healthy-account",
        "description": "Healthy, growing account - should NOT invent risk signals that don't exist",
        "case_type": "brief",
        "adversarial": False,
        "account_id": "ACC-3033",
        "checks": {"min_talking_points": 1},
        "judge_rubric": "Given this account has no escalation_notes and Healthy/Increasing status, the "
                         "brief should not fabricate churn risk or catastrophize; open_risks should be "
                         "empty or contain only genuinely ticket-grounded issues, not invented ones.",
    },
    {
        "id": "t2-03-churning-account",
        "description": "Churning account with a departed champion and vendor-evaluation signal in "
                        "escalation_notes",
        "case_type": "brief",
        "adversarial": False,
        "account_id": "ACC-2944",
        "checks": {"min_talking_points": 2},
        "judge_rubric": "The executive_summary and talking points should reflect real urgency given "
                         "this account is Churning with a departed champion and active competitor "
                         "evaluation - a bland/neutral tone here would be a quality failure.",
    },
    {
        "id": "t2-04-quote-fidelity",
        "description": "Verifies every risk-flag quote in the brief is an exact, verbatim substring of "
                        "its cited ticket (not paraphrased or hallucinated)",
        "case_type": "brief",
        "adversarial": False,
        "account_id": "ACC-3336",
        "checks": {"quotes_verbatim": True},
        "judge_rubric": None,  # pure rule-based check, no LLM judge needed
    },
    {
        "id": "t2-05-determinism",
        "description": "Same account_id called twice must return byte-identical output via caching, "
                        "not just 'probably similar' LLM output",
        "case_type": "brief_determinism",
        "adversarial": False,
        "account_id": "ACC-3336",
        "checks": {},
        "judge_rubric": None,
    },
    {
        "id": "t2-06-adversarial-unknown-account",
        "description": "ADVERSARIAL: account_id that doesn't exist in accounts.json",
        "case_type": "brief_missing_account",
        "adversarial": True,
        "account_id": "ACC-0000-DOES-NOT-EXIST",
        "checks": {},
        "judge_rubric": None,
    },
    {
        "id": "t2-07-adversarial-zero-tickets",
        "description": "ADVERSARIAL: account with zero tickets in the 90-day window (simulated - no "
                        "such account naturally exists in this dataset) - must not crash, and the "
                        "brief should rely on account metrics alone rather than fabricating ticket "
                        "content",
        "case_type": "brief_zero_tickets",
        "adversarial": True,
        "account_id": "ACC-3033",
        "checks": {},
        "judge_rubric": "With no tickets in the window, the brief must not reference any specific "
                         "ticket, quote, or issue that wasn't provided - it should discuss only the "
                         "account-level metrics it was given.",
    },
]
