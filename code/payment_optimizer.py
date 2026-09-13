from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
import logging

from code.payment_models import PlanType, PaymentPlan, PaymentEvent
from code.payment_ranker import rank_payment_plans
from code.state_builder import build_financial_state
from code.simulator import simulate_90_days
from code.simulation_models import PaymentInjection

logger = logging.getLogger(__name__)

class PaymentOptimizer:
    def __init__(self, dataset_bundle):
        self.bundle = dataset_bundle

    def optimize(self, request_id: str) -> Optional[PaymentPlan]:
        """
        Finds the best feasible payment plan for a given request.
        """
        # 1. Load request and user profile
        request = next((r for r in self.bundle.requests if r.request_id == request_id), None)
        if not request:
            logger.error(f"Request {request_id} not found")
            return None
        
        user_id = request.user_id
        profile = next((p for p in self.bundle.profiles if p.user_id == user_id), None)
        if not profile:
            logger.error(f"Profile for user {user_id} not found")
            return None

        # 2. Build current financial state (immutable)
        state = build_financial_state(self.bundle, request_id)
        
        # 3. Get available payment options
        options = [opt for opt in self.bundle.payment_options if opt.request_id == request_id]
        
        # 4. Generate candidate plans
        candidates = self._generate_candidates(request, profile, options)
        
        # 5. Validate safety and deadlines via Phase 4 Simulator
        safe_plans = []
        for plan in candidates:
            if self._validate_safety(state, plan, request):
                safe_plans.append(plan)
        
        if not safe_plans:
            return None
            
        # 6. Rank and select the best plan
        ranked = rank_payment_plans(safe_plans)
        return ranked[0]

    def _generate_candidates(self, request, profile, options) -> List[PaymentPlan]:
        candidates = []
        
        # Full Payment candidate
        full_opt = next((opt for opt in options if opt.payment_method == "full_payment"), None)
        if full_opt:
            plan = PaymentPlan(
                request_id=request.request_id,
                payment_option_id=full_opt.payment_option_id,
                plan_type=PlanType.FULL_PAYMENT,
                payment_method="full_payment",
                payments=[PaymentEvent(full_opt.first_payment_date, full_opt.payment_amount, "Full Payment")],
                total_paid=full_opt.total_payable_amount,
                fees=full_opt.financing_fee,
                interest=Decimal('0')
            )
            plan.accepted_method = True 
            candidates.append(plan)

        # Installment candidates
        for opt in options:
            if opt.payment_method == "installments":
                payments = []
                current_date = opt.first_payment_date
                for i in range(int(opt.number_of_payments)):
                    payments.append(PaymentEvent(current_date, opt.payment_amount, f"Installment {i+1}"))
                    current_date += timedelta(days=int(opt.payment_frequency_days or 0))
                
                plan = PaymentPlan(
                    request_id=request.request_id,
                    payment_option_id=opt.payment_option_id,
                    plan_type=PlanType.INSTALLMENT,
                    payment_method="installments",
                    payments=payments,
                    total_paid=opt.total_payable_amount,
                    fees=opt.financing_fee,
                    interest=Decimal('0')
                )
                plan.accepted_method = True
                candidates.append(plan)

        # Partial Payment candidate (only if allowed)
        if request.allows_partial_payment:
            # Partial payment structure: 
            # 1. amount_safe_to_pay today
            # 2. remaining balance on earliest_date_for_full_payment
            # This requires Phase 5 results which are usually generated on the fly.
            # For now, we implement the structural logic.
            pass

        return candidates

    def _validate_safety(self, state, plan: PaymentPlan, request) -> bool:
        # Convert plan payments into PaymentInjection objects
        modifications = []
        for p in plan.payments:
            modifications.append(PaymentInjection(
                payment_id=f"plan_{plan.payment_option_id}_{p.description}",
                payment_date=p.event_date,
                amount=p.amount,
                currency=state.currency
            ))
            
        # Use Phase 4 Simulator
        try:
            forecast = simulate_90_days(state, modifications=modifications)
            
            plan.is_safe = forecast.invariant_ok
            plan.min_balance_observed = forecast.minimum_observed_balance
            plan.first_breach_date = forecast.first_breach_date
            plan.min_headroom = forecast.minimum_headroom
            
            # Deadline check: last payment must be on or before desired_completion_date
            if plan.last_payment_date and request.desired_completion_date:
                plan.completes_by_deadline = plan.last_payment_date <= request.desired_completion_date
            else:
                plan.completes_by_deadline = False
            
            return plan.is_safe and plan.completes_by_deadline
        except Exception as e:
            logger.exception(f"Simulation failed for plan {plan.payment_option_id}: {e}")
            return False
