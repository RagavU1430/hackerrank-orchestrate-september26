"""Phase 9 end-to-end orchestration and reproducible submission generation."""

from collections import Counter
import csv
from dataclasses import dataclass
from pathlib import Path
import time
import tracemalloc
import logging

from code.evidence_manager import EvidenceManager
from code.final_validator import OUTPUT_COLUMNS, FinalOutputValidationError, validate_decision, validate_output_rows
from code.financial_agent import FinancialAgent


@dataclass(frozen=True)
class FinalRunResult:
    output_path: Path
    report_path: Path
    row_count: int
    status_counts: dict
    method_counts: dict
    spending_change_count: int
    evidence_updates_applied: int
    elapsed_seconds: float
    peak_memory_bytes: int
    determinism_verified: bool


def _write_csv(path, rows):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def _write_report(path, result, evidence_issues):
    lines = [
        "# Final Evaluation Report", "", "## Dataset validation", "", "PASS — Phase 1 validated before final processing.",
        "", "## Requests processed", "", str(result.row_count), "", "## Successful", "", str(result.row_count),
        "", "## Failed", "", "0", "", "## Affordability distribution", "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(result.status_counts.items()))
    lines.extend(["", "## Payment-method distribution", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(result.method_counts.items()))
    lines.extend(["", "## Spending-change distribution", "", f"Rows with changes: {result.spending_change_count}",
                  "", "## Evidence", "", f"Validated updates applied: {result.evidence_updates_applied}",
                  f"Unresolved/rejected evidence issues retained: {evidence_issues}",
                  "", "## Safety invariant", "", "PASS — every emitted payment plan was selected by the deterministic optimizer and final row validation passed.",
                  "", "## Output schema", "", "PASS — exact required columns and order.",
                  "", "## Output row count", "", f"PASS — {result.row_count} rows.",
                  "", "## Determinism", "", "PASS — two independent in-memory batches matched before write." if result.determinism_verified else "PENDING — this run used the single-batch mode; run --run-final for the two-batch comparison.",
                  "", "## Performance", "", f"Total runtime: {result.elapsed_seconds:.3f} seconds",
                  (f"Peak traced Python memory: {result.peak_memory_bytes} bytes" if result.peak_memory_bytes else "Peak traced Python memory: not collected during the two-pass reproducibility run."), "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def generate_final_output(bundle, output_path, report_path, verify_determinism=True):
    """Run the same production path for every request and atomically write output.csv."""
    if not bundle.validation_report.is_valid:
        raise FinalOutputValidationError("Phase 1 validation failed; final output was not generated")
    start = time.perf_counter()
    previous_disable = logging.root.manager.disable
    logging.disable(logging.INFO)
    # Allocation tracing is valuable for a single performance audit, but it is
    # prohibitively expensive across the two independent reproducibility runs.
    trace_memory = not verify_determinism
    if trace_memory:
        tracemalloc.start()
    manager = EvidenceManager(bundle)
    evidence = manager.process_all_evidence(use_cache=True)
    agent = FinancialAgent(bundle, evidence_bundle=evidence)
    rows, states = [], {}
    for request in sorted(bundle.requests, key=lambda item: item.request_id):
        state = manager.build_evidence_aware_state(request, evidence)
        decision = agent.get_decision(request.request_id, financial_state=state)
        row = validate_decision(decision, request, state)
        rows.append(row)
        states[request.request_id] = state
    rows = validate_output_rows(rows, bundle, states)
    if verify_determinism:
        repeat_agent = FinancialAgent(bundle, evidence_bundle=evidence)
        repeated = []
        for request in sorted(bundle.requests, key=lambda item: item.request_id):
            repeated_state = manager.build_evidence_aware_state(request, evidence)
            repeated.append(repeat_agent.get_decision(request.request_id, financial_state=repeated_state).to_output_dict())
        if rows != repeated:
            raise FinalOutputValidationError("Final pipeline is nondeterministic")
    _write_csv(Path(output_path), rows)
    elapsed = time.perf_counter() - start
    if trace_memory:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak = 0
    logging.disable(previous_disable)
    result = FinalRunResult(
        output_path=Path(output_path), report_path=Path(report_path), row_count=len(rows),
        status_counts=dict(Counter(row["affordability_status"] for row in rows)),
        method_counts=dict(Counter(row["recommended_payment_method"] for row in rows)),
        spending_change_count=sum(row["spending_changes_needed"] != "none" for row in rows),
        evidence_updates_applied=sum(len(state.evidence_updates) for state in states.values()),
        elapsed_seconds=elapsed, peak_memory_bytes=peak, determinism_verified=verify_determinism,
    )
    _write_report(result.report_path, result, len(evidence.validation_issues))
    return result


def validate_output_file(path, bundle):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != OUTPUT_COLUMNS:
            raise FinalOutputValidationError("CSV headers do not match required output schema")
        rows = list(reader)
    # File-level validation is deliberately schema/mapping focused. Full semantic
    # validation happens before write with the exact evidence-aware states.
    request_ids = {request.request_id for request in bundle.requests}
    if len(rows) != len(request_ids) or {row["request_id"] for row in rows} != request_ids:
        raise FinalOutputValidationError("CSV does not have exactly one row per evaluation request")
    return rows
