"""
Structured I/O contracts for the triage pipeline.

Keeping these as Pydantic models (rather than free-form dicts) is what
lets us force the LLM into a valid JSON shape via tool-use, and gives
Task 3's eval harness something concrete to validate against.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# --- Input ---------------------------------------------------------------

class TicketInput(BaseModel):
    """A raw incoming ticket. Matches the subject+body shape from the
    starter dataset; ticket_id/account_id are optional so the function
    also works for brand-new tickets that don't exist in tickets.json yet."""

    subject: str = Field(..., min_length=1, description="Ticket subject line")
    body: str = Field(..., min_length=1, description="Full ticket body text")
    ticket_id: Optional[str] = None
    account_id: Optional[str] = None
    company: Optional[str] = None
    plan_tier: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: str | dict) -> "TicketInput":
        """Accept either a raw text blob or a dict/JSON payload.

        Plain text is treated as the body with an empty subject, so the
        `/triage` endpoint can also accept a bare string ticket.
        """
        if isinstance(raw, str):
            return cls(subject="", body=raw)
        return cls(**raw)


# --- Output ----------------------------------------------------------------

UrgencyTier = Literal["P1", "P2", "P3", "P4"]

CategoryLabel = Literal[
    "Bug",
    "Feature Request",
    "How-To",
    "Performance",
    "Billing",
    "Integration",
    "Onboarding",
    "Data Loss",
]


class KBMatch(BaseModel):
    doc_path: str
    section: str
    score: float
    snippet: str


class TriageOutput(BaseModel):
    product_area: str = Field(..., description="Product/module the ticket concerns")
    issue_category: CategoryLabel
    urgency_tier: UrgencyTier
    reasoning: str = Field(..., description="Short justification for the classification")

    matched_kb_doc: Optional[KBMatch] = None

    recommended_team: str
    draft_response: str = Field(..., description="Draft first-response message to the customer")

    # Bookkeeping fields, filled in by the pipeline, not the LLM
    prompt_version: str = "v1"
    model: str = ""


# --- Task 2: TAM account health brief -----------------------------------

RiskSeverity = Literal["High", "Medium", "Low"]


class RiskFlag(BaseModel):
    """A single churn-risk / escalation signal grounded in one ticket.

    `quote` is guaranteed (by code, not just LLM instruction) to be an
    exact verbatim substring of that ticket's subject+body - see
    account_brief.py's quote-validation step.
    """
    ticket_id: str
    quote: str = Field(..., description="Verbatim substring from the ticket subject/body")
    risk_type: str = Field(..., description="e.g. 'Escalation risk', 'Repeated issue', 'Negative sentiment'")
    severity: RiskSeverity
    reason: str = Field(..., description="One short sentence on why this signals risk")


class AccountBrief(BaseModel):
    account_id: str
    company: str

    executive_summary: str = Field(..., description="3-5 sentence overview of account health")
    open_risks: list[RiskFlag] = Field(default_factory=list, description="Ticket-grounded risk flags")
    account_level_notes: list[str] = Field(
        default_factory=list,
        description="Risk signals from the account record itself (escalation_notes), not tied to a specific ticket",
    )
    recommended_talking_points: list[str] = Field(default_factory=list)

    # Bookkeeping / determinism metadata
    prompt_version: str = "v1"
    model: str = ""
    input_hash: str = ""
    generated_at: str = ""
    cache_hit: bool = False
