"""Evidence Validation module.

Performs deterministic post-validation on extracted image and message evidence
against domain invariants, currencies, dates, and event context.
"""

from decimal import Decimal
import logging
from typing import Dict, List, Tuple

from code.evidence_models import ExtractedImageEvidence, ExtractedMessageEvidence
from code.normalizers import VALID_CURRENCIES
from code.schemas import DatasetBundle

logger = logging.getLogger(__name__)


class EvidenceValidator:
    """Validates extracted image and message evidence against domain invariants."""

    def __init__(self, bundle: DatasetBundle):
        self.bundle = bundle
        self.profiles_by_id = bundle.indexes.profiles_by_user_id if bundle.indexes else {}
        self.events_by_id = bundle.indexes.events_by_id if bundle.indexes else {}

    def validate_image_evidence(
        self,
        image_evidence: Dict[str, ExtractedImageEvidence],
    ) -> Tuple[Dict[str, ExtractedImageEvidence], List[str]]:
        """Validate extracted image evidence.

        Returns:
            Tuple of (accepted_evidence_dict, issue_strings_list)
        """
        accepted: Dict[str, ExtractedImageEvidence] = {}
        issues: List[str] = []

        for img_id, ev in image_evidence.items():
            if ev.status != "accepted":
                issues.append(f"Image '{img_id}' status is '{ev.status}': {ev.reasoning}")
                continue

            # Check user exists
            if ev.user_id not in self.profiles_by_id:
                issues.append(f"Image '{img_id}' references unknown user '{ev.user_id}'")
                continue

            # Check linked event exists
            if not ev.related_event_id or ev.related_event_id not in self.events_by_id:
                issues.append(f"Image '{img_id}' references missing event '{ev.related_event_id}'")
                continue

            event = self.events_by_id[ev.related_event_id]

            # Check amount is positive finite Decimal
            if (
                ev.selected_amount is None
                or not isinstance(ev.selected_amount, Decimal)
                or not ev.selected_amount.is_finite()
                or ev.selected_amount <= 0
            ):
                issues.append(f"Image '{img_id}' has invalid selected amount: {ev.selected_amount}")
                continue

            # Check currency matches event/profile currency
            if ev.selected_currency and ev.selected_currency not in VALID_CURRENCIES:
                issues.append(f"Image '{img_id}' has unsupported currency: {ev.selected_currency}")
                continue

            accepted[img_id] = ev

        return accepted, issues

    def validate_message_evidence(
        self,
        message_evidence: Dict[str, ExtractedMessageEvidence],
    ) -> Tuple[Dict[str, ExtractedMessageEvidence], List[str]]:
        """Validate extracted message evidence.

        Returns:
            Tuple of (accepted_evidence_dict, issue_strings_list)
        """
        accepted: Dict[str, ExtractedMessageEvidence] = {}
        issues: List[str] = []

        for msg_id, ev in message_evidence.items():
            if ev.status != "accepted":
                continue

            if ev.user_id not in self.profiles_by_id:
                issues.append(f"Message '{msg_id}' references unknown user '{ev.user_id}'")
                continue

            # If amount is present, check finite and non-negative
            if ev.amount is not None:
                if not isinstance(ev.amount, Decimal) or not ev.amount.is_finite() or ev.amount <= 0:
                    issues.append(f"Message '{msg_id}' has invalid monetary amount: {ev.amount}")
                    continue

            # If currency is present, check valid
            if ev.currency and ev.currency not in VALID_CURRENCIES:
                issues.append(f"Message '{msg_id}' has unsupported currency: {ev.currency}")
                continue

            # If percentage is present, check range
            if ev.percentage_change is not None:
                if (
                    not isinstance(ev.percentage_change, Decimal)
                    or not ev.percentage_change.is_finite()
                    or ev.percentage_change <= 0
                ):
                    issues.append(f"Message '{msg_id}' has invalid percentage: {ev.percentage_change}")
                    continue

            accepted[msg_id] = ev

        return accepted, issues
