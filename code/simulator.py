"""Deterministic 90-day cash-flow simulator.

Consumes Phase 2 FinancialState + validated evidence.
No final affordability decisions. Only forecasts balance day by day.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import logging
from typing import Dict, List, Tuple, Union

from code.evidence import event_on_date, recurrence_on_date
from code.financial_state import FinancialState
from code.recurrence import advance
from code.simulation_models import (
    CashFlowForecast,
    DailyForecast,
    ForecastWarning,
    LedgerEntry,
    PaymentInjection,
    ReduceExpense,
    StopExpense,
)

logger = logging.getLogger(__name__)

FORECAST_DAYS = 90  # inclusive window is 91 snapshots: Day 0 .. Day 90
Modification = Union[PaymentInjection, StopExpense, ReduceExpense]


def _decimal_zero() -> Decimal:
    return Decimal("0")


def _validate_modifications(mods, state: FinancialState):
    for m in mods:
        if isinstance(m, PaymentInjection):
            if not isinstance(m.payment_date, date):
                raise ValueError("PaymentInjection date must be a date")
            if not isinstance(m.amount, Decimal) or not m.amount.is_finite() or m.amount < 0:
                raise ValueError("PaymentInjection amount must be nonnegative finite Decimal")
            if m.currency is not None and not isinstance(m.currency, str):
                raise ValueError("PaymentInjection currency must be string or None")
        elif isinstance(m, StopExpense):
            if not m.target_id or not isinstance(m.target_id, str):
                raise ValueError("StopExpense target_id invalid")
        elif isinstance(m, ReduceExpense):
            if not m.target_id or not isinstance(m.target_id, str):
                raise ValueError("ReduceExpense target_id invalid")
            if not isinstance(m.new_amount, Decimal) or not m.new_amount.is_finite() or m.new_amount < 0:
                raise ValueError("ReduceExpense new_amount must be nonnegative finite Decimal")
        else:
            raise ValueError("Unknown modification type")


def _convert(amount: Decimal, currency: str, home_currency: str, rate_date: date,
             rates: Dict, warnings: List[ForecastWarning], source_id: str) -> Tuple[Decimal | None, Decimal | None, date | None, str]:
    if amount is None:
        warnings.append(ForecastWarning("UNRESOLVED EVIDENCE", "unresolved_amount", source_id, "Missing monetary amount cannot be forecast."))
        return None, None, None, "unresolved_amount"
    if currency not in {"INR", "ZAR", "IDR", "USD", "EUR"}:
        warnings.append(ForecastWarning("DATASET ISSUE", "unresolved_currency", source_id, f"Unknown currency {currency}."))
        return None, None, None, "unresolved_currency"
    if currency == home_currency:
        return amount, Decimal("1"), None, "known"
    rate = rates.get((currency, home_currency, rate_date))
    if rate is None or not rate.is_finite() or rate <= 0:
        warnings.append(ForecastWarning("UNRESOLVED EVIDENCE", "unresolved_rate", source_id,
                                        f"Missing exchange rate {currency}->{home_currency} on {rate_date}."))
        return None, None, None, "unresolved_rate"
    return amount * rate, rate, rate_date, "known"


def _event_active_on(forecast_date: date, event, state: FinancialState):
    # Materialize event at forecast date to respect effective-dated amendments
    try:
        current = event_on_date(state, event.event_id, forecast_date)
    except Exception:
        # If not materializable, use original
        current = event
    return current


def _build_daily_ledger(state: FinancialState, start_date: date, end_date: date,
                        modifications: Tuple[Modification, ...]) -> Tuple[Dict[date, List[LedgerEntry]], List[ForecastWarning]]:
    warnings: List[ForecastWarning] = []
    ledger: Dict[date, List[LedgerEntry]] = defaultdict(list)

    rates = state.exchange_rates
    home = state.currency

    # Index modifications for fast lookup
    stops = {m.target_id for m in modifications if isinstance(m, StopExpense)}
    reduces = {m.target_id: m.new_amount for m in modifications if isinstance(m, ReduceExpense)}
    # Validate reduce not below zero etc handled elsewhere

    # Helper to check if entry should be stopped/reduced
    def is_stopped(entry_id: str, recurrence_id: str = "") -> bool:
        return entry_id in stops or recurrence_id in stops

    def reduced_amount(entry_id: str, recurrence_id: str, normalized: Decimal) -> Decimal:
        # Reduce applies to normalized home-currency amount
        if entry_id in reduces:
            cap = reduces[entry_id]
            return cap if cap < normalized else normalized
        if recurrence_id in reduces:
            cap = reduces[recurrence_id]
            return cap if cap < normalized else normalized
        return normalized

    # 1. Pending / scheduled / confirmed future income events with forecast_date
    for item in state.events:
        if item.forecast_date is None:
            continue
        if item.forecast_date < start_date or item.forecast_date > end_date:
            continue
        if item.cash_class in {"excluded", "superseded", "not_yet_known", "non_cash", "settled_debit", "settled_income", "pending_income", "uncertain_income"}:
            continue
        # Only forecast relevant classes: pending_debit, scheduled_debit, unsettled_debit, confirmed_future_income
        # But allow pending_debit etc filtered above; include remaining with forecast_date except excluded
        if item.cash_class not in {"pending_debit", "scheduled_debit", "unsettled_debit", "scheduled_future", "scheduled_due", "confirmed_future_income", "awaiting_settlement"}:
            # Actually awaiting_settlement for debit was classified as unsettled_debit already, so above covers.
            # Safer to include any remaining where forecast_date exists and direction is relevant and not excluded
            pass

        # Skip if superseded
        if item.superseded_by:
            continue

        # Check stops: if event_id is stopped, skip
        if item.event_id in stops:
            continue

        # Materialize event at its forecast date to get effective amount/date (evidence amendments)
        try:
            eff_event = event_on_date(state, item.event_id, item.forecast_date)
        except Exception as exc:
            warnings.append(ForecastWarning("DATASET ISSUE", "event_materialize_failed", item.event_id, str(exc)))
            continue

        if eff_event.amount is None:
            warnings.append(ForecastWarning("UNRESOLVED EVIDENCE", "unresolved_amount", item.event_id, "Event amount remains unresolved."))
            continue
        # Determine direction
        direction = eff_event.direction
        if direction not in {"credit", "debit"}:
            continue

        normalized, rate_used, rate_date, status = _convert(eff_event.amount, eff_event.currency, home, eff_event.settlement_date or item.forecast_date, rates, warnings, item.event_id)
        if normalized is None:
            continue
        # Apply reduction if any
        orig_normalized = normalized
        if item.event_id in reduces:
            normalized = reduced_amount(item.event_id, "", normalized)
            if normalized != orig_normalized:
                warnings.append(ForecastWarning("SIMULATION", "reduce_applied", item.event_id, f"Reduced {orig_normalized} -> {normalized}"))

        entry = LedgerEntry(
            entry_id=f"event:{item.event_id}:{item.forecast_date.isoformat()}",
            source_type="event",
            source_id=item.event_id,
            category=eff_event.category,
            direction=direction,
            original_amount=eff_event.amount,
            original_currency=eff_event.currency,
            normalized_amount=normalized,
            normalized_currency=home,
            exchange_rate_used=rate_used,
            exchange_rate_date=rate_date,
            amount_status=status,
        )
        ledger[item.forecast_date].append(entry)

    # 2. Recurring inflows/outflows
    for rec in state.recurrences:
        # Stopped recurrence globally
        if rec.recurrence_id in stops:
            continue
        if rec.event_id in stops:
            continue
        if not rec.active:
            continue
        # Find step index n0 such that advance(anchor, cadence, interval, n0) == next_expected_date
        n0 = None
        for n in range(0, 600):
            try:
                cand = advance(rec.anchor_date, rec.cadence, rec.interval, n)
            except Exception:
                break
            if cand == rec.next_expected_date:
                n0 = n
                break
            if cand > rec.next_expected_date:
                break
        if n0 is None:
            warnings.append(ForecastWarning("DATASET ISSUE", "recurrence_anchor_mismatch", rec.recurrence_id,
                                            f"Could not align next_expected_date {rec.next_expected_date} with anchor {rec.anchor_date}."))
            continue
        n = n0
        while True:
            try:
                current_date = advance(rec.anchor_date, rec.cadence, rec.interval, n)
            except Exception as exc:
                warnings.append(ForecastWarning("DATASET ISSUE", "advance_failed", rec.recurrence_id, str(exc)))
                break
            if current_date > end_date:
                break
            if current_date >= start_date:
                try:
                    eff_rec = recurrence_on_date(state, rec.recurrence_id, current_date)
                except Exception as exc:
                    warnings.append(ForecastWarning("DATASET ISSUE", "recurrence_materialize_failed", rec.recurrence_id, str(exc)))
                    eff_rec = rec

                if not eff_rec.active:
                    if eff_rec.end_date and current_date > eff_rec.end_date:
                        break
                    # inactive but before end -> skip this occurrence and continue
                else:
                    if current_date in eff_rec.explicit_occurrence_dates:
                        pass
                    elif eff_rec.recurrence_id in stops or eff_rec.event_id in stops:
                        pass
                    else:
                        if eff_rec.amount is None:
                            warnings.append(ForecastWarning("UNRESOLVED EVIDENCE", "unresolved_amount", rec.recurrence_id,
                                                            f"Recurrence {rec.recurrence_id} amount unresolved on {current_date}."))
                        else:
                            normalized, rate_used, rate_date, status = _convert(
                                eff_rec.amount, eff_rec.currency, home, current_date, rates, warnings, rec.recurrence_id)
                            if normalized is not None:
                                orig_norm = normalized
                                normalized = reduced_amount(eff_rec.event_id, eff_rec.recurrence_id, normalized)
                                if normalized != orig_norm:
                                    warnings.append(ForecastWarning("SIMULATION", "reduce_applied", rec.recurrence_id, f"Reduced {orig_norm} -> {normalized}"))
                                entry = LedgerEntry(
                                    entry_id=f"recurrence:{rec.recurrence_id}:{current_date.isoformat()}",
                                    source_type="recurrence",
                                    source_id=rec.recurrence_id,
                                    category=eff_rec.category,
                                    direction=eff_rec.direction,
                                    original_amount=eff_rec.amount,
                                    original_currency=eff_rec.currency,
                                    normalized_amount=normalized,
                                    normalized_currency=home,
                                    exchange_rate_used=rate_used,
                                    exchange_rate_date=rate_date,
                                    amount_status=status,
                                )
                                ledger[current_date].append(entry)
            n += 1

    # 3. Payment injections
    for inj in [m for m in modifications if isinstance(m, PaymentInjection)]:
        if inj.payment_date < start_date or inj.payment_date > end_date:
            continue
        curr = inj.currency or home
        normalized, rate_used, rate_date, status = _convert(inj.amount, curr, home, inj.payment_date, rates, warnings, inj.payment_id)
        if normalized is None:
            continue
        entry = LedgerEntry(
            entry_id=f"payment:{inj.payment_id}:{inj.payment_date.isoformat()}",
            source_type="payment_injection",
            source_id=inj.payment_id,
            category="hypothetical_payment",
            direction="debit",
            original_amount=inj.amount,
            original_currency=curr,
            normalized_amount=normalized,
            normalized_currency=home,
            exchange_rate_used=rate_used,
            exchange_rate_date=rate_date,
            amount_status=status,
        )
        ledger[inj.payment_date].append(entry)

    return ledger, warnings


def _find_step(anchor: date, cadence: str, interval: int, target: date) -> int | None:
    for n in range(0, 600):
        cand = advance(anchor, cadence, interval, n)
        if cand == target:
            return n
        if cand > target:
            return None
    return None


def simulate_90_days(
    financial_state: FinancialState,
    start_date: date = None,
    modifications: List[Modification] = None,
) -> CashFlowForecast:
    """Deterministic 90-day forecast.

    Window is inclusive: start_date .. start_date+90 (91 days).
    Baseline excludes hypothetical purchase; flexible spending still occurs.
    """
    if financial_state is None:
        raise ValueError("Missing FinancialState")
    if start_date is None:
        start_date = financial_state.request_date
    if type(start_date) is not date:
        raise ValueError("Start date must be a date")
    if financial_state.profile is None or financial_state.request is None:
        raise ValueError("Invalid FinancialState: missing profile/request")
    if not isinstance(financial_state.available_balance, Decimal) or not financial_state.available_balance.is_finite():
        raise ValueError("Starting balance must be finite Decimal")
    if not isinstance(financial_state.minimum_balance_to_keep, Decimal) or not financial_state.minimum_balance_to_keep.is_finite() or financial_state.minimum_balance_to_keep < 0:
        raise ValueError("Minimum balance must be nonnegative finite Decimal")

    mods = tuple(modifications or ())
    _validate_modifications(mods, financial_state)

    # Immutability guard: snapshot key fields
    before_available = financial_state.available_balance

    end_date = start_date + timedelta(days=FORECAST_DAYS)
    ledger, warnings = _build_daily_ledger(financial_state, start_date, end_date, mods)

    total_inflows = _decimal_zero()
    total_outflows = _decimal_zero()
    daily: List[DailyForecast] = []

    opening = financial_state.available_balance
    first_breach: date | None = None
    min_observed = opening
    min_date = start_date
    min_headroom = opening - financial_state.minimum_balance_to_keep
    # Initialize for Day 0 opening before any flows? We'll track closing instead
    # But we also want to detect breach on Day 0 closing.

    invariant_ok_global = True

    cur = start_date
    one_day = timedelta(days=1)
    while cur <= end_date:
        entries = ledger.get(cur, [])
        inflows = tuple(e for e in entries if e.direction == "credit")
        outflows = tuple(e for e in entries if e.direction == "debit")

        # Sort deterministically by source_id and entry_id
        inflows = tuple(sorted(inflows, key=lambda e: (e.source_id, e.entry_id)))
        outflows = tuple(sorted(outflows, key=lambda e: (e.source_id, e.entry_id)))

        sum_in = sum((e.normalized_amount for e in inflows), _decimal_zero())
        sum_out = sum((e.normalized_amount for e in outflows), _decimal_zero())
        net = sum_in - sum_out
        closing = opening + net
        headroom = closing - financial_state.minimum_balance_to_keep
        inv_ok = closing >= financial_state.minimum_balance_to_keep

        if not inv_ok and first_breach is None:
            first_breach = cur
        if closing < min_observed:
            min_observed = closing
            min_date = cur
        if headroom < min_headroom:
            min_headroom = headroom
        if not inv_ok:
            invariant_ok_global = False

        daily.append(DailyForecast(
            forecast_date=cur,
            opening_balance=opening,
            inflows=inflows,
            outflows=outflows,
            total_inflows=sum_in,
            total_outflows=sum_out,
            net_change=net,
            closing_balance=closing,
            minimum_balance=financial_state.minimum_balance_to_keep,
            headroom=headroom,
            invariant_ok=inv_ok,
        ))

        total_inflows += sum_in
        total_outflows += sum_out

        opening = closing
        cur += one_day

        # Immutability check mid-loop (state should not have changed)
        if financial_state.available_balance != before_available:
            raise ValueError("FinancialState was mutated during simulation")

    ending = daily[-1].closing_balance if daily else financial_state.available_balance

    forecast = CashFlowForecast(
        user_id=financial_state.user_id,
        request_id=financial_state.request_id,
        start_date=start_date,
        end_date=end_date,
        starting_balance=financial_state.available_balance,
        ending_balance=ending,
        minimum_balance=financial_state.minimum_balance_to_keep,
        minimum_balance_date=min_date,
        minimum_observed_balance=min_observed,
        minimum_headroom=min_headroom,
        first_breach_date=first_breach,
        total_inflows=total_inflows,
        total_outflows=total_outflows,
        daily_forecasts=tuple(daily),
        warnings=tuple(warnings),
        invariant_ok=invariant_ok_global,
    )

    # Invariants for forecast itself
    for i, d in enumerate(forecast.daily_forecasts):
        if d.closing_balance != d.opening_balance + d.net_change:
            raise ValueError("Forecast invariant violated: closing != opening + net")
        if d.net_change != d.total_inflows - d.total_outflows:
            raise ValueError("Forecast net_change invariant violated")
        if i > 0 and d.opening_balance != forecast.daily_forecasts[i - 1].closing_balance:
            raise ValueError("Day continuity violated")
        if not isinstance(d.closing_balance, Decimal):
            raise ValueError("Balance must be Decimal")

    if financial_state.available_balance != before_available:
        raise ValueError("FinancialState mutated post-simulation")

    logger.info("Forecast %s: %s -> %s start %s end %s breach %s headroom %s",
                forecast.request_id, forecast.start_date, forecast.end_date,
                forecast.starting_balance, forecast.ending_balance, forecast.first_breach_date, forecast.minimum_headroom)

    return forecast


def simulate_with_payment(
    financial_state: FinancialState,
    payment_date: date,
    payment_amount: Decimal,
    currency: str = None,
) -> CashFlowForecast:
    """Convenience helper for hypothetical single payment."""
    if not isinstance(payment_amount, Decimal):
        payment_amount = Decimal(str(payment_amount))
    return simulate_90_days(
        financial_state,
        start_date=financial_state.request_date,
        modifications=[PaymentInjection(payment_date=payment_date, amount=payment_amount,
                                        currency=currency or financial_state.currency)],
    )
