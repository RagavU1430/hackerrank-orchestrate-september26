"""Unit tests for Phase 1: Data Foundation & Ingestion."""

from datetime import date, datetime, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from code.data_loader import build_evidence_queue, load_dataset
from code.indexes import build_indexes
from code.normalizers import (
    parse_bool,
    parse_currency,
    parse_date,
    parse_datetime,
    parse_decimal,
    parse_int,
    parse_pipe_list,
)
from code.schemas import (
    FinancialEvent,
    FinancialProfile,
    ImageReference,
    PaymentOption,
    Request,
    SampleRequest,
)
from code.validators import (
    ValidationResult,
    validate_cross_references,
    validate_header,
    validate_identifiers,
)


class TestNormalizers(unittest.TestCase):
    """Test safe parsing and normalization functions."""

    def test_parse_decimal_valid(self):
        self.assertEqual(parse_decimal("100"), Decimal("100"))
        self.assertEqual(parse_decimal("1000.50"), Decimal("1000.50"))
        self.assertEqual(parse_decimal("1,234,567.89"), Decimal("1234567.89"))
        self.assertEqual(parse_decimal("0"), Decimal("0"))
        self.assertEqual(parse_decimal("  42.00  "), Decimal("42.00"))

    def test_parse_decimal_blank_and_missing(self):
        self.assertIsNone(parse_decimal("", allow_blank=True))
        self.assertIsNone(parse_decimal("   ", allow_blank=True))
        self.assertIsNone(parse_decimal(None, allow_blank=True))
        with self.assertRaises(ValueError):
            parse_decimal("", allow_blank=False)
        with self.assertRaises(ValueError):
            parse_decimal("invalid_amount")

    def test_parse_date(self):
        self.assertEqual(parse_date("2025-08-05"), date(2025, 8, 5))
        self.assertIsNone(parse_date("", allow_blank=True))
        with self.assertRaises(ValueError):
            parse_date("2025-13-45")
        with self.assertRaises(ValueError):
            parse_date("05-08-2025")
        with self.assertRaises(ValueError):
            parse_date("", allow_blank=False)

    def test_parse_datetime(self):
        dt = parse_datetime("2025-07-29T09:30:00Z")
        self.assertEqual(dt.year, 2025)
        self.assertEqual(dt.month, 7)
        self.assertEqual(dt.day, 29)
        self.assertEqual(dt.hour, 9)
        self.assertEqual(dt.minute, 30)

    def test_parse_int(self):
        self.assertEqual(parse_int("12"), 12)
        self.assertEqual(parse_int("1,000"), 1000)
        self.assertIsNone(parse_int("", allow_blank=True))
        with self.assertRaises(ValueError):
            parse_int("abc")

    def test_parse_bool(self):
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("True"))
        self.assertTrue(parse_bool("1"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool("False"))
        self.assertFalse(parse_bool("0"))
        with self.assertRaises(ValueError):
            parse_bool("maybe")

    def test_parse_pipe_list(self):
        self.assertEqual(
            parse_pipe_list("rent|education|groceries"),
            ["rent", "education", "groceries"],
        )
        self.assertEqual(parse_pipe_list(""), [])
        self.assertEqual(parse_pipe_list(None), [])

    def test_parse_currency(self):
        self.assertEqual(parse_currency("usd"), "USD")
        self.assertEqual(parse_currency("INR"), "INR")
        with self.assertRaises(ValueError):
            parse_currency("XYZ")


class TestValidators(unittest.TestCase):
    """Test schema, identifier, and referential integrity validations."""

    def test_validate_header_missing_column(self):
        res = ValidationResult()
        validate_header("requests", ["request_id", "user_id"], res)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.severity == "FATAL" for e in res.fatal_errors))

    def test_duplicate_identifiers(self):
        res = ValidationResult()
        profiles = [
            FinancialProfile(
                user_id="user_01",
                home_currency="USD",
                current_available_balance=Decimal("100"),
                minimum_balance_to_keep=Decimal("50"),
                financial_priorities=[],
                expense_categories_to_protect=[],
                expense_categories_user_is_willing_to_reduce=[],
                expense_categories_user_is_willing_to_stop=[],
                payment_methods_user_will_consider=["full_payment"],
                max_installment_months=None,
            ),
            FinancialProfile(
                user_id="user_01",  # Duplicate!
                home_currency="USD",
                current_available_balance=Decimal("200"),
                minimum_balance_to_keep=Decimal("50"),
                financial_priorities=[],
                expense_categories_to_protect=[],
                expense_categories_user_is_willing_to_reduce=[],
                expense_categories_user_is_willing_to_stop=[],
                payment_methods_user_will_consider=["full_payment"],
                max_installment_months=None,
            ),
        ]
        validate_identifiers(profiles, [], [], [], [], [], [], res)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Duplicate" in e.message for e in res.errors))

    def test_cross_reference_unknown_user(self):
        res = ValidationResult()
        profiles = [
            FinancialProfile(
                user_id="user_01",
                home_currency="USD",
                current_available_balance=Decimal("100"),
                minimum_balance_to_keep=Decimal("50"),
                financial_priorities=[],
                expense_categories_to_protect=[],
                expense_categories_user_is_willing_to_reduce=[],
                expense_categories_user_is_willing_to_stop=[],
                payment_methods_user_will_consider=["full_payment"],
                max_installment_months=None,
            )
        ]
        requests = [
            Request(
                request_id="request_01",
                user_id="user_99",  # Unknown user!
                request_date=date(2025, 1, 1),
                request_type="purchase",
                requested_amount=Decimal("100"),
                desired_completion_date=date(2025, 2, 1),
                allows_partial_payment=True,
                request_text="Sample",
            )
        ]
        validate_cross_references(profiles, [], requests, [], [], [], [], res)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Unknown user" in e.message for e in res.errors))


class TestMediaAndEvidenceQueue(unittest.TestCase):
    """Test dynamic discovery of image-linked events."""

    def test_dynamic_evidence_queue_discovery(self):
        res = ValidationResult()
        events = [
            FinancialEvent(
                event_id="event_01",
                user_id="user_01",
                event_type="expense",
                description="Test event",
                category="groceries",
                direction="debit",
                amount=None,  # Blank amount!
                currency="USD",
                event_date=date(2025, 1, 1),
                settlement_date=date(2025, 1, 1),
                status="settled",
                linked_event_id=None,
                flexibility="fixed",
                minimum_allowed_amount=None,
            ),
            FinancialEvent(
                event_id="event_02",
                user_id="user_01",
                event_type="expense",
                description="Normal event",
                category="groceries",
                direction="debit",
                amount=Decimal("50"),
                currency="USD",
                event_date=date(2025, 1, 1),
                settlement_date=date(2025, 1, 1),
                status="settled",
                linked_event_id=None,
                flexibility="fixed",
                minimum_allowed_amount=None,
            ),
        ]
        images = [
            ImageReference(
                image_id="image_01",
                user_id="user_01",
                request_id="request_01",
                related_event_id="event_01",
                file_path=Path("dummy.png"),
                file_exists=True,
                file_size_bytes=100,
            )
        ]
        queue = build_evidence_queue(events, images, res)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].event_id, "event_01")
        self.assertEqual(queue[0].image_id, "image_01")
        self.assertEqual(queue[0].amount_status, "requires_extraction")


class TestFullDatasetIntegration(unittest.TestCase):
    """End-to-end integration test of actual repository dataset bundle."""

    def test_load_dataset_integrity(self):
        bundle = load_dataset()
        self.assertEqual(len(bundle.profiles), 275)
        self.assertEqual(len(bundle.events), 25342)
        self.assertEqual(len(bundle.requests), 250)
        self.assertEqual(len(bundle.sample_requests), 25)
        self.assertEqual(len(bundle.payment_options), 790)
        self.assertEqual(len(bundle.exchange_rates), 134)
        self.assertEqual(len(bundle.messages), 215)
        self.assertEqual(len(bundle.images), 16)
        self.assertEqual(len(bundle.evidence_queue), 16)

        # Validation passed
        self.assertTrue(bundle.validation_report.is_valid)
        self.assertEqual(len(bundle.validation_report.fatal_errors), 0)
        self.assertEqual(len(bundle.validation_report.errors), 0)

        # Indexes work
        user_01_events = bundle.indexes.get_user_events("user_01")
        self.assertGreater(len(user_01_events), 0)

        req_01_options = bundle.indexes.get_request_payment_options("request_01")
        self.assertGreater(len(req_01_options), 0)


if __name__ == "__main__":
    unittest.main()
