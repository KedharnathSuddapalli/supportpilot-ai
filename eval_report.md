# Eval Report

Generated: 2026-08-28T15:25:46.749119+00:00
Model: `openai/gpt-oss-120b`

## Task 1 · Ticket Triage

**7/7 passed** · average quality score: **0.92**

| Case | Adversarial | Result | Quality | Notes |
|---|---|---|---|---|
| `t1-01-p1-data-loss` | no | ✅ PASS | 0.86 | category_matches_expected: expected 'Data Loss', got 'Integration' |
| `t1-02-billing-invoice-discrepancy` | no | ✅ PASS | 0.88 | urgency_matches_expected: expected 'P4', got 'P3' |
| `t1-03-feature-request-export` | no | ✅ PASS | 1.00 | all checks passed |
| `t1-04-how-to-permissions` | no | ✅ PASS | 0.99 | all checks passed |
| `t1-05-sso-kb-match` | no | ✅ PASS | 0.88 | urgency_matches_expected: expected 'P2', got 'P1' |
| `t1-06-adversarial-ambiguous` | ⚠️ yes | ✅ PASS | 0.87 | llm_judge: The reasoning confidently declares a billing cause without noting the ticket's ambiguity, and the draft response speculates about seat‑count billing rather than simply asking for clarification, violating the rubric's requirement to acknowledge uncertainty and avoid guessing fixes. |
| `t1-07-adversarial-minimal` | ⚠️ yes | ✅ PASS | 0.99 | all checks passed |

## Task 2 · Account Brief

**5/7 passed** · average quality score: **0.69**

| Case | Adversarial | Result | Quality | Notes |
|---|---|---|---|---|
| `t2-01-at-risk-with-escalation` | no | ❌ FAIL | 0.00 | no_exception: BadRequestError: Error code: 400 - {'error': {'message': 'Failed to parse tool call arguments as JSON', 'type': 'invalid_request_error', 'code': 'tool_use_failed', 'failed_generation': '{"name": "emit_risk_flags", "arguments": {\n  "risk_flags": [\n    {\n      "ticket_id": "TKT-10393",\n      "quote": "our Data Sources functionality has broken",\n      "risk_type": "Escalation risk",\n      "severity": "High",\n      "reason": "Critical Data Sources feature is broken for 486 users and the ticket remains open."\n    },\n    {\n      "ticket_id": "TKT-10466",\n      "quote": "Error when accessing Pipeline Monitoring in DataBridge Pro",\n      "risk_type": "Escalation risk",\n      "severity": "Medium",\n      "reason": "All users encounter a consistent error after the latest update and the issue is still unresolved."\n    },\n    {\n      "ticket_id": "TKT-10073",\n      "quote": "AnalyticsHub running extremely slowly for our team",\n      "risk_type": "Negative sentiment",\n      "severity": "Medium",\n     "}'}} |
| `t2-02-healthy-account` | no | ❌ FAIL | 0.00 | no_exception: BadRequestError: Error code: 400 - {'error': {'message': 'Tool choice is required, but model did not call a tool', 'type': 'invalid_request_error', 'code': 'tool_use_failed', 'failed_generation': ''}} |
| `t2-03-churning-account` | no | ✅ PASS | 1.00 | all checks passed |
| `t2-04-quote-fidelity` | no | ✅ PASS | 1.00 | all checks passed |
| `t2-05-determinism` | no | ✅ PASS | 1.00 | all checks passed |
| `t2-06-adversarial-unknown-account` | ⚠️ yes | ✅ PASS | 1.00 | all checks passed |
| `t2-07-adversarial-zero-tickets` | ⚠️ yes | ✅ PASS | 0.80 | llm_judge: The output references specific ticket counts and details (11 open tickets, P1 status, recent activity) despite the input providing no ticket information, violating the rubric's requirement to discuss only given account-level metrics. |

## Overall

**12/14 passed** · average quality score: **0.80**
