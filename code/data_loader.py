"""CSV data loader converting raw records into normalized typed models and DatasetBundle."""

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

from code.config import (
    DATASET_DIR,
    EXCHANGE_RATES_FILE,
    FINANCIAL_EVENTS_FILE,
    FINANCIAL_PROFILES_FILE,
    IMAGES_FILE,
    MEDIA_IMAGES_DIR,
    MESSAGES_FILE,
    PAYMENT_OPTIONS_FILE,
    REQUESTS_FILE,
    SAMPLE_REQUESTS_FILE,
    check_dataset_files,
)
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
    DatasetBundle,
    EvidenceReference,
    ExchangeRate,
    FinancialEvent,
    FinancialProfile,
    ImageReference,
    Message,
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

logger = logging.getLogger(__name__)


def load_financial_profiles(file_path: Path, result: ValidationResult) -> List[FinancialProfile]:
    """Load and normalize user financial profiles."""
    profiles: List[FinancialProfile] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("financial_profiles", reader.fieldnames or [], result)
        for row in reader:
            user_id = row["user_id"].strip()
            currency = parse_currency(row["home_currency"])
            avail_bal = parse_decimal(row["current_available_balance"], allow_blank=False)
            min_bal = parse_decimal(row["minimum_balance_to_keep"], allow_blank=False)
            priorities = parse_pipe_list(row["financial_priorities"])
            protect = parse_pipe_list(row["expense_categories_to_protect"])
            reduce_cats = parse_pipe_list(row["expense_categories_user_is_willing_to_reduce"])
            stop_cats = parse_pipe_list(row["expense_categories_user_is_willing_to_stop"])
            payment_methods = parse_pipe_list(row["payment_methods_user_will_consider"])
            max_inst = parse_int(row["max_installment_months"], allow_blank=True)

            profiles.append(
                FinancialProfile(
                    user_id=user_id,
                    home_currency=currency,
                    current_available_balance=avail_bal,  # type: ignore[arg-type]
                    minimum_balance_to_keep=min_bal,  # type: ignore[arg-type]
                    financial_priorities=priorities,
                    expense_categories_to_protect=protect,
                    expense_categories_user_is_willing_to_reduce=reduce_cats,
                    expense_categories_user_is_willing_to_stop=stop_cats,
                    payment_methods_user_will_consider=payment_methods,
                    max_installment_months=max_inst,
                )
            )
    return profiles


def load_financial_events(file_path: Path, result: ValidationResult) -> List[FinancialEvent]:
    """Load and normalize financial transactions and events."""
    events: List[FinancialEvent] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("financial_events", reader.fieldnames or [], result)
        for row in reader:
            event_id = row["event_id"].strip()
            user_id = row["user_id"].strip()
            event_type = row["event_type"].strip()
            desc = row["description"].strip()
            category = row["category"].strip()
            direction = row["direction"].strip()
            amount = parse_decimal(row["amount"], allow_blank=True)
            currency = parse_currency(row["currency"])
            event_date = parse_date(row["event_date"], allow_blank=False)
            settlement_date = parse_date(row["settlement_date"], allow_blank=True)
            status = row["status"].strip()
            linked_event_id = row["linked_event_id"].strip() or None
            flexibility = row["flexibility"].strip()
            min_allowed = parse_decimal(row["minimum_allowed_amount"], allow_blank=True)

            events.append(
                FinancialEvent(
                    event_id=event_id,
                    user_id=user_id,
                    event_type=event_type,
                    description=desc,
                    category=category,
                    direction=direction,
                    amount=amount,
                    currency=currency,
                    event_date=event_date,  # type: ignore[arg-type]
                    settlement_date=settlement_date,
                    status=status,
                    linked_event_id=linked_event_id,
                    flexibility=flexibility,
                    minimum_allowed_amount=min_allowed,
                )
            )
    return events


def load_requests(file_path: Path, result: ValidationResult) -> List[Request]:
    """Load and normalize evaluation requests."""
    requests: List[Request] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("requests", reader.fieldnames or [], result)
        for row in reader:
            req_id = row["request_id"].strip()
            user_id = row["user_id"].strip()
            req_date = parse_date(row["request_date"], allow_blank=False)
            req_type = row["request_type"].strip()
            req_amount = parse_decimal(row["requested_amount"], allow_blank=False)
            desired_date = parse_date(row["desired_completion_date"], allow_blank=False)
            allow_partial = parse_bool(row["allows_partial_payment"])
            text = row["request_text"].strip()

            requests.append(
                Request(
                    request_id=req_id,
                    user_id=user_id,
                    request_date=req_date,  # type: ignore[arg-type]
                    request_type=req_type,
                    requested_amount=req_amount,  # type: ignore[arg-type]
                    desired_completion_date=desired_date,  # type: ignore[arg-type]
                    allows_partial_payment=allow_partial,
                    request_text=text,
                )
            )
    return requests


def load_sample_requests(file_path: Path, result: ValidationResult) -> List[SampleRequest]:
    """Load and normalize sample requests with ground truth answers."""
    sample_requests: List[SampleRequest] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("sample_requests", reader.fieldnames or [], result)
        for row in reader:
            req_id = row["request_id"].strip()
            user_id = row["user_id"].strip()
            req_date = parse_date(row["request_date"], allow_blank=False)
            req_type = row["request_type"].strip()
            req_amount = parse_decimal(row["requested_amount"], allow_blank=False)
            desired_date = parse_date(row["desired_completion_date"], allow_blank=False)
            allow_partial = parse_bool(row["allows_partial_payment"])
            text = row["request_text"].strip()

            amt_safe = parse_decimal(row["amount_safe_to_pay"], allow_blank=False) or Decimal(0)
            afford_status = row["affordability_status"].strip()
            rec_method = row["recommended_payment_method"].strip()
            plan = row["payment_plan"].strip()
            earliest_date = parse_date(row["earliest_date_for_full_payment"], allow_blank=True)
            spending_changes = row["spending_changes_needed"].strip()
            explanation = row["decision_explanation"].strip()

            sample_requests.append(
                SampleRequest(
                    request_id=req_id,
                    user_id=user_id,
                    request_date=req_date,  # type: ignore[arg-type]
                    request_type=req_type,
                    requested_amount=req_amount,  # type: ignore[arg-type]
                    desired_completion_date=desired_date,  # type: ignore[arg-type]
                    allows_partial_payment=allow_partial,
                    request_text=text,
                    amount_safe_to_pay=amt_safe,
                    affordability_status=afford_status,
                    recommended_payment_method=rec_method,
                    payment_plan=plan,
                    earliest_date_for_full_payment=earliest_date,
                    spending_changes_needed=spending_changes,
                    decision_explanation=explanation,
                )
            )
    return sample_requests


def load_payment_options(file_path: Path, result: ValidationResult) -> List[PaymentOption]:
    """Load and normalize request payment options."""
    options: List[PaymentOption] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("request_payment_options", reader.fieldnames or [], result)
        for row in reader:
            opt_id = row["payment_option_id"].strip()
            req_id = row["request_id"].strip()
            method = row["payment_method"].strip()
            amt = parse_decimal(row["payment_amount"], allow_blank=False)
            num_payments = parse_int(row["number_of_payments"], allow_blank=False)
            first_date = parse_date(row["first_payment_date"], allow_blank=False)
            freq_days = parse_int(row["payment_frequency_days"], allow_blank=True)
            fee = parse_decimal(row["financing_fee"], allow_blank=False)
            total_payable = parse_decimal(row["total_payable_amount"], allow_blank=False)

            options.append(
                PaymentOption(
                    payment_option_id=opt_id,
                    request_id=req_id,
                    payment_method=method,
                    payment_amount=amt,  # type: ignore[arg-type]
                    number_of_payments=num_payments,  # type: ignore[arg-type]
                    first_payment_date=first_date,  # type: ignore[arg-type]
                    payment_frequency_days=freq_days,
                    financing_fee=fee,  # type: ignore[arg-type]
                    total_payable_amount=total_payable,  # type: ignore[arg-type]
                )
            )
    return options


def load_exchange_rates(file_path: Path, result: ValidationResult) -> List[ExchangeRate]:
    """Load and normalize exchange rates."""
    rates: List[ExchangeRate] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("exchange_rates", reader.fieldnames or [], result)
        for row in reader:
            rate_date = parse_date(row["rate_date"], allow_blank=False)
            from_curr = parse_currency(row["from_currency"])
            to_curr = parse_currency(row["to_currency"])
            rate = parse_decimal(row["rate"], allow_blank=False)

            rates.append(
                ExchangeRate(
                    rate_date=rate_date,  # type: ignore[arg-type]
                    from_currency=from_curr,
                    to_currency=to_curr,
                    rate=rate,  # type: ignore[arg-type]
                )
            )
    return rates


def load_messages(file_path: Path, result: ValidationResult) -> List[Message]:
    """Load and normalize unstructured messages."""
    messages: List[Message] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("messages", reader.fieldnames or [], result)
        for row in reader:
            msg_id = row["message_id"].strip()
            user_id = row["user_id"].strip()
            req_id = row["request_id"].strip() or None
            rel_event_id = row["related_event_id"].strip() or None
            sent_at = parse_datetime(row["sent_at"])
            source_type = row["source_type"].strip()
            text = row["message_text"].strip()

            messages.append(
                Message(
                    message_id=msg_id,
                    user_id=user_id,
                    request_id=req_id,
                    related_event_id=rel_event_id,
                    sent_at=sent_at,
                    source_type=source_type,
                    message_text=text,
                )
            )
    return messages


def load_images(file_path: Path, media_dir: Path, result: ValidationResult) -> List[ImageReference]:
    """Load and verify image metadata and local PNG existence."""
    images: List[ImageReference] = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header("images", reader.fieldnames or [], result)
        for row in reader:
            img_id = row["image_id"].strip()
            user_id = row["user_id"].strip()
            req_id = row["request_id"].strip() or None
            rel_event_id = row["related_event_id"].strip() or None

            img_path = media_dir / f"{img_id}.png"
            file_exists = img_path.is_file()
            file_size = img_path.stat().st_size if file_exists else 0

            images.append(
                ImageReference(
                    image_id=img_id,
                    user_id=user_id,
                    request_id=req_id,
                    related_event_id=rel_event_id,
                    file_path=img_path,
                    file_exists=file_exists,
                    file_size_bytes=file_size,
                )
            )
    return images


def build_evidence_queue(
    events: List[FinancialEvent],
    images: List[ImageReference],
    result: ValidationResult,
) -> List[EvidenceReference]:
    """Dynamically build evidence extraction queue for events with missing amounts."""
    # Map related_event_id -> ImageReference
    event_to_image: Dict[str, ImageReference] = {
        img.related_event_id: img for img in images if img.related_event_id
    }

    queue: List[EvidenceReference] = []
    for event in events:
        if event.amount is None:
            linked_img = event_to_image.get(event.event_id)
            if linked_img:
                queue.append(
                    EvidenceReference(
                        event_id=event.event_id,
                        user_id=event.user_id,
                        image_id=linked_img.image_id,
                        image_path=linked_img.file_path,
                        amount_status="requires_extraction",
                        event_type=event.event_type,
                        category=event.category,
                        event_date=event.event_date,
                    )
                )
            else:
                result.add(
                    "WARNING",
                    "financial_events",
                    event.event_id,
                    "amount",
                    f"Event has missing amount but no linked image found in images.csv",
                )
    return queue


def load_dataset() -> DatasetBundle:
    """Complete Phase 1 ingestion pipeline:

    1. Verify dataset files exist
    2. Load and normalize all CSVs
    3. Dynamically discover missing-amount evidence queue
    4. Build in-memory indexes
    5. Validate identifiers and cross-file relationships
    6. Return populated DatasetBundle
    """
    check_dataset_files()
    result = ValidationResult()

    logger.info("Loading financial profiles...")
    profiles = load_financial_profiles(FINANCIAL_PROFILES_FILE, result)
    logger.info(f"Loaded {len(profiles)} financial profiles")

    logger.info("Loading financial events...")
    events = load_financial_events(FINANCIAL_EVENTS_FILE, result)
    logger.info(f"Loaded {len(events)} financial events")

    logger.info("Loading evaluation requests...")
    requests = load_requests(REQUESTS_FILE, result)
    logger.info(f"Loaded {len(requests)} evaluation requests")

    logger.info("Loading sample requests...")
    sample_requests = load_sample_requests(SAMPLE_REQUESTS_FILE, result)
    logger.info(f"Loaded {len(sample_requests)} sample requests")

    logger.info("Loading payment options...")
    payment_options = load_payment_options(PAYMENT_OPTIONS_FILE, result)
    logger.info(f"Loaded {len(payment_options)} payment options")

    logger.info("Loading exchange rates...")
    exchange_rates = load_exchange_rates(EXCHANGE_RATES_FILE, result)
    logger.info(f"Loaded {len(exchange_rates)} exchange rates")

    logger.info("Loading messages...")
    messages = load_messages(MESSAGES_FILE, result)
    logger.info(f"Loaded {len(messages)} messages")

    logger.info("Loading images and verifying media files...")
    images = load_images(IMAGES_FILE, MEDIA_IMAGES_DIR, result)
    logger.info(f"Loaded {len(images)} image references")

    logger.info("Dynamically detecting missing-amount events for evidence queue...")
    evidence_queue = build_evidence_queue(events, images, result)
    logger.info(f"Discovered {len(evidence_queue)} events requiring evidence extraction")

    logger.info("Building in-memory indexing...")
    indexes = build_indexes(
        requests,
        sample_requests,
        profiles,
        events,
        payment_options,
        exchange_rates,
        messages,
        images,
        evidence_queue,
    )
    logger.info("Indexes built successfully")

    logger.info("Validating primary identifiers across all tables...")
    validate_identifiers(
        profiles,
        events,
        requests,
        sample_requests,
        payment_options,
        messages,
        images,
        result,
    )

    logger.info("Validating cross-file referential integrity...")
    validate_cross_references(
        profiles,
        events,
        requests,
        sample_requests,
        payment_options,
        messages,
        images,
        result,
    )

    bundle = DatasetBundle(
        requests=requests,
        sample_requests=sample_requests,
        profiles=profiles,
        events=events,
        payment_options=payment_options,
        exchange_rates=exchange_rates,
        messages=messages,
        images=images,
        evidence_queue=evidence_queue,
        indexes=indexes,
        validation_report=result,
    )

    return bundle
