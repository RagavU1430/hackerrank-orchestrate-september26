from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum, auto
from typing import List, Optional

class PlanType(Enum):
    FULL_PAYMENT = auto()
    PARTIAL_PAYMENT = auto()
    INSTALLMENT = auto()

@dataclass(frozen=True)
class PaymentEvent:
    event_date: date
    amount: Decimal
    description: str

@dataclass
class PaymentPlan:
    request_id: str
    payment_option_id: Optional[str]
    plan_type: PlanType
    payment_method: str
    payments: List[PaymentEvent]
    total_paid: Decimal
    fees: Decimal
    interest: Decimal
    
    # Validation and Safety results
    is_safe: bool = False
    completes_by_deadline: bool = False
    accepted_method: bool = False
    rejection_reason: Optional[str] = None
    
    # Diagnostics from Phase 4 Simulator
    min_balance_observed: Optional[Decimal] = None
    first_breach_date: Optional[date] = None
    min_headroom: Optional[Decimal] = None

    @property
    def first_payment_date(self) -> Optional[date]:
        return self.payments[0].event_date if self.payments else None

    @property
    def last_payment_date(self) -> Optional[date]:
        return self.payments[-1].event_date if self.payments else None

    @property
    def number_of_payments(self) -> int:
        return len(self.payments)
