"""
Lightweight FastAPI wrapper around triage_ticket().

Run with:
    uvicorn src.api:app --reload --port 8000

Then:
    curl -X POST http://localhost:8000/triage \\
      -H "Content-Type: application/json" \\
      -d '{"subject": "Cannot log in via SSO", "body": "New hires get an error when signing in with SSO."}'
"""
from __future__ import annotations

import json
import logging
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .schemas import TicketInput, TriageOutput, AccountBrief
from .triage import triage_ticket, stream_draft_response
from .account_brief import generate_account_brief

logger = logging.getLogger("triage_api")

app = FastAPI(
    title="Ticket Triage API",
    description="Classifies incoming support tickets and drafts a first response.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageOutput)
def triage_endpoint(ticket: TicketInput) -> TriageOutput:
    try:
        return triage_ticket(ticket.model_dump(exclude_none=True))
    except RuntimeError as e:
        # e.g. missing API key, or model failed to call the tool
        raise HTTPException(status_code=502, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Catch-all so failures are visible in the API response during
        # development instead of a bare "Internal Server Error". The full
        # traceback is also logged to the uvicorn console either way.
        logger.error("Unhandled error in /triage: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/accounts/{account_id}/brief", response_model=AccountBrief)
def account_brief_endpoint(account_id: str, force_refresh: bool = False) -> AccountBrief:
    try:
        return generate_account_brief(account_id, force_refresh=force_refresh)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error("Unhandled error in /accounts/%s/brief: %s\n%s", account_id, e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/triage/stream")
def triage_stream_endpoint(ticket: TicketInput):
    """Bonus: streaming demo. Classifies the ticket normally (structured,
    synchronous - same guarantees as /triage), then streams a live
    regeneration of the draft first-response message via Server-Sent
    Events, so a caller can render it token-by-token instead of waiting
    for the full response."""
    try:
        classification = triage_ticket(ticket.model_dump(exclude_none=True))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    kb_context = None
    if classification.matched_kb_doc:
        kb_context = classification.matched_kb_doc.snippet

    def event_gen():
        header = {
            "product_area": classification.product_area,
            "issue_category": classification.issue_category,
            "urgency_tier": classification.urgency_tier,
            "recommended_team": classification.recommended_team,
        }
        yield f"event: classification\ndata: {json.dumps(header)}\n\n"
        try:
            for chunk in stream_draft_response(ticket, header, kb_context):
                yield f"event: draft_chunk\ndata: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
