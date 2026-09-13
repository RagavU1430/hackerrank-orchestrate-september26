"""Phase 8 Customer-Facing AI Financial Agent & Explainable Decision Layer.

Orchestrates deterministic results from Phases 1-7, verifies claims with SafetyGuard,
serves conversational explanations, and deterministically routes hypothetical simulations.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from code.agent_context import AgentContext, build_agent_context
from code.explanation_engine import ExplanationModel
from code.payment_models import PaymentPlan
from code.safety_guard import SafetyGuard, _format_date, _format_money
from code.simulation_models import PaymentInjection
from code.simulator import simulate_90_days
from code.state_builder import build_financial_state

logger = logging.getLogger(__name__)


def format_payment_plan(
    affordability_status: str,
    recommended_payment_method: str,
    selected_plan: Optional[PaymentPlan],
    request_date: date,
    requested_amount: Decimal,
    safe_amount: Decimal,
    earliest_full_payment_date: Optional[date],
) -> str:
    """Format payment_plan string according to challenge specification."""
    if (
        recommended_payment_method in ("not_recommended", "none")
        or affordability_status == "not_affordable"
    ):
        return "none"

    if (
        recommended_payment_method == "wait"
        or affordability_status == "affordable_later"
    ):
        if earliest_full_payment_date:
            amt_str = (
                str(int(requested_amount))
                if requested_amount == requested_amount.to_integral_value()
                else f"{requested_amount:.2f}"
            )
            return f"{earliest_full_payment_date.isoformat()}:{amt_str}"
        return "none"

    if selected_plan and selected_plan.payments:
        parts = []
        for p in selected_plan.payments:
            amt_str = (
                str(int(p.amount))
                if p.amount == p.amount.to_integral_value()
                else f"{p.amount:.2f}"
            )
            parts.append(f"{p.event_date.isoformat()}:{amt_str}")
        return "|".join(parts)

    if recommended_payment_method == "full_payment":
        amt_str = (
            str(int(requested_amount))
            if requested_amount == requested_amount.to_integral_value()
            else f"{requested_amount:.2f}"
        )
        return f"{request_date.isoformat()}:{amt_str}"

    if recommended_payment_method == "partial_payment":
        if earliest_full_payment_date and safe_amount > Decimal("0"):
            rem = requested_amount - safe_amount
            s_str = (
                str(int(safe_amount))
                if safe_amount == safe_amount.to_integral_value()
                else f"{safe_amount:.2f}"
            )
            r_str = (
                str(int(rem))
                if rem == rem.to_integral_value()
                else f"{rem:.2f}"
            )
            return f"{request_date.isoformat()}:{s_str}|{earliest_full_payment_date.isoformat()}:{r_str}"

    return "none"


@dataclass(frozen=True)
class CustomerDecision:
    """Final internal decision object consumed by API and output mapping."""

    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str
    decision_explanation: str
    evidence_summary: List[str]
    warnings: List[str]

    def to_output_dict(self) -> Dict[str, str]:
        """Convert to exact challenge output.csv schema."""
        safe_str = (
            str(int(self.amount_safe_to_pay))
            if self.amount_safe_to_pay == self.amount_safe_to_pay.to_integral_value()
            else f"{self.amount_safe_to_pay:.2f}"
        )
        earliest_str = (
            self.earliest_date_for_full_payment.isoformat()
            if self.earliest_date_for_full_payment
            else ""
        )
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": safe_str,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": earliest_str,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


class FinancialAgent:
    """Phase 8 AI Financial Decision Agent & Interaction Layer."""

    def __init__(self, dataset_bundle, model: Optional[ExplanationModel] = None, evidence_bundle=None):
        self.bundle = dataset_bundle
        self.model = model or ExplanationModel()
        self.evidence_bundle = evidence_bundle
        self._context_cache: Dict[str, AgentContext] = {}

    def get_context(self, request_id: str, financial_state=None) -> AgentContext:
        """Retrieve or build deterministic AgentContext with request isolation."""
        if financial_state is not None:
            return build_agent_context(self.bundle, request_id, financial_state=financial_state)
        if request_id not in self._context_cache:
            state = None
            if self.evidence_bundle is not None:
                from code.evidence_manager import EvidenceManager
                request = self.bundle.indexes.requests_by_id.get(request_id)
                if request is None:
                    request = self.bundle.indexes.sample_requests_by_id.get(request_id)
                if request is None:
                    raise ValueError(f"Request '{request_id}' not found in bundle")
                state = EvidenceManager(self.bundle).build_evidence_aware_state(
                    request, self.evidence_bundle
                )
            self._context_cache[request_id] = build_agent_context(
                self.bundle, request_id, financial_state=state
            )
        return self._context_cache[request_id]

    def get_decision(self, request_id: str, financial_state=None) -> CustomerDecision:
        """Construct validated CustomerDecision for the requested item."""
        context = self.get_context(request_id, financial_state=financial_state)
        explanation = self.model.generate_decision_explanation(context)
        from code.safety_guard import SafetyGuard
        guard = SafetyGuard(context)
        if not guard.validate_response(explanation)[0]:
            explanation = guard.get_fallback_explanation()

        plan_str = format_payment_plan(
            affordability_status=context.affordability_status,
            recommended_payment_method=context.recommended_payment_method,
            selected_plan=context.selected_plan,
            request_date=context.request_date,
            requested_amount=context.requested_amount,
            safe_amount=context.amount_safe_to_pay,
            earliest_full_payment_date=context.earliest_full_payment_date,
        )

        ev_summaries = [e.description for e in context.evidence_summaries]

        return CustomerDecision(
            request_id=context.request_id,
            amount_safe_to_pay=context.amount_safe_to_pay,
            affordability_status=context.affordability_status,
            recommended_payment_method=context.recommended_payment_method,
            payment_plan=plan_str,
            earliest_date_for_full_payment=context.earliest_full_payment_date,
            spending_changes_needed=context.spending_changes_needed,
            decision_explanation=explanation,
            evidence_summary=ev_summaries,
            warnings=context.warnings,
        )

    def explain_decision(
        self, request_id: str, user_question: Optional[str] = None
    ) -> str:
        """Orchestrates the flow: Deterministic Result -> Facts -> Explanation -> Safety Guard."""
        context = self.get_context(request_id)

        if user_question:
            explanation = self.model.answer_customer_question(
                context, user_question
            )
        else:
            explanation = self.model.generate_decision_explanation(context)

        # Validate through Safety Guard
        guard = SafetyGuard(context)
        is_valid, error = guard.validate_response(explanation)

        if not is_valid:
            logger.warning(
                f"Validation failed for request {request_id}: {error}. Using deterministic fallback."
            )
            return guard.get_fallback_explanation()

        return explanation

    def handle_hypothetical(
        self,
        request_id: str,
        amount: Union[Decimal, float, str, int],
        payment_date: Union[date, str],
    ) -> str:
        """Deterministic simulation for 'What if I pay X on date Y?' questions."""
        result = self.answer_hypothetical_payment(request_id, amount, payment_date)
        return result["explanation"]

    def answer_hypothetical_payment(
        self,
        request_id: str,
        amount: Union[Decimal, float, str, int],
        payment_date: Union[date, str],
    ) -> Dict[str, Any]:
        """Evaluate hypothetical payment using Phase 4 deterministic simulator."""
        context = self.get_context(request_id)

        # 1. Clean and parse amount to Decimal
        if isinstance(amount, (int, float)):
            dec_amount = Decimal(str(amount))
        elif isinstance(amount, str):
            clean_str = re.sub(r"[^\d.]", "", amount)
            dec_amount = Decimal(clean_str) if clean_str else Decimal("0")
        else:
            dec_amount = Decimal(amount)

        # 2. Parse payment_date to date
        if isinstance(payment_date, str):
            clean_date_str = payment_date.strip()
            # Support ISO YYYY-MM-DD
            if re.match(r"^\d{4}-\d{2}-\d{2}$", clean_date_str):
                p_date = date.fromisoformat(clean_date_str)
            else:
                try:
                    p_date = datetime.strptime(clean_date_str, "%d %B %Y").date()
                except ValueError:
                    p_date = context.request_date
        else:
            p_date = payment_date

        # 3. Find request and build FinancialState
        req = next(
            (r for r in self.bundle.requests if r.request_id == request_id),
            None,
        )
        if not req and hasattr(self.bundle, "sample_requests"):
            req = next(
                (
                    r
                    for r in self.bundle.sample_requests
                    if r.request_id == request_id
                ),
                None,
            )
        if not req:
            raise ValueError(f"Request '{request_id}' not found in bundle")

        state = build_financial_state(self.bundle, req)

        # 4. Route to Phase 4 Simulator via PaymentInjection
        injection = PaymentInjection(
            payment_id=f"hypo_{request_id}",
            payment_date=p_date,
            amount=dec_amount,
            currency=state.currency,
        )

        forecast = simulate_90_days(
            state, start_date=req.request_date, modifications=[injection]
        )

        curr = context.home_currency
        amt_fmt = _format_money(dec_amount)
        min_fmt = _format_money(context.minimum_reserve)
        date_fmt = _format_date(p_date)
        obs_min_fmt = _format_money(forecast.minimum_observed_balance)

        if forecast.invariant_ok:
            explanation = (
                f"If you pay {curr} {amt_fmt} on {date_fmt}, your plan remains safe. "
                f"Your lowest projected balance would be {curr} {obs_min_fmt}, "
                f"maintaining your {curr} {min_fmt} minimum reserve throughout the forecast."
            )
        else:
            breach_str = (
                f" on {_format_date(forecast.first_breach_date)}"
                if forecast.first_breach_date
                else ""
            )
            explanation = (
                f"If you pay {curr} {amt_fmt} on {date_fmt}, your balance would drop below your "
                f"{curr} {min_fmt} minimum reserve to {curr} {obs_min_fmt}{breach_str}. "
                f"This payment is not financially safe."
            )

        return {
            "request_id": request_id,
            "amount": str(dec_amount),
            "payment_date": p_date.isoformat(),
            "is_safe": forecast.invariant_ok,
            "minimum_projected_balance": str(forecast.minimum_observed_balance),
            "minimum_headroom": str(forecast.minimum_headroom),
            "first_breach_date": (
                forecast.first_breach_date.isoformat()
                if forecast.first_breach_date
                else None
            ),
            "explanation": explanation,
        }

    def chat(self, request_id: str, user_message: str) -> str:
        """Conversational entry point with request isolation and hypothetical detection."""
        if not user_message or not user_message.strip():
            return "Please provide a question about this financial request."

        msg = user_message.strip()

        # Check for hypothetical payment scenario: "what if I pay [amount] on [date] / today"
        hypo_match = re.search(
            r"what\s+if\s+i\s+pay\s+([A-Za-z]+)?\s*([\d,]+(?:\.\d+)?)\s*(?:on\s+([\d-]{10}|\d{1,2}\s+[A-Za-z]+\s+\d{4})|today)?",
            msg,
            re.IGNORECASE,
        )
        if hypo_match:
            _, amt_raw, date_raw = hypo_match.groups()
            context = self.get_context(request_id)
            target_date = date_raw if date_raw else context.request_date
            return self.handle_hypothetical(request_id, amt_raw, target_date)

        # Standard grounded Q&A
        return self.explain_decision(request_id, user_question=msg)
