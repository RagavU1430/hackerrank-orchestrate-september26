"""Phase 4 simulation value objects.

Deterministic 90-day cash-flow forecast models.
All monetary values use Decimal. No LLM arithmetic.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class PaymentInjection:
    """Hypothetical additional payment to evaluate."""

    payment_date: date
    amount: Decimal
    currency: Optional[str] = None
    payment_id: str = "hypothetical"


@dataclass(frozen=True)
class StopExpense:
    """Stop a future flexible expense."""

    target_id: str  # event_id or recurrence_id


@dataclass(frozen=True)
class ReduceExpense:
    """Reduce a future flexible expense to a new home-currency amount."""

    target_id: str
    new_amount: Decimal


@dataclass(frozen=True)
class LedgerEntry:
    """One cash flow entry on a specific date."""

    entry_id: str
    source_type: str  # event | recurrence | payment_injection
    source_id: str
    category: str
    direction: str  # credit | debit
    original_amount: Optional[Decimal]
    original_currency: str
    normalized_amount: Optional[Decimal]
    normalized_currency: str
    exchange_rate_used: Optional[Decimal]
    exchange_rate_date: Optional[date]
    amount_status: str


@dataclass(frozen=True)
class DailyForecast:
    """One calendar day snapshot."""

    forecast_date: date
    opening_balance: Decimal
    inflows: Tuple[LedgerEntry, ...]
    outflows: Tuple[LedgerEntry, ...]
    total_inflows: Decimal
    total_outflows: Decimal
    net_change: Decimal
    closing_balance: Decimal
    minimum_balance: Decimal
    headroom: Decimal
    invariant_ok: bool


@dataclass(frozen=True)
class ForecastWarning:
    kind: str
    code: str
    source_id: str
    detail: str


@dataclass(frozen=True)
class CashFlowForecast:
    """90-day forecast result. Immutable."""

    user_id: str
    request_id: str
    start_date: date
    end_date: date
    starting_balance: Decimal
    ending_balance: Decimal
    minimum_balance: Decimal
    minimum_balance_date: Optional[date]
    minimum_observed_balance: Decimal
    minimum_headroom: Decimal
    first_breach_date: Optional[date]
    total_inflows: Decimal
    total_outflows: Decimal
    daily_forecasts: Tuple[DailyForecast, ...]
    warnings: Tuple[ForecastWarning, ...]
    invariant_ok: bool

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1
