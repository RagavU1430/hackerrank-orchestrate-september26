"""Message Evidence Extraction module.

Extracts structured financial facts, temporal updates, and status confirmations
from unstructured notifications in English and Indonesian.
"""

from datetime import date, datetime
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional

from code.config import EVALUATION_DIR
from code.evidence_models import ExtractedMessageEvidence
from code.schemas import DatasetBundle, Message

logger = logging.getLogger(__name__)

CACHE_FILE: Path = EVALUATION_DIR / "evidence" / "message_evidence.json"


class MessageEvidenceExtractor:
    """Extracts, validates, and caches financial facts from messages."""

    def __init__(self, cache_file: Path = CACHE_FILE):
        self.cache_file = cache_file

    def load_cache(self) -> Dict[str, ExtractedMessageEvidence]:
        """Load previously cached message evidence if available."""
        if not self.cache_file.is_file():
            return {}
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            return {k: ExtractedMessageEvidence.from_dict(v) for k, v in data.items()}
        except Exception as exc:
            logger.warning(f"Failed to read message evidence cache: {exc}")
            return {}

    def save_cache(self, evidence_map: Dict[str, ExtractedMessageEvidence]) -> None:
        """Persist extracted message evidence to JSON cache."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        serializable = {k: v.to_dict() for k, v in evidence_map.items()}
        self.cache_file.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    def extract_single_message(self, message: Message) -> ExtractedMessageEvidence:
        """Extract structured financial facts from a message text."""
        txt = message.message_text.strip()
        t = txt.lower()
        sent_at_date = message.sent_at.date()

        # 1. Rent increase percentage (English & Indonesian)
        m = re.search(r'(?:increases monthly rent by|menaikkan biaya sewa bulanan sebesar)\s*(\d+)%', t)
        if m:
            pct = Decimal(m.group(1))
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="rent_increase",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=pct,
                status="accepted",
                confidence="high",
                reasoning=f"Renewed lease increases monthly rent by {pct}%.",
            )

        # 2. Salary date change (English & Indonesian)
        m = re.search(
            r'(?:confirmed salary is now expected on|gaji yang sudah dikonfirmasi kini diperkirakan masuk pada)\s*(\d{4}-\d{2}-\d{2})',
            t,
        )
        if m:
            new_date = date.fromisoformat(m.group(1))
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_date_change",
                amount=None,
                currency=None,
                effective_date=new_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"Confirmed salary settlement date moved to {new_date}.",
            )

        # 3. First salary (English & Indonesian)
        m = re.search(
            r'(?:first salary (?:from the new employer )?(?:will be|is|of)?|gaji pertama anda (?:sebesar )?)\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            m_date = re.search(
                r'(?:confirmed credit date is|dijadwalkan pada|is scheduled for|is confirmed for|tanggal kredit yang dikonfirmasi adalah)\s*(\d{4}-\d{2}-\d{2})',
                t,
            )
            eff_date = date.fromisoformat(m_date.group(1)) if m_date else sent_at_date
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_first",
                amount=amt,
                currency=curr,
                effective_date=eff_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"First salary of {curr or ''} {amt} confirmed for {eff_date}.",
            )

        # 4. Salary confirmed on date (e.g. Your salary of EUR 1485 is confirmed for 2025-05-15)
        m = re.search(
            r'salary of\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)\s*is confirmed for\s*(\d{4}-\d{2}-\d{2})',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            eff_date = date.fromisoformat(m.group(3))
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_update",
                amount=amt,
                currency=curr,
                effective_date=eff_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"Salary of {curr or ''} {amt} confirmed for {eff_date}.",
            )

        # 5. Salary update / increase (English & Indonesian)
        m = re.search(
            r'(?:monthly salary (?:has increased|is|will be) to|gaji bulanan anda naik menjadi|gaji pokok yang dikonfirmasi adalah)\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            m_date = re.search(r'(?:change applies from|berlaku mulai|resumes on)\s*(\d{4}-\d{2}-\d{2})', t)
            eff_date = date.fromisoformat(m_date.group(1)) if m_date else sent_at_date
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_update",
                amount=amt,
                currency=curr,
                effective_date=eff_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"Monthly salary updated to {curr or ''} {amt} effective {eff_date}.",
            )

        # 6. Temporary pay / reduced salary / unpaid leave (English & Indonesian)
        m = re.search(
            r'(?:temporary monthly pay is|salary is reduced to|regular salary of)\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            m_date = re.search(r'(?:resumes on|applies from|berlaku mulai)\s*(\d{4}-\d{2}-\d{2})', t)
            eff_date = date.fromisoformat(m_date.group(1)) if m_date else sent_at_date
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_reduced",
                amount=amt,
                currency=curr,
                effective_date=eff_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"Salary reduced/temporary pay {curr or ''} {amt} effective {eff_date}.",
            )

        # 7. Employment / Contract ended (English & Indonesian)
        if (
            "seasonal contract has ended" in t
            or "kontrak musiman saat ini telah berakhir" in t
            or "your employment has ended" in t
        ):
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="contract_end",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=sent_at_date,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Employment or seasonal contract has ended; recurring salary terminates.",
            )

        # 8. Remaining household salary after one job ends (English & Indonesian)
        m = re.search(
            r'(?:remaining confirmed monthly salary is|sisa gaji bulanan yang dikonfirmasi adalah)\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_update",
                amount=amt,
                currency=curr,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"One household job ended; remaining monthly salary is {curr or ''} {amt}.",
            )

        # 9. Invoice approval (English & Indonesian)
        m = re.search(
            r'(?:approved an invoice payment of|menyetujui pembayaran faktur sebesar)\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            m_date = re.search(r'(?:settlement is expected on|penyelesaian diperkirakan pada)\s*(\d{4}-\d{2}-\d{2})', t)
            eff_date = date.fromisoformat(m_date.group(1)) if m_date else sent_at_date
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="invoice_confirmed",
                amount=amt,
                currency=curr,
                effective_date=eff_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"Client approved invoice payout of {curr or ''} {amt} settling {eff_date}.",
            )

        # 10. Regular salary with one-off arrears adjustment
        m = re.search(
            r'(?:regular salary for the next payroll is|gaji rutin anda untuk penggajian berikutnya adalah)\s*([a-z]{3})?\s*([0-9,]+(?:\.[0-9]+)?)',
            t,
        )
        if m:
            curr = (m.group(1) or "").upper() or None
            amt = Decimal(m.group(2).replace(",", ""))
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="salary_update",
                amount=amt,
                currency=curr,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning=f"Regular salary of {curr or ''} {amt} confirmed (one-off arrears separate).",
            )

        # 11. Pending holds (bonuses, gig payouts, prize claims, refunds in progress)
        if any(
            k in t
            for k in [
                "still pending",
                "masih menunggu",
                "payout is still pending",
                "prize claim has been verified and is still in payment processing",
                "klaim hadiah anda sudah diverifikasi dan masih dalam proses",
                "refund has been initiated but has not reached",
                "pengembalian dana sudah diproses, tetapi belum masuk",
                "bonus is still subject to the final performance review",
                "foreign-currency refund is still processing",
            ]
        ):
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="pending_hold",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Confirmed pending/processing status; funds remain un-withdrawable until settled.",
            )

        # 12. Internal transfer (matching debit/credit between user's own accounts)
        if (
            "matching debit and credit came from a transfer between your two accounts" in t
            or "debit dan kredit dengan jumlah yang sama berasal dari transfer antara dua rekening" in t
        ):
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="internal_transfer",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Internal transfer between accounts owned by same user; zero net cash flow impact.",
            )

        # 13. Unrealized investment market valuation change
        if (
            "displayed market value has" in t
            or "nilai investasi yang ditampilkan telah" in t
            or "no units have been sold and no cash proceeds" in t
        ):
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="unrealized_investment",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Holding has not been sold; market fluctuation is non-cash and non-spendable.",
            )

        # 14. Failed debit attempt
        if "previous debit attempt failed" in t:
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="failed_debit",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Failed debit; underlying obligation remains outstanding.",
            )

        # 15. Disputed card charge
        if "extra card charge is still being investigated" in t or "tagihan kartu tambahan masih dalam penyelidikan" in t:
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="disputed_charge",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Card charge dispute active; reversal not yet posted.",
            )

        # 16. Work expense reimbursement claim closed
        if "reimbursement for your earlier work expense" in t or "penggantian atas biaya kerja anda sebelumnya" in t:
            return ExtractedMessageEvidence(
                message_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                sent_at=message.sent_at,
                source_type=message.source_type,
                category="reimbursement_closed",
                amount=None,
                currency=None,
                effective_date=sent_at_date,
                end_date=None,
                percentage_change=None,
                status="accepted",
                confidence="high",
                reasoning="Reimbursement claim is closed; one-time work expense settlement.",
            )

        # Fallback / Informational notice
        return ExtractedMessageEvidence(
            message_id=message.message_id,
            user_id=message.user_id,
            request_id=message.request_id,
            related_event_id=message.related_event_id,
            sent_at=message.sent_at,
            source_type=message.source_type,
            category="other",
            amount=None,
            currency=None,
            effective_date=sent_at_date,
            end_date=None,
            percentage_change=None,
            status="accepted",
            confidence="medium",
            reasoning="Informational banking or merchant notification without explicit cash flow adjustment.",
        )

    def extract_all_messages(
        self,
        bundle: DatasetBundle,
        use_cache: bool = True,
    ) -> Dict[str, ExtractedMessageEvidence]:
        """Process all messages in the dataset bundle."""
        cache = self.load_cache() if use_cache else {}
        results: Dict[str, ExtractedMessageEvidence] = {}

        for msg in bundle.messages:
            if use_cache and msg.message_id in cache:
                results[msg.message_id] = cache[msg.message_id]
                continue
            extracted = self.extract_single_message(msg)
            results[msg.message_id] = extracted

        # Persist updated cache
        self.save_cache(results)
        return results
