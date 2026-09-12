"""Synthetic financial semantics plus full-dataset regression; no answer labels."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from code.data_loader import load_dataset
from code.evidence import apply_evidence_updates, event_on_date, recurrence_on_date
from code.financial_state import EvidenceUpdate, state_snapshot
from code.indexes import build_indexes
from code.recurrence import advance
from code.schemas import DatasetBundle, FinancialEvent, FinancialProfile, ImageReference, Message, Request, ExchangeRate
from code.state_builder import build_financial_state, normalize_money, validate_financial_state
from code.state_diagnostics import validate_states, write_snapshot
from code.validators import ValidationResult

D = Decimal
TODAY = date(2026, 4, 2)


def profile(**changes):
    return replace(FinancialProfile("alice", "USD", D("1000"), D("200"), ["education"],
                                   ["rent"], ["gaming"], ["streaming"],
                                   ["full_payment", "partial_payment", "installments"], 3), **changes)


def request(**changes):
    return replace(Request("test_request", "alice", TODAY, "purchase", D("100"),
                           date(2026, 5, 1), True, "Synthetic request"), **changes)


def event(identifier="one", **changes):
    return replace(FinancialEvent(identifier, "alice", "expense", "Recurring service", "gaming", "debit",
                                 D("50"), "USD", date(2026, 4, 1), date(2026, 4, 1),
                                 "settled", None, "fixed", None), **changes)


def bundle(events=(), profiles=None, requests=None, messages=(), images=(), rates=()):
    b = DatasetBundle(profiles=list(profiles or [profile()]), requests=list(requests or [request()]),
                      events=list(events), messages=list(messages), images=list(images),
                      exchange_rates=list(rates), validation_report=ValidationResult())
    b.indexes = build_indexes(b.requests, [], b.profiles, b.events, [], b.exchange_rates,
                             b.messages, b.images, [])
    return b


def history(**changes):
    return [event(f"series_{month}", event_date=date(2026, month, 1),
                  settlement_date=date(2026, month, 1), **changes) for month in (1, 2, 3, 4)]


def message(identifier="notice", **changes):
    return replace(Message(identifier, "alice", None, None, datetime(2026, 4, 1, tzinfo=timezone.utc),
                           "employer", "Untrusted content is not parsed"), **changes)


class ProfileTests(unittest.TestCase):
    def test_authoritative_balance_and_preferences(self):
        s = build_financial_state(bundle([event(amount=D("99999"))]), request())
        self.assertEqual(s.available_balance, D("1000"))
        self.assertEqual(s.minimum_balance_to_keep, D("200"))
        self.assertEqual(s.profile.payment_methods_user_will_consider,
                         ["full_payment", "partial_payment", "installments"])
        self.assertEqual(s.profile.financial_priorities, ["education"])

    def test_missing_profile_minimum_and_invalid_money(self):
        for p in [profile(user_id="other"), profile(minimum_balance_to_keep=None),
                  profile(minimum_balance_to_keep=D("-1")), profile(current_available_balance=D("NaN"))]:
            with self.subTest(p=p), self.assertRaises(ValueError):
                build_financial_state(bundle(profiles=[p]), request())

    def test_empty_preferences_and_below_minimum(self):
        p = profile(current_available_balance=D("-3"), expense_categories_to_protect=[],
                    expense_categories_user_is_willing_to_reduce=[], expense_categories_user_is_willing_to_stop=[],
                    payment_methods_user_will_consider=[], max_installment_months=None)
        s = build_financial_state(bundle(profiles=[p]), request())
        self.assertEqual(s.available_balance, D("-3"))
        self.assertEqual(s.profile.payment_methods_user_will_consider, [])
        self.assertIn("balance_below_minimum", {w.code for w in s.warnings})

    def test_personalized_two_users(self):
        p2 = profile(user_id="bob", minimum_balance_to_keep=D("700"),
                     payment_methods_user_will_consider=["full_payment"], max_installment_months=None,
                     expense_categories_user_is_willing_to_reduce=[])
        r2 = request(request_id="second", user_id="bob")
        events = history(flexibility="reducible", minimum_allowed_amount=D("20"))
        events += [replace(e, event_id="bob_"+e.event_id, user_id="bob", amount=D("80")) for e in events]
        b = bundle(events, [profile(), p2], [request(), r2])
        first, second = [build_financial_state(b, r) for r in b.requests]
        self.assertEqual(first.available_balance, second.available_balance)
        self.assertNotEqual(first.minimum_balance_to_keep, second.minimum_balance_to_keep)
        self.assertTrue(first.flexible_expenses)
        self.assertFalse(second.flexible_expenses)
        self.assertNotEqual(first.recurring_outflows[0].amount, second.recurring_outflows[0].amount)

    def test_bundle_guard_and_duplicate_event(self):
        b = bundle()
        b.validation_report.add("ERROR", "test", None, None, "invalid")
        with self.assertRaises(ValueError):
            build_financial_state(b, request())
        with self.assertRaises(ValueError):
            build_financial_state(bundle([event(), event()]), request())

    def test_unsupported_payment_preference_is_visible(self):
        s = build_financial_state(bundle(profiles=[profile(payment_methods_user_will_consider=["crypto"])]), request())
        self.assertIn("unsupported_payment_preference", {w.code for w in s.warnings})


class CashClassificationTests(unittest.TestCase):
    def test_income_states(self):
        events = [event("settled", direction="credit", event_type="income", category="salary"),
                  event("pending", direction="credit", event_type="income", category="salary", status="pending"),
                  event("future", direction="credit", event_type="income", category="salary", status="scheduled",
                        event_date=date(2026, 4, 15), settlement_date=date(2026, 4, 15)),
                  event("bonus", direction="credit", event_type="income", category="bonus", status="scheduled",
                        settlement_date=date(2026, 4, 15)),
                  event("valuation", direction="non_cash", event_type="investment_valuation", status="unrealized",
                        settlement_date=None)]
        s = build_financial_state(bundle(events), request())
        self.assertEqual([e.event_id for e in s.confirmed_income], ["settled"])
        self.assertEqual([e.event_id for e in s.pending_income], ["pending"])
        self.assertEqual([e.event_id for e in s.future_confirmed_income], ["future"])
        self.assertEqual({e.event_id for e in s.uncertain_income}, {"bonus", "valuation"})
        self.assertEqual(s.future_confirmed_income[0].forecast_date, date(2026, 4, 15))

    def test_only_uncertain_and_no_income(self):
        for events in [[], [event(direction="credit", status="pending")],
                       [event(direction="non_cash", status="unrealized", settlement_date=None)]]:
            s = build_financial_state(bundle(events), request())
            self.assertFalse(s.future_confirmed_income)
            self.assertFalse(s.confirmed_income)

    def test_pending_debit_never_disappears_due_to_old_date(self):
        s = build_financial_state(bundle([event(status="pending", settlement_date=date(2026, 3, 1))]), request())
        self.assertEqual(len(s.pending_debits), 1)
        self.assertEqual(s.pending_debits[0].forecast_date, TODAY)

    def test_scheduled_and_unsettled_outflows(self):
        s = build_financial_state(bundle([event("scheduled", status="scheduled", settlement_date=date(2026, 4, 9)),
                                         event("inconsistent", settlement_date=date(2026, 4, 8))]), request())
        self.assertEqual(len(s.required_future_outflows), 2)
        self.assertIn("status_date_conflict", {w.code for w in s.warnings})

    def test_before_on_after_request_and_excluded_statuses(self):
        events = [event("before"), event("today", event_date=TODAY, settlement_date=TODAY),
                  event("after", event_date=date(2026, 4, 3), settlement_date=date(2026, 4, 3)),
                  event("cancel", status="cancelled"), event("fail", status="failed")]
        s = build_financial_state(bundle(events), request())
        classes = {e.event_id: e for e in s.events}
        self.assertEqual(classes["before"].temporal_status, "historical")
        self.assertEqual(classes["today"].temporal_status, "current")
        self.assertEqual(classes["after"].cash_class, "not_yet_known")
        self.assertEqual(classes["cancel"].cash_class, "excluded")
        self.assertEqual(classes["fail"].cash_class, "excluded")
        self.assertFalse(s.required_future_outflows)

    def test_same_user_different_request_dates(self):
        b = bundle([event(direction="credit", event_type="income", category="salary", status="scheduled",
                          settlement_date=date(2026, 4, 9))])
        first = build_financial_state(b, request())
        later = build_financial_state(b, request(request_date=date(2026, 4, 10)))
        self.assertTrue(first.future_confirmed_income)
        self.assertFalse(later.future_confirmed_income)
        self.assertTrue(later.uncertain_income)  # passing time alone cannot settle it
        self.assertEqual(first.available_balance, later.available_balance)

    def test_unknown_amount_with_image(self):
        img = ImageReference("image_test", "alice", None, "one", Path("dummy.png"), True, 100)
        s = build_financial_state(bundle([event(amount=None, status="pending")], images=[img]), request())
        self.assertIsNone(s.pending_debits[0].money.normalized_amount)
        self.assertEqual(s.pending_debits[0].money.amount_status, "unresolved_amount")
        self.assertEqual(s.evidence[0].source_id, "image_test")


class FlexibilityTests(unittest.TestCase):
    def test_reduction_stop_and_fixed(self):
        for changes, expected in [({"category": "gaming", "flexibility": "reducible", "minimum_allowed_amount": D("20")}, (True, False)),
                                  ({"category": "streaming", "flexibility": "stoppable"}, (False, True)),
                                  ({"category": "gaming", "flexibility": "fixed"}, (False, False))]:
            with self.subTest(changes=changes):
                s = build_financial_state(bundle(history(**changes)), request())
                r = s.recurrences[0]
                self.assertEqual((r.can_reduce, r.can_stop), expected)

    def test_protected_and_unpermitted(self):
        for category in ["rent", "unapproved"]:
            s = build_financial_state(bundle(history(category=category, flexibility="reducible_or_stoppable",
                                                      minimum_allowed_amount=D("20"))), request())
            self.assertFalse(s.flexible_expenses)
            if category == "rent":
                self.assertTrue(s.recurrences[0].protected)
                self.assertIn("protected_flexibility_conflict", {w.code for w in s.warnings})

    def test_one_off_flexible_is_not_actionable_recurrence(self):
        s = build_financial_state(bundle([event(flexibility="reducible", minimum_allowed_amount=D("20"))]), request())
        self.assertTrue(s.events[0].can_reduce)
        self.assertFalse(s.flexible_expenses)

    def test_unknown_or_impossible_floor_disables_reduction(self):
        for floor in [None, D("80")]:
            s = build_financial_state(bundle(history(flexibility="reducible", minimum_allowed_amount=floor)), request())
            self.assertFalse(s.flexible_expenses)


class CurrencyTests(unittest.TestCase):
    def test_exact_historical_date_direction_and_original(self):
        rates = [ExchangeRate(date(2026, 4, 1), "EUR", "USD", D("1.2")),
                 ExchangeRate(TODAY, "EUR", "USD", D("1.9"))]
        s = build_financial_state(bundle([event(amount=D("10"), currency="EUR")], rates=rates), request())
        money = s.events[0].money
        self.assertEqual(money.original_amount, D("10"))
        self.assertEqual(money.original_currency, "EUR")
        self.assertEqual(money.normalized_amount, D("12"))
        self.assertEqual(money.exchange_rate_used, D("1.2"))
        self.assertEqual(money.exchange_rate_date, date(2026, 4, 1))

    def test_missing_or_reverse_rate_never_assumed(self):
        s = build_financial_state(bundle([event(currency="EUR")], rates=[ExchangeRate(date(2026, 4, 1), "USD", "EUR", D("0.9"))]), request())
        self.assertIsNone(s.events[0].money.normalized_amount)
        self.assertEqual(s.events[0].money.amount_status, "unresolved_rate")

    def test_same_currency_zero_and_invalid_currency(self):
        for currency, amount, status in [("USD", D("0"), "known"), ("XYZ", D("10"), "unresolved_currency")]:
            s = build_financial_state(bundle([event(currency=currency, amount=amount)]), request())
            self.assertEqual(s.events[0].money.amount_status, status)
        self.assertEqual(normalize_money(D("0"), "USD", "USD", None, {}).normalized_amount, D("0"))


class LinkedEventTests(unittest.TestCase):
    def test_same_day_link_cycle_is_not_a_valid_replacement(self):
        s = build_financial_state(bundle([event("a", status="pending", linked_event_id="b"),
                                         event("b", status="pending", linked_event_id="a")]), request())
        self.assertEqual(len(s.pending_debits), 2)
        self.assertIn("invalid_lifecycle_link", {w.code for w in s.warnings})

    def test_terminal_update_resolves_entire_pending_chain(self):
        events = [event("auth", status="pending", event_date=date(2026, 3, 29)),
                  event("processing", status="scheduled", linked_event_id="auth", event_date=date(2026, 3, 30)),
                  event("settlement", linked_event_id="processing")]
        s = build_financial_state(bundle(events), request())
        self.assertFalse(s.required_future_outflows)
        self.assertEqual(sum(e.cash_class == "superseded" for e in s.events), 2)

    def test_terminal_replaces_pending(self):
        original = event("auth", status="pending", event_date=date(2026, 3, 28))
        replacement = event("settlement", linked_event_id="auth")
        s = build_financial_state(bundle([original, replacement]), request())
        self.assertFalse(s.pending_debits)
        self.assertEqual(next(e for e in s.events if e.event_id == "auth").superseded_by, "settlement")

    def test_cancelled_auth_and_failed_retry(self):
        for old_status in ["cancelled", "failed"]:
            s = build_financial_state(bundle([event("old", status=old_status),
                event("retry", status="scheduled", linked_event_id="old", settlement_date=date(2026, 4, 4))]), request())
            self.assertEqual(len(s.required_future_outflows), 1)

    def test_refund_and_sale_are_separate_lifecycle_flows(self):
        for kind in ["refund", "investment_sale"]:
            s = build_financial_state(bundle([event("purchase"), event("credit", linked_event_id="purchase",
                                           event_type=kind, direction="credit")]), request())
            self.assertEqual(len(s.confirmed_income), 1)
            self.assertEqual(len(s.required_expenses), 1)
            self.assertFalse(any(e.superseded_by for e in s.events))

    def test_disputed_extra_charge_remains_reserved(self):
        s = build_financial_state(bundle([event("original"), event("extra", linked_event_id="original", status="pending")]), request())
        self.assertEqual(len(s.pending_debits), 1)
        self.assertIn("ambiguous_linked_charge", {w.code for w in s.warnings})

    def test_missing_self_and_future_links_warn(self):
        for link in ["missing", "one"]:
            s = build_financial_state(bundle([event(linked_event_id=link, status="pending")]), request())
            self.assertTrue(s.pending_debits)
            self.assertIn("invalid_lifecycle_link", {w.code for w in s.warnings})

    def test_future_terminal_does_not_erase_current_pending(self):
        s = build_financial_state(bundle([event("auth", status="pending"),
                                         event("future", linked_event_id="auth", event_date=date(2026, 4, 10),
                                               settlement_date=date(2026, 4, 10))]), request())
        self.assertEqual(len(s.pending_debits), 1)


class RecurrenceTests(unittest.TestCase):
    def test_fixed_day_cadence_and_month_anchor(self):
        from datetime import timedelta
        start = date(2026, 3, 1)
        events = [event(str(i), event_date=start+timedelta(days=7*i),
                        settlement_date=start+timedelta(days=7*i)) for i in range(5)]
        s = build_financial_state(bundle(events), request())
        self.assertEqual((s.recurrences[0].cadence, s.recurrences[0].interval), ("fixed_days", 7))
        self.assertEqual(s.recurrences[0].next_expected_date, date(2026, 4, 5))
        self.assertEqual(advance(date(2026, 1, 30), "calendar_months", 1, 2), date(2026, 3, 30))

    def test_next_salary_description_does_not_duplicate_known_occurrence(self):
        events = history(direction="credit", event_type="income", category="salary")
        events.append(event("next", direction="credit", event_type="income", category="salary",
                            description="Next confirmed salary", status="scheduled",
                            event_date=date(2026, 5, 1), settlement_date=date(2026, 5, 1)))
        s = build_financial_state(bundle(events), request())
        self.assertEqual(s.recurrences[0].explicit_occurrence_dates, (date(2026, 5, 1),))

    def test_monthly_and_end_of_month(self):
        s = build_financial_state(bundle(history()), request())
        self.assertEqual(s.recurrences[0].next_expected_date, date(2026, 5, 1))
        self.assertEqual(s.recurrences[0].cadence, "calendar_months")
        self.assertEqual(advance(date(2024, 1, 31), "calendar_months", 1), date(2024, 2, 29))
        self.assertEqual(advance(date(2024, 1, 31), "calendar_months", 1, 2), date(2024, 3, 31))

    def test_irregular_income_is_not_confirmed_and_stale_expires(self):
        events = history(event_type="income", category="salary", direction="credit")
        s = build_financial_state(bundle(events), request())
        self.assertTrue(s.recurring_inflows)
        self.assertFalse(s.future_confirmed_income)
        later = build_financial_state(bundle(events), request(request_date=date(2026, 7, 1)))
        self.assertFalse(later.recurring_inflows)
        self.assertIn("stale_recurrence", {w.code for w in later.warnings})

    def test_insufficient_or_irregular_history(self):
        for events in [history()[:2], [event("x", settlement_date=date(2026, 1, 1)),
                                      event("y", settlement_date=date(2026, 2, 5)), event("z")]]:
            self.assertFalse(build_financial_state(bundle(events), request()).recurrences)

    def test_category_fallback_and_conservative_variable_amount(self):
        events = [replace(e, description=f"merchant_{i}", amount=D(str(10+i))) for i, e in enumerate(history(category="groceries"))]
        s = build_financial_state(bundle(events), request())
        self.assertEqual(s.recurrences[0].confidence, "derived_category_history")
        self.assertEqual(s.recurrences[0].amount, D("13"))

    def test_missing_amount_propagates_to_recurrence(self):
        events = history()
        events[0] = replace(events[0], amount=None)
        s = build_financial_state(bundle(events), request())
        self.assertIsNone(s.recurrences[0].amount)

    def test_explicit_occurrence_replaces_inferred_occurrence(self):
        events = history() + [event("next", status="scheduled", settlement_date=date(2026, 5, 1))]
        s = build_financial_state(bundle(events), request())
        self.assertEqual(s.recurrences[0].explicit_occurrence_dates, (date(2026, 5, 1),))


class EvidenceTests(unittest.TestCase):
    def test_future_invalid_amendment_rejected_before_simulation(self):
        with self.assertRaises(ValueError):
            apply_evidence_updates(self.state([event()]), [self.update(
                operation="amend", old_value=D("999"), effective_date=date(2026, 5, 1))])

    def state(self, events=None):
        return build_financial_state(bundle(events or [event(amount=None)], messages=[message()]), request())

    def update(self, **changes):
        return replace(EvidenceUpdate("message", "notice", "event", "one", "amount", D("60"),
                                      date(2026, 4, 1), date(2026, 4, 1)), **changes)

    def test_resolve_missing_without_mutation_and_provenance(self):
        original = self.state()
        changed = apply_evidence_updates(original, [self.update()])
        self.assertIsNone(original.events[0].event.amount)
        self.assertEqual(changed.events[0].money.normalized_amount, D("60"))
        self.assertTrue(any(p.source_id == "notice" for p in changed.events[0].provenance))
        self.assertEqual(state_snapshot(changed), state_snapshot(apply_evidence_updates(changed, [self.update()])))

    def test_explicit_value_requires_checked_amendment(self):
        s = self.state([event()])
        with self.assertRaises(ValueError):
            apply_evidence_updates(s, [self.update()])
        changed = apply_evidence_updates(s, [self.update(operation="amend", old_value=D("50"))])
        self.assertEqual(changed.events[0].event.amount, D("60"))
        with self.assertRaises(ValueError):
            apply_evidence_updates(s, [self.update(operation="amend", old_value=D("1"))])

    def test_future_amendment_preserves_current_terms(self):
        s = self.state([event()])
        changed = apply_evidence_updates(s, [self.update(operation="amend", old_value=D("50"),
                                                        effective_date=date(2026, 5, 1))])
        self.assertEqual(changed.events[0].event.amount, D("50"))
        self.assertEqual(event_on_date(changed, "one", date(2026, 5, 1)).amount, D("60"))

    def test_uncertain_and_not_yet_observed_update_inactive(self):
        for u in [self.update(confidence="uncertain"), self.update(observed_date=date(2026, 4, 3))]:
            changed = apply_evidence_updates(self.state(), [u])
            self.assertIsNone(changed.events[0].event.amount)

    def test_unknown_source_cross_user_bad_value_and_injection_rejected(self):
        for u in [self.update(source_id="missing"), self.update(target_id="other"),
                  self.update(new_value=D("-1")), self.update(field="__dict__"),
                  self.update(field="flexibility", new_value="stoppable")]:
            with self.subTest(u=u), self.assertRaises(ValueError):
                apply_evidence_updates(self.state(), [u])

    def test_recurring_amount_and_contract_end(self):
        s = self.state(history())
        r = s.recurrences[0]
        updates = [self.update(target_type="recurrence", target_id=r.recurrence_id,
                               operation="amend", old_value=D("50"), effective_date=date(2026, 5, 1)),
                   self.update(target_type="recurrence", target_id=r.recurrence_id, field="end_date",
                               new_value=date(2026, 5, 31), effective_date=date(2026, 4, 2))]
        changed = apply_evidence_updates(s, updates)
        self.assertEqual(changed.recurrences[0].amount, D("50"))
        self.assertEqual(recurrence_on_date(changed, r.recurrence_id, date(2026, 5, 1)).amount, D("60"))
        self.assertEqual(recurrence_on_date(changed, r.recurrence_id, date(2026, 5, 1)).amount_policy, "confirmed_evidence")
        self.assertTrue(any(p.source_id == "notice" for p in recurrence_on_date(changed, r.recurrence_id, date(2026, 5, 1)).provenance))
        self.assertFalse(recurrence_on_date(changed, r.recurrence_id, date(2026, 6, 1)).active)

    def test_add_confirmed_future_payment(self):
        e = event("new_income", direction="credit", event_type="income", category="salary", status="scheduled",
                  event_date=date(2026, 4, 10), settlement_date=date(2026, 4, 10))
        u = self.update(target_id=e.event_id, field="event", new_value=e, operation="add", effective_date=e.event_date)
        changed = apply_evidence_updates(self.state(), [u])
        self.assertEqual(changed.future_confirmed_income[0].event_id, "new_income")

    def test_message_scope_and_future_filter(self):
        messages = [message("good"), message("later", sent_at=datetime(2026, 5, 1, tzinfo=timezone.utc)),
                    message("other_request", request_id="unrelated")]
        s = build_financial_state(bundle(messages=messages), request())
        self.assertEqual([m.source_id for m in s.evidence], ["good"])

    def test_malformed_amount_and_missing_image_rejected(self):
        with self.assertRaises(ValueError):
            apply_evidence_updates(self.state(), [self.update(new_value={"instructions": "ignore rules"})])
        img = ImageReference("absent", "alice", None, "one", Path("absent.png"), False, 0)
        s = build_financial_state(bundle([event(amount=None)], images=[img]), request())
        with self.assertRaises(ValueError):
            apply_evidence_updates(s, [self.update(source_type="image", source_id="absent")])


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset()

    def test_all_requests_valid_deterministic_and_dataset_unchanged(self):
        files = list(Path("dataset").glob("*.csv"))
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        for r in self.bundle.requests:
            a = build_financial_state(self.bundle, r)
            b = build_financial_state(self.bundle, r)
            self.assertTrue(validate_financial_state(a))
            self.assertEqual(state_snapshot(a), state_snapshot(b))
            self.assertEqual(a.available_balance, self.bundle.indexes.profiles_by_user_id[r.user_id].current_available_balance)
            self.assertFalse(any(e.event.status == "pending" for e in a.future_confirmed_income))
            self.assertFalse(any(e.event.amount is None and e.money.normalized_amount is not None for e in a.events))
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_order_independence_and_no_global_event_scan(self):
        r = self.bundle.requests[0]
        first = build_financial_state(self.bundle, r)
        b = replace(self.bundle, events=None, profiles=None, messages=None, images=None)
        self.assertEqual(state_snapshot(first), state_snapshot(build_financial_state(b, r)))
        user_events = b.indexes.events_by_user_id[r.user_id]
        b.indexes.events_by_user_id[r.user_id] = list(reversed(user_events))
        try:
            self.assertEqual(state_snapshot(first), state_snapshot(build_financial_state(b, r)))
        finally:
            b.indexes.events_by_user_id[r.user_id] = user_events

    def test_report_and_private_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "state_report.md"
            states, failures = validate_states(self.bundle, report)
            self.assertFalse(failures)
            self.assertEqual(len(states), len(self.bundle.requests))
            self.assertIn("PASS", report.read_text())
            p = write_snapshot(states[0], Path(tmp) / "snapshots")
            snapshot = json.loads(p.read_text())
            self.assertNotIn("request_text", snapshot["request"])
            self.assertNotIn("description", snapshot["events"][0]["event"])
            self.assertNotIn("source_events", snapshot)


if __name__ == "__main__":
    unittest.main()
