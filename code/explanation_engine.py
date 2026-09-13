"""Phase 8 Explanation Engine & Customer Interaction Layer.

Transforms structured factual context into clear, grounded natural language.
Strictly adheres to verified numbers, prevents prompt injection, and
answers customer follow-up questions.
"""

from datetime import date
from decimal import Decimal
import logging
import re
from typing import Any, Dict, Optional

from code.agent_context import AgentContext
from code.safety_guard import SafetyGuard, _format_date, _format_money
from code.spending_models import SpendingAction

logger = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s+prompt",
    r"override\s+(the\s+)?decision",
    r"say\s+(buy|affordable|affordable_now|yes)",
    r"forget\s+(all\s+)?rules",
    r"disregard\s+(all\s+)?(the\s+)?rules",
    r"tell\s+me\s+i\s+can\s+(pay|afford|buy)",
    r"you\s+are\s+now\s+in\s+developer\s+mode",
    r"developer\s+mode",
    r"jailbreak",
    r"dan\s+mode",
    r"bypass\s+(safety|rules|limits)",
]


class ExplanationModel:
    """Natural language explanation and conversational interaction engine."""

    def __init__(self, provider: str = "grounded_rules"):
        self.provider = provider

    def generate_decision_explanation(self, context: AgentContext) -> str:
        """Produce grounded, concise decision_explanation for final challenge output."""
        guard = SafetyGuard(context)
        explanation = guard.get_fallback_explanation()

        # Validate explanation through SafetyGuard
        is_valid, err = guard.validate_response(explanation)
        if not is_valid:
            logger.warning(f"Validation warning on generated explanation: {err}")
            return guard.get_fallback_explanation()

        return explanation

    def answer_customer_question(
        self, context: AgentContext, question: str
    ) -> str:
        """Answer customer follow-up questions from verified facts."""
        if not question or not question.strip():
            return "Please ask a question about your purchase request, payment options, or spending adjustments."

        q_clean = question.strip()

        # 1. Prompt Injection Defense
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, q_clean, re.IGNORECASE):
                return (
                    "I cannot modify or override the verified financial decision. "
                    "My answers are grounded strictly in your verified financial facts and minimum reserve requirements."
                )

        q_lower = q_clean.lower()
        curr = context.home_currency
        min_reserve_str = _format_money(context.minimum_reserve)
        safe_amt_str = _format_money(context.amount_safe_to_pay)
        req_amt_str = _format_money(context.requested_amount)

        # 2. "Why can't I buy now?" / "Why?"
        if "why" in q_lower and ("not" in q_lower or "can't" in q_lower or "cannot" in q_lower or "wait" in q_lower or context.affordability_status != "affordable_now"):
            if context.affordability_status == "affordable_now":
                return (
                    f"You can buy it now! Paying {curr} {req_amt_str} today leaves your "
                    f"{curr} {min_reserve_str} minimum reserve fully protected throughout the 90-day forecast."
                )

            crit_date_str = (
                f" around {_format_date(context.critical_date)}"
                if context.critical_date
                else " during upcoming bill cycles"
            )
            return (
                f"Paying the full {curr} {req_amt_str} today would cause your balance to drop below "
                f"your required minimum reserve of {curr} {min_reserve_str}{crit_date_str}. "
                f"Currently, only {curr} {safe_amt_str} is safe to spend today."
            )

        # 3. "When can I afford the full amount?" / "When?"
        if "when" in q_lower or "date" in q_lower or "how long" in q_lower:
            if context.affordability_status == "affordable_now":
                return f"You can afford the full {curr} {req_amt_str} today ({_format_date(context.request_date)})."
            if context.earliest_full_payment_date:
                return (
                    f"Based on your projected cash flow and incoming confirmed income, "
                    f"the earliest safe date for paying the full {curr} {req_amt_str} is "
                    f"{_format_date(context.earliest_full_payment_date)}."
                )
            return (
                f"The full {curr} {req_amt_str} cannot be safely paid in one lump sum within the current 90-day forecast "
                f"while maintaining your {curr} {min_reserve_str} minimum reserve."
            )

        # 4. "Why installments?"
        if "installment" in q_lower:
            if context.selected_plan and context.selected_plan.payments:
                num_inst = context.selected_plan.number_of_payments
                inst_amt_str = _format_money(context.selected_plan.payments[0].amount)
                return (
                    f"Installments spread the {curr} {req_amt_str} cost into {num_inst} payments of "
                    f"{curr} {inst_amt_str}. This prevents your balance from dropping below your "
                    f"{curr} {min_reserve_str} reserve on any day."
                )
            return (
                f"Installments are evaluated when paying in full today would breach your {curr} {min_reserve_str} minimum reserve."
            )

        # 5. "What needs to change?" / "Which expense needs to be reduced?" / "spending"
        if "change" in q_lower or "reduce" in q_lower or "stop" in q_lower or "cut" in q_lower or "spending" in q_lower:
            if context.spending_changes_needed == "none":
                return "No spending changes are required for this recommendation."

            items = []
            for c in context.spending_changes:
                cat_clean = c.category.replace("_", " ")
                if c.action == SpendingAction.STOP:
                    items.append(f"stopping your {cat_clean} expense ({c.event_id})")
                elif c.action == SpendingAction.REDUCE and c.target_amount is not None:
                    items.append(
                        f"reducing your {cat_clean} expense ({c.event_id}) to {curr} {_format_money(c.target_amount)}"
                    )
            return (
                f"To make this purchase financially safe, the plan requires: "
                f"{'; '.join(items)}. All requested changes belong to flexible categories you approved."
            )

        # 6. "How much can I safely pay?" / "How much"
        if "how much" in q_lower or "safe amount" in q_lower or "limit" in q_lower:
            return (
                f"You can safely pay up to {curr} {safe_amt_str} today on {_format_date(context.request_date)} "
                f"without risking your {curr} {min_reserve_str} minimum reserve."
            )

        # 7. Evidence / uncertainty questions
        if "evidence" in q_lower or "salary" in q_lower or "income" in q_lower:
            if context.evidence_summaries:
                ev_descs = [e.description for e in context.evidence_summaries]
                return f"Verified evidence influencing this decision: {'; '.join(ev_descs)}."
            return "This decision is based on your verified baseline financial history and active recurring commitments."

        # Default overview
        return (
            f"Recommendation: {context.recommended_payment_method.replace('_', ' ').title()}. "
            f"Affordability status: {context.affordability_status.replace('_', ' ').title()}. "
            f"Amount safe to pay today: {curr} {safe_amt_str}."
        )
