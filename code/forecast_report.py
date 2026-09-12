"""Generate Phase 4 forecast diagnostics report."""

from collections import Counter
from pathlib import Path
from decimal import Decimal

from code.simulator import simulate_90_days
from code.state_builder import build_financial_state


def generate_forecast_report(bundle, report_path: Path):
    """Run baseline forecasts for all requests and summarize."""
    requests_sorted = sorted(bundle.requests, key=lambda r: r.request_id)
    forecasts = []
    failures = []
    for req in requests_sorted:
        try:
            state = build_financial_state(bundle, req)
            fc = simulate_90_days(state)
            forecasts.append(fc)
        except Exception as exc:  # keep as failure
            failures.append((req.request_id, str(exc)))

    total = len(requests_sorted)
    passed = sum(1 for f in forecasts if f.invariant_ok)
    breached = len(forecasts) - passed
    warnings_counter = Counter()
    for f in forecasts:
        for w in f.warnings:
            warnings_counter[(w.kind, w.code)] += 1

    # Income/expense classification counts from ledger totals
    # Minimum headroom stats
    if forecasts:
        headrooms = [f.minimum_headroom for f in forecasts]
        min_hr = min(headrooms)
        max_hr = max(headrooms)
        avg_hr = sum(headrooms, Decimal(0)) / Decimal(len(headrooms))
        min_bal = min(f.minimum_observed_balance for f in forecasts)
        max_bal = max(f.minimum_observed_balance for f in forecasts)
    else:
        min_hr = max_hr = avg_hr = min_bal = max_bal = Decimal(0)

    lines = [
        "# 90-Day Forecast Report",
        "",
        "## Simulation Coverage",
        "",
        f"Total evaluation requests: {total}",
        f"Forecasts generated: {len(forecasts)}",
        f"Failures: {len(failures)}",
        f"Window: 90 days (91 calendar snapshots incl. start date) per request",
        "",
        "## Invariant Summary",
        "",
        f"Invariant PASS (balance never below minimum): {passed}",
        f"Invariant BREACH: {breached}",
        "",
        "## Minimum Balance Statistics",
        "",
        f"Minimum observed balance (across forecasts) min: {min_bal} max: {max_bal}",
        f"Minimum headroom min: {min_hr} max: {max_hr} avg: {avg_hr.quantize(Decimal('0.01')) if forecasts else Decimal(0)}",
        "",
        "## Total Flow Statistics",
        "",
        f"Aggregate inflows: {sum((f.total_inflows for f in forecasts), Decimal(0))}",
        f"Aggregate outflows: {sum((f.total_outflows for f in forecasts), Decimal(0))}",
        "",
        "## Income Classifications",
        "",
        f"Total confirmed future inflows projected: {sum(len([e for d in f.daily_forecasts for e in d.inflows]) for f in forecasts)}",
        "Baseline excludes pending/uncertain/unrealized income per challenge rules.",
        "",
        "## Expense Classifications",
        "",
        f"Total outflow entries projected: {sum(len([e for d in f.daily_forecasts for e in d.outflows]) for f in forecasts)}",
        "Includes pending, scheduled, unsettled, and recurring debits. Flexible spending still occurs in baseline.",
        "",
        "## Warnings",
        "",
        "| Kind | Code | Count |",
        "| --- | --- | ---: |",
    ]
    for (kind, code), cnt in sorted(warnings_counter.items()):
        lines.append(f"| {kind} | {code} | {cnt} |")
    if not warnings_counter:
        lines.append("| - | none | 0 |")
    lines.extend([
        "",
        "## Unresolved Events",
        "",
        f"Warnings total: {sum(warnings_counter.values())}",
        "Unresolved amounts/rates remain explicit and are not substituted with zero.",
        "",
        "## State Validation",
        "PASS" if not failures else "FAIL",
        "",
        f"Failures: {len(failures)}",
    ])
    for fid, err in failures:
        lines.append(f"- {fid}: {err}")
    lines.extend([
        "",
        "## Example Forecasts",
        "",
        "| Request | User | Start | End | Starting Balance | Ending Balance | Min Headroom | First Breach |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ])
    for f in forecasts[:8]:
        lines.append(f"| {f.request_id} | {f.user_id} | {f.start_date} | {f.end_date} | {f.starting_balance} | {f.ending_balance} | {f.minimum_headroom} | {f.first_breach_date or 'NONE'} |")
    lines.append("")
    lines.append("## Diagnostics")
    lines.append("")
    lines.append("Run `python -m code.main --simulate <request_id>` for per-request verbose ledger.")
    lines.append("")

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return forecasts, failures, report_path
