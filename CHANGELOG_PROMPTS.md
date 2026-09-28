# Prompt Changelog

Every prompt used by the LLM pipelines is tagged with a version string, carried through into every
structured output (`TriageOutput.prompt_version`, `AccountBrief.prompt_version`) and into the eval
report, so a quality regression can always be traced back to a specific prompt version rather than
just "the model got worse."

## Task 1 — Triage (`TRIAGE_SYSTEM_PROMPT`, `src/prompts.py`)

### v1 — current
- Initial system prompt: 4-product classification, 8-category enum, P1-P4 urgency defined by
  business impact (not customer tone), forced `emit_triage` tool call.
- Instructs the model to use the retrieved KB excerpt only if genuinely relevant, rather than forcing
  a reference to it every time.

## Task 2 — Account Brief (`RISK_EXTRACTION_SYSTEM_PROMPT` + `BRIEF_SYNTHESIS_SYSTEM_PROMPT`,
`src/prompts.py`)

### v1 — current
- Two-prompt chain (risk extraction, then synthesis) rather than one combined prompt — see
  `DESIGN_NOTE.md` for the latency/quality rationale.
- Risk-extraction prompt explicitly forbids padding output with non-risks ("most routine tickets are
  NOT risk signals") after early testing showed the model over-flagging when not told this.
- Synthesis prompt explicitly forbids inventing facts/quotes beyond what's provided, since it only
  receives the pre-validated risk list, never raw tickets.

## How to bump a version

1. Edit the prompt text in `src/prompts.py`.
2. Increment `TRIAGE_PROMPT_VERSION` or `BRIEF_PROMPT_VERSION` at the top of the file.
3. Add a dated entry to this file describing what changed and why.
4. Re-run `python3 tests/run_eval.py` — the report's `prompt_version` field lets you diff quality
   scores between versions directly. Task 2's cache is keyed in part by `prompt_version`, so bumping
   it correctly invalidates stale cached briefs generated under the old prompt.
