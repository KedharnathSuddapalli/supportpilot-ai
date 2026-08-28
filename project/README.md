# Support & TAM AI Tooling

Two LLM-powered internal tools, plus the eval harness that checks they still work:

1. **Ticket triage agent** (Task 1) — classifies an incoming support ticket, matches it to the
   knowledge base, and drafts a first response.
2. **TAM account health brief** (Task 2) — turns an account's recent ticket history into a
   QBR-ready summary with quote-grounded risk flags.
3. **Eval harness** (Task 3) — 14 test cases (7 per task, including adversarial ones) with
   rule-based + LLM-as-judge scoring.

Design note (failure modes, latency/quality trade-off, data sensitivity, scaling): **[`DESIGN_NOTE.md`](./DESIGN_NOTE.md)**
Prompt version history: **[`CHANGELOG_PROMPTS.md`](./CHANGELOG_PROMPTS.md)**

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set your Groq API key (free tier, no credit card — get one at
https://console.groq.com/keys):

```
GROQ_API_KEY=gsk_your_real_key_here
```

That's the only required change — everything else in `.env.example` has a working default.

> **Why Groq?** It exposes an OpenAI-compatible API, so the code uses the standard `openai` SDK
> pointed at Groq's base URL. KB retrieval uses a local `sentence-transformers` embedding model —
> the first run will download it (~80MB) from huggingface.co, then it's cached.

---

## Sample run — Task 1 (Ticket Triage)

**As a Python function:**
```python
from src.triage import triage_ticket

result = triage_ticket({
    "subject": "SSO configuration not working for new users",
    "body": "New joiners can't authenticate via SSO. Existing users have no issues.",
})
print(result.model_dump_json(indent=2))
```

**As a REST API:**
```bash
uvicorn src.api:app --reload
# then POST to http://127.0.0.1:8000/triage — see /docs for interactive Swagger UI
```

**Streaming variant (bonus):**
```bash
curl -N -X POST http://127.0.0.1:8000/triage/stream \
  -H "Content-Type: application/json" \
  -d '{"subject": "SSO not working", "body": "New users cant log in via SSO"}'
```

---

## Sample run — Task 2 (Account Brief)

**As a Python function:**
```python
from src.account_brief import generate_account_brief

brief = generate_account_brief("ACC-3336")
print(brief.model_dump_json(indent=2))

# calling it again with the same account_id returns the exact cached brief -
# no new LLM call, guaranteed identical output:
brief_again = generate_account_brief("ACC-3336")
assert brief_again.cache_hit is True
```

**As a REST API:**
```bash
uvicorn src.api:app --reload
# GET http://127.0.0.1:8000/accounts/ACC-3336/brief
# add ?force_refresh=true to bypass the cache and regenerate
```

---

## Sample run — Task 3 (Eval Harness)

```bash
python3 tests/run_eval.py
```

Runs all 14 test cases against the real pipeline and writes `eval_report.json` and
`eval_report.md` to the project root. Console output shows a live pass/fail + quality score per
case as it runs.

Lightweight sanity checks that don't need a live API key or model download:
```bash
python3 tests/smoke_test.py                    # Task 1 pipeline wiring
python3 tests/smoke_test_task2.py               # Task 2 pipeline wiring + caching
python3 tests/verify_eval_harness_dry_run.py     # eval harness scoring logic
```

---

## Bonus features implemented

- **Thin UI** (`ui/app.py`) — Streamlit app for both tasks, usable by a non-technical TAM:
  ```bash
  streamlit run ui/app.py
  ```
- **Streaming output** — `POST /triage/stream` streams the draft response live via Server-Sent
  Events (see `src/triage.py::stream_draft_response`).
- **CI eval harness** — `.github/workflows/eval.yml` runs the smoke tests on every push, and the
  full eval harness if a `GROQ_API_KEY` repo secret is configured.
- **Prompt versioning** — every prompt is tagged (`TRIAGE_PROMPT_VERSION`, `BRIEF_PROMPT_VERSION`
  in `src/prompts.py`), carried into every output and the eval report; history in
  `CHANGELOG_PROMPTS.md`.

---

## Project structure

```
src/
  config.py          # env vars, model/retrieval settings, team routing table
  schemas.py          # Pydantic I/O contracts (TriageOutput, AccountBrief, etc.)
  retrieval.py         # local embedding-based KB retrieval (sentence-transformers)
  prompts.py            # versioned prompt templates
  triage.py               # Task 1 pipeline
  accounts_data.py         # account <-> ticket joining + 90-day windowing
  cache.py                  # content-hash cache for deterministic account briefs
  account_brief.py           # Task 2 pipeline (2-step LLM chain + quote validation)
  api.py                       # FastAPI app (/triage, /accounts/{id}/brief, /triage/stream)
tests/
  judges.py           # rule-based + LLM-as-judge scoring primitives
  eval_cases.py         # 14 hand-picked test cases (real data, incl. adversarial)
  run_eval.py             # eval harness runner -> eval_report.json / eval_report.md
  smoke_test*.py             # pipeline-wiring sanity checks (mocked, no API key needed)
ui/
  app.py             # bonus Streamlit UI
data/                # provided mock dataset (accounts.json, tickets.json)
knowledge-base/      # provided product/troubleshooting docs
```

---

## Data note

`tickets.json`'s own `category` field was found to be uncorrelated with actual ticket content
(e.g. a clear invoice question tagged "Bug") during eval-case construction — so it isn't used as
ground truth anywhere in this repo. Ground truth for the eval harness was hand-derived by reading
real ticket text. See `tests/eval_cases.py` docstring for detail.

Also note: `ticket.account_id` mostly doesn't match any `account_id` in `accounts.json` (only ~4 of
484 unique values do) — `accounts_data.py` joins on `account_id` first and falls back to `company`
name, which matches 100% of the time in the provided dataset.
