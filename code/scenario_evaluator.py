"""Scenario and hypothetical payment evaluation engine.

Consumes Phase 4 simulate_90_days deterministically without mutating FinancialState.
"""

from datetime import date
from decimal import Decimal
import logging
from typing import List, Optional, Sequence, Union

from code.affordability_models import (
    INVALID_REQUEST,
    MISSING_FINANCIAL_STATE,
    PaymentEvaluation,
    ScenarioEvaluation,
)
from code.financial_state import FinancialState
from code.schemas import Request
from code.simulation_models import (
    PaymentInjection,
    ReduceExpense,
    StopExpense,
)
from code.simulator import Modification, simulate_90_days

logger = logging.getLogger(__name__)


def evaluate_scenario(
    financial_state: FinancialState,
    payment_events: Optional[Sequence[PaymentInjection]] = None,
    modifications: Optional[Sequence[Modification]] = None,
) -> ScenarioEvaluation:
    """Evaluate whether an arbitrary set of hypothetical modifications maintains balance invariants.

    Pure function: leaves financial_state strictly unmutated.
    """
    if financial_state is None:
        raise ValueError(f"{MISSING_FINANCIAL_STATE}: financial_state is required")

    mods: List[Modification] = []
    if payment_events:
        mods.extend(payment_events)
    if modifications:
        mods.extend(modifications)

    # Run deterministic simulation over the 90-day window
    forecast = simulate_90_days(
        financial_state,
        start_date=financial_state.request_date,
        modifications=mods,
    )

    # Invariant check: closing balance >= minimum_balance_to_keep on every single day
    min_keep = financial_state.minimum_balance_to_keep
    is_safe = forecast.invariant_ok and (forecast.minimum_observed_balance >= min_keep)
    if is_safe:
        # Extra verification pass across all daily snapshots
        for d in forecast.daily_forecasts:
            if d.closing_balance < min_keep:
                is_safe = False
                break

    return ScenarioEvaluation(
        safe=is_safe,
        minimum_balance=min_keep,
        minimum_observed_balance=forecast.minimum_observed_balance,
        minimum_headroom=forecast.minimum_headroom,
        first_breach_date=forecast.first_breach_date,
        forecast=forecast,
    )


def evaluate_full_payment(
    financial_state: FinancialState,
    request: Request,
    payment_date: date,
) -> PaymentEvaluation:
    """Evaluate a single hypothetical full payment on a specific date.

    Returns structured diagnostics and safety outcome.
    """
    if financial_state is None:
        raise ValueError(f"{MISSING_FINANCIAL_STATE}: financial_state is required")
    if request is None:
        raise ValueError(f"{INVALID_REQUEST}: request is required")
    if not isinstance(payment_date, date):
        raise ValueError("payment_date must be a valid date object")

    amount = request.requested_amount
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    if amount < Decimal("0"):
        raise ValueError(f"{INVALID_REQUEST}: requested_amount cannot be negative ({amount})")

    # Payment injection for full requested amount
    injection = PaymentInjection(
        payment_date=payment_date,
        amount=amount,
        currency=financial_state.currency,
        payment_id=f"full_payment_{request.request_id}_{payment_date.isoformat()}",
    )

    scenario = evaluate_scenario(financial_state, payment_events=[injection])

    return PaymentEvaluation(
        payment_date=payment_date,
        payment_amount=amount,
        safe=scenario.safe,
        minimum_balance_observed=scenario.minimum_observed_balance,
        minimum_headroom=scenario.minimum_headroom,
        first_breach_date=scenario.first_breach_date,
        forecast=scenario.forecast,
    )
