"""Main CLI entry point for Buy or Wait?

Supports Phase 1 validation via:
    python -m code.main --validate
    python code/main.py --validate
"""

import argparse
import logging
from pathlib import Path
import sys
import time

# Ensure repo root is on sys.path and avoid stdlib 'code' clash
REPO_ROOT_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) in sys.path:
    sys.path.remove(str(CODE_DIR))
if str(REPO_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_DIR))

# If standard library 'code' was imported without package path, remove it
if "code" in sys.modules and not hasattr(sys.modules["code"], "__path__"):
    del sys.modules["code"]

from code.config import DATA_QUALITY_REPORT_FILE, REPO_ROOT
from code.data_loader import load_dataset
from code.data_quality import generate_data_quality_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("buy_or_wait")


def run_validation() -> int:
    """Execute Phase 1 dataset ingestion, indexing, and validation pipeline."""
    start_time = time.perf_counter()
    print("=" * 70)
    print("  Buy or Wait? — Phase 1: Data Foundation & Evidence-Ready Ingestion")
    print("=" * 70)
    print(f"Repository Root: {REPO_ROOT}")

    try:
        bundle = load_dataset()
    except Exception as exc:
        logger.exception(f"Fatal error during dataset ingestion: {exc}")
        print(f"\n[FATAL ERROR] Ingestion failed: {exc}")
        return 1

    # Generate data quality report
    report_content = generate_data_quality_report(bundle, DATA_QUALITY_REPORT_FILE)
    elapsed = time.perf_counter() - start_time

    val = bundle.validation_report
    print("\n--- Ingestion & Validation Summary ---")
    print(f"  Financial Profiles:   {len(bundle.profiles):>6}")
    print(f"  Financial Events:     {len(bundle.events):>6}")
    print(f"  Evaluation Requests:  {len(bundle.requests):>6}")
    print(f"  Sample Requests:      {len(bundle.sample_requests):>6}")
    print(f"  Payment Options:      {len(bundle.payment_options):>6}")
    print(f"  Exchange Rates:       {len(bundle.exchange_rates):>6}")
    print(f"  Messages:             {len(bundle.messages):>6}")
    print(f"  Images Verified:      {len(bundle.images):>6}")
    print(f"  Evidence Queue Items: {len(bundle.evidence_queue):>6}")
    print(f"  Execution Time:       {elapsed:.3f} seconds")
    print(f"  Quality Report:       {DATA_QUALITY_REPORT_FILE}")

    if val.fatal_errors or val.errors:
        print("\n[VALIDATION FAILED]")
        for err in val.fatal_errors + val.errors:
            print(f"  - [{err.severity}] {err.dataset}: {err.message}")
        return 1

    if val.warnings:
        print(f"\n[VALIDATION PASSED WITH {len(val.warnings)} WARNINGS]")
        for w in val.warnings:
            print(f"  - [{w.severity}] {w.dataset}: {w.message}")
    else:
        print("\n[VALIDATION PASSED PERFECTLY]")
        print("  All schemas, identifiers, and cross-references verified.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Buy or Wait? Financial Decision Agent")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--validate",
        action="store_true",
        help="Run Phase 1 data ingestion, cross-reference validation, and quality reporting",
    )

    modes.add_argument("--build-state", metavar="REQUEST_ID", help="Print one Phase 2 financial state summary")
    modes.add_argument("--validate-states", action="store_true", help="Validate all Phase 2 states and write the aggregate report")
    modes.add_argument("--extract-evidence", action="store_true", help="Extract and cache multimodal evidence from images and messages")
    modes.add_argument("--validate-evidence", action="store_true", help="Validate and report on extracted multimodal evidence")
    modes.add_argument("--simulate", metavar="REQUEST_ID", help="Run 90-day cash-flow simulation for one request")
    modes.add_argument("--validate-forecasts", action="store_true", help="Run baseline 90-day simulation for all requests and write forecast report")
    parser.add_argument("--snapshots", action="store_true", help="Write ignored Phase 2 diagnostic JSON snapshots")
    parser.add_argument("--verbose", action="store_true", help="Show daily ledger for --simulate")
    args = parser.parse_args()

    if args.simulate or args.validate_forecasts:
        from code.forecast_report import generate_forecast_report
        from code.simulator import simulate_90_days
        from code.state_builder import build_financial_state
        try:
            bundle = load_dataset()
            if not bundle.validation_report.is_valid:
                raise ValueError("Phase 1 validation failed; forecast not run")
            if args.simulate:
                state = build_financial_state(bundle, args.simulate)
                forecast = simulate_90_days(state)
                # Concise summary
                print("=" * 70)
                print(f"  Buy or Wait? — Phase 4: 90-Day Forecast — {forecast.request_id}")
                print("=" * 70)
                print(f"Request: {forecast.request_id}")
                print(f"User: {forecast.user_id}")
                print("")
                print("90-Day Forecast")
                print("---------------")
                print(f"Start Date: {forecast.start_date}")
                print(f"End Date: {forecast.end_date} ({forecast.days} days)")
                print("")
                print(f"Starting Balance: {forecast.starting_balance} {state.currency}")
                print(f"Ending Balance: {forecast.ending_balance} {state.currency}")
                print("")
                print(f"Minimum Balance: {forecast.minimum_observed_balance} {state.currency}")
                print(f"Minimum Balance Date: {forecast.minimum_balance_date}")
                print("")
                print(f"Minimum Reserve: {forecast.minimum_balance} {state.currency}")
                print(f"Minimum Headroom: {forecast.minimum_headroom} {state.currency}")
                print("")
                print(f"Total Inflows: {forecast.total_inflows} {state.currency}")
                print(f"Total Outflows: {forecast.total_outflows} {state.currency}")
                print("")
                print(f"First Safety Breach: {forecast.first_breach_date or 'NONE'}")
                print("")
                print(f"Invariant: {'PASS' if forecast.invariant_ok else 'BREACH'}")
                print(f"Warnings: {len(forecast.warnings)}")
                for w in forecast.warnings[:5]:
                    print(f"  - [{w.kind}] {w.code}: {w.source_id}")
                if args.verbose:
                    print("\nDaily Ledger (showing days with flows):")
                    for d in forecast.daily_forecasts:
                        if d.inflows or d.outflows:
                            print(f"{d.forecast_date} Open:{d.opening_balance} In:{d.total_inflows} Out:{d.total_outflows} Net:{d.net_change} Close:{d.closing_balance} Headroom:{d.headroom} {'OK' if d.invariant_ok else 'BREACH'}")
                            for e in d.inflows:
                                print(f"  + {e.source_id} {e.category} {e.normalized_amount}")
                            for e in d.outflows:
                                print(f"  - {e.source_id} {e.category} {e.normalized_amount}")
                exit_code = 0
            else:
                from code.config import FORECAST_REPORT_FILE
                forecasts, failures, report = generate_forecast_report(bundle, FORECAST_REPORT_FILE)
                print(f"Phase 4: {len(forecasts)}/{len(bundle.requests)} forecasts; {len(failures)} failures; Report: {report}")
                print(f"  Invariant PASS: {sum(1 for f in forecasts if f.invariant_ok)} BREACH: {sum(1 for f in forecasts if not f.invariant_ok)}")
                exit_code = 1 if failures else 0
        except Exception as exc:
            logger.exception("Phase 4 forecasting failed: %s", exc)
            exit_code = 1
    elif args.extract_evidence or args.validate_evidence:
        from code.evidence_manager import EvidenceManager
        from code.evidence_report import generate_evidence_report
        try:
            bundle = load_dataset()
            manager = EvidenceManager(bundle)
            print("=" * 70)
            print("  Buy or Wait? — Phase 3: Multimodal Evidence Intelligence")
            print("=" * 70)
            evidence_bundle = manager.process_all_evidence(use_cache=True)
            report_path = REPO_ROOT / "evaluation" / "evidence_report.md"
            generate_evidence_report(evidence_bundle, report_path)
            print(f"  Images Processed:      {len(evidence_bundle.images):>5} (Accepted: {len(evidence_bundle.accepted_images)})")
            print(f"  Messages Processed:    {len(evidence_bundle.messages):>5} (Accepted: {len(evidence_bundle.accepted_messages)})")
            print(f"  Validation Issues:     {len(evidence_bundle.validation_issues):>5}")
            print(f"  Conflicts:             {len(evidence_bundle.conflicts):>5}")
            print(f"  Evidence Report:       {report_path}")
            print("\n[PHASE 3 EVIDENCE EXTRACTION COMPLETE & VALIDATED]")
            exit_code = 0
        except Exception as exc:
            logger.exception("Phase 3 evidence processing failed: %s", exc)
            exit_code = 1
    elif args.build_state or args.validate_states:
        from code.state_builder import build_financial_state
        from code.state_diagnostics import state_summary, validate_states, write_snapshot
        import json
        try:
            bundle = load_dataset()
            if not bundle.validation_report.is_valid:
                raise ValueError("Phase 1 validation failed; Phase 2 was not run")
            snapshot_dir = REPO_ROOT / "evaluation" / "state_snapshots"
            if args.build_state:
                state = build_financial_state(bundle, args.build_state)
                print(json.dumps(state_summary(state), indent=2, sort_keys=True))
                if args.snapshots:
                    print(f"Snapshot: {write_snapshot(state, snapshot_dir)}")
                exit_code = 0
            else:
                report = REPO_ROOT / "evaluation" / "state_report.md"
                states, failures = validate_states(bundle, report, snapshot_dir if args.snapshots else None)
                print(f"Phase 2: {len(states)}/{len(bundle.requests)} states; {len(failures)} failures; "
                      f"{sum(len(s.warnings) for s in states)} warnings. Report: {report}")
                exit_code = 1 if failures else 0
        except (ValueError, OSError) as exc:
            logger.error("Phase 2 failed: %s", exc)
            exit_code = 1
    else:
        if args.snapshots:
            parser.error("--snapshots requires --build-state or --validate-states")
        if args.verbose:
            parser.error("--verbose requires --simulate")
        exit_code = run_validation()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
