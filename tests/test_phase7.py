"""Tests for Phase 7: Deterministic Spending Adjustment Optimizer.

Verifies:
1. Model formatting (stop:<event_id> and reduce_to:<event_id>:<amount>)
2. Candidate generation mutual exclusivity (STOP and REDUCE never on same event)
3. Candidate generation maximum limit (<= 3 changes)
4. Protected categories never eligible
5. Unwilling categories never eligible
6. Fixed expenses never eligible
7. Already affordable requests require 0 spending changes ('none')
8. Real dataset 1-change STOP: request_74 -> stop:event_6893
9. Real dataset 1-change REDUCE: request_81 -> reduce_to:event_7636:37.50
10. Real dataset 2-change combination: request_64 -> 2 changes
11. Real dataset 3-change combination: request_166 -> 3 changes
12. Scenario isolation (no mutation of FinancialState)
"""

from datetime import date, timedelta
from decimal import Decimal
import pytest

from code.data_loader import load_dataset
from code.financial_state import FinancialState, Recurrence
from code.payment_models import PaymentEvent, PaymentPlan, PlanType
from code.schemas import FinancialEvent, FinancialProfile, PaymentOption, Request
from code.simulation_models import StopExpense, ReduceExpense
from code.spending_models import (
    SpendingAction,
    SpendingChange,
    SpendingChangeSet,
    SpendingOptimizationResult,
)
from code.spending_optimizer import (
    SpendingOptimizer,
    generate_candidate_change_sets,
    get_eligible_spending_changes,
)
from code.state_builder import build_financial_state


def _make_dummy_state(
    balance: Decimal,
    min_keep: Decimal,
    willing_stop: list,
    willing_reduce: list,
    protect: list,
    recurrences: tuple = (),
    options: tuple = (),
    request_date: date = date(2026, 1, 1),
    requested_amount: Decimal = Decimal("500"),
    desired_completion_date: date = date(2026, 1, 15),
    considered_methods: tuple = ("full_payment", "installments"),
) -> FinancialState:
    profile = FinancialProfile(
        user_id="user_test",
        home_currency="USD",
        current_available_balance=balance,
        minimum_balance_to_keep=min_keep,
        financial_priorities=[],
        expense_categories_to_protect=protect,
        expense_categories_user_is_willing_to_reduce=willing_reduce,
        expense_categories_user_is_willing_to_stop=willing_stop,
        payment_methods_user_will_consider=list(considered_methods),
        max_installment_months=12,
    )
    req = Request(
        request_id="req_test",
        user_id="user_test",
        request_date=request_date,
        request_type="purchase",
        requested_amount=requested_amount,
        desired_completion_date=desired_completion_date,
        allows_partial_payment=False,
        request_text="dummy purchase request",
    )
    return FinancialState(
        request=req,
        profile=profile,
        events=(),
        recurrences=recurrences,
        payment_options=options,
        evidence=(),
        evidence_updates=(),
        warnings=(),
        source_events=(),
        exchange_rates={},
    )


def test_spending_change_model_formatting():
    """Verify challenge formatting: stop:<event_id> and reduce_to:<event_id>:<amount>"""
    stop_c = SpendingChange("event_10", SpendingAction.STOP, "streaming")
    assert stop_c.to_output_str() == "stop:event_10"

    red_int = SpendingChange(
        "event_20",
        SpendingAction.REDUCE,
        "dining",
        target_amount=Decimal("100"),
        original_amount=Decimal("250"),
    )
    assert red_int.to_output_str() == "reduce_to:event_20:100"

    red_dec = SpendingChange(
        "event_30",
        SpendingAction.REDUCE,
        "streaming",
        target_amount=Decimal("23.50"),
        original_amount=Decimal("47.00"),
    )
    assert red_dec.to_output_str() == "reduce_to:event_30:23.50"

    cs = SpendingChangeSet((stop_c, red_int))
    assert cs.to_output_str() == "stop:event_10|reduce_to:event_20:100"

    empty_cs = SpendingChangeSet(())
    assert empty_cs.to_output_str() == "none"


def test_candidate_generation_mutual_exclusivity():
    """An event must never appear as both STOP and REDUCE in the same candidate set."""
    changes = [
        SpendingChange("event_01", SpendingAction.STOP, "streaming"),
        SpendingChange(
            "event_01", SpendingAction.REDUCE, "streaming", target_amount=Decimal("10")
        ),
        SpendingChange("event_02", SpendingAction.STOP, "cloud_storage"),
        SpendingChange(
            "event_03", SpendingAction.REDUCE, "dining", target_amount=Decimal("50")
        ),
    ]

    candidate_sets = generate_candidate_change_sets(changes, max_changes=3)

    for cs in candidate_sets:
        event_ids = [c.event_id for c in cs.changes]
        assert len(event_ids) == len(
            set(event_ids)
        ), f"Duplicate event_id in change set: {cs}"
        assert cs.num_changes <= 3


def test_candidate_generation_max_limit():
    """Verify that no candidate set exceeds 3 changes."""
    changes = [
        SpendingChange(f"event_{i}", SpendingAction.STOP, "cat") for i in range(10)
    ]
    candidate_sets = generate_candidate_change_sets(changes, max_changes=3)
    assert all(cs.num_changes <= 3 for cs in candidate_sets)
    assert any(cs.num_changes == 1 for cs in candidate_sets)
    assert any(cs.num_changes == 2 for cs in candidate_sets)
    assert any(cs.num_changes == 3 for cs in candidate_sets)
    assert not any(cs.num_changes > 3 for cs in candidate_sets)


def test_protected_categories_never_eligible():
    """Events in expense_categories_to_protect must never be eligible for modification."""
    rec = Recurrence(
        recurrence_id="rec_01",
        event_id="event_01",
        source_event_ids=("event_01",),
        category="rent",
        direction="debit",
        currency="USD",
        amount=Decimal("500"),
        amount_policy="fixed",
        cadence="calendar_months",
        interval=1,
        anchor_date=date(2026, 1, 1),
        next_expected_date=date(2026, 1, 1),
        end_date=None,
        confidence="high",
        active=True,
        protected=True,
        can_reduce=True,
        can_stop=True,
        minimum_allowed_amount=Decimal("100"),
        explicit_occurrence_dates=(),
        provenance=(),
    )

    state = _make_dummy_state(
        balance=Decimal("1000"),
        min_keep=Decimal("200"),
        willing_stop=["rent", "streaming"],
        willing_reduce=["rent", "streaming"],
        protect=["rent"],  # rent is protected!
        recurrences=(rec,),
    )

    eligible = get_eligible_spending_changes(state)
    assert len(eligible) == 0, "Protected category 'rent' must not be eligible!"


def test_unwilling_categories_never_eligible():
    """Categories not in user willing list must never be eligible."""
    rec = Recurrence(
        recurrence_id="rec_01",
        event_id="event_01",
        source_event_ids=("event_01",),
        category="shopping",
        direction="debit",
        currency="USD",
        amount=Decimal("100"),
        amount_policy="fixed",
        cadence="calendar_months",
        interval=1,
        anchor_date=date(2026, 1, 1),
        next_expected_date=date(2026, 1, 1),
        end_date=None,
        confidence="high",
        active=True,
        protected=False,
        can_reduce=True,
        can_stop=True,
        minimum_allowed_amount=Decimal("50"),
        explicit_occurrence_dates=(),
        provenance=(),
    )

    state = _make_dummy_state(
        balance=Decimal("1000"),
        min_keep=Decimal("200"),
        willing_stop=["streaming"],
        willing_reduce=["dining"],
        protect=[],  # shopping is NOT in willing_stop or willing_reduce
        recurrences=(rec,),
    )

    eligible = get_eligible_spending_changes(state)
    assert len(eligible) == 0, "Unwilling category 'shopping' must not be eligible!"


def test_fixed_expenses_never_eligible():
    """Fixed non-flexible expenses can neither be stopped nor reduced."""
    rec = Recurrence(
        recurrence_id="rec_01",
        event_id="event_01",
        source_event_ids=("event_01",),
        category="streaming",
        direction="debit",
        currency="USD",
        amount=Decimal("20"),
        amount_policy="fixed",
        cadence="calendar_months",
        interval=1,
        anchor_date=date(2026, 1, 1),
        next_expected_date=date(2026, 1, 1),
        end_date=None,
        confidence="high",
        active=True,
        protected=False,
        can_reduce=False,
        can_stop=False,
        minimum_allowed_amount=None,
        explicit_occurrence_dates=(),
        provenance=(),
    )

    state = _make_dummy_state(
        balance=Decimal("1000"),
        min_keep=Decimal("200"),
        willing_stop=["streaming"],
        willing_reduce=["streaming"],
        protect=[],
        recurrences=(rec,),
    )

    eligible = get_eligible_spending_changes(state)
    assert len(eligible) == 0, "Fixed recurrence must not be eligible!"


def test_already_affordable_returns_none():
    """If a payment plan is already safe, zero spending changes are returned."""
    bundle = load_dataset()
    opt = SpendingOptimizer(bundle)
    res = opt.optimize_spending("request_26")

    assert res.affordability_status == "affordable_now"
    assert res.spending_changes_needed == "none"
    assert res.has_spending_changes is False
    assert res.num_spending_changes == 0


def test_evaluation_request_74_single_stop():
    """request_74 requires 1 STOP change to become affordable."""
    bundle = load_dataset()
    opt = SpendingOptimizer(bundle)
    res = opt.optimize_spending("request_74")

    assert res.spending_changes_needed == "stop:event_6893"
    assert res.affordability_status == "affordable_with_plan"
    assert res.recommended_payment_method == "full_payment"
    assert res.has_spending_changes is True
    assert res.num_spending_changes == 1
    assert res.selected_scenario is not None
    assert res.selected_scenario.is_safe is True
    assert res.selected_scenario.completes_by_deadline is True


def test_evaluation_request_81_single_reduce():
    """request_81 requires 1 REDUCE change to become affordable."""
    bundle = load_dataset()
    opt = SpendingOptimizer(bundle)
    res = opt.optimize_spending("request_81")

    assert res.spending_changes_needed == "reduce_to:event_7636:37.50"
    assert res.affordability_status == "affordable_with_plan"
    assert res.recommended_payment_method == "full_payment"
    assert res.has_spending_changes is True
    assert res.num_spending_changes == 1
    assert res.selected_scenario is not None
    assert res.selected_scenario.is_safe is True
    assert res.selected_scenario.completes_by_deadline is True


def test_evaluation_request_64_two_changes():
    """request_64 requires 2 spending changes to become affordable."""
    bundle = load_dataset()
    opt = SpendingOptimizer(bundle)
    res = opt.optimize_spending("request_64")

    assert res.spending_changes_needed == "reduce_to:event_5949:530|reduce_to:event_5951:950"
    assert res.affordability_status == "affordable_with_plan"
    assert res.has_spending_changes is True
    assert res.num_spending_changes == 2
    assert res.selected_scenario is not None
    assert res.selected_scenario.is_safe is True
    assert res.selected_scenario.completes_by_deadline is True


def test_evaluation_request_166_three_changes():
    """request_166 requires 3 spending changes to become affordable."""
    bundle = load_dataset()
    opt = SpendingOptimizer(bundle)
    res = opt.optimize_spending("request_166")

    assert (
        res.spending_changes_needed
        == "reduce_to:event_15208:29.50|reduce_to:event_15209:45.20|reduce_to:event_15245:47"
    )
    assert res.affordability_status == "affordable_with_plan"
    assert res.has_spending_changes is True
    assert res.num_spending_changes == 3
    assert res.selected_scenario is not None
    assert res.selected_scenario.is_safe is True
    assert res.selected_scenario.completes_by_deadline is True


def test_scenario_isolation_no_mutation():
    """Running optimization must not mutate the financial state or its collections."""
    bundle = load_dataset()
    opt = SpendingOptimizer(bundle)

    req = opt._get_request("request_74")
    state_before = build_financial_state(bundle, req)
    recurrences_before = tuple(state_before.recurrences)
    events_before = tuple(state_before.events)
    balance_before = state_before.profile.current_available_balance

    res = opt.optimize_spending("request_74")

    state_after = build_financial_state(bundle, req)
    assert len(state_after.recurrences) == len(recurrences_before)
    assert len(state_after.events) == len(events_before)
    assert state_after.profile.current_available_balance == balance_before
