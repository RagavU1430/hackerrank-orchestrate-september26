from datetime import date
from decimal import Decimal

import pytest

from code.final_validator import FinalOutputValidationError, validate_decision
from code.financial_agent import CustomerDecision
from code.state_builder import build_financial_state
from code.data_loader import load_dataset


@pytest.fixture(scope="module")
def bundle():
    return load_dataset()


def test_final_validator_rejects_unsafe_not_affordable_plan(bundle):
    request = bundle.requests[0]
    state = build_financial_state(bundle, request)
    decision = CustomerDecision(
        request_id=request.request_id, amount_safe_to_pay=Decimal("0"),
        affordability_status="not_affordable", recommended_payment_method="full_payment",
        payment_plan=f"{request.request_date}:1", earliest_date_for_full_payment=request.request_date,
        spending_changes_needed="none", decision_explanation="Invalid plan.", evidence_summary=[], warnings=[],
    )
    with pytest.raises(FinalOutputValidationError):
        validate_decision(decision, request, state)


def test_final_validator_rejects_wrong_request_mapping(bundle):
    request = bundle.requests[0]
    state = build_financial_state(bundle, request)
    decision = CustomerDecision(
        request_id="wrong", amount_safe_to_pay=Decimal("0"),
        affordability_status="not_affordable", recommended_payment_method="not_recommended",
        payment_plan="none", earliest_date_for_full_payment=None,
        spending_changes_needed="none", decision_explanation="No safe plan.", evidence_summary=[], warnings=[],
    )
    with pytest.raises(FinalOutputValidationError):
        validate_decision(decision, request, state)
