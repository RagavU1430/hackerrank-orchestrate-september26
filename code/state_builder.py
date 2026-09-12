"""Deterministic request-date reconstruction over the Phase 1 DatasetBundle."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import logging

from code.evidence import apply_fields, ordered_updates, validate_updates
from code.financial_state import (
    EvidenceMetadata, EventState, FinancialState, Money, Provenance, StateWarning,
)
from code.normalizers import VALID_CURRENCIES
from code.recurrence import infer_recurrences

logger = logging.getLogger(__name__)
STATUSES = {"settled", "pending", "scheduled", "cancelled", "failed", "unrealized"}
FLEXIBILITIES = {"fixed", "reducible", "stoppable", "reducible_or_stoppable"}


def normalize_money(amount, currency, home_currency, settlement_date, rates):
    """Exact supplied direction and settlement date only; never carry rates forward."""
    if amount is not None:
        _finite(amount, "Monetary amount", True)
    if currency not in VALID_CURRENCIES:
        return Money(amount, currency, None, home_currency, None, settlement_date, "unresolved_currency")
    if amount is None:
        return Money(None, currency, None, home_currency, None, settlement_date, "unresolved_amount")
    if currency == home_currency:
        return Money(amount, currency, amount, home_currency, Decimal(1), None, "known")
    rate = rates.get((currency, home_currency, settlement_date))
    if rate is None or not rate.is_finite() or rate <= 0:
        return Money(amount, currency, None, home_currency, None, settlement_date, "unresolved_rate")
    return Money(amount, currency, amount * rate, home_currency, rate, settlement_date, "known")


def _finite(value, label, nonnegative=False):
    if not isinstance(value, Decimal) or not value.is_finite() or (nonnegative and value < 0):
        raise ValueError(f"{label} must be a {'nonnegative ' if nonnegative else ''}finite Decimal")


def _validate_inputs(profile, request, events):
    if profile is None or profile.user_id != request.user_id:
        raise ValueError("Request profile is missing or belongs to another user")
    if not request.request_id or not request.user_id or type(request.request_date) is not date:
        raise ValueError("Request identity and date must be valid")
    if profile.home_currency not in VALID_CURRENCIES:
        raise ValueError("Profile home currency is unknown")
    _finite(profile.current_available_balance, "Starting balance")
    _finite(profile.minimum_balance_to_keep, "Minimum balance", True)
    if profile.max_installment_months is not None and (
            type(profile.max_installment_months) is not int or profile.max_installment_months <= 0):
        raise ValueError("Installment months must be positive or absent")
    seen = set()
    for e in events:
        if not e.event_id or e.event_id in seen or e.user_id != request.user_id:
            raise ValueError("Duplicate, empty, or wrong-user event identifier")
        seen.add(e.event_id)
        if type(e.event_date) is not date or (e.settlement_date is not None and type(e.settlement_date) is not date):
            raise ValueError("Invalid event dates")
        if e.status not in STATUSES or e.direction not in {"credit", "debit", "non_cash"} or e.flexibility not in FLEXIBILITIES:
            raise ValueError("Unknown event status, direction, or flexibility")
        if e.amount is not None:
            _finite(e.amount, "Event amount", True)
        if e.minimum_allowed_amount is not None:
            _finite(e.minimum_allowed_amount, "Minimum event amount", True)


def _classification(e, request_date):
    if e.event_date > request_date and e.status != "scheduled":
        return "not_yet_known", "not_yet_known", None
    if e.status in {"failed", "cancelled"}:
        return e.status, "excluded", None
    if e.direction == "non_cash" or e.status == "unrealized":
        return "non_cash", "non_cash", None
    future = e.settlement_date is not None and e.settlement_date > request_date
    if e.status == "pending":
        return "pending", "pending_debit" if e.direction == "debit" else "pending_income", (
            max(request_date, e.settlement_date or request_date) if e.direction == "debit" else None)
    if e.status == "scheduled":
        temporal = "scheduled_future" if future else "scheduled_due"
        if e.direction == "debit":
            return temporal, "scheduled_debit", max(request_date, e.settlement_date or request_date)
        # The dataset contract explicitly supplies next confirmed salary rows.
        # Other scheduled credits are not confirmation of bonuses/refunds/etc.
        if e.event_type == "income" and e.category == "salary" and future:
            return temporal, "confirmed_future_income", e.settlement_date
        return temporal, "uncertain_income", None
    if e.settlement_date is None or future:
        return "awaiting_settlement", "unsettled_debit" if e.direction == "debit" else "uncertain_income", (
            e.settlement_date or request_date if e.direction == "debit" else None)
    return ("current" if e.settlement_date == request_date else "historical",
            "settled_debit" if e.direction == "debit" else "settled_income", None)


def _linked_supersessions(events, request_date, warnings):
    by_id = {e.event_id: e for e in events}
    superseded = {}
    for e in sorted(events, key=lambda e: (e.event_date, e.event_id)):
        if not e.linked_event_id:
            continue
        chain, ancestor = set(), e
        while ancestor and ancestor.event_id not in chain:
            chain.add(ancestor.event_id)
            ancestor = by_id.get(ancestor.linked_event_id)
        if ancestor:
            warnings.append(StateWarning("DATASET ISSUE", "invalid_lifecycle_link", e.event_id,
                                         "Cyclic lifecycle link retained without deduplication."))
            continue
        old = by_id.get(e.linked_event_id)
        if old is None or old.event_id == e.event_id or old.event_date > e.event_date:
            warnings.append(StateWarning("DATASET ISSUE", "invalid_lifecycle_link", e.event_id,
                                         "Linked predecessor is missing, self-linked, or later than this event."))
            continue
        if e.event_date > request_date:
            continue
        # Same-direction terminal updates can replace an unresolved authorization.
        # Refunds and sales have opposite direction: never erase their originals.
        same_obligation = (e.direction == old.direction and e.category == old.category
                           and e.currency == old.currency and e.event_type == old.event_type)
        if same_obligation and old.status in {"pending", "scheduled"} and e.status in {"settled", "cancelled", "failed"}:
            if e.status != "settled" or (e.settlement_date and e.settlement_date <= request_date):
                ancestor = old
                visited = {e.event_id}
                while ancestor and ancestor.event_id not in visited:
                    visited.add(ancestor.event_id)
                    compatible = (ancestor.direction == e.direction and ancestor.category == e.category
                                  and ancestor.currency == e.currency and ancestor.event_type == e.event_type)
                    if not compatible or ancestor.status not in {"pending", "scheduled"}:
                        break
                    superseded[ancestor.event_id] = e.event_id
                    ancestor = by_id.get(ancestor.linked_event_id)
        elif same_obligation and old.status == "settled" and e.status in {"pending", "scheduled", "settled"}:
            # A later pending charge can be an actual second debit. A link is not
            # evidence of reversal or identity. Reserve until evidence resolves it.
            warnings.append(StateWarning("UNRESOLVED EVIDENCE", "ambiguous_linked_charge", e.event_id,
                                         "Separate same-direction lifecycle charge retained; link alone cannot prove duplication."))
    return superseded


def reconstruct_state(profile, request, source_events, rates, options=(), metadata=(), updates=()):
    _validate_inputs(profile, request, source_events)
    updates = ordered_updates(updates)
    validate_updates(updates, source_events, metadata, request)
    warnings = []
    if profile.current_available_balance < profile.minimum_balance_to_keep:
        warnings.append(StateWarning("DATASET ISSUE", "balance_below_minimum", profile.user_id,
                                     "Authoritative balance is below the requested reserve; preserved unchanged."))
    if set(profile.payment_methods_user_will_consider) - {"full_payment", "partial_payment", "installments"}:
        warnings.append(StateWarning("DATASET ISSUE", "unsupported_payment_preference", profile.user_id,
                                     "Unrecognized payment preference retained."))
    if ("installments" in profile.payment_methods_user_will_consider) != (profile.max_installment_months is not None):
        warnings.append(StateWarning("DATASET ISSUE", "installment_preference_conflict", profile.user_id,
                                     "Installment acceptance and maximum months disagree."))
    originals = list(source_events)
    for u in updates:
        if u.operation == "add" and u.confidence == "confirmed" and u.observed_date <= request.request_date:
            originals.append(u.new_value)
    events = tuple(apply_fields(e, updates, "event", e.event_id, request.request_date, request.request_date)
                   for e in originals)
    _validate_inputs(profile, request, events)
    supersessions = _linked_supersessions(events, request.request_date, warnings)
    items = []
    for e in sorted(events, key=lambda e: (e.event_date, e.event_id)):
        temporal, cash, forecast = _classification(e, request.request_date)
        superseded_by = supersessions.get(e.event_id)
        if superseded_by:
            cash, forecast = "superseded", None
        money = normalize_money(e.amount, e.currency, profile.home_currency, e.settlement_date, rates)
        if money.amount_status != "known":
            kind = "UNRESOLVED EVIDENCE" if e.amount is None else "DATASET ISSUE"
            warnings.append(StateWarning(kind, money.amount_status, e.event_id,
                                         "Monetary value remains unresolved; never substitute zero."))
        if e.settlement_date is None and cash != "non_cash":
            warnings.append(StateWarning("DATASET ISSUE", "missing_settlement_date", e.event_id,
                                         "Cash settlement date is unknown; outgoing obligation retained."))
        if e.settlement_date and e.settlement_date < e.event_date:
            warnings.append(StateWarning("DATASET ISSUE", "settlement_before_event", e.event_id,
                                         "Settlement precedes event date; source dates retained."))
        if temporal == "awaiting_settlement" or (e.status == "scheduled" and e.settlement_date and e.settlement_date < request.request_date):
            warnings.append(StateWarning("DATASET ISSUE", "status_date_conflict", e.event_id,
                                         "Status and settlement timing disagree; no unconfirmed credit counted."))
        protected = e.category in profile.expense_categories_to_protect
        reduce = e.direction == "debit" and e.flexibility in {"reducible", "reducible_or_stoppable"} and e.category in profile.expense_categories_user_is_willing_to_reduce
        stop = e.direction == "debit" and e.flexibility in {"stoppable", "reducible_or_stoppable"} and e.category in profile.expense_categories_user_is_willing_to_stop
        if protected and e.flexibility != "fixed":
            warnings.append(StateWarning("DATASET ISSUE", "protected_flexibility_conflict", e.event_id,
                                         "Protected category overrides event flexibility."))
        if e.minimum_allowed_amount is not None and e.amount is not None and e.minimum_allowed_amount > e.amount:
            warnings.append(StateWarning("DATASET ISSUE", "minimum_exceeds_amount", e.event_id,
                                         "Reduction disabled because minimum amount exceeds event amount."))
            reduce = False
        # Missing minimum is not permission to reduce to zero.
        if reduce and e.minimum_allowed_amount is None:
            warnings.append(StateWarning("UNRESOLVED EVIDENCE", "missing_reduction_floor", e.event_id,
                                         "Reduction eligibility awaits a minimum allowed amount."))
            reduce = False
        provenance = [Provenance("financial_event", e.event_id, "event", e.event_date, "known"),
                      Provenance("profile", profile.user_id, "preferences", request.request_date, "known")]
        provenance.extend(Provenance(u.source_type, u.source_id, u.field, u.effective_date, u.confidence)
                          for u in updates if u.target_type == "event" and u.target_id == e.event_id
                          and u.observed_date <= request.request_date and u.effective_date <= request.request_date
                          and u.confidence == "confirmed")
        items.append(EventState(e, money, temporal, cash, forecast, protected,
                               reduce and not protected, stop and not protected, superseded_by, tuple(provenance)))
    recurrences = infer_recurrences(items, request.request_date)
    recurrence_ids = {r.recurrence_id for r in recurrences}
    if any(u.target_type == "recurrence" and u.target_id not in recurrence_ids for u in updates):
        raise ValueError("Evidence targets an unknown inferred recurrence")
    # Validate the complete known timeline now, including future amendments.
    # A bad old_value must not wait until simulation to become a failure.
    for e in originals:
        known = [u.effective_date for u in updates if u.target_type == "event" and u.target_id == e.event_id
                 and u.confidence == "confirmed" and u.observed_date <= request.request_date]
        if known:
            future_e = apply_fields(e, updates, "event", e.event_id, max(known), request.request_date)
            _validate_inputs(profile, request, (future_e,))
    for r in recurrences:
        known = [u.effective_date for u in updates if u.target_type == "recurrence" and u.target_id == r.recurrence_id
                 and u.confidence == "confirmed" and u.observed_date <= request.request_date]
        if known:
            apply_fields(r, updates, "recurrence", r.recurrence_id, max(known), request.request_date)
    adjusted = []
    for r in recurrences:
        r = apply_fields(r, updates, "recurrence", r.recurrence_id, request.request_date, request.request_date)
        if r.end_date and r.end_date < request.request_date:
            r = replace(r, active=False)
        adjusted.append(r)
        if r.confidence.startswith("stale"):
            warnings.append(StateWarning("UNRESOLVED EVIDENCE", "stale_recurrence", r.recurrence_id,
                                         "Expected occurrence is missing: income inactive; debit obligation retained conservatively."))
    for m in metadata:
        resolved = any(u.source_type == m.source_type and u.source_id == m.source_id
                       and u.confidence == "confirmed" and u.observed_date <= request.request_date for u in updates)
        if not resolved:
            warnings.append(StateWarning("UNRESOLVED EVIDENCE", "unparsed_" + m.source_type, m.source_id,
                                         "Supporting content has not been interpreted by Phase 2."))
    for u in updates:
        if u.confidence != "confirmed" or u.observed_date > request.request_date:
            warnings.append(StateWarning("UNRESOLVED EVIDENCE", "inactive_evidence_update", u.source_id,
                                         "Uncertain or not-yet-observed update retained without changing financial facts."))
    state = FinancialState(request, profile, tuple(items), tuple(adjusted), tuple(options), tuple(metadata),
                           updates, tuple(sorted(set(warnings), key=lambda w: (w.kind, w.code, w.source_id))),
                           tuple(source_events), dict(rates))
    validate_financial_state(state)
    logger.info("State %s: %d events, %d recurrences, %d pending debits, %d confirmed future inflows, %d warnings; validation passed",
                state.request_id, len(items), len(recurrences), len(state.pending_debits),
                len(state.future_confirmed_income), len(state.warnings))
    return state


def build_financial_state(dataset_bundle, request, evidence_updates=()):
    """Public entry point. Uses only Phase 1 indexes and validated records."""
    b = dataset_bundle
    if b.indexes is None or b.validation_report is None or not b.validation_report.is_valid:
        raise ValueError("Phase 2 requires a validated, indexed DatasetBundle")
    if isinstance(request, str):
        request = b.indexes.requests_by_id.get(request)
    if request is None:
        raise ValueError("Unknown request")
    profile = b.indexes.profiles_by_user_id.get(request.user_id)
    metadata = []
    for m in b.indexes.messages_by_user_id.get(request.user_id, ()):
        if m.request_id in {None, request.request_id} and m.sent_at.date() <= request.request_date:
            metadata.append(EvidenceMetadata("message", m.message_id, m.related_event_id, m.sent_at.date(), "unparsed"))
    for i in b.indexes.images_by_user_id.get(request.user_id, ()):
        if i.request_id in {None, request.request_id}:
            metadata.append(EvidenceMetadata("image", i.image_id, i.related_event_id, None,
                                             "unparsed" if i.file_exists else "missing"))
    return reconstruct_state(deepcopy(profile), request, tuple(b.indexes.get_user_events(request.user_id)),
                             b.indexes.exchange_rates_by_pair_and_date,
                             b.indexes.get_request_payment_options(request.request_id),
                             tuple(sorted(metadata, key=lambda m: (m.source_type, m.source_id))), evidence_updates)


def validate_financial_state(state):
    _validate_inputs(state.profile, state.request, tuple(i.event for i in state.events))
    ids = {i.event_id for i in state.events}
    for i in state.events:
        if i.protected and (i.can_reduce or i.can_stop):
            raise ValueError("Protected expense became actionable")
        if i.event.amount is None and i.money.normalized_amount is not None:
            raise ValueError("Unknown money was fabricated")
        if i.cash_class in {"settled_income", "settled_debit", "excluded", "superseded", "non_cash", "pending_income", "uncertain_income", "not_yet_known"} and i.forecast_date is not None:
            raise ValueError("Non-forecast event acquired a cash forecast date")
        if i.forecast_date is not None and i.forecast_date < state.request_date:
            raise ValueError("Forecast obligation predates starting balance")
    used = set()
    for r in state.recurrences:
        if r.interval <= 0 or r.next_expected_date < state.request_date or not set(r.source_event_ids) <= ids:
            raise ValueError("Invalid recurrence dates or provenance")
        if used.intersection(r.source_event_ids):
            raise ValueError("Historical event counted in multiple recurrence patterns")
        used.update(r.source_event_ids)
        if r.protected and (r.can_reduce or r.can_stop):
            raise ValueError("Protected recurrence became actionable")
    return True
