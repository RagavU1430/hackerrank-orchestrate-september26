"""Typed models for Phase 3 Multimodal Evidence Intelligence.

Defines intermediate extraction candidates, document representations,
conflict records, and resolution provenance.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CandidateAmount:
    """An individual candidate amount extracted from a document."""

    label: str
    amount: Decimal
    currency: str
    confidence: float = 1.0


@dataclass(frozen=True)
class ExtractedImageEvidence:
    """Structured extraction result for a media image."""

    image_id: str
    user_id: str
    related_event_id: Optional[str]
    document_type: str  # payslip | rent_receipt | grocery_bill | utility_bill | etc.
    document_date: Optional[date]
    candidates: List[CandidateAmount]
    selected_amount: Optional[Decimal]
    selected_currency: Optional[str]
    status: str  # accepted | ambiguous | rejected | requires_review
    confidence: str  # high | medium | low
    method: str  # deterministic | OCR | VLM | hybrid
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.document_date:
            data["document_date"] = self.document_date.isoformat()
        if self.selected_amount is not None:
            data["selected_amount"] = str(self.selected_amount)
        data["candidates"] = [
            {
                "label": c.label,
                "amount": str(c.amount),
                "currency": c.currency,
                "confidence": c.confidence,
            }
            for c in self.candidates
        ]
        return data

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExtractedImageEvidence":
        candidates = [
            CandidateAmount(
                label=c["label"],
                amount=Decimal(str(c["amount"])),
                currency=c["currency"],
                confidence=float(c.get("confidence", 1.0)),
            )
            for c in d.get("candidates", [])
        ]
        doc_date = date.fromisoformat(d["document_date"]) if d.get("document_date") else None
        sel_amt = Decimal(str(d["selected_amount"])) if d.get("selected_amount") is not None else None
        return cls(
            image_id=d["image_id"],
            user_id=d["user_id"],
            related_event_id=d.get("related_event_id"),
            document_type=d["document_type"],
            document_date=doc_date,
            candidates=candidates,
            selected_amount=sel_amt,
            selected_currency=d.get("selected_currency"),
            status=d["status"],
            confidence=d["confidence"],
            method=d["method"],
            reasoning=d.get("reasoning", ""),
        )


@dataclass(frozen=True)
class ExtractedMessageEvidence:
    """Structured extraction result for an unstructured notification."""

    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: datetime
    source_type: str
    category: str  # salary_update | salary_reduced | salary_date_change | contract_end | rent_increase | etc.
    amount: Optional[Decimal]
    currency: Optional[str]
    effective_date: Optional[date]
    end_date: Optional[date]
    percentage_change: Optional[Decimal]
    status: str  # accepted | ambiguous | rejected | requires_review
    confidence: str  # high | medium | low
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["sent_at"] = self.sent_at.isoformat()
        if self.effective_date:
            data["effective_date"] = self.effective_date.isoformat()
        if self.end_date:
            data["end_date"] = self.end_date.isoformat()
        if self.amount is not None:
            data["amount"] = str(self.amount)
        if self.percentage_change is not None:
            data["percentage_change"] = str(self.percentage_change)
        return data

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExtractedMessageEvidence":
        eff_date = date.fromisoformat(d["effective_date"]) if d.get("effective_date") else None
        end_date = date.fromisoformat(d["end_date"]) if d.get("end_date") else None
        amt = Decimal(str(d["amount"])) if d.get("amount") is not None else None
        pct = Decimal(str(d["percentage_change"])) if d.get("percentage_change") is not None else None
        return cls(
            message_id=d["message_id"],
            user_id=d["user_id"],
            request_id=d.get("request_id"),
            related_event_id=d.get("related_event_id"),
            sent_at=datetime.fromisoformat(d["sent_at"]),
            source_type=d["source_type"],
            category=d["category"],
            amount=amt,
            currency=d.get("currency"),
            effective_date=eff_date,
            end_date=end_date,
            percentage_change=pct,
            status=d["status"],
            confidence=d["confidence"],
            reasoning=d.get("reasoning", ""),
        )


@dataclass(frozen=True)
class EvidenceConflict:
    """Represents contradictory evidence discovered across sources."""

    conflict_id: str
    user_id: str
    target_type: str  # event | recurrence
    target_id: str
    field: str
    sources: List[str]
    values: List[str]
    resolution_status: str  # resolved | requires_review
    resolved_value: Optional[str] = None
    reasoning: str = ""
