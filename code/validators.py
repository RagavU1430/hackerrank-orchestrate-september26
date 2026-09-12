"""Cross-file and structural schema validators.

Performs duplicate ID checks, foreign-key reconciliation, media resolution,
and generates structured validation error/warning lists.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from code.schemas import (
    ExchangeRate,
    FinancialEvent,
    FinancialProfile,
    ImageReference,
    Message,
    PaymentOption,
    Request,
    SampleRequest,
)

EXPECTED_HEADERS: Dict[str, List[str]] = {
    "requests": [
        "request_id",
        "user_id",
        "request_date",
        "request_type",
        "requested_amount",
        "desired_completion_date",
        "allows_partial_payment",
        "request_text",
    ],
    "sample_requests": [
        "request_id",
        "user_id",
        "request_date",
        "request_type",
        "requested_amount",
        "desired_completion_date",
        "allows_partial_payment",
        "request_text",
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    ],
    "financial_profiles": [
        "user_id",
        "home_currency",
        "current_available_balance",
        "minimum_balance_to_keep",
        "financial_priorities",
        "expense_categories_to_protect",
        "expense_categories_user_is_willing_to_reduce",
        "expense_categories_user_is_willing_to_stop",
        "payment_methods_user_will_consider",
        "max_installment_months",
    ],
    "financial_events": [
        "event_id",
        "user_id",
        "event_type",
        "description",
        "category",
        "direction",
        "amount",
        "currency",
        "event_date",
        "settlement_date",
        "status",
        "linked_event_id",
        "flexibility",
        "minimum_allowed_amount",
    ],
    "request_payment_options": [
        "payment_option_id",
        "request_id",
        "payment_method",
        "payment_amount",
        "number_of_payments",
        "first_payment_date",
        "payment_frequency_days",
        "financing_fee",
        "total_payable_amount",
    ],
    "exchange_rates": [
        "rate_date",
        "from_currency",
        "to_currency",
        "rate",
    ],
    "messages": [
        "message_id",
        "user_id",
        "request_id",
        "related_event_id",
        "sent_at",
        "source_type",
        "message_text",
    ],
    "images": [
        "image_id",
        "user_id",
        "request_id",
        "related_event_id",
    ],
}


@dataclass
class ValidationIssue:
    severity: str  # "FATAL", "ERROR", "WARNING", "INFO"
    dataset: str
    record_id: Optional[str]
    field: Optional[str]
    message: str


@dataclass
class ValidationResult:
    is_valid: bool = True
    fatal_errors: List[ValidationIssue] = field(default_factory=list)
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    infos: List[ValidationIssue] = field(default_factory=list)

    def add(self, severity: str, dataset: str, record_id: Optional[str], field: Optional[str], message: str) -> None:
        issue = ValidationIssue(severity, dataset, record_id, field, message)
        if severity == "FATAL":
            self.fatal_errors.append(issue)
            self.is_valid = False
        elif severity == "ERROR":
            self.errors.append(issue)
            self.is_valid = False
        elif severity == "WARNING":
            self.warnings.append(issue)
        else:
            self.infos.append(issue)


def validate_header(dataset_name: str, actual_header: List[str], result: ValidationResult) -> None:
    """Validate that actual CSV header contains all expected columns in correct format."""
    expected = EXPECTED_HEADERS.get(dataset_name)
    if not expected:
        return

    missing_cols = [col for col in expected if col not in actual_header]
    if missing_cols:
        result.add(
            "FATAL",
            dataset_name,
            None,
            "header",
            f"Missing required columns: {missing_cols}",
        )

    extra_cols = [col for col in actual_header if col not in expected]
    if extra_cols:
        result.add(
            "WARNING",
            dataset_name,
            None,
            "header",
            f"Encountered unexpected additional columns: {extra_cols}",
        )


def validate_identifiers(
    profiles: List[FinancialProfile],
    events: List[FinancialEvent],
    requests: List[Request],
    sample_requests: List[SampleRequest],
    payment_options: List[PaymentOption],
    messages: List[Message],
    images: List[ImageReference],
    result: ValidationResult,
) -> None:
    """Check for duplicate primary IDs across all collections."""

    def check_dups(items: list, id_extractor, dataset_name: str, id_name: str):
        seen: Set[str] = set()
        for item in items:
            item_id = id_extractor(item)
            if item_id in seen:
                result.add(
                    "ERROR",
                    dataset_name,
                    item_id,
                    id_name,
                    f"Duplicate identifier found: '{item_id}'",
                )
            seen.add(item_id)

    check_dups(profiles, lambda p: p.user_id, "financial_profiles", "user_id")
    check_dups(events, lambda e: e.event_id, "financial_events", "event_id")
    check_dups(requests, lambda r: r.request_id, "requests", "request_id")
    check_dups(sample_requests, lambda r: r.request_id, "sample_requests", "request_id")
    check_dups(payment_options, lambda o: o.payment_option_id, "request_payment_options", "payment_option_id")
    check_dups(messages, lambda m: m.message_id, "messages", "message_id")
    check_dups(images, lambda i: i.image_id, "images", "image_id")


def validate_cross_references(
    profiles: List[FinancialProfile],
    events: List[FinancialEvent],
    requests: List[Request],
    sample_requests: List[SampleRequest],
    payment_options: List[PaymentOption],
    messages: List[Message],
    images: List[ImageReference],
    result: ValidationResult,
) -> None:
    """Validate referential integrity between users, events, requests, options, and images."""
    user_ids: Set[str] = {p.user_id for p in profiles}
    event_ids: Set[str] = {e.event_id for e in events}
    all_req_ids: Set[str] = {r.request_id for r in requests} | {r.request_id for r in sample_requests}

    # Requests -> Users
    for r in requests:
        if r.user_id not in user_ids:
            result.add("ERROR", "requests", r.request_id, "user_id", f"Unknown user '{r.user_id}'")

    for r in sample_requests:
        if r.user_id not in user_ids:
            result.add("ERROR", "sample_requests", r.request_id, "user_id", f"Unknown user '{r.user_id}'")

    # Events -> Users
    for e in events:
        if e.user_id not in user_ids:
            result.add("ERROR", "financial_events", e.event_id, "user_id", f"Unknown user '{e.user_id}'")

        # Linked event check (if populated)
        if e.linked_event_id and e.linked_event_id not in event_ids:
            result.add(
                "WARNING",
                "financial_events",
                e.event_id,
                "linked_event_id",
                f"Linked event '{e.linked_event_id}' not found in financial_events",
            )

    # PaymentOptions -> Requests
    for opt in payment_options:
        if opt.request_id not in all_req_ids:
            result.add(
                "ERROR",
                "request_payment_options",
                opt.payment_option_id,
                "request_id",
                f"Referenced request '{opt.request_id}' not found in requests or sample_requests",
            )

    # Messages -> Users, Requests, Events
    for m in messages:
        if m.user_id not in user_ids:
            result.add("ERROR", "messages", m.message_id, "user_id", f"Unknown user '{m.user_id}'")
        if m.request_id and m.request_id not in all_req_ids:
            result.add(
                "WARNING",
                "messages",
                m.message_id,
                "request_id",
                f"Referenced request '{m.request_id}' not found",
            )
        if m.related_event_id and m.related_event_id not in event_ids:
            result.add(
                "WARNING",
                "messages",
                m.message_id,
                "related_event_id",
                f"Referenced event '{m.related_event_id}' not found",
            )

    # Images -> Users, Requests, Events, Filesystem
    for img in images:
        if img.user_id not in user_ids:
            result.add("ERROR", "images", img.image_id, "user_id", f"Unknown user '{img.user_id}'")
        if img.request_id and img.request_id not in all_req_ids:
            result.add(
                "WARNING",
                "images",
                img.image_id,
                "request_id",
                f"Referenced request '{img.request_id}' not found",
            )
        if img.related_event_id and img.related_event_id not in event_ids:
            result.add(
                "ERROR",
                "images",
                img.image_id,
                "related_event_id",
                f"Referenced event '{img.related_event_id}' not found in financial_events",
            )
        if not img.file_exists:
            result.add(
                "ERROR",
                "images",
                img.image_id,
                "file_path",
                f"Referenced image file does not exist at: '{img.file_path}'",
            )
        elif img.file_size_bytes == 0:
            result.add(
                "WARNING",
                "images",
                img.image_id,
                "file_path",
                f"Referenced image file is 0 bytes at: '{img.file_path}'",
            )
