"""Deterministic Affordability Decision Engine.

Coordinates baseline cash-flow forecasting, available safe headroom calculation,
hypothetical payment validation, earliest full-payment date search, and structured diagnostics.
"""

from datetime import date
from decimal import Decimal
import logging
from typing import Dict, List, Optional

from code.affordability_models import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    NOT_AFFORDABLE,
    AffordabilityDecision,
    DecisionDiagnostics,
    INVALID_REQUEST,
    MISSING_FINANCIAL_STATE,
    PaymentEvaluation,
)
from code.date_search import find_earliest_safe_full_payment_date
from code.financial_state import FinancialState
from code.schemas import Request
from code.simulation_models import CashFlowForecast
from code.simulator import simulate_90_days

logger = logging.getLogger(__name__)


def calculate_amount_safe_to_pay(
    financial_state: FinancialState,
    request: Request,
    baseline_forecast: Optional[CashFlowForecast] = None,
) -> Decimal:
    """Calculate the maximum amount safe to pay on request_date.

    Constrained by the minimum headroom across the 90-day forecast:
        amount_safe_to_pay = max(0, min(requested_amount, minimum_headroom_over_forecast))
    """
    if financial_state is None:
        raise ValueError(f"{MISSING_FINANCIAL_STATE}: financial_state is required")
    if request is None:
        raise ValueError(f"{INVALID_REQUEST}: request is required")

    requested_amount = request.requested_amount
    if not isinstance(requested_amount, Decimal):
        requested_amount = Decimal(str(requested_amount))
    if requested_amount < Decimal("0"):
        raise ValueError(f"{INVALID_REQUEST}: requested_amount cannot be negative ({requested_amount})")

    if baseline_forecast is None:
        baseline_forecast = simulate_90_days(financial_state, start_date=request.request_date)

    min_headroom = baseline_forecast.minimum_headroom

    # Must be bounded within [0, requested_amount]
    amount_safe = max(Decimal("0"), min(requested_amount, min_headroom))
    return amount_safe


def evaluate_affordability(
    financial_state: FinancialState,
    request: Optional[Request] = None,
) -> AffordabilityDecision:
    """Run full deterministic affordability analysis for a request.

    Consumes FinancialState, runs Phase 4 simulation, determines safe amount,
    earliest full payment date, and challenge affordability status.
    """
    if financial_state is None:
        raise ValueError(f"{MISSING_FINANCIAL_STATE}: financial_state is required")
    if request is None:
        request = financial_state.request
    if request is None:
        raise ValueError(f"{INVALID_REQUEST}: request is missing from financial state")

    requested_amount = request.requested_amount
    if not isinstance(requested_amount, Decimal):
        requested_amount = Decimal(str(requested_amount))
    if requested_amount < Decimal("0"):
        raise ValueError(f"{INVALID_REQUEST}: requested_amount cannot be negative ({requested_amount})")

    # 1. Baseline 90-day forecast (unmodified financial state)
    baseline_forecast = simulate_90_days(financial_state, start_date=request.request_date)

    # 2. Compute amount safe to pay today
    amount_safe_to_pay = calculate_amount_safe_to_pay(financial_state, request, baseline_forecast)

    # 3. Search for earliest safe full-payment date
    earliest_safe_date, payment_evaluations = find_earliest_safe_full_payment_date(
        financial_state,
        request,
        baseline_forecast=baseline_forecast,
    )

    # 4. Determine challenge affordability status
    # Full payment safe on request_date
    is_safe_today = (earliest_safe_date == request.request_date)

    considered_methods = set(financial_state.profile.payment_methods_user_will_consider)
    user_accepts_full_payment = "full_payment" in considered_methods

    if is_safe_today:
        if user_accepts_full_payment:
            status = AFFORDABLE_NOW
        else:
            status = AFFORDABLE_WITH_PLAN
    elif earliest_safe_date is not None:
        status = AFFORDABLE_LATER
    else:
        status = NOT_AFFORDABLE

    # 5. Compile rich deterministic diagnostics
    reasons: List[str] = []
    if baseline_forecast.first_breach_date is not None:
        reasons.append(
            f"Baseline balance breaches reserve on {baseline_forecast.first_breach_date.isoformat()}"
        )
    if not is_safe_today and requested_amount > Decimal("0"):
        reasons.append(
            f"Full requested amount ({requested_amount} {financial_state.currency}) exceeds "
            f"minimum available headroom ({baseline_forecast.minimum_headroom} {financial_state.currency})"
        )
    if earliest_safe_date is not None and earliest_safe_date > request.request_date:
        reasons.append(
            f"Full payment becomes safe on {earliest_safe_date.isoformat()} once sufficient headroom accumulates"
        )
    elif earliest_safe_date is None:
        reasons.append("Full payment cannot be safely completed within the 90-day forecast period")

    diagnostics = DecisionDiagnostics(
        requested_amount=requested_amount,
        safe_amount=amount_safe_to_pay,
        minimum_reserve=financial_state.minimum_balance_to_keep,
        minimum_baseline_balance=baseline_forecast.minimum_observed_balance,
        minimum_baseline_headroom=baseline_forecast.minimum_headroom,
        first_baseline_breach=baseline_forecast.first_breach_date,
        full_payment_safe=is_safe_today,
        earliest_safe_date=earliest_safe_date,
        is_fully_affordable=(amount_safe_to_pay == requested_amount),
        is_partially_affordable=(Decimal("0") < amount_safe_to_pay < requested_amount),
        is_future_affordable=(earliest_safe_date is not None and earliest_safe_date > request.request_date),
        is_not_affordable_now=(amount_safe_to_pay == Decimal("0")),
        breach_reasons=tuple(reasons),
    )

    decision = AffordabilityDecision(
        request_id=request.request_id,
        user_id=request.user_id,
        requested_amount=requested_amount,
        amount_safe_to_pay=amount_safe_to_pay,
        affordability_status=status,
        earliest_date_for_full_payment=earliest_safe_date,
        baseline_forecast=baseline_forecast,
        payment_evaluations=payment_evaluations,
        decision_diagnostics=diagnostics,
    )

    logger.info(
        "Affordability %s: amount_safe=%s, status=%s, earliest=%s",
        decision.request_id,
        decision.amount_safe_to_pay,
        decision.affordability_status,
        decision.earliest_date_for_full_payment,
    )

    return decision
