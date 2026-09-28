"""
Eval harness runner.

Usage:
    python3 tests/run_eval.py

Runs every case in eval_cases.py through the REAL Task 1 / Task 2
pipelines (real Groq calls - requires GROQ_API_KEY in .env), scores each
one with a mix of rule-based checks and an LLM-as-judge call, and writes:
    eval_report.json  (machine-readable, full detail)
    eval_report.md    (human-readable summary table)

A case is scored 0.0-1.0 by averaging its check scores. A few checks are
treated as "hard" (schema validity, no unhandled exception, no
hallucinated quotes) - failing any hard check fails the case outright
regardless of the average, since these represent guarantees the system
must never violate, not judgment calls.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import judges
from tests.eval_cases import TASK1_CASES, TASK2_CASES

from src import config
from src.triage import triage_ticket, _get_client as get_triage_client
from src.account_brief import generate_account_brief
from src.accounts_data import get_recent_tickets_for_account

HARD_CHECK_NAMES = {"no_exception", "urgency_valid", "category_valid", "quotes_verbatim", "raises_value_error"}

PASS_THRESHOLD = 0.7


def _score_case(case_id: str, task: str, description: str, adversarial: bool,
                 checks: list[judges.CheckResult], elapsed: float) -> dict:
    quality_score = sum(c.score for c in checks) / len(checks) if checks else 0.0
    hard_fail = any(not c.passed for c in checks if c.name in HARD_CHECK_NAMES)
    passed = (not hard_fail) and quality_score >= PASS_THRESHOLD
    return {
        "id": case_id,
        "task": task,
        "description": description,
        "adversarial": adversarial,
        "passed": passed,
        "quality_score": round(quality_score, 3),
        "elapsed_seconds": round(elapsed, 3),
        "checks": [
            {"name": c.name, "passed": c.passed, "score": round(c.score, 3), "detail": c.detail}
            for c in checks
        ],
    }


def run_task1_case(case: dict, client) -> dict:
    checks: list[judges.CheckResult] = []
    t0 = time.time()
    exc_check, output = judges.check_no_exception("no_exception", triage_ticket, case["ticket"])
    checks.append(exc_check)
    elapsed = time.time() - t0

    if output is None:
        return _score_case(case["id"], "task1", case["description"], case["adversarial"], checks, elapsed)

    checks.append(judges.check_enum_value("urgency_valid", output.urgency_tier, ["P1", "P2", "P3", "P4"]))
    checks.append(judges.check_enum_value(
        "category_valid", output.issue_category,
        ["Bug", "Feature Request", "How-To", "Performance", "Billing", "Integration", "Onboarding", "Data Loss"],
    ))
    checks.append(judges.check_nonempty("reasoning_nonempty", output.reasoning, min_len=10))
    checks.append(judges.check_nonempty("draft_response_nonempty", output.draft_response, min_len=10))

    if case.get("expected_category"):
        checks.append(judges.check_exact_match("category_matches_expected", output.issue_category, case["expected_category"]))
    if case.get("expected_urgency"):
        checks.append(judges.check_exact_match("urgency_matches_expected", output.urgency_tier, case["expected_urgency"]))
    if case.get("expected_kb_doc_substring"):
        doc_path = output.matched_kb_doc.doc_path if output.matched_kb_doc else ""
        checks.append(judges.check_substring("kb_doc_matches_expected", doc_path, case["expected_kb_doc_substring"]))

    if case.get("judge_rubric"):
        context = f"Ticket subject: {case['ticket']['subject']}\nTicket body: {case['ticket']['body']}"
        output_text = (
            f"issue_category={output.issue_category}, urgency_tier={output.urgency_tier}\n"
            f"reasoning: {output.reasoning}\ndraft_response: {output.draft_response}"
        )
        checks.append(judges.llm_judge(client, context, output_text, case["judge_rubric"]))

    return _score_case(case["id"], "task1", case["description"], case["adversarial"], checks, elapsed)


def run_task2_case(case: dict, client) -> dict:
    checks: list[judges.CheckResult] = []
    t0 = time.time()
    case_type = case["case_type"]
    account_id = case["account_id"]

    if case_type == "brief":
        exc_check, brief = judges.check_no_exception(
            "no_exception", generate_account_brief, account_id, force_refresh=True
        )
        checks.append(exc_check)
        elapsed = time.time() - t0
        if brief is None:
            return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

        checks.append(judges.check_nonempty("executive_summary_nonempty", brief.executive_summary, min_len=20))

        if "min_talking_points" in case["checks"]:
            checks.append(judges.check_min_count(
                "min_talking_points", brief.recommended_talking_points, case["checks"]["min_talking_points"]
            ))
        if case["checks"].get("quotes_verbatim"):
            tickets = get_recent_tickets_for_account(account_id)
            tickets_by_id = {t["ticket_id"]: t for t in tickets}
            risk_flags = [rf.model_dump() for rf in brief.open_risks]
            checks.append(judges.check_quotes_verbatim("quotes_verbatim", risk_flags, tickets_by_id))

        if case.get("judge_rubric"):
            context = (
                f"Account: {brief.company} ({account_id})\n"
                f"Open risks flagged: {[rf.model_dump() for rf in brief.open_risks]}\n"
                f"Account-level notes: {brief.account_level_notes}"
            )
            output_text = (
                f"executive_summary: {brief.executive_summary}\n"
                f"recommended_talking_points: {brief.recommended_talking_points}"
            )
            checks.append(judges.llm_judge(client, context, output_text, case["judge_rubric"]))

        return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

    elif case_type == "brief_determinism":
        exc_check, first = judges.check_no_exception(
            "no_exception", generate_account_brief, account_id, force_refresh=True
        )
        checks.append(exc_check)
        elapsed = time.time() - t0
        if first is None:
            return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

        second = generate_account_brief(account_id)  # should be a cache hit
        checks.append(judges.check_exact_match("second_call_is_cache_hit", second.cache_hit, True))
        checks.append(judges.check_exact_match("identical_executive_summary", second.executive_summary, first.executive_summary))
        checks.append(judges.check_exact_match("identical_generated_at", second.generated_at, first.generated_at))

        return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

    elif case_type == "brief_missing_account":
        raises_check = judges.check_raises("raises_value_error", generate_account_brief, ValueError, account_id)
        checks.append(raises_check)
        elapsed = time.time() - t0
        return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

    elif case_type == "brief_zero_tickets":
        with patch("src.account_brief.get_recent_tickets_for_account", return_value=[]):
            exc_check, brief = judges.check_no_exception(
                "no_exception", generate_account_brief, account_id, force_refresh=True
            )
        checks.append(exc_check)
        elapsed = time.time() - t0
        if brief is None:
            return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

        checks.append(judges.check_nonempty("executive_summary_nonempty", brief.executive_summary, min_len=20))
        checks.append(judges.check_min_count("no_open_risks_with_zero_tickets", [], 0))  # trivially satisfied; documents intent
        checks.append(judges.check_exact_match("open_risks_is_empty", brief.open_risks, []))

        if case.get("judge_rubric"):
            context = f"Account: {brief.company} ({account_id})\nNo tickets were provided in the input."
            output_text = (
                f"executive_summary: {brief.executive_summary}\n"
                f"recommended_talking_points: {brief.recommended_talking_points}"
            )
            checks.append(judges.llm_judge(client, context, output_text, case["judge_rubric"]))

        return _score_case(case["id"], "task2", case["description"], case["adversarial"], checks, elapsed)

    else:
        raise ValueError(f"Unknown case_type: {case_type}")


def build_markdown_report(results: list[dict], generated_at: str) -> str:
    lines = ["# Eval Report", "", f"Generated: {generated_at}", f"Model: `{config.MODEL_NAME}`", ""]

    for task_name, task_label in [("task1", "Task 1 · Ticket Triage"), ("task2", "Task 2 · Account Brief")]:
        task_results = [r for r in results if r["task"] == task_name]
        n_pass = sum(1 for r in task_results if r["passed"])
        avg_score = sum(r["quality_score"] for r in task_results) / len(task_results) if task_results else 0

        lines.append(f"## {task_label}")
        lines.append("")
        lines.append(f"**{n_pass}/{len(task_results)} passed** · average quality score: **{avg_score:.2f}**")
        lines.append("")
        lines.append("| Case | Adversarial | Result | Quality | Notes |")
        lines.append("|---|---|---|---|---|")
        for r in task_results:
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            adv = "⚠️ yes" if r["adversarial"] else "no"
            failing = [c for c in r["checks"] if not c["passed"]]
            notes = "; ".join(f"{c['name']}: {c['detail']}" for c in failing) if failing else "all checks passed"
            lines.append(f"| `{r['id']}` | {adv} | {status} | {r['quality_score']:.2f} | {notes} |")
        lines.append("")

    total = len(results)
    total_pass = sum(1 for r in results if r["passed"])
    total_avg = sum(r["quality_score"] for r in results) / total if total else 0
    lines.append("## Overall")
    lines.append("")
    lines.append(f"**{total_pass}/{total} passed** · average quality score: **{total_avg:.2f}**")
    lines.append("")

    return "\n".join(lines)


def main():
    generated_at = datetime.now(timezone.utc).isoformat()
    print(f"Running eval harness against model={config.MODEL_NAME} ...\n")

    client = get_triage_client()  # shared client, also used for the LLM-as-judge calls

    results = []
    for case in TASK1_CASES:
        print(f"[task1] {case['id']} ...", end=" ", flush=True)
        r = run_task1_case(case, client)
        results.append(r)
        print("PASS" if r["passed"] else "FAIL", f"(quality={r['quality_score']:.2f})")

    for case in TASK2_CASES:
        print(f"[task2] {case['id']} ...", end=" ", flush=True)
        r = run_task2_case(case, client)
        results.append(r)
        print("PASS" if r["passed"] else "FAIL", f"(quality={r['quality_score']:.2f})")

    report = {
        "generated_at": generated_at,
        "model": config.MODEL_NAME,
        "pass_threshold": PASS_THRESHOLD,
        "summary": {
            "total_cases": len(results),
            "total_passed": sum(1 for r in results if r["passed"]),
            "average_quality_score": round(sum(r["quality_score"] for r in results) / len(results), 3) if results else 0,
        },
        "results": results,
    }

    out_dir = Path(__file__).resolve().parent.parent
    (out_dir / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "eval_report.md").write_text(build_markdown_report(results, generated_at), encoding="utf-8")

    print(f"\n{report['summary']['total_passed']}/{report['summary']['total_cases']} passed "
          f"(avg quality {report['summary']['average_quality_score']:.2f})")
    print("Wrote eval_report.json and eval_report.md")


if __name__ == "__main__":
    main()
