"""Aggregate Phase 2 diagnostics. No predictions or evaluation labels."""

from collections import Counter
import json
from pathlib import Path

from code.financial_state import state_snapshot
from code.state_builder import build_financial_state


def state_summary(state):
    return {
        "request_id": state.request_id,
        "user_id": state.user_id,
        "request_date": str(state.request_date),
        "currency": state.currency,
        "starting_balance": str(state.available_balance),
        "minimum_balance": str(state.minimum_balance_to_keep),
        "historical_or_current_income_records": len(state.confirmed_income),
        "confirmed_future_inflows": len(state.future_confirmed_income),
        "pending_income": len(state.pending_income),
        "uncertain_or_non_cash": len(state.uncertain_income),
        "pending_debits": len(state.pending_debits),
        "scheduled_debits": len(state.scheduled_debits),
        "derived_recurring_inflows": len(state.recurring_inflows),
        "derived_recurring_outflows": len(state.recurring_outflows),
        "actionable_recurring_expenses": len(state.flexible_expenses),
        "unresolved_amounts": sum(e.money.amount_status == "unresolved_amount" for e in state.events),
        "foreign_currency_events": sum(e.event.currency != state.currency for e in state.events),
        "warnings": dict(sorted(Counter(w.code for w in state.warnings).items())),
    }


def write_snapshot(state, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Identifiers originate in data; prevent paths escaping snapshot directory.
    if not state.request_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in state.request_id):
        raise ValueError("Request identifier is unsafe as a snapshot filename")
    path = directory / (state.request_id + ".json")
    path.write_text(json.dumps(state_snapshot(state), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_states(bundle, report_path, snapshot_directory=None):
    states, failures = [], []
    for request in sorted(bundle.requests, key=lambda r: r.request_id):
        try:
            state = build_financial_state(bundle, request)
            states.append(state)
            if snapshot_directory is not None:
                write_snapshot(state, snapshot_directory)
        except ValueError as exc:
            failures.append((request.request_id, str(exc)))
    income, expense, warnings = Counter(), Counter(), Counter()
    for state in states:
        for item in state.events:
            (income if item.event.direction != "debit" else expense)[item.cash_class] += 1
        warnings.update((w.kind, w.code) for w in state.warnings)
    status = "FAIL" if failures else "PASS WITH WARNINGS" if warnings else "PASS"
    lines = ["# Financial State Report", "", "## Requests Processed", "",
             f"{len(states)} / {len(bundle.requests)} requests reconstructed. Counts below are request-scoped.",
             "", "## Users Processed", "", str(len({s.user_id for s in states})),
             "", "## Income Classification", ""]
    lines.extend(f"- {key}: {value}" for key, value in sorted(income.items()))
    lines.extend(["", "Historical/current settled income is already reflected in the profile balance. "
                  "Inferred income is derived metadata, not confirmed future money.",
                  "", "## Expense Classification", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(expense.items()))
    lines.extend(["", "## Pending Obligations", "",
                  f"Pending debits: {sum(len(s.pending_debits) for s in states)}. "
                  "Disputed linked charges remain reserved until confirmed evidence resolves them.",
                  "", "## Recurring Obligations", "",
                  f"Active derived inflow patterns: {sum(len(s.recurring_inflows) for s in states)}.",
                  f"Active derived outflow patterns: {sum(len(s.recurring_outflows) for s in states)}.",
                  "", "## Flexible Spending", "",
                  f"Active recurring expenses eligible for later adjustment: {sum(len(s.flexible_expenses) for s in states)}.",
                  "Eligibility requires recurrence, event flexibility, profile permission and no protection. No changes are proposed.",
                  "", "## Currency Conversion", ""])
    money = Counter(e.money.amount_status for s in states for e in s.events)
    lines.extend(f"- {key}: {value}" for key, value in sorted(money.items()))
    lines.extend(["", "Rates use exact settlement date and direction. Future recurrence occurrences must "
                  "be converted at their own dates with the rate table retained in the state.",
                  "", "## Evidence", "",
                  f"Request-scoped metadata references: {sum(len(s.evidence) for s in states)}. "
                  "No NLP, image extraction or model calls were performed.",
                  "", "## Warnings", "", "| Classification | Code | Count |", "| --- | --- | ---: |"])
    lines.extend(f"| {kind} | {code} | {count} |" for (kind, code), count in sorted(warnings.items()))
    lines.extend(["", "## State Validation", "", status, "",
                  f"IMPLEMENTATION ISSUE: {len(failures)} reconstruction failures."])
    lines.extend(f"- {identifier}: {error}" for identifier, error in failures)
    lines.extend(["", "## Example Diagnostic States", "",
                  "Examples are selected by state properties, never by evaluation answers. "
                  "Balances and raw transaction details are omitted from this aggregate report.", "",
                  "| Situation | Request | Future inflows | Pending debits | Recurring outflows | Unknown amounts |", "| --- | --- | ---: | ---: | ---: | ---: |"])
    most_expense_records = max(states, key=lambda s: len(s.required_expenses), default=None)
    reserve_states = [s for s in states if s.minimum_balance_to_keep > 0]
    lowest_balance_ratio = min(reserve_states, key=lambda s: s.available_balance / s.minimum_balance_to_keep,
                               default=None)
    predicates = {
        "normal income": lambda s: bool(s.confirmed_income),
        "largest expense history": lambda s: s is most_expense_records,
        "pending payment": lambda s: bool(s.pending_debits),
        "missing amount": lambda s: any(e.event.amount is None for e in s.events),
        "multiple currencies": lambda s: any(e.event.currency != s.currency for e in s.events),
        "flexible expense": lambda s: bool(s.flexible_expenses),
        "lowest balance/reserve ratio": lambda s: s is lowest_balance_ratio,
        "below minimum": lambda s: s.available_balance < s.minimum_balance_to_keep,
    }
    for label, predicate in predicates.items():
        match = next((s for s in states if predicate(s)), None)
        if match:
            summary = state_summary(match)
            lines.append(f"| {label} | {match.request_id} | {len(match.future_confirmed_income)} | {len(match.pending_debits)} | {len(match.recurring_outflows)} | {summary['unresolved_amounts']} |")
        else:
            lines.append(f"| {label} (not present; synthetic tests cover it) | - | - | - | - | - |")
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return states, failures
