"""Deterministic search engine for earliest safe full-payment date.

Identifies the first date within the 90-day forecast horizon where paying
the full requested amount satisfies all balance invariants.
"""

from datetime import date, timedelta
from decimal import Decimal
import logging
from typing import Dict, Optional, Tuple

from code.affordability_models import PaymentEvaluation
from code.financial_state import FinancialState
from code.scenario_evaluator import evaluate_full_payment
from code.schemas import Request
from code.simulation_models import CashFlowForecast

logger = logging.getLogger(__name__)


def find_earliest_safe_full_payment_date(
    financial_state: FinancialState,
    request: Request,
    baseline_forecast: Optional[CashFlowForecast] = None,
    max_days: int = 90,
) -> Tuple[Optional[date], Dict[date, PaymentEvaluation]]:
    """Find the earliest calendar date on or after request_date where full payment is safe.

    Returns:
        (earliest_date, payment_evaluations_dict)
        earliest_date is None if no date within the forecast window is safe.
    """
    if financial_state is None or request is None:
        raise ValueError("financial_state and request are required")

    evaluations: Dict[date, PaymentEvaluation] = {}
    requested_amount = request.requested_amount
    if not isinstance(requested_amount, Decimal):
        requested_amount = Decimal(str(requested_amount))

    start_date = request.request_date
    end_date = start_date + timedelta(days=max_days)

    # If requested_amount is 0, check start_date immediately
    if requested_amount == Decimal("0"):
        eval_start = evaluate_full_payment(financial_state, request, start_date)
        evaluations[start_date] = eval_start
        return (start_date if eval_start.safe else None), evaluations

    # Use baseline forecast to quickly filter candidate dates
    if baseline_forecast is not None:
        daily_map = {d.forecast_date: d for d in baseline_forecast.daily_forecasts}
        first_baseline_breach = baseline_forecast.first_breach_date
    else:
        daily_map = {}
        first_baseline_breach = None

    cur_date = start_date
    one_day = timedelta(days=1)

    while cur_date <= end_date:
        # If baseline itself had a breach before cur_date, no future payment can cure it
        if first_baseline_breach is not None and cur_date > first_baseline_breach:
            break

        # Check candidate date feasibility using baseline headroom
        candidate_feasible = True
        if daily_map:
            # Check all days from cur_date through end_date
            check_date = cur_date
            while check_date <= end_date:
                daily_snap = daily_map.get(check_date)
                if daily_snap is None or daily_snap.headroom < requested_amount:
                    candidate_feasible = False
                    break
                check_date += one_day

        if candidate_feasible:
            # Run exact simulation validation with payment injection
            ev = evaluate_full_payment(financial_state, request, cur_date)
            evaluations[cur_date] = ev
            if ev.safe:
                return cur_date, evaluations

        cur_date += one_day

    return None, evaluations
