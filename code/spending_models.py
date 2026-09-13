"""Phase 7 spending adjustment value objects and data structures.

All monetary amounts are represented as Decimal.
Deterministic optimization without LLM decision making.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from code.payment_models import PaymentPlan
from code.simulation_models import CashFlowForecast


class SpendingAction(str, Enum):
    STOP = "stop"
    REDUCE = "reduce_to"


@dataclass(frozen=True)
class SpendingChange:
    """A single spending modification on an eligible financial event."""

    event_id: str
    action: SpendingAction
    category: str
    target_amount: Optional[Decimal] = None  # None for STOP, minimum_allowed_amount for REDUCE
    original_amount: Optional[Decimal] = None

    def to_output_str(self) -> str:
        """Format as challenge spec: stop:<event_id> or reduce_to:<event_id>:<new_amount>"""
        if self.action == SpendingAction.STOP:
            return f"stop:{self.event_id}"
        elif self.action == SpendingAction.REDUCE:
            if self.target_amount is None:
                raise ValueError(f"Reduce action for {self.event_id} missing target_amount")
            # Format integer as int string, fractional decimal as 2 decimal places
            if self.target_amount == self.target_amount.to_integral_value():
                amt_str = str(int(self.target_amount))
            else:
                amt_str = f"{self.target_amount:.2f}"
            return f"reduce_to:{self.event_id}:{amt_str}"
        raise ValueError(f"Unknown action: {self.action}")


@dataclass(frozen=True)
class SpendingChangeSet:
    """A combination of up to 3 spending changes."""

    changes: Tuple[SpendingChange, ...] = field(default_factory=tuple)

    @property
    def num_changes(self) -> int:
        return len(self.changes)

    def to_output_str(self) -> str:
        if not self.changes:
            return "none"
        return "|".join(c.to_output_str() for c in self.changes)


@dataclass
class DecisionScenario:
    """A complete evaluated scenario: PaymentPlan + SpendingChangeSet + Simulation Results."""

    request_id: str
    payment_plan: Optional[PaymentPlan]
    spending_changes: SpendingChangeSet

    # Feasibility and safety
    is_safe: bool = False
    completes_by_deadline: bool = False

    # Financial metrics
    min_balance_observed: Optional[Decimal] = None
    min_headroom: Optional[Decimal] = None
    first_breach_date: Optional[date] = None
    total_paid: Decimal = Decimal("0")
    projected_savings: Decimal = Decimal("0")

    # Diagnostics
    rejection_reason: Optional[str] = None


@dataclass
class SpendingOptimizationResult:
    """Final result of Phase 7 spending optimization for a request."""

    request_id: str
    selected_scenario: Optional[DecisionScenario]
    spending_changes_needed: str  # e.g. "stop:event_476" or "none"
    affordability_status: str  # "affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"
    recommended_payment_method: str  # "full_payment", "installments", "partial_payment", "wait", "not_recommended"
    has_spending_changes: bool
    num_spending_changes: int
    diagnostics: Dict[str, Any] = field(default_factory=dict)
