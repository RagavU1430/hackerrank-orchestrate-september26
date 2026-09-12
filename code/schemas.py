"""Domain schemas and typed models for Buy or Wait?

All monetary amounts are represented as Decimal to prevent floating-point
inaccuracies. Missing and blank amounts are explicitly preserved as None.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Optional


@dataclass(frozen=True)
class FinancialProfile:
    """User financial profile, balances, preferences, and priorities."""

    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: List[str]
    expense_categories_to_protect: List[str]
    expense_categories_user_is_willing_to_reduce: List[str]
    expense_categories_user_is_willing_to_stop: List[str]
    payment_methods_user_will_consider: List[str]
    max_installment_months: Optional[int]


@dataclass(frozen=True)
class FinancialEvent:
    """Historical, pending, scheduled, settled, or non-cash financial transaction."""

    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str  # debit | credit | non_cash
    amount: Optional[Decimal]  # None if blank/requires image extraction
    currency: str
    event_date: date
    settlement_date: Optional[date]  # None for unrealized investments
    status: str  # settled | pending | scheduled | cancelled | failed | unrealized
    linked_event_id: Optional[str]
    flexibility: str  # fixed | stoppable | reducible | reducible_or_stoppable
    minimum_allowed_amount: Optional[Decimal]


@dataclass(frozen=True)
class Request:
    """Evaluation request from dataset/requests.csv."""

    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class SampleRequest(Request):
    """Ground-truth sample request from dataset/sample_requests.csv."""

    amount_safe_to_pay: Decimal = Decimal(0)
    affordability_status: str = ""
    recommended_payment_method: str = ""
    payment_plan: str = ""
    earliest_date_for_full_payment: Optional[date] = None
    spending_changes_needed: str = ""
    decision_explanation: str = ""


@dataclass(frozen=True)
class PaymentOption:
    """Seller or provider payment terms for a purchase request."""

    payment_option_id: str
    request_id: str
    payment_method: str  # full_payment | installments
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]  # None for single full payment
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass(frozen=True)
class ExchangeRate:
    """Dated exchange rate between two currencies."""

    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class Message:
    """Unstructured notification from employer, bank, merchant, or service provider."""

    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: datetime
    source_type: str  # employer | service_provider | bank | merchant | financial_service
    message_text: str


@dataclass(frozen=True)
class ImageReference:
    """Image metadata and file-system reference."""

    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    file_path: Path
    file_exists: bool
    file_size_bytes: int


@dataclass(frozen=True)
class EvidenceReference:
    """Dynamically detected financial event with missing amount requiring image extraction."""

    event_id: str
    user_id: str
    image_id: str
    image_path: Path
    amount_status: str = "requires_extraction"
    event_type: str = ""
    category: str = ""
    event_date: Optional[date] = None


@dataclass
class DatasetBundle:
    """Single central container holding all normalized dataset records, indexes,

    and validation results for consumption by all system phases.
    """

    requests: List[Request] = field(default_factory=list)
    sample_requests: List[SampleRequest] = field(default_factory=list)
    profiles: List[FinancialProfile] = field(default_factory=list)
    events: List[FinancialEvent] = field(default_factory=list)
    payment_options: List[PaymentOption] = field(default_factory=list)
    exchange_rates: List[ExchangeRate] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    images: List[ImageReference] = field(default_factory=list)
    evidence_queue: List[EvidenceReference] = field(default_factory=list)
    indexes: Any = None
    validation_report: Any = None
