"""Batch evaluation and diagnostics reporting for Phase 5 Affordability Decision Engine."""

from collections import Counter
from decimal import Decimal
import logging
from pathlib import Path
from typing import List, Tuple

from code.affordability import evaluate_affordability
from code.affordability_models import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    NOT_AFFORDABLE,
    AffordabilityDecision,
)
from code.state_builder import build_financial_state

logger = logging.getLogger(__name__)


def generate_affordability_report(
    bundle,
    report_path: Path,
) -> Tuple[List[AffordabilityDecision], List[Tuple[str, str]], Path]:
    """Evaluate all evaluation requests through Phase 5 Affordability Decision Engine.

    Generates evaluation/affordability_report.md.
    """
    requests_sorted = sorted(bundle.requests, key=lambda r: r.request_id)
    decisions: List[AffordabilityDecision] = []
    failures: List[Tuple[str, str]] = []

    for req in requests_sorted:
        try:
            state = build_financial_state(bundle, req)
            dec = evaluate_affordability(state, req)
            decisions.append(dec)
        except Exception as exc:
            logger.exception("Affordability evaluation failed for %s: %s", req.request_id, exc)
            failures.append((req.request_id, str(exc)))

    status_counts = Counter(d.affordability_status for d in decisions)
    fully_affordable = sum(1 for d in decisions if d.decision_diagnostics.is_fully_affordable)
    partially_affordable = sum(1 for d in decisions if d.decision_diagnostics.is_partially_affordable)
    zero_safe = sum(1 for d in decisions if d.decision_diagnostics.is_not_affordable_now)
    future_safe = sum(1 for d in decisions if d.decision_diagnostics.is_future_affordable)
    no_safe_date = sum(1 for d in decisions if d.earliest_date_for_full_payment is None)

    # Invariant checks
    invariants_passed = all(
        Decimal("0") <= d.amount_safe_to_pay <= d.requested_amount
        for d in decisions
    )

    lines = [
        "# Affordability Decision Report",
        "",
        "## Summary",
        "",
        f"- **Requests Evaluated**: {len(decisions)} / {len(requests_sorted)}",
        f"- **Failures / Errors**: {len(failures)}",
        f"- **Safety Invariant Check (0 <= safe <= requested)**: {'PASS' if invariants_passed else 'FAIL'}",
        "",
        "## Status Distribution",
        "",
        "| Affordability Status | Count | Percentage |",
        "| --- | ---: | ---: |",
        f"| `{AFFORDABLE_NOW}` | {status_counts[AFFORDABLE_NOW]} | {status_counts[AFFORDABLE_NOW] / len(decisions) * 100:.1f}% |",
        f"| `{AFFORDABLE_WITH_PLAN}` | {status_counts[AFFORDABLE_WITH_PLAN]} | {status_counts[AFFORDABLE_WITH_PLAN] / len(decisions) * 100:.1f}% |",
        f"| `{AFFORDABLE_LATER}` | {status_counts[AFFORDABLE_LATER]} | {status_counts[AFFORDABLE_LATER] / len(decisions) * 100:.1f}% |",
        f"| `{NOT_AFFORDABLE}` | {status_counts[NOT_AFFORDABLE]} | {status_counts[NOT_AFFORDABLE] / len(decisions) * 100:.1f}% |",
        "",
        "## Affordability Breakdown",
        "",
        f"- **Fully Affordable Today (`safe == requested`)**: {fully_affordable}",
        f"- **Partially Affordable Today (`0 < safe < requested`)**: {partially_affordable}",
        f"- **Zero Safe Today (`safe == 0`)**: {zero_safe}",
        f"- **Future Full Payment Safe Date Found**: {future_safe}",
        f"- **No Safe Full Payment Date in 90 Days**: {no_safe_date}",
        "",
        "## Sample Decisions",
        "",
        "| Request ID | User | Requested | Safe Today | Earliest Full Date | Status |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]

    for d in decisions[:15]:
        earliest_str = d.earliest_date_for_full_payment.isoformat() if d.earliest_date_for_full_payment else "none"
        lines.append(
            f"| `{d.request_id}` | `{d.user_id}` | {d.requested_amount} | "
            f"{d.amount_safe_to_pay} | {earliest_str} | `{d.affordability_status}` |"
        )

    if failures:
        lines.extend([
            "",
            "## Evaluation Failures",
            "",
            "| Request ID | Error |",
            "| --- | --- |",
        ])
        for rid, err in failures:
            lines.append(f"| `{rid}` | {err} |")

    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Affordability report written to %s", report_path)

    return decisions, failures, report_path
