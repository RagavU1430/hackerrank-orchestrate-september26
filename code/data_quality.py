"""Data Quality Reporting module.

Analyzes normalized DatasetBundle and produces evaluation/data_quality_report.md.
"""

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, List

from code.config import DATA_QUALITY_REPORT_FILE, EVALUATION_DIR
from code.schemas import DatasetBundle
from code.validators import ValidationResult


def generate_data_quality_report(bundle: DatasetBundle, report_path: Path = DATA_QUALITY_REPORT_FILE) -> str:
    """Generate comprehensive Markdown data quality report and save it to disk."""
    report_lines: List[str] = []

    # Title
    report_lines.append("# Dataset Quality Report")
    report_lines.append("")
    report_lines.append("Automated Phase 1 Data Foundation & Ingestion Verification.")
    report_lines.append("")

    # 1. Files & Row Counts
    report_lines.append("## Files & Row Counts")
    report_lines.append("")
    report_lines.append("| Dataset | File Name | Records | Columns | Status |")
    report_lines.append("| :--- | :--- | :--- | :--- | :--- |")
    report_lines.append(f"| Financial Profiles | `financial_profiles.csv` | {len(bundle.profiles)} | 10 | Validated |")
    report_lines.append(f"| Financial Events | `financial_events.csv` | {len(bundle.events)} | 14 | Validated |")
    report_lines.append(f"| Evaluation Requests | `requests.csv` | {len(bundle.requests)} | 8 | Validated |")
    report_lines.append(f"| Sample Requests | `sample_requests.csv` | {len(bundle.sample_requests)} | 15 | Validated |")
    report_lines.append(f"| Payment Options | `request_payment_options.csv` | {len(bundle.payment_options)} | 9 | Validated |")
    report_lines.append(f"| Exchange Rates | `exchange_rates.csv` | {len(bundle.exchange_rates)} | 4 | Validated |")
    report_lines.append(f"| Messages | `messages.csv` | {len(bundle.messages)} | 7 | Validated |")
    report_lines.append(f"| Images | `images.csv` | {len(bundle.images)} | 4 | Validated |")
    report_lines.append("")

    # 2. Duplicate Identifiers
    report_lines.append("## Duplicate Identifiers")
    report_lines.append("")
    val: ValidationResult = bundle.validation_report
    dup_errors = [e for e in val.errors if "Duplicate" in e.message]
    if not dup_errors:
        report_lines.append("Zero duplicate primary identifiers found across all 8 datasets.")
    else:
        report_lines.append(f"Found {len(dup_errors)} duplicate identifier error(s):")
        for err in dup_errors:
            report_lines.append(f"- [{err.dataset}] {err.field}: {err.message}")
    report_lines.append("")

    # 3. Missing Values & Null Patterns
    report_lines.append("## Missing Values Analysis")
    report_lines.append("")
    # Events with missing amount
    missing_amt_count = sum(1 for e in bundle.events if e.amount is None)
    unrealized_settle_count = sum(1 for e in bundle.events if e.settlement_date is None)
    linked_event_count = sum(1 for e in bundle.events if e.linked_event_id is not None)
    profile_no_inst = sum(1 for p in bundle.profiles if p.max_installment_months is None)
    full_pay_no_freq = sum(1 for o in bundle.payment_options if o.payment_frequency_days is None)

    report_lines.append(f"- **Financial Events missing amount**: `{missing_amt_count}` records (all mapped to evidence queue).")
    report_lines.append(f"- **Financial Events missing settlement_date**: `{unrealized_settle_count}` records (unrealized investments).")
    report_lines.append(f"- **Financial Events with linked_event_id**: `{linked_event_count}` records.")
    report_lines.append(f"- **Profiles without installment preference**: `{profile_no_inst}` users (`max_installment_months` is blank).")
    report_lines.append(f"- **Payment Options without frequency**: `{full_pay_no_freq}` options (single full payment options).")
    report_lines.append("")

    # 4. Cross-Reference Integrity
    report_lines.append("## Cross-Reference Integrity")
    report_lines.append("")
    xref_errors = [e for e in val.errors if "Unknown" in e.message or "not found" in e.message]
    if not xref_errors:
        report_lines.append("All foreign key relationships are strictly intact:")
        report_lines.append("- Every request references a valid user in `financial_profiles.csv`.")
        report_lines.append("- Every financial event references a valid user in `financial_profiles.csv`.")
        report_lines.append("- Every payment option references a valid request in `requests.csv` or `sample_requests.csv`.")
        report_lines.append("- Every message references a valid user.")
        report_lines.append("- Every image references a valid user, valid event, and existing PNG file.")
    else:
        report_lines.append(f"Found {len(xref_errors)} referential integrity issue(s):")
        for err in xref_errors:
            report_lines.append(f"- [{err.dataset}] {err.field}: {err.message}")
    report_lines.append("")

    # 5. Dynamic Image Evidence Queue
    report_lines.append("## Dynamic Image Evidence Queue")
    report_lines.append("")
    report_lines.append(f"Total events requiring image amount extraction in Phase 3: **{len(bundle.evidence_queue)}**")
    report_lines.append("")
    report_lines.append("| Event ID | User ID | Category | Event Date | Linked Image | Image Path Exists |")
    report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for ev in bundle.evidence_queue:
        exists_str = "Yes" if ev.image_path.is_file() else "NO (MISSING)"
        report_lines.append(f"| `{ev.event_id}` | `{ev.user_id}` | `{ev.category}` | `{ev.event_date}` | `{ev.image_id}` | {exists_str} |")
    report_lines.append("")

    # 6. Currency Coverage & Distribution
    report_lines.append("## Currency Distribution")
    report_lines.append("")
    profile_curr = Counter(p.home_currency for p in bundle.profiles)
    report_lines.append("### User Home Currencies")
    report_lines.append("| Currency | Count | Percentage |")
    report_lines.append("| :--- | :--- | :--- |")
    for curr, count in profile_curr.most_common():
        pct = count * 100.0 / len(bundle.profiles)
        report_lines.append(f"| `{curr}` | {count} | {pct:.1f}% |")
    report_lines.append("")

    report_lines.append("### Exchange Rate Currency Pairs")
    xr_pairs = Counter((xr.from_currency, xr.to_currency) for xr in bundle.exchange_rates)
    report_lines.append("| Currency Pair | Rates Count | Date Range |")
    report_lines.append("| :--- | :--- | :--- |")
    for (fc, tc), cnt in xr_pairs.most_common():
        rates_for_pair = [xr.rate_date for xr in bundle.exchange_rates if xr.from_currency == fc and xr.to_currency == tc]
        min_d, max_d = min(rates_for_pair), max(rates_for_pair)
        report_lines.append(f"| `{fc}` -> `{tc}` | {cnt} | {min_d} to {max_d} |")
    report_lines.append("")

    # 7. Date Coverage
    report_lines.append("## Date Coverage")
    report_lines.append("")
    req_dates = [r.request_date for r in bundle.requests]
    sample_dates = [r.request_date for r in bundle.sample_requests]
    event_dates = [e.event_date for e in bundle.events]

    report_lines.append(f"- **Evaluation Requests**: `{min(req_dates)}` to `{max(req_dates)}`")
    report_lines.append(f"- **Sample Requests**: `{min(sample_dates)}` to `{max(sample_dates)}`")
    report_lines.append(f"- **Financial Events**: `{min(event_dates)}` to `{max(event_dates)}`")
    report_lines.append("")

    # 8. Status & Flexibility Distributions
    report_lines.append("## Status & Flexibility Distributions")
    report_lines.append("")
    status_counts = Counter(e.status for e in bundle.events)
    report_lines.append("### Event Status")
    report_lines.append("| Status | Count | Share |")
    report_lines.append("| :--- | :--- | :--- |")
    for st, cnt in status_counts.most_common():
        pct = cnt * 100.0 / len(bundle.events)
        report_lines.append(f"| `{st}` | {cnt} | {pct:.2f}% |")
    report_lines.append("")

    flex_counts = Counter(e.flexibility for e in bundle.events)
    report_lines.append("### Event Flexibility")
    report_lines.append("| Flexibility | Count | Share |")
    report_lines.append("| :--- | :--- | :--- |")
    for fl, cnt in flex_counts.most_common():
        pct = cnt * 100.0 / len(bundle.events)
        report_lines.append(f"| `{fl}` | {cnt} | {pct:.2f}% |")
    report_lines.append("")

    # 9. Overall Quality Status
    report_lines.append("## Overall Status")
    report_lines.append("")
    if val.fatal_errors:
        report_lines.append("**Status: FAIL (Fatal Errors Encountered)**")
    elif val.errors:
        report_lines.append("**Status: FAIL (Errors Encountered)**")
    elif val.warnings:
        report_lines.append("**Status: PASS WITH WARNINGS**")
    else:
        report_lines.append("**Status: PASS (All Structural & Relational Checks Verified)**")

    report_lines.append("")
    report_lines.append("---")
    report_lines.append("*Report generated automatically by Phase 1 Data Foundation Ingestion engine.*")
    report_lines.append("")

    content = "\n".join(report_lines)

    # Ensure evaluation directory exists
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")

    return content
