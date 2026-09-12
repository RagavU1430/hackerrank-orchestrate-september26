"""Phase 3 integration: validated structured facts, without parsing messages/images."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from code.financial_state import EvidenceUpdate, Provenance
from code.schemas import FinancialEvent

EVENT_FIELDS = {"amount", "status", "settlement_date", "minimum_allowed_amount"}
RECURRENCE_FIELDS = {"amount", "end_date"}


def validate_updates(updates, source_events, metadata, request):
    events = {e.event_id: e for e in source_events}
    sources = {(m.source_type, m.source_id): m for m in metadata}
    seen = {}
    for u in updates:
        if not isinstance(u, EvidenceUpdate):
            raise ValueError("Evidence must be a typed EvidenceUpdate")
        if u.source_type not in {"message", "image"} or (u.source_type, u.source_id) not in sources:
            raise ValueError("Evidence source is absent or outside this request's scope")
        source = sources[u.source_type, u.source_id]
        if source.status == "missing":
            raise ValueError("Missing image cannot establish a fact")
        if type(u.observed_date) is not date or type(u.effective_date) is not date:
            raise ValueError("Evidence dates must be dates")
        if source.observed_date and u.observed_date < source.observed_date:
            raise ValueError("Evidence cannot be known before its source")
        if u.confidence not in {"confirmed", "uncertain"}:
            raise ValueError("Unsupported evidence confidence")
        if u.target_type not in {"event", "recurrence"} or u.operation not in {"resolve", "amend", "add"}:
            raise ValueError("Unsupported evidence target or operation")
        if u.operation == "add":
            e = u.new_value
            if (u.target_type != "event" or u.field != "event" or not isinstance(e, FinancialEvent)
                    or e.event_id != u.target_id or e.user_id != request.user_id
                    or e.event_id in events or e.event_date != u.effective_date):
                raise ValueError("Added evidence event must be new, user-scoped and effective-dated")
            events[e.event_id] = e
        else:
            fields = EVENT_FIELDS if u.target_type == "event" else RECURRENCE_FIELDS
            if u.field not in fields:
                raise ValueError("Evidence field is not allowed")
            if u.target_type == "event" and u.target_id not in events:
                raise ValueError("Evidence target event is missing")
            if (source.related_event_id and u.target_type == "event"
                    and source.related_event_id != u.target_id):
                raise ValueError("Evidence source is linked to a different event")
            if u.field in {"amount", "minimum_allowed_amount"}:
                if not isinstance(u.new_value, Decimal) or not u.new_value.is_finite() or u.new_value < 0:
                    raise ValueError("Evidence amount must be a nonnegative finite Decimal")
            if u.field in {"settlement_date", "end_date"} and type(u.new_value) is not date:
                raise ValueError("Evidence date must be a date")
            if u.field == "status" and u.new_value not in {"settled", "scheduled", "pending", "failed", "cancelled", "unrealized"}:
                raise ValueError("Unsupported evidence status")
        key = (u.target_type, u.target_id, u.field, u.effective_date, u.observed_date)
        if key in seen and seen[key] != u:
            raise ValueError("Conflicting simultaneous evidence requires Phase 3 resolution")
        seen[key] = u


def ordered_updates(updates):
    unique = []
    for u in updates:
        if not isinstance(u, EvidenceUpdate) or type(u.effective_date) is not date or type(u.observed_date) is not date:
            raise ValueError("Evidence must have typed updates and valid dates")
        if any(not isinstance(v, str) for v in (u.source_type, u.source_id, u.target_type, u.target_id, u.field)):
            raise ValueError("Evidence source, target and field must be strings")
        if u not in unique:
            unique.append(u)
    return tuple(sorted(unique, key=lambda u: (
        u.effective_date, u.observed_date, u.source_type, u.source_id, u.target_type, u.target_id, u.field)))


def apply_fields(value, updates, target_type, target_id, on_date, known_on):
    for u in updates:
        if (u.target_type != target_type or u.target_id != target_id or u.operation == "add"
                or u.confidence != "confirmed" or u.observed_date > known_on or u.effective_date > on_date):
            continue
        old = getattr(value, u.field)
        if u.operation == "resolve" and old is not None:
            if old == u.new_value:
                continue
            raise ValueError("Resolution cannot overwrite an explicit structured value; use amendment")
        if u.operation == "amend" and old != u.old_value:
            raise ValueError("Amendment old_value does not match; resolve conflict explicitly")
        value = replace(value, **{u.field: u.new_value})
        if target_type == "recurrence":
            value = replace(value, provenance=value.provenance + (
                Provenance(u.source_type, u.source_id, u.field, u.effective_date, u.confidence),))
            if u.field == "amount":
                value = replace(value, amount_policy="confirmed_evidence")
    return value


def event_on_date(state, event_id, on_date):
    """Materialize a known event's future amendments without reopening data."""
    if on_date < state.request_date:
        raise ValueError("Use a request-specific rebuild for dates before this state")
    originals = {e.event_id: e for e in state.source_events}
    for u in state.evidence_updates:
        if (u.operation == "add" and u.confidence == "confirmed"
                and u.observed_date <= state.request_date):
            originals[u.target_id] = u.new_value
    if event_id not in originals:
        raise ValueError("Unknown event")
    return apply_fields(originals[event_id], state.evidence_updates, "event", event_id,
                        on_date, state.request_date)


def recurrence_on_date(state, recurrence_id, on_date):
    """Return future-dated recurrence terms. End dates do not remove provenance."""
    if on_date < state.request_date:
        raise ValueError("Cannot resolve recurrence before state date")
    # Re-infer from the current event facts, then apply the complete timeline once.
    from code.recurrence import infer_recurrences
    recurrence = next((r for r in infer_recurrences(state.events, state.request_date)
                       if r.recurrence_id == recurrence_id), None)
    if recurrence is None:
        raise ValueError("Unknown recurrence")
    recurrence = apply_fields(recurrence, state.evidence_updates, "recurrence", recurrence_id,
                              on_date, state.request_date)
    if recurrence.end_date and on_date > recurrence.end_date:
        recurrence = replace(recurrence, active=False)
    return recurrence


def apply_evidence_updates(state, evidence_updates):
    """Return a fresh, validated state. Never mutate the Phase 1 bundle or input state."""
    from code.state_builder import reconstruct_state
    updates = ordered_updates(state.evidence_updates + tuple(evidence_updates))
    return reconstruct_state(state.profile, state.request, state.source_events,
                             state.exchange_rates, state.payment_options, state.evidence, updates)
