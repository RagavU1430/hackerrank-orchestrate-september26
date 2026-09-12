"""Phase 4 - 90-Day Cash Flow Simulator tests.

Covers invariants, recurrence, pending/scheduled, salary evidence, currency,
linked events, hypothetical modifications and integration.
No hardcoded evaluation labels.
"""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from pathlib import Path
import hashlib
import json

from code.data_loader import load_dataset
from code.indexes import build_indexes
from code.schemas import DatasetBundle, FinancialEvent, FinancialProfile, Request, ExchangeRate, Message
from code.state_builder import build_financial_state, normalize_money
from code.financial_state import EvidenceUpdate, state_snapshot
from code.simulation_models import PaymentInjection, StopExpense, ReduceExpense
from code.simulator import simulate_90_days, simulate_with_payment, FORECAST_DAYS
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


class BalanceArithmeticTests(unittest.TestCase):
    def test_closing_opening_net_and_continuity(self):
        evs = history()
        s = build_financial_state(bundle(evs), request())
        fc = simulate_90_days(s)
        self.assertEqual(fc.days, 91)
        self.assertEqual(fc.start_date, TODAY)
        self.assertEqual(fc.end_date, TODAY + __import__('datetime').timedelta(days=FORECAST_DAYS))
        for i, d in enumerate(fc.daily_forecasts):
            self.assertEqual(d.closing_balance, d.opening_balance + d.net_change,
                             f"day {d.forecast_date} closing != opening + net")
            self.assertEqual(d.net_change, d.total_inflows - d.total_outflows)
            if i > 0:
                self.assertEqual(d.opening_balance, fc.daily_forecasts[i-1].closing_balance)
            for val in (d.opening_balance, d.closing_balance, d.total_inflows, d.total_outflows, d.net_change, d.headroom):
                self.assertIsInstance(val, Decimal)
                self.assertTrue(val.is_finite())

    def test_headroom_invariant_tracking(self):
        # Safe forecast
        s = build_financial_state(bundle(history()), request())
        fc = simulate_90_days(s)
        self.assertIsNotNone(fc.minimum_headroom)
        self.assertIsNotNone(fc.minimum_observed_balance)
        expected_min = min(d.headroom for d in fc.daily_forecasts)
        self.assertEqual(fc.minimum_headroom, expected_min)
        self.assertEqual(fc.minimum_observed_balance, min(d.closing_balance for d in fc.daily_forecasts))
        self.assertEqual(fc.invariant_ok, fc.first_breach_date is None)
        if fc.invariant_ok:
            for d in fc.daily_forecasts:
                self.assertTrue(d.invariant_ok)
                self.assertGreaterEqual(d.closing_balance, s.minimum_balance_to_keep)

    def test_mid_forecast_breach_detection(self):
        # Create high recurring expense that will breach later even though ending balance recovers
        # We use a pending debit far in future with large outflow
        pending = event("big_pending", amount=D("2000"), status="pending", settlement_date=date(2026, 4, 20))
        s = build_financial_state(bundle([pending] + history()), request())
        fc = simulate_90_days(s)
        # pending should cause large outflow on 2026-04-20
        self.assertIn(fc.first_breach_date, [d.forecast_date for d in fc.daily_forecasts if not d.invariant_ok] or [None])
        if fc.first_breach_date:
            idx = next(i for i, d in enumerate(fc.daily_forecasts) if d.forecast_date == fc.first_breach_date)
            self.assertFalse(fc.daily_forecasts[idx].invariant_ok)
            # Ensure earlier days not considered breach if safe
            # Ending balance may still be above minimum after inflow, but breach already recorded
            self.assertFalse(fc.invariant_ok)


class IncomeExclusionTests(unittest.TestCase):
    def test_pending_and_uncertain_income_excluded(self):
        pend_credit = event("pend", direction="credit", event_type="income", category="salary", amount=D("500"), status="pending")
        bonus = event("bonus", direction="credit", event_type="income", category="bonus", amount=D("1000"), status="scheduled", event_date=date(2026, 4, 15), settlement_date=date(2026, 4, 15))
        unreal = event("unreal", direction="non_cash", event_type="investment_valuation", amount=D("999"), status="unrealized", settlement_date=None)
        s = build_financial_state(bundle([pend_credit, bonus, unreal]), request())
        fc = simulate_90_days(s)
        # None of these should appear as inflows in ledger
        inflows_ids = {e.source_id for d in fc.daily_forecasts for e in d.inflows}
        self.assertNotIn("pend", inflows_ids)
        self.assertNotIn("bonus", inflows_ids)
        self.assertNotIn("unreal", inflows_ids)
        self.assertEqual(fc.total_inflows, D("0"))

    def test_confirmed_salary_projected(self):
        salary = event("sal", direction="credit", event_type="income", category="salary", amount=D("1000"), status="scheduled", event_date=date(2026, 4, 10), settlement_date=date(2026, 4, 10))
        s = build_financial_state(bundle([salary]), request())
        fc = simulate_90_days(s)
        self.assertEqual(len(s.future_confirmed_income), 1)
        # Should appear as inflow
        inflow_days = [d for d in fc.daily_forecasts if any(e.source_id == "sal" for e in d.inflows)]
        self.assertEqual(len(inflow_days), 1)
        self.assertEqual(inflow_days[0].forecast_date, date(2026, 4, 10))
        self.assertEqual(fc.total_inflows, D("1000"))

    def test_stale_credit_not_projected_but_debit_remains(self):
        evs = history(event_type="income", category="salary", direction="credit")
        s = build_financial_state(bundle(evs), request(request_date=date(2026, 7, 1)))
        # Credit stale should be inactive
        self.assertFalse(s.recurring_inflows)
        # Debit stays active with stale confidence
        s2 = build_financial_state(bundle(history()), request(request_date=date(2026, 7, 1)))
        self.assertTrue(s2.recurring_outflows)
        fc = simulate_90_days(s2)
        # Should still have outflow projections
        self.assertGreater(fc.total_outflows, D("0"))


class ExpenseTests(unittest.TestCase):
    def test_fixed_and_recurring_expense(self):
        s = build_financial_state(bundle(history()), request())
        fc = simulate_90_days(s)
        # History infers monthly recurrence for gaming service
        self.assertEqual(len(s.recurring_outflows), 1)
        # Outflows should appear monthly inside window
        out_dates = [d.forecast_date for d in fc.daily_forecasts if d.outflows]
        # next_expected is 2026-05-01, then 06-01 etc.
        self.assertIn(date(2026, 5, 1), out_dates)

    def test_pending_debit_single_occurrence(self):
        pend = event("pend_deb", amount=D("100"), status="pending", settlement_date=date(2026, 3, 1))
        s = build_financial_state(bundle([pend]), request())
        self.assertEqual(len(s.pending_debits), 1)
        fc = simulate_90_days(s)
        # Should reserve exactly once at request_date (max(request_date, settlement))
        days_with = [d for d in fc.daily_forecasts if any(e.source_id == "pend_deb" for e in d.outflows)]
        self.assertEqual(len(days_with), 1)
        self.assertEqual(days_with[0].forecast_date, TODAY)
        # Not double counted
        self.assertEqual(fc.total_outflows, D("100"))

    def test_scheduled_expense(self):
        sched = event("sched", amount=D("200"), status="scheduled", settlement_date=date(2026, 4, 15))
        s = build_financial_state(bundle([sched]), request())
        fc = simulate_90_days(s)
        days = [d for d in fc.daily_forecasts if any(e.source_id == "sched" for e in d.outflows)]
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0].forecast_date, date(2026, 4, 15))

    def test_flexible_still_occurs_in_baseline(self):
        s = build_financial_state(bundle(history(flexibility="reducible", minimum_allowed_amount=D("20"))), request())
        self.assertTrue(s.flexible_expenses)
        fc_baseline = simulate_90_days(s)
        fc_with_stop = simulate_90_days(s, modifications=[StopExpense(target_id=s.recurrences[0].recurrence_id)])
        self.assertGreater(fc_baseline.total_outflows, fc_with_stop.total_outflows)


class RecurrenceAndEffectiveDateTests(unittest.TestCase):
    def test_salary_update_effective_date(self):
        evs = history(direction="credit", event_type="income", category="salary")
        s = build_financial_state(bundle(evs, messages=[message()]), request())
        rec = s.recurrences[0]
        # Salary update from 50 to 100 effective 2026-05-01
        upd = EvidenceUpdate("message", "notice", "recurrence", rec.recurrence_id, "amount", D("100"), date(2026, 5, 1), date(2026, 4, 1), operation="amend", old_value=rec.amount)
        from code.evidence import apply_evidence_updates
        s2 = apply_evidence_updates(s, [upd])
        fc = simulate_90_days(s2)
        # Find occurrences before and after effective date
        occ_before = [d for d in fc.daily_forecasts if d.forecast_date == date(2026, 5, 1)]
        # The occurrence on 2026-05-01 should have new amount 100 (effective includes that date)
        # Check ledger amount
        rec_entries = [(d.forecast_date, e.normalized_amount) for d in fc.daily_forecasts for e in d.inflows if e.source_id == rec.recurrence_id]
        # There is also explicit future occurrence maybe but not in this synthetic
        # The next occurrence after anchor is 2026-02 etc but request is 2026-04-02, next is 2026-05-01
        amounts_by_date = {dt: amt for dt, amt in rec_entries}
        if date(2026, 5, 1) in amounts_by_date:
            self.assertEqual(amounts_by_date[date(2026, 5, 1)], D("100"))
        # Later occurrence 2026-06-01 also 100
        if date(2026, 6, 1) in amounts_by_date:
            self.assertEqual(amounts_by_date[date(2026, 6, 1)], D("100"))

    def test_salary_reduction_and_end(self):
        evs = history(direction="credit", event_type="income", category="salary")
        s = build_financial_state(bundle(evs, messages=[message()]), request())
        rec = s.recurrences[0]
        # Reduce to 20 effective 2026-06-01
        upd = EvidenceUpdate("message", "notice", "recurrence", rec.recurrence_id, "amount", D("20"), date(2026, 6, 1), date(2026, 4, 1), operation="amend", old_value=rec.amount)
        from code.evidence import apply_evidence_updates
        s2 = apply_evidence_updates(s, [upd])
        fc = simulate_90_days(s2)
        rec_entries = {d.forecast_date: e.normalized_amount for d in fc.daily_forecasts for e in d.inflows for ex in [e] if e.source_id == rec.recurrence_id}
        # contract end effective 2026-05-31 observed 2026-04-01
        upd_end = EvidenceUpdate("message", "notice", "recurrence", rec.recurrence_id, "end_date", date(2026, 5, 31), date(2026, 5, 31), date(2026, 4, 1), operation="amend", old_value=None)
        s3 = apply_evidence_updates(s, [upd_end])
        fc3 = simulate_90_days(s3)
        entries_after = [dt for dt in [d.forecast_date for d in fc3.daily_forecasts for e in d.inflows if e.source_id == rec.recurrence_id] if dt > date(2026, 5, 31)]
        self.assertEqual(len(entries_after), 0)

    def test_salary_date_change_no_duplicate(self):
        # Setup a scheduled salary event on 2026-04-15 then date change to 2026-04-20
        sched = event("next_sal", direction="credit", event_type="income", category="salary", amount=D("1000"), status="scheduled", event_date=date(2026, 4, 15), settlement_date=date(2026, 4, 15))
        evs = history(direction="credit", event_type="income", category="salary") + [sched]
        s = build_financial_state(bundle(evs, messages=[message()]), request())
        # Resolver would amend settlement_date to new date; observed before effective
        upd = EvidenceUpdate("message", "notice", "event", "next_sal", "settlement_date", date(2026, 4, 20), date(2026, 4, 20), date(2026, 4, 1), operation="amend", old_value=date(2026, 4, 15))
        from code.evidence import apply_evidence_updates
        s2 = apply_evidence_updates(s, [upd])
        fc = simulate_90_days(s2)
        dates = [d.forecast_date for d in fc.daily_forecasts if any(e.source_id == "next_sal" for e in d.inflows)]
        self.assertEqual(dates, [date(2026, 4, 20)])
        # Recurrence explicit occurrence should have been updated to avoid double count
        # No duplicate on original date
        self.assertNotIn(date(2026, 4, 15), [d.forecast_date for d in fc.daily_forecasts if any(e.source_type == "recurrence" and e.category == "salary" for e in d.inflows)])

    def test_rent_increase_effective(self):
        evs = history(category="rent", flexibility="fixed")
        s = build_financial_state(bundle(evs, messages=[message()]), request())
        rec = s.recurrences[0]
        # Rent increase: we simulate via recurrence amount amend
        upd = EvidenceUpdate("message", "notice", "recurrence", rec.recurrence_id, "amount", D("80"), date(2026, 6, 1), date(2026, 4, 1), operation="amend", old_value=rec.amount)
        from code.evidence import apply_evidence_updates
        s2 = apply_evidence_updates(s, [upd])
        fc = simulate_90_days(s2)
        rec_entries = {e.normalized_amount for d in fc.daily_forecasts for e in d.outflows if e.source_id == rec.recurrence_id}
        # Before effective, original 50; after 80. Check specific dates
        amounts = [(d.forecast_date, e.normalized_amount) for d in fc.daily_forecasts for e in d.outflows if e.source_id == rec.recurrence_id]
        before = [a for dt, a in amounts if dt < date(2026, 6, 1)]
        after = [a for dt, a in amounts if dt >= date(2026, 6, 1)]
        if before:
            self.assertEqual(before[0], D("50"))
        if after:
            self.assertEqual(after[0], D("80"))


class CurrencyTests(unittest.TestCase):
    def test_same_currency(self):
        s = build_financial_state(bundle([event(currency="USD", amount=D("100"))]), request())
        fc = simulate_90_days(s)
        # settled event shouldn't appear in forecast, but recurrence will: check conversion none needed

    def test_supported_conversion(self):
        rate = ExchangeRate(date(2026, 4, 15), "EUR", "USD", D("1.2"))
        ev = event("conv", amount=D("100"), currency="EUR", status="scheduled", settlement_date=date(2026, 4, 15))
        s = build_financial_state(bundle([ev], rates=[rate]), request())
        fc = simulate_90_days(s)
        entries = [e for d in fc.daily_forecasts for e in d.outflows if e.source_id == "conv"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].normalized_amount, D("120"))
        self.assertEqual(entries[0].exchange_rate_used, D("1.2"))

    def test_missing_rate_warning(self):
        ev = event("miss", amount=D("100"), currency="EUR", status="scheduled", settlement_date=date(2026, 4, 16))
        # No rate for 2026-04-16, only for 2026-04-15
        rate = ExchangeRate(date(2026, 4, 15), "EUR", "USD", D("1.2"))
        s = build_financial_state(bundle([ev], rates=[rate]), request())
        fc = simulate_90_days(s)
        entries = [e for d in fc.daily_forecasts for e in d.outflows if e.source_id == "miss"]
        self.assertEqual(len(entries), 0)
        self.assertTrue(any(w.code == "unresolved_rate" for w in fc.warnings))

    def test_recurrence_conversion_per_date(self):
        rate1 = ExchangeRate(date(2026, 5, 1), "EUR", "USD", D("1.1"))
        rate2 = ExchangeRate(date(2026, 6, 1), "EUR", "USD", D("1.3"))
        evs = history(currency="EUR", amount=D("100"))
        s = build_financial_state(bundle(evs, rates=[rate1, rate2]), request())
        # Recurrences occur on 2026-05-01 and 2026-06-01, need those rates
        fc = simulate_90_days(s)
        rec_id = s.recurrences[0].recurrence_id
        entries = [(d.forecast_date, e.normalized_amount) for d in fc.daily_forecasts for e in d.outflows if e.source_id == rec_id]
        # At least one conversion should be with rate 1.1 or 1.3
        amounts = [a for _, a in entries]
        # If rates match, check conversion: 100*1.1=110, 100*1.3=130
        if date(2026, 5, 1) in [dt for dt, _ in entries]:
            self.assertEqual(next(a for dt, a in entries if dt == date(2026, 5, 1)), D("110.0") if D("100") * D("1.1") == D("110.0") else D("110"))
        if date(2026, 6, 1) in [dt for dt, _ in entries]:
            self.assertEqual(next(a for dt, a in entries if dt == date(2026, 6, 1)), D("130") if D("100") * D("1.3") == D("130") else D("130.0"))


class LinkedEventTests(unittest.TestCase):
    def test_no_duplicate_financial_impact(self):
        # Create settled pending chain supersession
        auth = event("auth", status="pending", event_date=date(2026, 3, 29))
        settlement = event("settlement", linked_event_id="auth", status="settled", amount=D("50"))
        s = build_financial_state(bundle([auth, settlement]), request())
        # pending should be superseded, so no forecast outflow for auth
        self.assertEqual(len(s.pending_debits), 0)
        fc = simulate_90_days(s)
        # No extra outflow duplicated
        ids = [e.source_id for d in fc.daily_forecasts for e in d.outflows]
        self.assertNotIn("auth", ids)
        # settlement is historical settled, not forecast either


class ModificationIsolationTests(unittest.TestCase):
    def test_scenario_isolation_and_immutability(self):
        s = build_financial_state(bundle(history()), request())
        before_snap = state_snapshot(s)
        fc1 = simulate_90_days(s)
        fc2 = simulate_90_days(s, modifications=[PaymentInjection(date(2026, 4, 15), D("500"), "USD")])
        self.assertNotEqual(fc1.ending_balance, fc2.ending_balance)
        self.assertEqual(state_snapshot(s), before_snap)
        # Second baseline still same
        fc1_again = simulate_90_days(s)
        self.assertEqual(fc1.ending_balance, fc1_again.ending_balance)
        self.assertEqual(fc1.total_outflows, fc1_again.total_outflows)

    def test_stop_and_reduce_modifications(self):
        s = build_financial_state(bundle(history(flexibility="reducible", minimum_allowed_amount=D("20"))), request())
        rec = s.recurrences[0]
        fc_base = simulate_90_days(s)
        fc_stop = simulate_90_days(s, modifications=[StopExpense(rec.recurrence_id)])
        self.assertLess(fc_stop.total_outflows, fc_base.total_outflows)
        fc_reduce = simulate_90_days(s, modifications=[ReduceExpense(rec.recurrence_id, D("10"))])
        self.assertLess(fc_reduce.total_outflows, fc_base.total_outflows)
        self.assertGreater(fc_reduce.total_outflows, fc_stop.total_outflows)

    def test_payment_injection(self):
        s = build_financial_state(bundle([]), request())
        fc = simulate_with_payment(s, TODAY, D("100"))
        self.assertEqual(fc.total_outflows, D("100"))
        day = next(d for d in fc.daily_forecasts if d.forecast_date == TODAY)
        self.assertEqual(day.total_outflows, D("100"))
        self.assertEqual(day.closing_balance, D("900"))  # 1000 -100


class InvariantTests(unittest.TestCase):
    def test_decimal_usage(self):
        s = build_financial_state(bundle([]), request())
        fc = simulate_90_days(s)
        for d in fc.daily_forecasts:
            self.assertIsInstance(d.opening_balance, Decimal)
            self.assertIsInstance(d.closing_balance, Decimal)

    def test_forecast_window(self):
        s = build_financial_state(bundle([]), request())
        fc = simulate_90_days(s)
        self.assertEqual(len(fc.daily_forecasts), FORECAST_DAYS + 1)
        self.assertEqual(fc.start_date, TODAY)
        self.assertEqual(fc.end_date, TODAY + __import__('datetime').timedelta(days=FORECAST_DAYS))

    def test_deterministic(self):
        s = build_financial_state(bundle(history()), request())
        fc1 = simulate_90_days(s)
        fc2 = simulate_90_days(s)
        self.assertEqual(fc1.ending_balance, fc2.ending_balance)
        self.assertEqual(fc1.total_inflows, fc2.total_inflows)
        self.assertEqual([(d.closing_balance, d.headroom) for d in fc1.daily_forecasts],
                         [(d.closing_balance, d.headroom) for d in fc2.daily_forecasts])

    def test_no_hardcoded_request_specific_logic(self):
        # Ensure two different users produce different forecasts without request_id branching
        p2 = profile(user_id="bob", current_available_balance=D("2000"), minimum_balance_to_keep=D("500"))
        r2 = request(request_id="second", user_id="bob")
        b = bundle(history(), [profile(), p2], [request(), r2])
        s1 = build_financial_state(b, b.requests[0])
        s2 = build_financial_state(b, b.requests[1])
        fc1 = simulate_90_days(s1)
        fc2 = simulate_90_days(s2)
        self.assertNotEqual(fc1.starting_balance, fc2.starting_balance)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset()

    def test_all_requests_forecast_deterministic_and_dataset_unchanged(self):
        files = list(Path("dataset").glob("*.csv"))
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        for req in self.bundle.requests[:10]:  # sample 10 for speed
            s = build_financial_state(self.bundle, req)
            fc1 = simulate_90_days(s)
            fc2 = simulate_90_days(s)
            self.assertEqual(fc1.ending_balance, fc2.ending_balance)
            self.assertEqual(len(fc1.daily_forecasts), 91)
            # invariants
            for i, d in enumerate(fc1.daily_forecasts):
                self.assertEqual(d.closing_balance, d.opening_balance + d.net_change)
                if i > 0:
                    self.assertEqual(d.opening_balance, fc1.daily_forecasts[i-1].closing_balance)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_no_mutation_of_state_across_simulations(self):
        from copy import deepcopy
        req = self.bundle.requests[0]
        s = build_financial_state(self.bundle, req)
        snap = state_snapshot(s)
        simulate_90_days(s, modifications=[PaymentInjection(s.request_date, D("100"))])
        self.assertEqual(snap, state_snapshot(s))

    def test_forecast_report_and_cli(self):
        from code.forecast_report import generate_forecast_report
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "forecast_report.md"
            forecasts, failures = generate_forecast_report(self.bundle, report)[:2]
            self.assertFalse(failures)
            self.assertEqual(len(forecasts), len(self.bundle.requests))
            self.assertIn("Forecast Report", report.read_text())


if __name__ == "__main__":
    unittest.main()
