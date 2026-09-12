"""Unit and integration tests for Phase 3: Multimodal Evidence Intelligence."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from code.data_loader import load_dataset
from code.evidence_manager import EvidenceManager
from code.evidence_models import CandidateAmount, ExtractedImageEvidence, ExtractedMessageEvidence
from code.evidence_resolver import EvidenceResolver
from code.evidence_validator import EvidenceValidator
from code.financial_state import EvidenceUpdate
from code.image_extractor import ImageEvidenceExtractor
from code.message_extractor import MessageEvidenceExtractor
from code.schemas import FinancialEvent, Message, Request
from code.state_builder import build_financial_state, validate_financial_state


class TestImageEvidenceExtraction(unittest.TestCase):
    """Test image document parsing, candidate selection, and validation."""

    def setUp(self):
        self.extractor = ImageEvidenceExtractor()
        self.bundle = load_dataset()

    def test_dynamic_evidence_queue_extraction(self):
        """Confirm all 16 items in dynamic evidence queue are extracted and accepted."""
        results = self.extractor.extract_evidence_queue(self.bundle, use_cache=True)
        self.assertEqual(len(results), 16)
        for img_id, ev in results.items():
            self.assertEqual(ev.status, "accepted")
            self.assertIsNotNone(ev.selected_amount)
            self.assertGreater(ev.selected_amount, Decimal(0))
            self.assertIn(ev.selected_currency, {"IDR", "INR", "USD", "EUR", "ZAR"})

    def test_missing_image_file_handling(self):
        """Test graceful rejection when image file does not exist."""
        from code.schemas import EvidenceReference

        missing_ref = EvidenceReference(
            event_id="event_fake",
            user_id="user_fake",
            image_id="image_missing",
            image_path=Path("non_existent_image.png"),
            amount_status="requires_extraction",
        )
        res = self.extractor.extract_single_image(missing_ref)
        self.assertEqual(res.status, "rejected")
        self.assertIn("does not exist", res.reasoning)


class TestMessageEvidenceExtraction(unittest.TestCase):
    """Test message parsing across languages, categories, and patterns."""

    def setUp(self):
        self.extractor = MessageEvidenceExtractor()

    def test_salary_increase_english(self):
        msg = Message(
            message_id="msg_test_01",
            user_id="user_01",
            request_id=None,
            related_event_id=None,
            sent_at=datetime(2026, 7, 1, 9, 30, tzinfo=timezone.utc),
            source_type="employer",
            message_text="Your monthly salary has increased to USD 2988. The change applies from 2026-07-15.",
        )
        res = self.extractor.extract_single_message(msg)
        self.assertEqual(res.category, "salary_update")
        self.assertEqual(res.amount, Decimal("2988"))
        self.assertEqual(res.currency, "USD")
        self.assertEqual(res.effective_date, date(2026, 7, 15))
        self.assertEqual(res.status, "accepted")

    def test_salary_increase_indonesian(self):
        msg = Message(
            message_id="msg_test_02",
            user_id="user_02",
            request_id=None,
            related_event_id=None,
            sent_at=datetime(2025, 7, 29, 9, 30, tzinfo=timezone.utc),
            source_type="employer",
            message_text="Rincian penggajian Anda di Cobalt Systems telah berubah. Gaji bulanan Anda naik menjadi IDR 42750000. Perubahan ini berlaku mulai 2025-08-15.",
        )
        res = self.extractor.extract_single_message(msg)
        self.assertEqual(res.category, "salary_update")
        self.assertEqual(res.amount, Decimal("42750000"))
        self.assertEqual(res.currency, "IDR")
        self.assertEqual(res.effective_date, date(2025, 8, 15))

    def test_rent_increase_percentage(self):
        msg = Message(
            message_id="msg_test_03",
            user_id="user_16",
            request_id=None,
            related_event_id=None,
            sent_at=datetime(2023, 8, 1, 9, 30, tzinfo=timezone.utc),
            source_type="service_provider",
            message_text="The renewed lease increases monthly rent by 12%. The new amount will be used for the next rent payment.",
        )
        res = self.extractor.extract_single_message(msg)
        self.assertEqual(res.category, "rent_increase")
        self.assertEqual(res.percentage_change, Decimal("12"))
        self.assertEqual(res.effective_date, date(2023, 8, 1))

    def test_contract_ended(self):
        msg = Message(
            message_id="msg_test_04",
            user_id="user_12",
            request_id=None,
            related_event_id=None,
            sent_at=datetime(2026, 3, 25, 9, 30, tzinfo=timezone.utc),
            source_type="employer",
            message_text="The current seasonal contract has ended. No off-season income or renewal has been confirmed.",
        )
        res = self.extractor.extract_single_message(msg)
        self.assertEqual(res.category, "contract_end")
        self.assertEqual(res.end_date, date(2026, 3, 25))

    def test_pending_bonus_hold(self):
        msg = Message(
            message_id="msg_test_05",
            user_id="user_04",
            request_id=None,
            related_event_id=None,
            sent_at=datetime(2024, 6, 1, 9, 30, tzinfo=timezone.utc),
            source_type="employer",
            message_text="Your quarterly bonus is still subject to the final performance review. The final amount and payment date have not been approved yet.",
        )
        res = self.extractor.extract_single_message(msg)
        self.assertEqual(res.category, "pending_hold")
        self.assertIsNone(res.amount)

    def test_internal_transfer_neutral(self):
        msg = Message(
            message_id="msg_test_06",
            user_id="user_18",
            request_id=None,
            related_event_id=None,
            sent_at=datetime(2026, 7, 1, 9, 30, tzinfo=timezone.utc),
            source_type="bank",
            message_text="The matching debit and credit came from a transfer between your two accounts.",
        )
        res = self.extractor.extract_single_message(msg)
        self.assertEqual(res.category, "internal_transfer")


class TestEvidenceStateIntegration(unittest.TestCase):
    """End-to-end integration of Phase 3 evidence into Phase 2 FinancialState."""

    def setUp(self):
        self.bundle = load_dataset()
        self.manager = EvidenceManager(self.bundle)
        self.evidence_bundle = self.manager.process_all_evidence(use_cache=True)

    def test_image_amount_resolution_in_financial_state(self):
        """Verify user_03 request_03 missing salary event is resolved by image_01."""
        req_03 = self.bundle.indexes.sample_requests_by_id["request_03"]

        # Base state before evidence has unresolved amount
        base_state = build_financial_state(self.bundle, req_03)
        unresolved_events = [e for e in base_state.events if e.money.amount_status == "unresolved_amount"]
        self.assertEqual(len(unresolved_events), 1)
        self.assertEqual(unresolved_events[0].event_id, "event_253")

        # Evidence-aware state resolves event_253 with image_01 (4,365,000 IDR)
        updated_state = self.manager.build_evidence_aware_state(req_03, self.evidence_bundle)
        evt_253_state = next(e for e in updated_state.events if e.event_id == "event_253")

        self.assertEqual(evt_253_state.money.amount_status, "known")
        self.assertEqual(evt_253_state.money.original_amount, Decimal("4365000"))
        self.assertEqual(evt_253_state.money.normalized_amount, Decimal("4365000"))

        # State validation invariant holds
        self.assertTrue(validate_financial_state(updated_state))

    def test_all_sample_states_build_cleanly_with_evidence(self):
        """Verify all 25 sample requests integrate evidence without invariant violations."""
        for req in self.bundle.sample_requests:
            state = self.manager.build_evidence_aware_state(req, self.evidence_bundle)
            self.assertTrue(validate_financial_state(state))


if __name__ == "__main__":
    unittest.main()
