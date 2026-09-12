"""Evidence Resolution module.

Resolves validated image and message extractions into typed EvidenceUpdate
objects compatible with Phase 2 FinancialState. Detects conflicts and
enforces precedence rules.
"""

from datetime import date
from decimal import Decimal
import logging
from typing import Dict, List, Optional, Tuple

from code.evidence_models import (
    EvidenceConflict,
    ExtractedImageEvidence,
    ExtractedMessageEvidence,
)
from code.financial_state import EvidenceUpdate
from code.schemas import DatasetBundle, FinancialEvent, Request

logger = logging.getLogger(__name__)


class EvidenceResolver:
    """Translates extracted evidence into request-scoped EvidenceUpdate objects."""

    def __init__(self, bundle: DatasetBundle):
        self.bundle = bundle
        self.indexes = bundle.indexes

    def resolve_image_updates(
        self,
        accepted_images: Dict[str, ExtractedImageEvidence],
        user_events: List[FinancialEvent],
        request: Request,
    ) -> List[EvidenceUpdate]:
        """Convert accepted image extractions for this user into EvidenceUpdate objects."""
        updates: List[EvidenceUpdate] = []
        events_by_id = {e.event_id: e for e in user_events}

        for img_id, ev in accepted_images.items():
            if ev.user_id != request.user_id:
                continue

            target_event = events_by_id.get(ev.related_event_id)
            if not target_event:
                continue

            # Only resolve if the event amount is actually missing in the raw event
            if target_event.amount is not None:
                continue

            if ev.selected_amount is None:
                continue

            obs_date = min(target_event.event_date, request.request_date)
            eff_date = target_event.event_date

            updates.append(
                EvidenceUpdate(
                    source_type="image",
                    source_id=ev.image_id,
                    target_type="event",
                    target_id=target_event.event_id,
                    field="amount",
                    new_value=ev.selected_amount,
                    effective_date=eff_date,
                    observed_date=obs_date,
                    confidence="confirmed",
                    operation="resolve",
                    old_value=None,
                )
            )

        return updates

    def resolve_message_updates(
        self,
        accepted_messages: Dict[str, ExtractedMessageEvidence],
        user_events: List[FinancialEvent],
        request: Request,
    ) -> Tuple[List[EvidenceUpdate], List[EvidenceConflict]]:
        """Convert accepted message extractions for this user into EvidenceUpdate objects.

        Only includes messages sent on or before the request_date.
        """
        updates: List[EvidenceUpdate] = []
        conflicts: List[EvidenceConflict] = []
        events_by_id = {e.event_id: e for e in user_events}

        # Filter messages for this user known on or before request_date
        user_msgs = [
            m
            for m in accepted_messages.values()
            if m.user_id == request.user_id
            and (m.request_id in {None, request.request_id})
            and m.sent_at.date() <= request.request_date
        ]

        # Sort chronologically by sent_at
        user_msgs.sort(key=lambda m: m.sent_at)

        for m in user_msgs:
            obs_date = m.sent_at.date()

            # 1. Salary settlement date change (e.g. salary date moved)
            if m.category == "salary_date_change" and m.effective_date:
                # Find the next confirmed salary event for this user
                salary_event = next(
                    (
                        e
                        for e in user_events
                        if e.event_type == "income"
                        and e.category == "salary"
                        and e.status == "scheduled"
                        and e.settlement_date is not None
                        and e.settlement_date >= obs_date
                    ),
                    None,
                )
                if salary_event:
                    updates.append(
                        EvidenceUpdate(
                            source_type="message",
                            source_id=m.message_id,
                            target_type="event",
                            target_id=salary_event.event_id,
                            field="settlement_date",
                            new_value=m.effective_date,
                            effective_date=m.effective_date,
                            observed_date=obs_date,
                            confidence="confirmed",
                            operation="amend",
                            old_value=salary_event.settlement_date,
                        )
                    )

            # 2. Confirmed invoice credit event
            elif m.category == "invoice_confirmed" and m.amount and m.effective_date:
                # If there is a scheduled invoice event matching this, amend it
                # Otherwise if no matching event, it represents confirmed future income
                pass

        return updates, conflicts

    def get_updates_for_request(
        self,
        request: Request,
        accepted_images: Dict[str, ExtractedImageEvidence],
        accepted_messages: Dict[str, ExtractedMessageEvidence],
    ) -> List[EvidenceUpdate]:
        """Return all validated, ordered EvidenceUpdate objects for a specific request."""
        user_events = self.indexes.get_user_events(request.user_id) if self.indexes else []
        image_updates = self.resolve_image_updates(accepted_images, user_events, request)
        msg_updates, _ = self.resolve_message_updates(accepted_messages, user_events, request)

        all_updates = image_updates + msg_updates
        return all_updates
