from typing import List
from code.payment_models import PaymentPlan

def rank_payment_plans(plans: List[PaymentPlan]) -> List[PaymentPlan]:
    """
    Ranks payment plans deterministically according to the challenge rules.
    
    Ranking Priorities:
    1. Complete by desired date (True first)
    2. No spending changes (In Phase 6, this is always True as we don't optimize spending yet)
    3. Minimize total amount paid (Ascending)
    4. Start payment earlier (Ascending date)
    5. Fewer payments (Ascending count)
    6. Lowest payment_option_id (Ascending)
    """
    
    def ranking_key(plan: PaymentPlan):
        # 1. Completes by desired date: True (1) -> False (0). We want True first, so use -1.
        completes_by_deadline = -1 if plan.completes_by_deadline else 1
        
        # 2. Spending changes: In Phase 6, we assume no changes. 
        # This will be integrated in Phase 7. For now, it's a constant.
        requires_spending_change = 0 
        
        # 3. Total paid: Lower is better.
        total_paid = plan.total_paid
        
        # 4. Start earlier: Earlier date is better.
        first_date = plan.first_payment_date or date.max
        
        # 5. Fewer payments: Lower count is better.
        num_payments = plan.number_of_payments
        
        # 6. Lowest payment_option_id: Lower ID is better.
        option_id = plan.payment_option_id or "zzzzzz"
        
        return (
            completes_by_deadline, 
            requires_spending_change, 
            total_paid, 
            first_date, 
            num_payments, 
            option_id
        )

    # Sort plans based on the ranking key
    return sorted(plans, key=ranking_key)
