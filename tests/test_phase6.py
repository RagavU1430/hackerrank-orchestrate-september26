import pytest
from decimal import Decimal
from datetime import date, timedelta
from code.payment_models import PlanType, PaymentPlan, PaymentEvent
from code.payment_optimizer import PaymentOptimizer
from code.schemas import DatasetBundle, FinancialProfile, Request, PaymentOption, FinancialEvent

def get_empty_bundle():
    """Returns a completely fresh, empty DatasetBundle."""
    return DatasetBundle()

def test_full_payment_safe():
    bundle = get_empty_bundle()
    
    request_id = "safe_r1"
    user_id = "safe_u1"
    
    profile = FinancialProfile(
        user_id=user_id, 
        home_currency="USD", 
        current_available_balance=Decimal("1000"), 
        minimum_balance_to_keep=Decimal("100"), 
        financial_priorities=[], 
        expense_categories_to_protect=[], 
        expense_categories_user_is_willing_to_reduce=[], 
        expense_categories_user_is_willing_to_stop=[], 
        payment_methods_user_will_consider=["full_payment"], 
        max_installment_months=None
    )
    
    request = Request(
        request_id=request_id, 
        user_id=user_id, 
        request_date=date(2026, 1, 1), 
        request_type="purchase", 
        requested_amount=Decimal("500"), 
        desired_completion_date=date(2026, 1, 10), 
        allows_partial_payment=False, 
        request_text="Laptop"
    )
    
    option = PaymentOption(
        payment_option_id="opt1", 
        request_id=request_id, 
        payment_method="full_payment", 
        payment_amount=Decimal("500"), 
        number_of_payments=1, 
        first_payment_date=date(2026, 1, 1), 
        payment_frequency_days=None, 
        financing_fee=Decimal("0"), 
        total_payable_amount=Decimal("500")
    )
    
    bundle.profiles.append(profile)
    bundle.requests.append(request)
    bundle.payment_options.append(option)
    
    from code.indexes import build_indexes
    bundle.indexes = build_indexes(
        bundle.requests, 
        bundle.sample_requests, 
        bundle.profiles, 
        bundle.events, 
        bundle.payment_options, 
        bundle.exchange_rates, 
        bundle.messages, 
        bundle.images, 
        bundle.evidence_queue
    )
    bundle.validation_report = type('obj', (object,), {'is_valid': True})
    
    optimizer = PaymentOptimizer(bundle)
    best_plan = optimizer.optimize(request_id)
    
    assert best_plan is not None
    assert best_plan.plan_type == PlanType.FULL_PAYMENT
    assert best_plan.is_safe is True

def test_full_payment_unsafe():
    bundle = get_empty_bundle()
    
    request_id = "unsafe_r1"
    user_id = "unsafe_u1"
    
    profile = FinancialProfile(
        user_id=user_id, 
        home_currency="USD", 
        current_available_balance=Decimal("200"), 
        minimum_balance_to_keep=Decimal("100"), 
        financial_priorities=[], 
        expense_categories_to_protect=[], 
        expense_categories_user_is_willing_to_reduce=[], 
        expense_categories_user_is_willing_to_stop=[], 
        payment_methods_user_will_consider=["full_payment"], 
        max_installment_months=None
    )
    
    request = Request(
        request_id=request_id, 
        user_id=user_id, 
        request_date=date(2026, 1, 1), 
        request_type="purchase", 
        requested_amount=Decimal("500"), 
        desired_completion_date=date(2026, 1, 10), 
        allows_partial_payment=False, 
        request_text="Laptop"
    )
    
    option = PaymentOption(
        payment_option_id="opt1", 
        request_id=request_id, 
        payment_method="full_payment", 
        payment_amount=Decimal("500"), 
        number_of_payments=1, 
        first_payment_date=date(2026, 1, 1), 
        payment_frequency_days=None, 
        financing_fee=Decimal("0"), 
        total_payable_amount=Decimal("500")
    )
    
    bundle.profiles.append(profile)
    bundle.requests.append(request)
    bundle.payment_options.append(option)
    
    from code.indexes import build_indexes
    bundle.indexes = build_indexes(
        bundle.requests, 
        bundle.sample_requests, 
        bundle.profiles, 
        bundle.events, 
        bundle.payment_options, 
        bundle.exchange_rates, 
        bundle.messages, 
        bundle.images, 
        bundle.evidence_queue
    )
    bundle.validation_report = type('obj', (object,), {'is_valid': True})
    
    optimizer = PaymentOptimizer(bundle)
    best_plan = optimizer.optimize(request_id)
    
    assert best_plan is None # Should be unsafe

def test_installment_plan_safety():
    bundle = get_empty_bundle()
    
    request_id = "inst_r1"
    user_id = "inst_u1"
    
    profile = FinancialProfile(
        user_id=user_id, 
        home_currency="USD", 
        current_available_balance=Decimal("300"), 
        minimum_balance_to_keep=Decimal("100"), 
        financial_priorities=[], 
        expense_categories_to_protect=[], 
        expense_categories_user_is_willing_to_reduce=[], 
        expense_categories_user_is_willing_to_stop=[], 
        payment_methods_user_will_consider=["full_payment", "installments"], 
        max_installment_months=24
    )
    
    request = Request(
        request_id=request_id, 
        user_id=user_id, 
        request_date=date(2026, 1, 1), 
        request_type="purchase", 
        requested_amount=Decimal("400"), 
        desired_completion_date=date(2026, 5, 1), 
        allows_partial_payment=False, 
        request_text="Laptop"
    )
    
    options = [
        PaymentOption(
            payment_option_id="opt_full", 
            request_id=request_id, 
            payment_method="full_payment", 
            payment_amount=Decimal("400"), 
            number_of_payments=1, 
            first_payment_date=date(2026, 1, 1), 
            payment_frequency_days=None, 
            financing_fee=Decimal("0"), 
            total_payable_amount=Decimal("400")
        ),
        PaymentOption(
            payment_option_id="opt_inst", 
            request_id=request_id, 
            payment_method="installments", 
            payment_amount=Decimal("100"), 
            number_of_payments=4, 
            first_payment_date=date(2026, 1, 1), 
            payment_frequency_days=30, 
            financing_fee=Decimal("0"), 
            total_payable_amount=Decimal("400")
        ),
    ]
    
    # Explicitly add salary events for each month to bypass recurrence detection logic in tests
    salary_dates = [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    for i, s_date in enumerate(salary_dates):
        bundle.events.append(FinancialEvent(
            event_id=f"salary_{i+1}",
            user_id=user_id,
            event_type="income",
            description="Monthly Salary",
            category="salary",
            direction="credit",
            amount=Decimal("200"),
            currency="USD",
            event_date=s_date,
            settlement_date=s_date,
            status="scheduled",
            linked_event_id=None,
            flexibility="fixed",
            minimum_allowed_amount=None
        ))
    
    bundle.profiles.append(profile)
    bundle.requests.append(request)
    bundle.payment_options.extend(options)
    
    from code.indexes import build_indexes
    bundle.indexes = build_indexes(
        bundle.requests, 
        bundle.sample_requests, 
        bundle.profiles, 
        bundle.events, 
        bundle.payment_options, 
        bundle.exchange_rates, 
        bundle.messages, 
        bundle.images, 
        bundle.evidence_queue
    )
    bundle.validation_report = type('obj', (object,), {'is_valid': True})
    
    optimizer = PaymentOptimizer(bundle)
    best_plan = optimizer.optimize(request_id)
    
    assert best_plan is not None
    assert best_plan.payment_option_id == "opt_inst"
    assert best_plan.plan_type == PlanType.INSTALLMENT
