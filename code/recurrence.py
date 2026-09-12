"""Conservative history-supported cadence inference, with no cash simulation."""

from calendar import monthrange
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta

from code.financial_state import Provenance, Recurrence


def advance(anchor: date, cadence: str, interval: int, steps: int = 1) -> date:
    if interval <= 0 or steps < 0:
        raise ValueError("Recurrence intervals must be positive")
    if cadence == "fixed_days":
        return anchor + timedelta(days=interval * steps)
    if cadence != "calendar_months":
        raise ValueError("Unsupported cadence")
    month = anchor.year * 12 + anchor.month - 1 + interval * steps
    year, zero_month = divmod(month, 12)
    last = monthrange(year, zero_month + 1)[1]
    end_of_month = anchor.day == monthrange(anchor.year, anchor.month)[1]
    return date(year, zero_month + 1, last if end_of_month else min(anchor.day, last))


def detect_cadence(dates):
    """Require three distinct observations and two identical calendar/day gaps."""
    if len(dates) < 3 or len(set(dates)) != len(dates):
        return None
    month_gaps = [(b.year-a.year)*12+b.month-a.month for a, b in zip(dates, dates[1:])]
    if len(set(month_gaps)) == 1 and month_gaps[0] > 0:
        interval = month_gaps[0]
        if all(advance(dates[0], "calendar_months", interval, i) == d
               for i, d in enumerate(dates)):
            return "calendar_months", interval
    gaps = [(b-a).days for a, b in zip(dates, dates[1:])]
    if len(set(gaps)) == 1 and gaps[0] > 0:
        return "fixed_days", gaps[0]
    return None


def infer_recurrences(items, request_date):
    """Group source descriptions first; use category cadence only as fallback.

    Category fallback is debit-only, homogeneous in flexibility/currency/type,
    and requires >=4 observations. This captures variable essential spending
    whose merchant descriptions vary without merging unrelated income sources.
    Every credit series remains derived, never a confirmed future inflow.
    """
    groups = defaultdict(list)
    for item in items:
        e = item.event
        if (item.cash_class in {"settled_income", "settled_debit"}
                and e.settlement_date is not None and e.settlement_date <= request_date
                and not e.linked_event_id and e.event_type in {"income", "expense", "subscription", "debt_payment"}):
            key = (e.event_type, e.category, e.direction, e.currency, e.flexibility)
            groups[key].append(item)
    results = []
    for key, group in sorted(groups.items()):
        by_source = defaultdict(list)
        for item in group:
            by_source[item.event.description].append(item)
        candidates = []
        used = set()
        for _, source in sorted(by_source.items()):
            source.sort(key=lambda x: (x.event.settlement_date, x.event_id))
            cadence = detect_cadence([x.event.settlement_date for x in source])
            if cadence:
                candidates.append((source, cadence, "derived_source_history"))
                used.update(x.event_id for x in source)
        remaining = sorted((x for x in group if x.event_id not in used),
                           key=lambda x: (x.event.settlement_date, x.event_id))
        if key[2] == "debit" and len(remaining) >= 4:
            cadence = detect_cadence([x.event.settlement_date for x in remaining])
            if cadence:
                candidates.append((remaining, cadence, "derived_category_history"))
        for source, (cadence, interval), confidence in candidates:
            latest = source[-1]
            anchor = source[0].event.settlement_date
            step = len(source)
            next_date = advance(anchor, cadence, interval, step)
            # A missed occurrence does not prove cancellation. Debit patterns
            # remain obligations with stale confidence; credit patterns expire.
            stale = next_date < request_date
            while next_date < request_date:
                step += 1
                next_date = advance(anchor, cadence, interval, step)
            amounts = [x.event.amount for x in source]
            amount = None if None in amounts else (
                max(amounts) if key[2] == "debit" else min(amounts))
            # Same source with known future scheduled occurrence replaces that
            # recurrence occurrence, rather than adding a second payment.
            explicit = tuple(sorted({x.forecast_date for x in items
                                     if x.forecast_date is not None
                                     and x.event.direction == key[2]
                                     and x.event.category == key[1]
                                     and x.event.currency == key[3]
                                     and x.event.description == latest.event.description
                                     and x.cash_class in {"scheduled_debit", "pending_debit", "confirmed_future_income"}}))
            results.append(Recurrence(
                "recurrence:" + source[0].event_id, latest.event_id,
                tuple(x.event_id for x in source), key[1], key[2], key[3], amount,
                "unresolved" if amount is None else ("historical_max" if key[2] == "debit" else "historical_min"),
                cadence, interval, anchor, next_date, None,
                "stale_" + confidence if stale else confidence,
                not stale or key[2] == "debit", latest.protected,
                latest.can_reduce, latest.can_stop, latest.event.minimum_allowed_amount,
                explicit, tuple(Provenance("financial_event", x.event_id, "recurrence",
                                           x.event.settlement_date, confidence) for x in source),
            ))
    # A schedule can use a different description (e.g. next salary versus
    # historical payroll). Match only an unambiguous cadence/date/currency/type
    # occurrence; never suppress two separate sources in the same category.
    for item in items:
        if item.forecast_date is None or item.cash_class not in {"confirmed_future_income", "scheduled_debit", "pending_debit"}:
            continue
        matches = []
        for index, r in enumerate(results):
            if (r.direction, r.category, r.currency) != (item.event.direction, item.event.category, item.event.currency):
                continue
            occurrence = r.anchor_date
            step = 0
            while occurrence < item.forecast_date:
                step += 1
                occurrence = advance(r.anchor_date, r.cadence, r.interval, step)
            if occurrence == item.forecast_date:
                matches.append(index)
        if len(matches) == 1:
            index = matches[0]
            r = results[index]
            results[index] = replace(r, explicit_occurrence_dates=tuple(sorted(
                set(r.explicit_occurrence_dates) | {item.forecast_date})))
    return tuple(sorted(results, key=lambda r: r.recurrence_id))
