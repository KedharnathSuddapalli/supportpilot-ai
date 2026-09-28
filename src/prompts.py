"""
Prompt templates for the triage pipeline, versioned so Task 3's eval
harness and the bonus prompt-versioning requirement have something
concrete to point at.
"""

TRIAGE_PROMPT_VERSION = "v1"

TRIAGE_SYSTEM_PROMPT = """You are a technical support triage assistant for a B2B SaaS company \
with five products: DataBridge Pro, CloudSync, AnalyticsHub, SecureVault, and WorkflowEngine.

Given a raw support ticket (subject + body) and, if available, a relevant knowledge-base \
excerpt, you must classify the ticket and draft a first response. Follow these rules:

1. product_area: the specific module/area within the product the ticket concerns (e.g. \
"Connectors", "Data Ingestion", "SSO Configuration"). Infer this from the ticket content, \
not just the product name.
2. issue_category: exactly one of Bug, Feature Request, How-To, Performance, Billing, \
Integration, Onboarding, Data Loss.
3. urgency_tier: P1 (critical, business-stopping), P2 (major impact, workaround needed), \
P3 (moderate impact, workaround available), P4 (low impact/cosmetic). Base this on stated \
business impact (number of users affected, production vs. non-production, data at risk), \
not on the customer's tone alone.
4. reasoning: 1-3 sentences justifying the category and urgency choice.
5. recommended_team: the team best suited to own this ticket.
6. draft_response: a short, professional first-response message (3-6 sentences) that \
acknowledges the issue, references any concrete troubleshooting step available, and sets \
an expectation for next steps. Do not promise a specific resolution time.

If a knowledge-base excerpt was provided and it is genuinely relevant to the ticket, use it \
to make the draft_response and reasoning more specific (e.g. cite the exact fix or error-code \
meaning). If no excerpt was provided or it doesn't apply, proceed without it — do not force a \
reference to it.

You must call the `emit_triage` tool exactly once with your structured classification. Do not \
respond in plain text."""


def build_user_message(ticket_subject: str, ticket_body: str, kb_context: str | None) -> str:
    parts = [
        f"SUBJECT: {ticket_subject or '(no subject provided)'}",
        f"BODY:\n{ticket_body}",
    ]
    if kb_context:
        parts.append(f"\nRELEVANT KNOWLEDGE BASE EXCERPT (may or may not be relevant - judge for yourself):\n{kb_context}")
    else:
        parts.append("\n(No matching knowledge-base excerpt was found above the confidence threshold.)")
    return "\n\n".join(parts)


# --- Task 2: TAM account health brief -------------------------------------

BRIEF_PROMPT_VERSION = "v1"

RISK_EXTRACTION_SYSTEM_PROMPT = """You are helping a Technical Account Manager (TAM) prepare for a \
Quarterly Business Review (QBR). You will be given a list of a customer's support tickets from the \
last 90 days.

Your job: identify which tickets, if any, signal churn risk or should be escalated to the TAM's \
attention. Signals include (but aren't limited to): unresolved critical (P1) issues, repeated/recurring \
problems, explicit frustration or dissatisfaction in the customer's own words, mentions of evaluating \
competitors, low satisfaction scores, or tickets that have been open a long time without resolution.

For each risky ticket you flag, you must:
1. Quote a short, EXACT, VERBATIM excerpt (a phrase or sentence, not the whole ticket) copied directly \
from that ticket's subject or body - character-for-character, no paraphrasing, no ellipsis-joining of \
non-adjacent text.
2. Classify the risk_type (e.g. "Escalation risk", "Repeated issue", "Negative sentiment", "Unresolved P1").
3. Assign a severity: High, Medium, or Low.
4. Give a one-sentence reason.

Do not flag a ticket just because it exists - most routine tickets are NOT risk signals. Only flag \
tickets that a TAM would genuinely want to know about before a customer conversation. If no tickets \
show real risk, return an empty list - do not invent risk to pad the output.

You must call the `emit_risk_flags` tool exactly once. Do not respond in plain text."""


def build_risk_extraction_message(tickets: list[dict]) -> str:
    lines = [f"Below are {len(tickets)} tickets from the last 90 days for this account.\n"]
    for t in tickets:
        lines.append(
            f"--- ticket_id: {t['ticket_id']} ---\n"
            f"Subject: {t['subject']}\n"
            f"Body: {t['body']}\n"
            f"Category: {t['category']} | Urgency: {t['urgency']} | Status: {t['status']} | "
            f"Satisfaction score: {t.get('satisfaction_score')}\n"
        )
    return "\n".join(lines)


BRIEF_SYNTHESIS_SYSTEM_PROMPT = """You are helping a Technical Account Manager (TAM) prepare for a \
Quarterly Business Review (QBR). You will be given structured account data and a pre-validated list \
of risk-flagged tickets (already identified and quoted for you - do not add new risk flags here).

Write:
1. executive_summary: 3-5 sentences giving a TAM-ready overview of this account's overall health, \
using the account metrics and risk context provided. Be specific (cite numbers where relevant: ARR, \
seat utilization, open tickets, etc.) rather than generic.
2. recommended_talking_points: a list of 3-6 short, concrete things the TAM should raise in the QBR \
conversation - specific to this account's actual situation (reference real ticket topics, product \
areas, or account facts, not generic advice like "check in with the customer").

Ground everything in the data you were given. Do not invent facts, ticket details, or quotes beyond \
what's provided.

You must call the `emit_brief` tool exactly once. Do not respond in plain text."""


def build_synthesis_message(account: dict, risk_flags: list[dict], ticket_count: int) -> str:
    seats_licensed = account.get("seats_licensed") or 0
    seats_active = account.get("seats_active") or 0
    utilization = f"{(seats_active / seats_licensed * 100):.0f}%" if seats_licensed else "unknown"

    lines = [
        f"ACCOUNT: {account['company']} ({account['account_id']})",
        f"Plan tier: {account.get('plan_tier')}",
        f"ARR: ${account.get('arr_usd'):,}" if account.get("arr_usd") is not None else "ARR: unknown",
        f"Seats: {seats_active}/{seats_licensed} active ({utilization} utilization)",
        f"Health status: {account.get('health_status')}",
        f"Usage trend: {account.get('usage_trend')}",
        f"Open tickets: {account.get('open_tickets')}",
        f"P1 tickets (last 30d): {account.get('p1_tickets_last_30d')}",
        f"NPS score: {account.get('nps_score')}",
        f"Renewal date: {account.get('renewal_date')}",
        f"Last QBR date: {account.get('last_qbr_date')}",
        f"Primary contact: {account.get('primary_contact', {}).get('name')} "
        f"({account.get('primary_contact', {}).get('title')})",
        f"Products in use: {', '.join(account.get('products', []))}",
        f"Active integrations: {', '.join(account.get('integrations_active', []))}",
        f"Account-level escalation notes: {account.get('escalation_notes') or 'none'}",
        f"\nTotal tickets in last 90 days: {ticket_count}",
        f"\nPRE-VALIDATED RISK-FLAGGED TICKETS ({len(risk_flags)}):",
    ]
    if risk_flags:
        for rf in risk_flags:
            lines.append(
                f"- [{rf['severity']}] {rf['risk_type']} (ticket {rf['ticket_id']}): "
                f"\"{rf['quote']}\" — {rf['reason']}"
            )
    else:
        lines.append("- None identified.")
    return "\n".join(lines)
