"""Phase 2 value objects. Money stays Decimal; unknown money stays None."""

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from code.schemas import FinancialEvent, FinancialProfile, PaymentOption, Request


@dataclass(frozen=True)
class StateWarning:
    kind: str  # DATASET ISSUE | UNRESOLVED EVIDENCE
    code: str
    source_id: str
    detail: str


@dataclass(frozen=True)
class Provenance:
    source_type: str
    source_id: str
    field: str
    effective_date: Optional[date]
    confidence: str


@dataclass(frozen=True)
class Money:
    original_amount: Optional[Decimal]
    original_currency: str
    normalized_amount: Optional[Decimal]
    normalized_currency: str
    exchange_rate_used: Optional[Decimal]
    exchange_rate_date: Optional[date]
    amount_status: str  # known | unresolved_amount | unresolved_currency | unresolved_rate


@dataclass(frozen=True)
class EventState:
    event: FinancialEvent
    money: Money
    temporal_status: str
    cash_class: str
    forecast_date: Optional[date]
    protected: bool
    can_reduce: bool
    can_stop: bool
    superseded_by: Optional[str]
    provenance: tuple[Provenance, ...]

    @property
    def event_id(self) -> str:
        return self.event.event_id


@dataclass(frozen=True)
class Recurrence:
    recurrence_id: str
    event_id: str
    source_event_ids: tuple[str, ...]
    category: str
    direction: str
    currency: str
    amount: Optional[Decimal]
    amount_policy: str
    cadence: str  # calendar_months | fixed_days
    interval: int
    anchor_date: date
    next_expected_date: date
    end_date: Optional[date]
    confidence: str
    active: bool
    protected: bool
    can_reduce: bool
    can_stop: bool
    minimum_allowed_amount: Optional[Decimal]
    explicit_occurrence_dates: tuple[date, ...]
    provenance: tuple[Provenance, ...]


@dataclass(frozen=True)
class EvidenceUpdate:
    """Typed facts supplied by Phase 3, never raw instructions.

    target_type is event or recurrence. operation is resolve, amend, or add.
    add requires a FinancialEvent in new_value and field='event'. Recurrences
    accept amount/end_date. Event fields are explicitly allowlisted by evidence.py.
    observed_date is when the fact became known; effective_date is when it applies.
    """

    source_type: str
    source_id: str
    target_type: str
    target_id: str
    field: str
    new_value: Any
    effective_date: date
    observed_date: date
    confidence: str = "confirmed"
    operation: str = "resolve"
    old_value: Any = None


@dataclass(frozen=True)
class EvidenceMetadata:
    source_type: str
    source_id: str
    related_event_id: Optional[str]
    observed_date: Optional[date]
    status: str


@dataclass(frozen=True)
class FinancialState:
    request: Request
    profile: FinancialProfile
    events: tuple[EventState, ...]
    recurrences: tuple[Recurrence, ...]
    payment_options: tuple[PaymentOption, ...]
    evidence: tuple[EvidenceMetadata, ...]
    evidence_updates: tuple[EvidenceUpdate, ...]
    warnings: tuple[StateWarning, ...]
    # Rebuild context enables evidence application without reopening CSVs. It is
    # deliberately omitted from snapshots, which also exclude free-text fields.
    source_events: tuple[FinancialEvent, ...] = field(repr=False)
    exchange_rates: dict = field(repr=False)

    @property
    def request_id(self):
        return self.request.request_id

    @property
    def user_id(self):
        return self.request.user_id

    @property
    def request_date(self):
        return self.request.request_date

    @property
    def currency(self):
        return self.profile.home_currency

    @property
    def available_balance(self):
        return self.profile.current_available_balance

    @property
    def minimum_balance_to_keep(self):
        return self.profile.minimum_balance_to_keep

    def cash_items(self, *classes):
        return tuple(e for e in self.events if e.cash_class in classes)

    @property
    def confirmed_income(self):
        return self.cash_items("settled_income")

    @property
    def future_confirmed_income(self):
        return self.cash_items("confirmed_future_income")

    @property
    def pending_income(self):
        return self.cash_items("pending_income")

    @property
    def uncertain_income(self):
        return self.cash_items("uncertain_income", "non_cash")

    @property
    def pending_debits(self):
        return self.cash_items("pending_debit")

    @property
    def scheduled_debits(self):
        return self.cash_items("scheduled_debit", "unsettled_debit")

    @property
    def required_future_outflows(self):
        # All cash commitments remain in the baseline, including optional ones.
        return self.pending_debits + self.scheduled_debits

    @property
    def required_expenses(self):
        return tuple(e for e in self.events if e.event.direction == "debit"
                     and e.cash_class not in {"excluded", "superseded", "not_yet_known"})

    @property
    def flexible_expenses(self):
        # Only history-supported recurring expenses may eventually be changed.
        return tuple(r for r in self.recurrences if r.active and (r.can_reduce or r.can_stop))

    @property
    def recurring_inflows(self):
        return tuple(r for r in self.recurrences if r.direction == "credit" and r.active)

    @property
    def recurring_outflows(self):
        return tuple(r for r in self.recurrences if r.direction == "debit" and r.active)


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def state_snapshot(state: FinancialState) -> dict:
    """Diagnostic data only: no message text, paths, descriptions, or raw bundle."""
    events = []
    for item in state.events:
        row = json_value(item)
        row["event"].pop("description")
        events.append(row)
    return {
        "request": {k: json_value(v) for k, v in asdict(state.request).items()
                    if k != "request_text"},
        "profile": json_value(state.profile),
        "events": events,
        "recurrences": json_value(state.recurrences),
        "evidence": json_value(state.evidence),
        "evidence_updates": [{k: json_value(v) for k, v in asdict(u).items()
                              if k not in {"new_value", "old_value"}}
                             for u in state.evidence_updates],
        "warnings": json_value(state.warnings),
    }
