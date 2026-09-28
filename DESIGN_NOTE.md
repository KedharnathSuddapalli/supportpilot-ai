# Design Note

## Failure modes

**1. LLM misclassification on ambiguous tickets.** A ticket with weak signal (e.g. "something's wrong
since the last charge" — Billing or Bug?) can get a confident-sounding but wrong category, which
misroutes it to the wrong team. *Detection:* the eval harness's adversarial cases (`t1-06`,
`t1-07`) specifically probe this; in production I'd log a `confidence` proxy (e.g. whether the
model's own reasoning hedges) and flag low-confidence tickets for a human second look rather than
auto-routing them. *Mitigation:* the deterministic `CATEGORY_TEAM_MAP` cross-check in `triage.py`
already prevents a bad team-name hallucination even when the category itself is uncertain.

**2. Hallucinated quotes in the account brief.** An LLM asked to "quote a ticket" can paraphrase and
still present it as verbatim, which would break trust with a TAM who checks it against the real
ticket. *Detection & mitigation:* this is handled structurally, not just by prompting — every quote
the risk-extraction LLM proposes is checked in code (`_validate_quote` in `account_brief.py`) against
the real ticket text, and anything that isn't an exact substring is silently dropped before the
synthesis step ever sees it. The eval harness re-verifies this independently (`t2-04`).

**3. Retrieval returning a plausible-but-wrong KB doc.** Embedding similarity can surface a
topically-adjacent but factually wrong document (e.g. a CloudSync doc for a WorkflowEngine issue),
which would make the draft response cite the wrong fix. *Detection:* the `KB_MIN_SCORE` threshold in
`config.py` suppresses low-confidence matches rather than forcing a match; in production I'd also log
every (query, matched_doc, score) triple and periodically sample-review low-margin matches (top-1 score
close to top-2). *Mitigation:* the prompt explicitly instructs the model to judge relevance itself
rather than blindly trusting the retrieved snippet.

## Latency vs. quality trade-off

The clearest trade-off is **Task 2's two-call chain** (risk extraction → synthesis) instead of one
combined call. This roughly doubles LLM latency for a brief, but keeps the risk-extraction step
narrowly focused (just "find risky tickets and quote them") so the model doesn't have to juggle
extraction and prose-writing in the same pass — in testing, a single combined call produced vaguer,
less-grounded executive summaries. If latency were the hard constraint, I'd collapse this to one call
and accept looser grounding, or keep two calls but run them concurrently for independent accounts
(they don't depend on each other across accounts, only within one). I'd also drop the LLM-as-judge
step from any latency-critical path — it belongs only in the offline eval harness, not the live
request path, which is exactly how it's built today.

## Data sensitivity

Ticket and account text (names, emails, business details) is customer PII, and every LLM call in
this system sends raw ticket/account text to Groq's API — that's an inherent tension for any
LLM-based product using a hosted model. Two mitigations already in the design: (1) **retrieval never
leaves the process** — the embedding model runs locally (`sentence-transformers`), so KB matching
never sends ticket text to an external service; only the final classification/synthesis calls do,
which is the minimum necessary surface. (2) **The account brief cache** (`cache.py`) means a repeat
request for the same account doesn't re-transmit ticket data to the LLM at all. For a real
production version, I'd add: field-level redaction/tokenization of obvious PII (emails, names) before
the prompt is built, a data processing agreement with the LLM vendor, and routing to a
self-hosted/VPC-deployed model for any account tagged as handling regulated data.

## Scaling (10× ticket volume)

At 10× volume (5,000 tickets, 500 accounts), the first thing to break is **the LLM API rate limit** —
Groq's free tier (~30 req/min) would throttle triage almost immediately; this needs a paid tier and a
request queue with backoff, not just "call the API for every ticket as it arrives." Second,
**`load_accounts()`/`load_tickets()`** currently read the full JSON file into memory via `lru_cache`
on every process start — fine at 500 tickets, but at 10×+ scale this should move to an actual database
(even SQLite) with indexed lookups on `account_id`/`company` instead of linear scans in
`accounts_data.py`. Third, the **embedding retrieval index** is rebuilt in-process at startup; that's
fine for a 9-doc KB but wouldn't scale to a large KB — a persistent vector store (rather than an
in-memory numpy array) would be needed once the KB itself grows past a few hundred docs. The
**account-brief cache** actually scales *well* here — it means the 10× ticket volume only translates
to fresh LLM calls for accounts with genuinely new tickets, not a 10× LLM cost increase across the
board.
