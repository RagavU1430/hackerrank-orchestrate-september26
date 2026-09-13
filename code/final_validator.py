"""Phase 9 validation for serialized submission rows.

Validation is intentionally independent of formatting code: malformed or unsafe
rows fail before output.csv is replaced.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from code.affordability_models import ALLOWED_AFFORDABILITY_STATUSES
from code.financial_agent import CustomerDecision
from code.spending_optimizer import get_eligible_spending_changes

OUTPUT_COLUMNS = (
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
)
PAYMENT_METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
PAYMENT_ENTRY = re.compile(r"^(\d{4}-\d{2}-\d{2}):([0-9]+(?:\.[0-9]{1,2})?)$")


class FinalOutputValidationError(ValueError):
    pass


def _amount(value, field):
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise FinalOutputValidationError(f"{field} is not a decimal") from exc
    if not result.is_finite() or result < 0:
        raise FinalOutputValidationError(f"{field} must be finite and nonnegative")
    return result


def _parse_plan(text):
    if text == "none":
        return []
    parts = text.split("|")
    parsed = []
    for part in parts:
        match = PAYMENT_ENTRY.fullmatch(part)
        if not match:
            raise FinalOutputValidationError(f"Invalid payment plan entry: {part!r}")
        parsed.append((date.fromisoformat(match.group(1)), _amount(match.group(2), "payment amount")))
    if parsed != sorted(parsed):
        raise FinalOutputValidationError("Payment plan is not chronological")
    return parsed


def _validate_spending(text, state):
    if text == "none":
        return
    parts = text.split("|")
    if len(parts) > 3 or len(set(parts)) != len(parts):
        raise FinalOutputValidationError("Spending changes must contain one to three unique actions")
    eligible = {}
    for change in get_eligible_spending_changes(state):
        eligible[change.to_output_str()] = change
    seen_events = set()
    for part in parts:
        change = eligible.get(part)
        if change is None:
            raise FinalOutputValidationError(f"Invalid or ineligible spending change: {part}")
        if change.event_id in seen_events:
            raise FinalOutputValidationError("An expense cannot be stopped and reduced together")
        seen_events.add(change.event_id)


def validate_decision(decision: CustomerDecision, request, state):
    """Validate one final row against the request, state and challenge contract."""
    row = decision.to_output_dict()
    if tuple(row) != OUTPUT_COLUMNS:
        raise FinalOutputValidationError("Output fields are not in the required order")
    if row["request_id"] != request.request_id:
        raise FinalOutputValidationError("Decision request mapping mismatch")
    safe = _amount(row["amount_safe_to_pay"], "amount_safe_to_pay")
    if safe > request.requested_amount:
        raise FinalOutputValidationError("amount_safe_to_pay exceeds requested amount")
    status = row["affordability_status"]
    method = row["recommended_payment_method"]
    if status not in ALLOWED_AFFORDABILITY_STATUSES or method not in PAYMENT_METHODS:
        raise FinalOutputValidationError("Unsupported status or recommended payment method")
    earliest = row["earliest_date_for_full_payment"]
    earliest_date = date.fromisoformat(earliest) if earliest else None
    if earliest_date and earliest_date < request.request_date:
        raise FinalOutputValidationError("Earliest full payment date predates request")
    plan = _parse_plan(row["payment_plan"])
    _validate_spending(row["spending_changes_needed"], state)
    if not row["decision_explanation"].strip():
        raise FinalOutputValidationError("Decision explanation is blank")
    if status == "not_affordable":
        # A future full-payment date remains a useful Phase 5 fact even when it
        # misses the request's desired completion date. It is not a payment
        # recommendation, so the plan must still be none.
        if method != "not_recommended" or plan:
            raise FinalOutputValidationError("Not-affordable row has a payment recommendation")
    elif status == "affordable_later":
        if method != "wait" or len(plan) != 1 or earliest_date is None:
            raise FinalOutputValidationError("Later-affordable row must use one wait payment")
        if plan[0] != (earliest_date, request.requested_amount):
            raise FinalOutputValidationError("Wait plan must pay requested amount on earliest date")
    elif method == "full_payment":
        if len(plan) != 1 or plan[0] != (request.request_date, request.requested_amount):
            raise FinalOutputValidationError("Full-payment plan must pay requested amount today")
    elif method == "partial_payment":
        if not request.allows_partial_payment or len(plan) != 2 or earliest_date is None:
            raise FinalOutputValidationError("Partial-payment plan is invalid")
        if plan[0] != (request.request_date, safe) or sum(amount for _, amount in plan) != request.requested_amount:
            raise FinalOutputValidationError("Partial-payment schedule does not match safe amount/request total")
        if plan[1][0] != earliest_date or not (0 < safe < request.requested_amount):
            raise FinalOutputValidationError("Partial-payment completion date or amount is invalid")
    elif method == "installments":
        if not plan:
            raise FinalOutputValidationError("Installment recommendation has no schedule")
        options = state.payment_options
        matches = []
        for option in options:
            if option.payment_method != "installments":
                continue
            expected = [(option.first_payment_date + timedelta(days=option.payment_frequency_days * i), option.payment_amount)
                        for i in range(option.number_of_payments)]
            if expected == plan:
                matches.append(option)
        if not matches:
            raise FinalOutputValidationError("Installment schedule does not match a supplied option")
    else:
        raise FinalOutputValidationError("Unsupported status/method combination")
    return row


def validate_output_rows(rows, bundle, states_by_request):
    """Validate final rows collectively; return rows in request CSV order."""
    requests = {r.request_id: r for r in bundle.requests}
    if len(rows) != len(requests):
        raise FinalOutputValidationError("Output row count does not equal evaluation request count")
    ids = [row.get("request_id") for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(requests):
        raise FinalOutputValidationError("Output request IDs are missing, duplicate, or unknown")
    normalized = []
    for raw in rows:
        if tuple(raw) != OUTPUT_COLUMNS:
            raise FinalOutputValidationError("Output CSV columns do not exactly match the contract")
        request = requests[raw["request_id"]]
        state = states_by_request[request.request_id]
        decision = CustomerDecision(
            request_id=raw["request_id"], amount_safe_to_pay=_amount(raw["amount_safe_to_pay"], "amount_safe_to_pay"),
            affordability_status=raw["affordability_status"], recommended_payment_method=raw["recommended_payment_method"],
            payment_plan=raw["payment_plan"], earliest_date_for_full_payment=date.fromisoformat(raw["earliest_date_for_full_payment"]) if raw["earliest_date_for_full_payment"] else None,
            spending_changes_needed=raw["spending_changes_needed"], decision_explanation=raw["decision_explanation"], evidence_summary=[], warnings=[],
        )
        normalized.append(validate_decision(decision, request, state))
    return normalized
