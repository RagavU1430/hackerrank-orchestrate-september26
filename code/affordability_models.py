"""Phase 5 domain models and value objects for Affordability Decision Engine.

All monetary amounts use Decimal. All models are immutable dataclasses.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from code.simulation_models import CashFlowForecast


# Challenge-defined status values
AFFORDABLE_NOW = "affordable_now"
AFFORDABLE_WITH_PLAN = "affordable_with_plan"
AFFORDABLE_LATER = "affordable_later"
NOT_AFFORDABLE = "not_affordable"

ALLOWED_AFFORDABILITY_STATUSES = {
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    AFFORDABLE_LATER,
    NOT_AFFORDABLE,
}

# Standard error categories
INVALID_REQUEST = "INVALID_REQUEST"
MISSING_FINANCIAL_STATE = "MISSING_FINANCIAL_STATE"
INVALID_FINANCIAL_STATE = "INVALID_FINANCIAL_STATE"
SIMULATION_ERROR = "SIMULATION_ERROR"
MISSING_REQUIRED_CURRENCY_CONVERSION = "MISSING_REQUIRED_CURRENCY_CONVERSION"
INSUFFICIENT_FORECAST = "INSUFFICIENT_FORECAST"
DATA_QUALITY_WARNING = "DATA_QUALITY_WARNING"


@dataclass(frozen=True)
class PaymentEvaluation:
    """Diagnostic outcome of evaluating a single payment on a specific date."""

    payment_date: date
    payment_amount: Decimal
    safe: bool
    minimum_balance_observed: Decimal
    minimum_headroom: Decimal
    first_breach_date: Optional[date]
    forecast: CashFlowForecast


@dataclass(frozen=True)
class ScenarioEvaluation:
    """Safety evaluation of an arbitrary set of hypothetical payment events."""

    safe: bool
    minimum_balance: Decimal
    minimum_observed_balance: Decimal
    minimum_headroom: Decimal
    first_breach_date: Optional[date]
    forecast: CashFlowForecast


@dataclass(frozen=True)
class DecisionDiagnostics:
    """Structured, deterministic financial facts explaining the decision."""

    requested_amount: Decimal
    safe_amount: Decimal
    minimum_reserve: Decimal
    minimum_baseline_balance: Decimal
    minimum_baseline_headroom: Decimal
    first_baseline_breach: Optional[date]
    full_payment_safe: bool
    earliest_safe_date: Optional[date]
    is_fully_affordable: bool
    is_partially_affordable: bool
    is_future_affordable: bool
    is_not_affordable_now: bool
    breach_reasons: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AffordabilityDecision:
    """Core result of Phase 5 Affordability Decision Engine."""

    request_id: str
    user_id: str
    requested_amount: Decimal
    amount_safe_to_pay: Decimal
    affordability_status: str
    earliest_date_for_full_payment: Optional[date]
    baseline_forecast: CashFlowForecast
    payment_evaluations: Dict[date, PaymentEvaluation]
    decision_diagnostics: DecisionDiagnostics

    def __post_init__(self):
        if not isinstance(self.amount_safe_to_pay, Decimal):
            raise TypeError("amount_safe_to_pay must be a Decimal")
        if not (Decimal("0") <= self.amount_safe_to_pay <= self.requested_amount):
            raise ValueError(
                f"Invariant violation: amount_safe_to_pay ({self.amount_safe_to_pay}) "
                f"must be between 0 and requested_amount ({self.requested_amount})"
            )
        if self.affordability_status not in ALLOWED_AFFORDABILITY_STATUSES:
            raise ValueError(f"Invalid affordability_status: {self.affordability_status}")
