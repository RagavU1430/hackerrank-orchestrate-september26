"""Tests for Phase 5: Deterministic Affordability Decision Engine."""

from datetime import date, timedelta
from decimal import Decimal
import pytest

from code.affordability import (
    calculate_amount_safe_to_pay,
    evaluate_affordability,
)
from code.affordability_models import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    NOT_AFFORDABLE,
    INVALID_REQUEST,
    PaymentEvaluation,
    ScenarioEvaluation,
)
from code.data_loader import load_dataset
from code.date_search import find_earliest_safe_full_payment_date
from code.financial_state import (
    EventState,
    FinancialState,
    Money,
    Recurrence,
)
from code.scenario_evaluator import (
    evaluate_full_payment,
    evaluate_scenario,
)
from code.schemas import FinancialEvent, FinancialProfile, Request
from code.simulation_models import PaymentInjection
from code.state_builder import build_financial_state


def _dummy_money(amount: Decimal, currency: str = "USD") -> Money:
    return Money(
        original_amount=amount,
        original_currency=currency,
        normalized_amount=amount,
        normalized_currency=currency,
        exchange_rate_used=Decimal("1"),
        exchange_rate_date=None,
        amount_status="known",
    )


def _make_state(
    balance: Decimal,
    min_keep: Decimal,
    request_amount: Decimal,
    request_date: date = date(2026, 1, 1),
    considered_methods: tuple = ("full_payment", "installments"),
    events: tuple = (),
    recurrences: tuple = (),
) -> FinancialState:
    profile = FinancialProfile(
        user_id="user_test",
        home_currency="USD",
        current_available_balance=balance,
        minimum_balance_to_keep=min_keep,
        financial_priorities=["emergency_fund"],
        expense_categories_to_protect=["housing"],
        expense_categories_user_is_willing_to_reduce=[],
        expense_categories_user_is_willing_to_stop=[],
        payment_methods_user_will_consider=list(considered_methods),
        max_installment_months=6,
    )
    req = Request(
        request_id="req_test",
        user_id="user_test",
        request_date=request_date,
        request_type="purchase",
        requested_amount=request_amount,
        desired_completion_date=request_date + timedelta(days=30),
        allows_partial_payment=True,
        request_text="Can I buy this?",
    )
    return FinancialState(
        request=req,
        profile=profile,
        events=events,
        recurrences=recurrences,
        payment_options=(),
        evidence=(),
        evidence_updates=(),
        warnings=(),
        source_events=tuple(e.event for e in events),
        exchange_rates={},
    )


class TestAffordabilityCalculation:
    """Core mathematical bounds and safe amount logic."""

    def test_full_affordability(self):
        """When minimum headroom exceeds requested amount, full payment is safe."""
        state = _make_state(balance=Decimal("1000"), min_keep=Decimal("200"), request_amount=Decimal("300"))
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("300")
        assert dec.affordability_status == AFFORDABLE_NOW
        assert dec.earliest_date_for_full_payment == state.request_date
        assert dec.decision_diagnostics.is_fully_affordable is True
        assert dec.decision_diagnostics.is_partially_affordable is False
        assert dec.decision_diagnostics.full_payment_safe is True

    def test_partial_affordability(self):
        """When minimum headroom is between 0 and requested amount."""
        state = _make_state(balance=Decimal("500"), min_keep=Decimal("200"), request_amount=Decimal("400"))
        # Headroom is 300, requested is 400
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("300")
        assert dec.decision_diagnostics.is_partially_affordable is True
        assert dec.decision_diagnostics.is_fully_affordable is False

    def test_no_affordability_zero_headroom(self):
        """When available balance equals minimum keep, safe amount is 0."""
        state = _make_state(balance=Decimal("200"), min_keep=Decimal("200"), request_amount=Decimal("100"))
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("0")
        assert dec.decision_diagnostics.is_not_affordable_now is True
        assert dec.affordability_status == NOT_AFFORDABLE

    def test_no_affordability_under_breach(self):
        """When baseline balance is already below minimum reserve."""
        state = _make_state(balance=Decimal("150"), min_keep=Decimal("200"), request_amount=Decimal("100"))
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("0")
        assert dec.decision_diagnostics.is_not_affordable_now is True
        assert dec.affordability_status == NOT_AFFORDABLE

    def test_zero_requested_amount(self):
        """Requested amount of 0 yields safe amount 0 and affordable_now."""
        state = _make_state(balance=Decimal("500"), min_keep=Decimal("200"), request_amount=Decimal("0"))
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("0")
        assert dec.affordability_status == AFFORDABLE_NOW
        assert dec.earliest_date_for_full_payment == state.request_date

    def test_negative_requested_amount_rejected(self):
        """Negative requested amount raises ValueError."""
        state = _make_state(balance=Decimal("500"), min_keep=Decimal("200"), request_amount=Decimal("-50"))
        with pytest.raises(ValueError) as exc:
            evaluate_affordability(state)
        assert INVALID_REQUEST in str(exc.value)

    def test_exact_minimum_balance_not_violation(self):
        """Balance exactly reaching minimum reserve is valid and safe."""
        # Balance 500, min 200, request 300 -> ending balance 200 == min 200
        state = _make_state(balance=Decimal("500"), min_keep=Decimal("200"), request_amount=Decimal("300"))
        ev = evaluate_full_payment(state, state.request, state.request_date)
        assert ev.safe is True
        assert ev.minimum_headroom == Decimal("0")
        assert ev.minimum_balance_observed == Decimal("200")


class TestScenarioEvaluation:
    """Scenario evaluator with payment injection and state immutability."""

    def test_state_immutability(self):
        """Evaluating scenarios must never mutate the original FinancialState."""
        state = _make_state(balance=Decimal("1000"), min_keep=Decimal("200"), request_amount=Decimal("300"))
        orig_balance = state.available_balance
        orig_min = state.minimum_balance_to_keep

        dec = evaluate_affordability(state)
        assert state.available_balance == orig_balance
        assert state.minimum_balance_to_keep == orig_min

    def test_evaluate_scenario_arbitrary_payments(self):
        """evaluate_scenario evaluates arbitrary sets of PaymentInjection objects."""
        state = _make_state(balance=Decimal("1000"), min_keep=Decimal("200"), request_amount=Decimal("600"))
        # Two payments of 250 on day 5 and day 10
        p1 = PaymentInjection(payment_date=date(2026, 1, 5), amount=Decimal("250"))
        p2 = PaymentInjection(payment_date=date(2026, 1, 10), amount=Decimal("250"))
        scen = evaluate_scenario(state, payment_events=[p1, p2])
        assert scen.safe is True
        assert scen.minimum_observed_balance == Decimal("500")
        assert scen.minimum_headroom == Decimal("300")


class TestDateSearchAndFutureAffordability:
    """Earliest safe date identification over 90-day horizon."""

    def test_mid_forecast_breach_rejects_immediate_payment(self):
        """A payment that looks safe on day 0 is rejected if a scheduled debit creates a future breach."""
        # Balance 1000, min 200. On day 10, scheduled debit of 700.
        # Immediate headroom on day 0 seems to be 800, but day 10 balance drops to 300 (headroom 100).
        ev_sched = EventState(
            event=FinancialEvent(
                event_id="bill_1",
                user_id="user_test",
                event_type="expense",
                description="Upcoming bill",
                category="utilities",
                direction="debit",
                amount=Decimal("700"),
                currency="USD",
                event_date=date(2026, 1, 10),
                settlement_date=date(2026, 1, 10),
                status="scheduled",
                linked_event_id=None,
                flexibility="fixed",
                minimum_allowed_amount=None,
            ),
            money=_dummy_money(Decimal("700")),
            temporal_status="future",
            cash_class="scheduled_debit",
            forecast_date=date(2026, 1, 10),
            protected=True,
            can_reduce=False,
            can_stop=False,
            superseded_by=None,
            provenance=(),
        )
        state = _make_state(
            balance=Decimal("1000"),
            min_keep=Decimal("200"),
            request_amount=Decimal("300"),  # 300 > minimum headroom 100
            events=(ev_sched,),
        )
        dec = evaluate_affordability(state)
        # Safe amount today is only 100 (due to Day 10 bill)
        assert dec.amount_safe_to_pay == Decimal("100")
        assert dec.decision_diagnostics.full_payment_safe is False
        assert dec.affordability_status == NOT_AFFORDABLE

    def test_salary_timing_future_safe_date(self):
        """Payment unsafe today becomes safe on confirmed salary settlement date."""
        # Balance 400, min 200 (headroom 200). Request is 500.
        # Confirmed salary of 1000 arrives on 2026-01-15.
        salary_event = EventState(
            event=FinancialEvent(
                event_id="sal_1",
                user_id="user_test",
                event_type="income",
                description="Confirmed salary",
                category="salary",
                direction="credit",
                amount=Decimal("1000"),
                currency="USD",
                event_date=date(2026, 1, 15),
                settlement_date=date(2026, 1, 15),
                status="scheduled",
                linked_event_id=None,
                flexibility="fixed",
                minimum_allowed_amount=None,
            ),
            money=_dummy_money(Decimal("1000")),
            temporal_status="future",
            cash_class="confirmed_future_income",
            forecast_date=date(2026, 1, 15),
            protected=True,
            can_reduce=False,
            can_stop=False,
            superseded_by=None,
            provenance=(),
        )
        state = _make_state(
            balance=Decimal("400"),
            min_keep=Decimal("200"),
            request_amount=Decimal("500"),
            events=(salary_event,),
        )
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("200")
        assert dec.affordability_status == AFFORDABLE_LATER
        assert dec.earliest_date_for_full_payment == date(2026, 1, 15)
        assert dec.decision_diagnostics.is_future_affordable is True


class TestMonotonicityAndInvariants:
    """Property tests for financial decision integrity."""

    def test_monotonicity_of_safe_amount(self):
        """Increasing requested amount on identical state never increases amount_safe_to_pay."""
        state1 = _make_state(balance=Decimal("1000"), min_keep=Decimal("300"), request_amount=Decimal("200"))
        state2 = _make_state(balance=Decimal("1000"), min_keep=Decimal("300"), request_amount=Decimal("500"))
        state3 = _make_state(balance=Decimal("1000"), min_keep=Decimal("300"), request_amount=Decimal("800"))

        dec1 = evaluate_affordability(state1)
        dec2 = evaluate_affordability(state2)
        dec3 = evaluate_affordability(state3)

        # For state1 (req=200, headroom=700), safe=200
        # For state2 (req=500, headroom=700), safe=500
        # For state3 (req=800, headroom=700), safe=700 (capped at headroom)
        assert dec1.amount_safe_to_pay == Decimal("200")
        assert dec2.amount_safe_to_pay == Decimal("500")
        assert dec3.amount_safe_to_pay == Decimal("700")

    def test_user_only_considers_installments_status(self):
        """When full payment is safe today but user will not consider full_payment -> affordable_with_plan."""
        state = _make_state(
            balance=Decimal("1000"),
            min_keep=Decimal("200"),
            request_amount=Decimal("300"),
            considered_methods=("installments",),  # no full_payment
        )
        dec = evaluate_affordability(state)
        assert dec.amount_safe_to_pay == Decimal("300")
        assert dec.earliest_date_for_full_payment == state.request_date
        assert dec.affordability_status == AFFORDABLE_WITH_PLAN


class TestDatasetIntegration:
    """Integration checks on real dataset requests."""

    def test_real_dataset_evaluation_requests(self):
        """Verify on real evaluation requests from dataset."""
        bundle = load_dataset()
        for req in bundle.requests[:10]:
            state = build_financial_state(bundle, req)
            dec = evaluate_affordability(state, req)

            # Invariant checks
            assert Decimal("0") <= dec.amount_safe_to_pay <= req.requested_amount
            assert dec.affordability_status in {AFFORDABLE_NOW, AFFORDABLE_WITH_PLAN, AFFORDABLE_LATER, NOT_AFFORDABLE}
            if dec.affordability_status == AFFORDABLE_NOW:
                assert dec.earliest_date_for_full_payment == req.request_date
                assert dec.amount_safe_to_pay == req.requested_amount
