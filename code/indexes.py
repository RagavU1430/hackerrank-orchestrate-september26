"""In-memory indexing for high-performance O(1) lookups across all financial entities."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from code.schemas import (
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


@dataclass
class DatasetIndexes:
    """Pre-indexed lookups for instant access without re-scanning datasets."""

    requests_by_id: Dict[str, Request] = field(default_factory=dict)
    sample_requests_by_id: Dict[str, SampleRequest] = field(default_factory=dict)
    profiles_by_user_id: Dict[str, FinancialProfile] = field(default_factory=dict)
    events_by_id: Dict[str, FinancialEvent] = field(default_factory=dict)
    events_by_user_id: Dict[str, List[FinancialEvent]] = field(default_factory=lambda: defaultdict(list))
    payment_options_by_request_id: Dict[str, List[PaymentOption]] = field(default_factory=lambda: defaultdict(list))
    messages_by_user_id: Dict[str, List[Message]] = field(default_factory=lambda: defaultdict(list))
    messages_by_request_id: Dict[str, List[Message]] = field(default_factory=lambda: defaultdict(list))
    messages_by_event_id: Dict[str, List[Message]] = field(default_factory=lambda: defaultdict(list))
    images_by_id: Dict[str, ImageReference] = field(default_factory=dict)
    images_by_event_id: Dict[str, ImageReference] = field(default_factory=dict)
    images_by_user_id: Dict[str, List[ImageReference]] = field(default_factory=lambda: defaultdict(list))
    exchange_rates_by_pair_and_date: Dict[Tuple[str, str, date], Decimal] = field(default_factory=dict)
    evidence_by_event_id: Dict[str, EvidenceReference] = field(default_factory=dict)

    def get_user_events(self, user_id: str) -> List[FinancialEvent]:
        """Return all events for a user, sorted by event_date."""
        return self.events_by_user_id.get(user_id, [])

    def get_request_payment_options(self, request_id: str) -> List[PaymentOption]:
        """Return payment options for a given request."""
        return self.payment_options_by_request_id.get(request_id, [])

    def get_exchange_rate(self, from_curr: str, to_curr: str, rate_date: date) -> Optional[Decimal]:
        """Look up fixed exchange rate on a given settlement date."""
        if from_curr == to_curr:
            return Decimal("1.0")
        return self.exchange_rates_by_pair_and_date.get((from_curr, to_curr, rate_date))


def build_indexes(
    requests: List[Request],
    sample_requests: List[SampleRequest],
    profiles: List[FinancialProfile],
    events: List[FinancialEvent],
    payment_options: List[PaymentOption],
    exchange_rates: List[ExchangeRate],
    messages: List[Message],
    images: List[ImageReference],
    evidence_queue: List[EvidenceReference],
) -> DatasetIndexes:
    """Build all lookup indexes efficiently in a single pass."""
    idx = DatasetIndexes()

    # Requests
    for r in requests:
        idx.requests_by_id[r.request_id] = r
    for sr in sample_requests:
        idx.sample_requests_by_id[sr.request_id] = sr

    # Profiles
    for p in profiles:
        idx.profiles_by_user_id[p.user_id] = p

    # Events
    for e in events:
        idx.events_by_id[e.event_id] = e
        idx.events_by_user_id[e.user_id].append(e)

    # Sort each user's events chronologically
    for user_id in idx.events_by_user_id:
        idx.events_by_user_id[user_id].sort(key=lambda x: x.event_date)

    # Payment Options
    for opt in payment_options:
        idx.payment_options_by_request_id[opt.request_id].append(opt)

    # Sort options by ID for deterministic tie-breaking
    for req_id in idx.payment_options_by_request_id:
        idx.payment_options_by_request_id[req_id].sort(key=lambda x: x.payment_option_id)

    # Messages
    for m in messages:
        idx.messages_by_user_id[m.user_id].append(m)
        if m.request_id:
            idx.messages_by_request_id[m.request_id].append(m)
        if m.related_event_id:
            idx.messages_by_event_id[m.related_event_id].append(m)

    # Sort user messages chronologically
    for user_id in idx.messages_by_user_id:
        idx.messages_by_user_id[user_id].sort(key=lambda x: x.sent_at)

    # Images
    for img in images:
        idx.images_by_id[img.image_id] = img
        idx.images_by_user_id[img.user_id].append(img)
        if img.related_event_id:
            idx.images_by_event_id[img.related_event_id] = img

    # Exchange Rates
    for xr in exchange_rates:
        idx.exchange_rates_by_pair_and_date[(xr.from_currency, xr.to_currency, xr.rate_date)] = xr.rate

    # Evidence references
    for ev in evidence_queue:
        idx.evidence_by_event_id[ev.event_id] = ev

    return idx
