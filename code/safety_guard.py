"""Phase 8 Safety Guard & Grounded Fallback Generator.

Ensures zero financial hallucinations. Validates generated text against
deterministic facts in AgentContext, and provides deterministic fallback
explanations whenever validation fails or the model is unavailable.
"""

from datetime import date
from decimal import Decimal
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from code.agent_context import AgentContext
from code.spending_models import SpendingAction

logger = logging.getLogger(__name__)


def _format_money(val: Decimal) -> str:
    """Format decimal as integer if integral, else 2 decimal places."""
    if val == val.to_integral_value():
        return f"{int(val):,}".replace(",", ",")
    return f"{val:,.2f}"


def _format_date(d: date) -> str:
    """Format date in ISO or challenge style (e.g. 15 November 2019)."""
    months = [
        "",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    return f"{d.day} {months[d.month]} {d.year}"


class SafetyGuard:
    """Validates explanation text against verified AgentContext facts."""

    def __init__(self, context: AgentContext):
        self.context = context

    def validate_response(self, text: str) -> Tuple[bool, Optional[str]]:
        """Verify that response text does not contradict deterministic facts."""
        if not text or not text.strip():
            return False, "Empty explanation text"

        t_lower = text.lower()
        status = self.context.affordability_status
        method = self.context.recommended_payment_method

        # 1. Contradiction of 'not_affordable'
        if status == "not_affordable":
            if (
                "affordable now" in t_lower
                or "pay in full today" in t_lower
                or "safely pay the full" in t_lower
            ):
                return (
                    False,
                    "Contradiction: response claims affordable for not_affordable request",
                )

        # 2. Contradiction of 'affordable_now'
        if status == "affordable_now":
            if "not affordable" in t_lower or "cannot afford" in t_lower:
                return (
                    False,
                    "Contradiction: response claims not affordable for affordable_now request",
                )

        # 3. Contradiction of 'wait'
        if method == "wait":
            if "pay today" in t_lower and "wait" not in t_lower:
                return (
                    False,
                    "Contradiction: recommended method is wait, but text recommends paying today",
                )

        # 4. Spending cuts consistency
        if self.context.spending_changes_needed == "none":
            if "reduce rent" in t_lower or "stop rent" in t_lower:
                return False, "Protected rent cannot be modified"
        else:
            if "no spending changes" in t_lower or "no changes required" in t_lower:
                return (
                    False,
                    "Contradiction: spending changes are required but text claims none needed",
                )

        # 5. Check numeric amounts stated as safe
        # If response states safe to pay amount, ensure it does not exceed amount_safe_to_pay
        safe_matches = re.findall(r"safely pay\s+([A-Za-z]+)?\s*([\d,]+(?:\.\d+)?)", t_lower)
        for _, amt_str in safe_matches:
            try:
                amt = Decimal(amt_str.replace(",", ""))
                if amt > self.context.amount_safe_to_pay:
                    return (
                        False,
                        f"Numeric contradiction: safe amount {amt} exceeds verified safe amount {self.context.amount_safe_to_pay}",
                    )
            except Exception:
                pass

        return True, None

    def get_fallback_explanation(self) -> str:
        """Produce 100% deterministic, grounded explanation matching challenge contract."""
        ctx = self.context
        curr = ctx.home_currency
        req_amt_str = _format_money(ctx.requested_amount)
        min_reserve_str = _format_money(ctx.minimum_reserve)
        safe_amt_str = _format_money(ctx.amount_safe_to_pay)

        status = ctx.affordability_status
        method = ctx.recommended_payment_method

        # Build spending change clause if present
        spending_clause = ""
        if ctx.spending_changes:
            change_clauses = []
            for c in ctx.spending_changes:
                cat_clean = c.category.replace("_", " ")
                if c.action == SpendingAction.STOP:
                    change_clauses.append(f"Stop the {cat_clean} expense ({c.event_id})")
                elif c.action == SpendingAction.REDUCE:
                    if c.target_amount is not None:
                        new_amt_str = _format_money(c.target_amount)
                        change_clauses.append(
                            f"Reduce the {cat_clean} expense ({c.event_id}) to {curr} {new_amt_str}"
                        )
            spending_clause = " and ".join(change_clauses)

        # 1. Affordable Now
        if status == "affordable_now":
            return (
                f"Pay {curr} {req_amt_str} today. "
                f"This leaves at least {curr} {min_reserve_str} available over the next 90 days."
            )

        # 2. Affordable with Plan (Full payment with spending changes)
        if status == "affordable_with_plan" and method == "full_payment":
            prefix = f"{spending_clause}, then " if spending_clause else ""
            return (
                f"{prefix}pay {curr} {req_amt_str} today. "
                f"This leaves at least {curr} {min_reserve_str} available."
            )

        # 3. Affordable with Plan (Installments)
        if status == "affordable_with_plan" and method == "installments":
            prefix = f"{spending_clause}, then " if spending_clause else ""
            if ctx.selected_plan and ctx.selected_plan.payments:
                num_inst = ctx.selected_plan.number_of_payments
                first_pay = ctx.selected_plan.payments[0]
                inst_amt_str = _format_money(first_pay.amount)
                start_date_str = _format_date(first_pay.event_date)
                return (
                    f"{prefix}use {num_inst} installments of {curr} {inst_amt_str}, "
                    f"starting {start_date_str}. "
                    f"This leaves at least {curr} {min_reserve_str} available."
                )
            return (
                f"{prefix}use the available installment plan. "
                f"This leaves at least {curr} {min_reserve_str} available."
            )

        # 4. Affordable with Plan (Partial payment)
        if status == "affordable_with_plan" and method == "partial_payment":
            rem_amt = max(Decimal("0"), ctx.requested_amount - ctx.amount_safe_to_pay)
            rem_amt_str = _format_money(rem_amt)
            date_str = (
                _format_date(ctx.earliest_full_payment_date)
                if ctx.earliest_full_payment_date
                else "a later date"
            )
            return (
                f"Pay {curr} {safe_amt_str} today and the remaining {curr} {rem_amt_str} on {date_str}. "
                f"This completes the full request and keeps the {curr} {min_reserve_str} minimum protected."
            )

        # 5. Affordable Later (Wait)
        if method == "wait" or status == "affordable_later":
            if ctx.earliest_full_payment_date:
                safe_date_str = _format_date(ctx.earliest_full_payment_date)
                return (
                    f"Pay {curr} {req_amt_str} in full on {safe_date_str}. "
                    f"Paying earlier would take the balance below the {curr} {min_reserve_str} minimum."
                )
            return (
                f"Wait until upcoming income settles before paying {curr} {req_amt_str}. "
                f"Paying now would take the balance below the {curr} {min_reserve_str} minimum."
            )

        # 6. Not Affordable
        if ctx.earliest_full_payment_date is None and ctx.amount_safe_to_pay > Decimal("0"):
            return (
                f"Do not proceed with the {curr} {req_amt_str} request. "
                f"Although {curr} {safe_amt_str} is available today, the full amount cannot be completed safely within 90 days."
            )

        deadline_str = _format_date(ctx.desired_completion_date)
        return (
            f"Do not make this payment by {deadline_str}. "
            f"None of the available options keeps the {curr} {min_reserve_str} minimum protected."
        )
