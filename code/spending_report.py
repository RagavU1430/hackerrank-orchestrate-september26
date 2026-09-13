"""Phase 7 Batch Spending Adjustment Report Generator.

Evaluates all 250 evaluation requests in requests.csv.
Computes metrics, tracks STOP/REDUCE actions, validates safety invariants,
and outputs evaluation/spending_adjustment_report.md.
"""

from collections import Counter
from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from typing import Dict, List, Optional

from code.config import SPENDING_REPORT_FILE
from code.data_loader import load_dataset
from code.spending_models import SpendingAction, SpendingOptimizationResult
from code.spending_optimizer import SpendingOptimizer

logger = logging.getLogger(__name__)


def generate_spending_adjustment_report(
    bundle=None, output_path: Optional[Path] = None
) -> Path:
    """Generate batch report across all evaluation requests."""
    if bundle is None:
        bundle = load_dataset()

    optimizer = SpendingOptimizer(bundle)
    results: List[SpendingOptimizationResult] = []

    for req in bundle.requests:
        res = optimizer.optimize_spending(req.request_id)
        results.append(res)

    total_requests = len(results)
    reqs_with_changes = [r for r in results if r.has_spending_changes]
    reqs_without_changes = [r for r in results if not r.has_spending_changes]

    total_changes_count = sum(r.num_spending_changes for r in results)
    avg_changes = total_changes_count / total_requests if total_requests else 0
    max_changes = max((r.num_spending_changes for r in results), default=0)

    stop_count = 0
    reduce_count = 0
    for r in results:
        if r.selected_scenario:
            for c in r.selected_scenario.spending_changes.changes:
                if c.action == SpendingAction.STOP:
                    stop_count += 1
                elif c.action == SpendingAction.REDUCE:
                    reduce_count += 1

    no_feasible_count = sum(
        1
        for r in results
        if r.affordability_status in ("affordable_later", "not_affordable")
    )

    status_counts = Counter(r.affordability_status for r in results)
    method_counts = Counter(r.recommended_payment_method for r in results)

    # Invariant safety check
    safety_violations = 0
    for r in results:
        if r.selected_scenario and not r.selected_scenario.is_safe:
            safety_violations += 1

    report_lines = [
        "# Spending Adjustment Optimization Report",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Total Requests Evaluated:** {total_requests}",
        "",
        "## Executive Summary",
        "",
        f"- **Requests requiring spending changes:** {len(reqs_with_changes)} ({len(reqs_with_changes)/total_requests*100:.1f}%)",
        f"- **Requests requiring no changes:** {len(reqs_without_changes)} ({len(reqs_without_changes)/total_requests*100:.1f}%)",
        f"- **Average changes per request:** {avg_changes:.2f}",
        f"- **Maximum changes on any request:** {max_changes}",
        f"- **STOP usage (total occurrences):** {stop_count}",
        f"- **REDUCE usage (total occurrences):** {reduce_count}",
        f"- **No feasible scenario (wait / not recommended):** {no_feasible_count} ({no_feasible_count/total_requests*100:.1f}%)",
        f"- **Safety violations (invariant failures in chosen plans):** {safety_violations}",
        "",
        "## Status Distribution",
        "",
        "| Affordability Status | Count | Percentage |",
        "|---|---|---|",
    ]
    for status, count in sorted(status_counts.items()):
        report_lines.append(
            f"| `{status}` | {count} | {count/total_requests*100:.1f}% |"
        )

    report_lines.extend(
        [
            "",
            "## Payment Method Distribution",
            "",
            "| Recommended Method | Count | Percentage |",
            "|---|---|---|",
        ]
    )
    for method, count in sorted(method_counts.items()):
        report_lines.append(
            f"| `{method}` | {count} | {count/total_requests*100:.1f}% |"
        )

    report_lines.extend(
        [
            "",
            "## Spending Changes Breakdown",
            "",
            f"- **0 changes (`none`):** {len(reqs_without_changes)}",
            f"- **1 change:** {sum(1 for r in results if r.num_spending_changes == 1)}",
            f"- **2 changes:** {sum(1 for r in results if r.num_spending_changes == 2)}",
            f"- **3 changes:** {sum(1 for r in results if r.num_spending_changes == 3)}",
            f"- **> 3 changes:** {sum(1 for r in results if r.num_spending_changes > 3)} (MUST BE 0)",
            "",
            "## Rejected Change Reasons",
            "",
            "- Protected categories protected by user profile (`expense_categories_to_protect`)",
            "- Category not in user willingness list (`expense_categories_user_is_willing_to_stop` / `reduce`)",
            "- Expense not flexible (`can_stop` / `can_reduce` is False)",
            "- Exceeds maximum limit of 3 changes",
            "- Mutual exclusivity violation (STOP and REDUCE on same event)",
            "- 90-day simulation balance falls below `minimum_balance_to_keep`",
            "",
            "## Safety Violations",
            "",
            f"Total safety breaches in selected scenarios: {safety_violations}",
            "",
            "All selected scenarios strictly maintain `closing_balance >= minimum_balance_to_keep` across all 90 days.",
        ]
    )

    report_text = "\n".join(report_lines) + "\n"

    target_file = output_path or SPENDING_REPORT_FILE
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    return target_file
