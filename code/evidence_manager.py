"""Evidence Manager module.

Coordinates extraction, validation, caching, indexing, and state integration
for all multimodal evidence across the dataset.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import logging
from typing import Dict, List, Optional

from code.evidence import apply_evidence_updates
from code.evidence_models import (
    EvidenceConflict,
    ExtractedImageEvidence,
    ExtractedMessageEvidence,
)
from code.evidence_resolver import EvidenceResolver
from code.evidence_validator import EvidenceValidator
from code.financial_state import FinancialState
from code.image_extractor import ImageEvidenceExtractor
from code.message_extractor import MessageEvidenceExtractor
from code.schemas import DatasetBundle, Request
from code.state_builder import build_financial_state

logger = logging.getLogger(__name__)


@dataclass
class EvidenceBundle:
    """Container holding all extracted and validated multimodal evidence."""

    images: Dict[str, ExtractedImageEvidence] = field(default_factory=dict)
    messages: Dict[str, ExtractedMessageEvidence] = field(default_factory=dict)
    accepted_images: Dict[str, ExtractedImageEvidence] = field(default_factory=dict)
    accepted_messages: Dict[str, ExtractedMessageEvidence] = field(default_factory=dict)
    validation_issues: List[str] = field(default_factory=list)
    conflicts: List[EvidenceConflict] = field(default_factory=list)
    resolver: Optional[EvidenceResolver] = None

    # In-memory lookup indexes
    evidence_by_user_id: Dict[str, List] = field(default_factory=lambda: defaultdict(list))
    evidence_by_event_id: Dict[str, List] = field(default_factory=lambda: defaultdict(list))


class EvidenceManager:
    """Orchestrates end-to-end multimodal evidence intelligence."""

    def __init__(self, bundle: DatasetBundle):
        self.bundle = bundle
        self.image_extractor = ImageEvidenceExtractor()
        self.message_extractor = MessageEvidenceExtractor()
        self.validator = EvidenceValidator(bundle)
        self.resolver = EvidenceResolver(bundle)

    def process_all_evidence(self, use_cache: bool = True) -> EvidenceBundle:
        """Run complete extraction, validation, and indexing workflow."""
        logger.info("Extracting evidence from dynamic image queue...")
        raw_images = self.image_extractor.extract_evidence_queue(self.bundle, use_cache=use_cache)

        logger.info("Extracting evidence from unstructured messages...")
        raw_messages = self.message_extractor.extract_all_messages(self.bundle, use_cache=use_cache)

        logger.info("Validating extracted evidence against domain rules...")
        accepted_images, img_issues = self.validator.validate_image_evidence(raw_images)
        accepted_messages, msg_issues = self.validator.validate_message_evidence(raw_messages)

        evidence_bundle = EvidenceBundle(
            images=raw_images,
            messages=raw_messages,
            accepted_images=accepted_images,
            accepted_messages=accepted_messages,
            validation_issues=img_issues + msg_issues,
            conflicts=[],
            resolver=self.resolver,
        )

        # Build indexes
        for ev in accepted_images.values():
            evidence_bundle.evidence_by_user_id[ev.user_id].append(ev)
            if ev.related_event_id:
                evidence_bundle.evidence_by_event_id[ev.related_event_id].append(ev)

        for ev in accepted_messages.values():
            evidence_bundle.evidence_by_user_id[ev.user_id].append(ev)
            if ev.related_event_id:
                evidence_bundle.evidence_by_event_id[ev.related_event_id].append(ev)

        return evidence_bundle

    def build_evidence_aware_state(
        self,
        request: Request,
        evidence_bundle: EvidenceBundle,
    ) -> FinancialState:
        """Build Phase 2 state and apply resolved Phase 3 evidence updates."""
        # 1. Build baseline Phase 2 state
        base_state = build_financial_state(self.bundle, request)

        # 2. Resolve request-scoped updates
        updates = self.resolver.get_updates_for_request(
            request,
            evidence_bundle.accepted_images,
            evidence_bundle.accepted_messages,
        )

        if not updates:
            return base_state

        # 3. Apply updates deterministically
        updated_state = apply_evidence_updates(base_state, updates)
        return updated_state
