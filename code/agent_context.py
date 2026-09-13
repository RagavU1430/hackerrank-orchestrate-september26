"""Phase 8 Agent Context Aggregator.

Unified structured factual context connecting deterministic engines (Phases 1-7).
Strictly separates verified facts from LLM interpretation.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from code.affordability import evaluate_affordability
from code.financial_state import FinancialState
from code.payment_models import PaymentPlan
from code.schemas import FinancialProfile, Request
from code.simulator import simulate_90_days
from code.spending_models import SpendingChange, SpendingOptimizationResult
from code.spending_optimizer import SpendingOptimizer
from code.state_builder import build_financial_state


@dataclass(frozen=True)
class EvidenceSummary:
    """A grounded piece of evidence used in the decision."""

    source_id: str
    source_type: str  # image | message | event
    field: str
    value: Any
    effective_date: Optional[date]
    confidence: str
    description: str


@dataclass
class AgentContext:
    """Unified factual context consumed by the AI Financial Agent."""

    request_id: str
    user_id: str
    request_date: date
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool

    # Financial State (Phase 2)
    home_currency: str
    current_balance: Decimal
    minimum_reserve: Decimal
    expense_categories_to_protect: Tuple[str, ...]
    expense_categories_willing_to_stop: Tuple[str, ...]
    expense_categories_willing_to_reduce: Tuple[str, ...]
    payment_methods_considered: Tuple[str, ...]

    # Affordability Decision (Phase 5)
    affordability_status: str
    amount_safe_to_pay: Decimal
    earliest_full_payment_date: Optional[date]

    # Payment Plan & Spending Adjustment (Phase 6 & 7)
    recommended_payment_method: str
    selected_plan: Optional[PaymentPlan]
    spending_changes_needed: str  # e.g. "stop:event_476" or "none"
    spending_changes: Tuple[SpendingChange, ...]
    total_cost: Decimal

    # Cash Flow Forecast Diagnostics (Phase 4)
    critical_date: Optional[date]  # minimum balance date
    minimum_balance_observed: Decimal
    minimum_headroom: Decimal
    first_breach_date: Optional[date]

    # Evidence & Provenance (Phase 3)
    evidence_summaries: List[EvidenceSummary] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Compact serialized factual representation for LLM and SafetyGuard."""
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "request_date": self.request_date.isoformat(),
            "financials": {
                "currency": self.home_currency,
                "current_balance": str(self.current_balance),
                "minimum_reserve": str(self.minimum_reserve),
                "requested_amount": str(self.requested_amount),
                "safe_to_pay": str(self.amount_safe_to_pay),
            },
            "decision": {
                "affordability_status": self.affordability_status,
                "recommended_payment_method": self.recommended_payment_method,
                "earliest_full_payment_date": (
                    self.earliest_full_payment_date.isoformat()
                    if self.earliest_full_payment_date
                    else "none"
                ),
                "desired_completion_date": self.desired_completion_date.isoformat(),
                "total_cost": str(self.total_cost),
            },
            "payment_plan": {
                "method": self.recommended_payment_method,
                "type": (
                    self.selected_plan.plan_type.name
                    if self.selected_plan
                    else "NONE"
                ),
                "payments": [
                    {
                        "date": p.event_date.isoformat(),
                        "amount": str(p.amount),
                        "description": p.description,
                    }
                    for p in self.selected_plan.payments
                ]
                if self.selected_plan
                else [],
                "number_of_payments": (
                    self.selected_plan.number_of_payments
                    if self.selected_plan
                    else 0
                ),
            },
            "spending_changes": {
                "needed": self.spending_changes_needed,
                "items": [
                    {
                        "event_id": c.event_id,
                        "action": c.action.value,
                        "category": c.category,
                        "target_amount": (
                            str(c.target_amount)
                            if c.target_amount is not None
                            else None
                        ),
                    }
                    for c in self.spending_changes
                ],
            },
            "forecast_diagnostics": {
                "critical_date": (
                    self.critical_date.isoformat() if self.critical_date else None
                ),
                "minimum_balance_observed": str(self.minimum_balance_observed),
                "minimum_headroom": str(self.minimum_headroom),
                "first_breach_date": (
                    self.first_breach_date.isoformat()
                    if self.first_breach_date
                    else None
                ),
            },
            "evidence": [
                {
                    "source_id": e.source_id,
                    "source_type": e.source_type,
                    "field": e.field,
                    "value": str(e.value),
                    "effective_date": (
                        e.effective_date.isoformat() if e.effective_date else None
                    ),
                    "confidence": e.confidence,
                    "description": e.description,
                }
                for e in self.evidence_summaries
            ],
            "warnings": self.warnings,
        }


def build_agent_context(
    bundle, request_id: str, financial_state: Optional[FinancialState] = None
) -> AgentContext:
    """Assemble the unified AgentContext from Phases 1-7 deterministic engines."""
    req = next((r for r in bundle.requests if r.request_id == request_id), None)
    if not req and hasattr(bundle, "sample_requests"):
        req = next(
            (r for r in bundle.sample_requests if r.request_id == request_id),
            None,
        )
    if not req:
        raise ValueError(f"Request '{request_id}' not found in bundle")

    profile = next(p for p in bundle.profiles if p.user_id == req.user_id)
    state = financial_state or build_financial_state(bundle, req)
    if state.request_id != req.request_id or state.user_id != req.user_id:
        raise ValueError("Provided financial state does not match agent request")

    # Phase 4 Baseline Forecast
    baseline_forecast = simulate_90_days(state, start_date=req.request_date)

    # Phase 5 Affordability Decision
    affordability = evaluate_affordability(state, req)

    # Phase 7 Spending Optimization (which wraps Phase 6 Payment Optimization)
    spending_opt = SpendingOptimizer(bundle)
    opt_result: SpendingOptimizationResult = spending_opt.optimize_spending(request_id, state)

    selected_plan = (
        opt_result.selected_scenario.payment_plan
        if opt_result.selected_scenario
        else None
    )
    spending_changes = (
        opt_result.selected_scenario.spending_changes.changes
        if opt_result.selected_scenario
        else ()
    )
    total_cost = (
        selected_plan.total_paid
        if selected_plan
        else req.requested_amount
    )

    # Gather evidence summaries from state
    evidence_summaries: List[EvidenceSummary] = []
    for upd in state.evidence_updates:
        evidence_summaries.append(
            EvidenceSummary(
                source_id=upd.source_id,
                source_type=upd.source_type,
                field=upd.field,
                value=upd.new_value,
                effective_date=upd.effective_date,
                confidence=upd.confidence,
                description=f"{upd.source_type} {upd.source_id} updated {upd.field} to {upd.new_value}",
            )
        )

    # Warnings from state and forecast
    warnings = [w.detail for w in state.warnings] + [
        w.detail for w in baseline_forecast.warnings
    ]

    return AgentContext(
        request_id=req.request_id,
        user_id=req.user_id,
        request_date=req.request_date,
        requested_amount=req.requested_amount,
        desired_completion_date=req.desired_completion_date,
        allows_partial_payment=req.allows_partial_payment,
        home_currency=profile.home_currency,
        current_balance=profile.current_available_balance,
        minimum_reserve=profile.minimum_balance_to_keep,
        expense_categories_to_protect=tuple(profile.expense_categories_to_protect),
        expense_categories_willing_to_stop=tuple(
            profile.expense_categories_user_is_willing_to_stop
        ),
        expense_categories_willing_to_reduce=tuple(
            profile.expense_categories_user_is_willing_to_reduce
        ),
        payment_methods_considered=tuple(
            profile.payment_methods_user_will_consider
        ),
        affordability_status=opt_result.affordability_status,
        amount_safe_to_pay=affordability.amount_safe_to_pay,
        earliest_full_payment_date=affordability.earliest_date_for_full_payment,
        recommended_payment_method=opt_result.recommended_payment_method,
        selected_plan=selected_plan,
        spending_changes_needed=opt_result.spending_changes_needed,
        spending_changes=spending_changes,
        total_cost=total_cost,
        critical_date=baseline_forecast.minimum_balance_date,
        minimum_balance_observed=baseline_forecast.minimum_observed_balance,
        minimum_headroom=baseline_forecast.minimum_headroom,
        first_breach_date=baseline_forecast.first_breach_date,
        evidence_summaries=evidence_summaries,
        warnings=warnings,
    )
