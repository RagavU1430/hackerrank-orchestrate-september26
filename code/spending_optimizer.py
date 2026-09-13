"""Phase 7 Deterministic Spending Adjustment Optimizer.

Finds the minimal and best set of user-permitted flexible spending changes
to make an otherwise infeasible purchase/payment plan financially safe.
"""

from datetime import date, timedelta
from decimal import Decimal
import itertools
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from code.affordability import evaluate_affordability
from code.affordability_models import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    NOT_AFFORDABLE,
)
from code.financial_state import FinancialState
from code.payment_models import PaymentEvent, PaymentPlan, PlanType
from code.payment_optimizer import PaymentOptimizer
from code.payment_ranker import rank_payment_plans
from code.schemas import FinancialProfile, PaymentOption, Request
from code.simulation_models import PaymentInjection, ReduceExpense, StopExpense
from code.simulator import simulate_90_days
from code.spending_models import (
    DecisionScenario,
    SpendingAction,
    SpendingChange,
    SpendingChangeSet,
    SpendingOptimizationResult,
)
from code.state_builder import build_financial_state

logger = logging.getLogger(__name__)


def get_eligible_spending_changes(state: FinancialState) -> List[SpendingChange]:
    """Extract all eligible spending changes for the user's financial state.

    Only active recurrences that:
    1. Are flexible (can_stop or can_reduce)
    2. Belong to categories the user is willing to stop or reduce
    3. Are NOT in expense_categories_to_protect
    4. For REDUCE: have minimum_allowed_amount < current amount
    """
    profile = state.profile
    protected = set(profile.expense_categories_to_protect)
    willing_stop = set(profile.expense_categories_user_is_willing_to_stop)
    willing_reduce = set(profile.expense_categories_user_is_willing_to_reduce)

    eligible: List[SpendingChange] = []
    seen_keys: Set[Tuple[str, SpendingAction]] = set()

    for rec in state.recurrences:
        if not rec.active:
            continue
        cat = rec.category
        if cat in protected:
            continue

        # Check STOP eligibility
        if rec.can_stop and cat in willing_stop:
            key = (rec.event_id, SpendingAction.STOP)
            if key not in seen_keys:
                eligible.append(
                    SpendingChange(
                        event_id=rec.event_id,
                        action=SpendingAction.STOP,
                        category=cat,
                        original_amount=rec.amount,
                    )
                )
                seen_keys.add(key)

        # Check REDUCE eligibility
        if (
            rec.can_reduce
            and cat in willing_reduce
            and rec.minimum_allowed_amount is not None
        ):
            if rec.amount is None or rec.minimum_allowed_amount < rec.amount:
                key = (rec.event_id, SpendingAction.REDUCE)
                if key not in seen_keys:
                    eligible.append(
                        SpendingChange(
                            event_id=rec.event_id,
                            action=SpendingAction.REDUCE,
                            category=cat,
                            target_amount=rec.minimum_allowed_amount,
                            original_amount=rec.amount,
                        )
                    )
                    seen_keys.add(key)

    # Sort deterministically by event_id, action
    return sorted(eligible, key=lambda c: (c.event_id, c.action.value))


def generate_candidate_change_sets(
    eligible_changes: List[SpendingChange], max_changes: int = 3
) -> List[SpendingChangeSet]:
    """Generate candidate change sets of size 1..max_changes.

    Enforces mutual exclusivity: an event cannot have both STOP and REDUCE.
    Sorted deterministically.
    """
    candidates: List[SpendingChangeSet] = []

    # 1 change
    for c in eligible_changes:
        candidates.append(SpendingChangeSet((c,)))

    # 2 changes
    if max_changes >= 2:
        for c1, c2 in itertools.combinations(eligible_changes, 2):
            if c1.event_id != c2.event_id:
                sorted_pair = tuple(
                    sorted([c1, c2], key=lambda c: (c.event_id, c.action.value))
                )
                candidates.append(SpendingChangeSet(sorted_pair))

    # 3 changes
    if max_changes >= 3:
        for c1, c2, c3 in itertools.combinations(eligible_changes, 3):
            if len({c1.event_id, c2.event_id, c3.event_id}) == 3:
                sorted_triplet = tuple(
                    sorted([c1, c2, c3], key=lambda c: (c.event_id, c.action.value))
                )
                candidates.append(SpendingChangeSet(sorted_triplet))

    return candidates


class SpendingOptimizer:
    """Orchestrates candidate payment plans, spending change sets, simulation, and deterministic ranking."""

    def __init__(self, dataset_bundle):
        self.bundle = dataset_bundle

    def _get_request(self, request_id: str) -> Optional[Request]:
        req = next((r for r in self.bundle.requests if r.request_id == request_id), None)
        if not req and hasattr(self.bundle, "sample_requests"):
            req = next(
                (r for r in self.bundle.sample_requests if r.request_id == request_id),
                None,
            )
        return req

    def generate_candidate_payment_plans(
        self,
        request: Request,
        profile: FinancialProfile,
        options: List[PaymentOption],
    ) -> List[PaymentPlan]:
        """Generate all candidate payment plans allowed by user preferences."""
        candidates: List[PaymentPlan] = []
        considered = set(profile.payment_methods_user_will_consider)

        # 1. Full Payment candidate
        if "full_payment" in considered:
            full_opt = next(
                (opt for opt in options if opt.payment_method == "full_payment"),
                None,
            )
            if full_opt:
                plan = PaymentPlan(
                    request_id=request.request_id,
                    payment_option_id=full_opt.payment_option_id,
                    plan_type=PlanType.FULL_PAYMENT,
                    payment_method="full_payment",
                    payments=[
                        PaymentEvent(
                            full_opt.first_payment_date,
                            full_opt.payment_amount,
                            "Full Payment",
                        )
                    ],
                    total_paid=full_opt.total_payable_amount,
                    fees=full_opt.financing_fee,
                    interest=Decimal("0"),
                    accepted_method=True,
                )
                candidates.append(plan)

        # 2. Installment candidates
        if "installments" in considered:
            for opt in options:
                if opt.payment_method == "installments":
                    num_payments = int(opt.number_of_payments)
                    freq_days = int(opt.payment_frequency_days or 0)

                    # Validate max_installment_months
                    if profile.max_installment_months is not None:
                        total_span_days = (num_payments - 1) * freq_days
                        span_months = (total_span_days + 29) // 30
                        if span_months > profile.max_installment_months:
                            continue

                    payments = []
                    current_date = opt.first_payment_date
                    for i in range(num_payments):
                        payments.append(
                            PaymentEvent(
                                current_date,
                                opt.payment_amount,
                                f"Installment {i+1}",
                            )
                        )
                        current_date += timedelta(days=freq_days)

                    plan = PaymentPlan(
                        request_id=request.request_id,
                        payment_option_id=opt.payment_option_id,
                        plan_type=PlanType.INSTALLMENT,
                        payment_method="installments",
                        payments=payments,
                        total_paid=opt.total_payable_amount,
                        fees=opt.financing_fee,
                        interest=Decimal("0"),
                        accepted_method=True,
                    )
                    candidates.append(plan)

        return candidates

    def _evaluate_scenario(
        self,
        state: FinancialState,
        plan: PaymentPlan,
        change_set: SpendingChangeSet,
        request: Request,
    ) -> DecisionScenario:
        """Simulate candidate scenario (payment plan + spending changes) for 90 days."""
        # Convert plan payments to PaymentInjections
        modifications: List[Any] = []
        for p in plan.payments:
            modifications.append(
                PaymentInjection(
                    payment_id=f"plan_{plan.payment_option_id}_{p.description}",
                    payment_date=p.event_date,
                    amount=p.amount,
                    currency=state.currency,
                )
            )

        # Convert spending changes to StopExpense and ReduceExpense
        for c in change_set.changes:
            if c.action == SpendingAction.STOP:
                modifications.append(StopExpense(target_id=c.event_id))
            elif c.action == SpendingAction.REDUCE:
                if c.target_amount is not None:
                    modifications.append(
                        ReduceExpense(target_id=c.event_id, new_amount=c.target_amount)
                    )

        # Run 90-day simulation
        try:
            forecast = simulate_90_days(
                state, modifications=modifications, start_date=request.request_date
            )
            is_safe = forecast.invariant_ok

            # Deadline check
            completes_by_deadline = False
            if plan.last_payment_date and request.desired_completion_date:
                completes_by_deadline = (
                    plan.last_payment_date <= request.desired_completion_date
                )

            # Compute approximate projected savings over forecast
            projected_savings = Decimal("0")
            for c in change_set.changes:
                if c.original_amount is not None:
                    if c.action == SpendingAction.STOP:
                        projected_savings += c.original_amount
                    elif (
                        c.action == SpendingAction.REDUCE
                        and c.target_amount is not None
                    ):
                        projected_savings += max(
                            Decimal("0"), c.original_amount - c.target_amount
                        )

            return DecisionScenario(
                request_id=request.request_id,
                payment_plan=plan,
                spending_changes=change_set,
                is_safe=is_safe,
                completes_by_deadline=completes_by_deadline,
                min_balance_observed=forecast.minimum_observed_balance,
                min_headroom=forecast.minimum_headroom,
                first_breach_date=forecast.first_breach_date,
                total_paid=plan.total_paid,
                projected_savings=projected_savings,
            )
        except Exception as exc:
            logger.exception(
                f"Simulation failed for scenario {plan.payment_option_id} with {change_set}: {exc}"
            )
            return DecisionScenario(
                request_id=request.request_id,
                payment_plan=plan,
                spending_changes=change_set,
                is_safe=False,
                completes_by_deadline=False,
                rejection_reason=str(exc),
            )

    def optimize_spending(
        self, request_id: str, financial_state: Optional[FinancialState] = None
    ) -> SpendingOptimizationResult:
        """Main Phase 7 optimization entry point for a request."""
        # 1. Load request and profile
        request = self._get_request(request_id)
        if not request:
            raise ValueError(f"Request {request_id} not found")

        profile = next(
            (p for p in self.bundle.profiles if p.user_id == request.user_id), None
        )
        if not profile:
            raise ValueError(f"Profile for user {request.user_id} not found")

        # 2. Build financial state
        state = financial_state or build_financial_state(self.bundle, request)
        if state.request_id != request_id or state.user_id != request.user_id:
            raise ValueError("Provided financial state does not match optimization request")

        # 3. Get payment options and generate candidate payment plans
        options = [
            opt
            for opt in self.bundle.payment_options
            if opt.request_id == request_id
        ]
        candidate_plans = self.generate_candidate_payment_plans(
            request, profile, options
        )

        # 4. Phase 5 affordability baseline
        affordability = evaluate_affordability(state, request)

        # 5. Check baseline scenarios without spending changes (0 changes)
        empty_changes = SpendingChangeSet(())
        baseline_scenarios: List[DecisionScenario] = []
        for plan in candidate_plans:
            scen = self._evaluate_scenario(state, plan, empty_changes, request)
            if scen.is_safe and scen.completes_by_deadline:
                baseline_scenarios.append(scen)

        if baseline_scenarios:
            # Safe without spending changes!
            best_scen = self._rank_scenarios(baseline_scenarios)[0]
            # Determine status: affordable_now if full payment on request date, else affordable_with_plan
            is_aff_now = (
                best_scen.payment_plan is not None
                and best_scen.payment_plan.plan_type == PlanType.FULL_PAYMENT
                and best_scen.payment_plan.first_payment_date == request.request_date
            )
            aff_status = AFFORDABLE_NOW if is_aff_now else AFFORDABLE_WITH_PLAN

            return SpendingOptimizationResult(
                request_id=request_id,
                selected_scenario=best_scen,
                spending_changes_needed="none",
                affordability_status=aff_status,
                recommended_payment_method=best_scen.payment_plan.payment_method
                if best_scen.payment_plan
                else "none",
                has_spending_changes=False,
                num_spending_changes=0,
                diagnostics={"baseline_safe": True, "plans_tested": len(candidate_plans)},
            )

        # 6. Check partial payment baseline without spending changes (if allowed)
        if (
            request.allows_partial_payment
            and "partial_payment" in profile.payment_methods_user_will_consider
            and Decimal("0") < affordability.amount_safe_to_pay < request.requested_amount
            and affordability.earliest_date_for_full_payment is not None
            and affordability.earliest_date_for_full_payment <= request.desired_completion_date
        ):
            part_plan = PaymentPlan(
                request_id=request.request_id,
                payment_option_id="partial_payment",
                plan_type=PlanType.PARTIAL_PAYMENT,
                payment_method="partial_payment",
                payments=[
                    PaymentEvent(
                        request.request_date,
                        affordability.amount_safe_to_pay,
                        "Initial Payment",
                    ),
                    PaymentEvent(
                        affordability.earliest_date_for_full_payment,
                        request.requested_amount - affordability.amount_safe_to_pay,
                        "Completion Payment",
                    ),
                ],
                total_paid=request.requested_amount,
                fees=Decimal("0"),
                interest=Decimal("0"),
                accepted_method=True,
            )
            scen = self._evaluate_scenario(state, part_plan, empty_changes, request)
            if scen.is_safe and scen.completes_by_deadline:
                return SpendingOptimizationResult(
                    request_id=request_id,
                    selected_scenario=scen,
                    spending_changes_needed="none",
                    affordability_status=AFFORDABLE_WITH_PLAN,
                    recommended_payment_method="partial_payment",
                    has_spending_changes=False,
                    num_spending_changes=0,
                    diagnostics={"baseline_safe": True, "partial_payment": True},
                )

        # 7. No baseline plan is safe -> search eligible spending changes
        eligible_changes = get_eligible_spending_changes(state)
        candidate_change_sets = generate_candidate_change_sets(
            eligible_changes, max_changes=3
        )

        # Search size by size (1 change, then 2 changes, then 3 changes)
        for k in (1, 2, 3):
            k_change_sets = [cs for cs in candidate_change_sets if cs.num_changes == k]
            feasible_k_scenarios: List[DecisionScenario] = []

            for cs in k_change_sets:
                for plan in candidate_plans:
                    scen = self._evaluate_scenario(state, plan, cs, request)
                    if scen.is_safe and scen.completes_by_deadline:
                        feasible_k_scenarios.append(scen)

            if feasible_k_scenarios:
                # Found feasible scenario(s) with k changes!
                best_scen = self._rank_scenarios(feasible_k_scenarios)[0]
                return SpendingOptimizationResult(
                    request_id=request_id,
                    selected_scenario=best_scen,
                    spending_changes_needed=best_scen.spending_changes.to_output_str(),
                    affordability_status=AFFORDABLE_WITH_PLAN,
                    recommended_payment_method=best_scen.payment_plan.payment_method
                    if best_scen.payment_plan
                    else "none",
                    has_spending_changes=True,
                    num_spending_changes=k,
                    diagnostics={
                        "eligible_changes_count": len(eligible_changes),
                        "changes_evaluated": len(candidate_change_sets),
                        "selected_changes": best_scen.spending_changes.to_output_str(),
                    },
                )

        # 8. No feasible scenario found even with 3 spending changes!
        # Fall back to Phase 5 affordability recommendation
        if (
            affordability.earliest_date_for_full_payment is not None
            and affordability.earliest_date_for_full_payment <= request.desired_completion_date
        ):
            # Safe later by the desired completion date
            aff_status = AFFORDABLE_LATER
            rec_method = "wait"
        elif (
            affordability.affordability_status == AFFORDABLE_LATER
            and "full_payment" in profile.payment_methods_user_will_consider
        ):
            aff_status = AFFORDABLE_LATER
            rec_method = "wait"
        else:
            aff_status = NOT_AFFORDABLE
            rec_method = "not_recommended"

        return SpendingOptimizationResult(
            request_id=request_id,
            selected_scenario=None,
            spending_changes_needed="none",
            affordability_status=aff_status,
            recommended_payment_method=rec_method,
            has_spending_changes=False,
            num_spending_changes=0,
            diagnostics={
                "eligible_changes_count": len(eligible_changes),
                "infeasible_even_with_changes": True,
            },
        )

    def _rank_scenarios(
        self, scenarios: List[DecisionScenario]
    ) -> List[DecisionScenario]:
        """Rank scenarios deterministically according to challenge rules.

        1. Completes by deadline (True first)
        2. Fewer spending changes (Ascending: 0, 1, 2, 3)
        3. Total payment cost / total paid (Ascending)
        4. Starts earlier / first payment date (Ascending date)
        5. Fewer payments (Ascending count)
        6. Lowest payment option ID (Ascending)
        7. Deterministic tie-breaker on spending changes string
        """

        def ranking_key(scen: DecisionScenario):
            plan = scen.payment_plan
            completes_by_deadline = -1 if scen.completes_by_deadline else 1
            num_changes = scen.spending_changes.num_changes
            total_paid = plan.total_paid if plan else Decimal("Infinity")
            first_date = (
                plan.first_payment_date if plan and plan.first_payment_date else date.max
            )
            num_payments = plan.number_of_payments if plan else 9999
            option_id = (plan.payment_option_id or "zzzzzz") if plan else "zzzzzz"
            changes_str = scen.spending_changes.to_output_str()

            return (
                completes_by_deadline,
                num_changes,
                total_paid,
                first_date,
                num_payments,
                option_id,
                changes_str,
            )

        return sorted(scenarios, key=ranking_key)
