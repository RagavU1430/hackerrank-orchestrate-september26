# Phase 2: Personalized Financial State Engine

Phase 2 reconstructs what is known for a request. It does not calculate affordability,
generate output.csv, rank payment plans, parse natural language, extract image amounts,
or run a balance simulator. It makes no model calls or network requests.

## Run and verify

Python 3.10+ is sufficient; the engine and unittest tests use only the standard library.
Run from the repository root:

```sh
python -m unittest discover -s tests -v
python -m pytest -q                         # optional, requires pytest
python -m code.main --validate             # existing Phase 1 command
python -m code.main --validate-states
python -m code.main --build-state request_100 --snapshots
```

`python code/main.py` also works. `--validate-states --snapshots` writes one JSON per
evaluation request into ignored `evaluation/state_snapshots/`. Snapshots are opt-in,
include financial values for local debugging, and omit free-text content, image paths,
and the raw bundle. The tracked aggregate report omits monetary balances and histories.
No input dataset is written. The package exposes the stdlib `code` console API so
Python's debugger and pytest can coexist with the challenge's `code` package name.

## Entry point and state contract

```python
from code.data_loader import load_dataset
from code.state_builder import build_financial_state

bundle = load_dataset()
state = build_financial_state(bundle, bundle.requests[0])
# A request ID from bundle.requests also works.
```

An indexed bundle with a passing Phase 1 validation report is required. Phase 2 adds
financial invariants that Phase 1 does not enforce, including finite Decimal amounts,
nonnegative reserves, valid dates/statuses, unique event identities, and protection.
Each build uses only the user's indexed records. It does not scan the global event
list, sample answers, or organizer files. Output order is stable, independent of input
event ordering and wall-clock time. The Phase 1 objects are not mutated.

`state.profile` preserves home currency, priorities, protected categories, reduction
and stopping permissions, payment methods and installment limit. `state.request` and
`state.payment_options` preserve request context without selecting an offer.

| Consumer field | Meaning |
| --- | --- |
| `available_balance` | Unmodified profile current_available_balance |
| `minimum_balance_to_keep` | Unmodified profile reserve, even when balance is lower |
| `confirmed_income` | Already settled historical/current credits; never add these to starting balance |
| `future_confirmed_income` | Supplied scheduled salary with a future settlement date |
| `pending_income` | Pending credits; excluded from usable inflows |
| `uncertain_income` | Other unconfirmed credits and non-cash metadata |
| `pending_debits` | Outstanding debits; past expected dates do not erase the obligation |
| `scheduled_debits` | Scheduled commitments and debits whose settlement is unresolved |
| `required_future_outflows` | Pending plus scheduled/unsettled debits; do not add the component lists again |
| `required_expenses` | Retained debit history and commitments, including fixed/protected/flexible expenses |
| `recurring_inflows` | Active inferred income patterns, explicitly **derived**, not confirmed future credits |
| `recurring_outflows` | Active inferred debit patterns with conservative amounts |
| `flexible_expenses` | Active recurring debits with event permission, profile consent and no protection |
| `events` | One record per event ID, original event fields, cash/date classification, money and provenance |
| `evidence`, `evidence_updates`, `warnings` | Scoped source references, structured dated facts, unresolved issues |

`EventState.can_reduce/can_stop` describe event/profile permission only. Use
`state.flexible_expenses` for the later optimizer's recurring-only eligibility.
Missing reduction floors disable reduction; missing amounts remain None. Protection
always wins, and contradictory flexibility is reported. No expense is removed from
the baseline merely because it could eventually be adjusted.

## Date and lifecycle semantics discovered in the supplied data

The input has event_date, settlement_date and status, but no observation timestamp for
events and no explicit recurrence field. It supplies future-dated **scheduled salary**
rows as known schedules; excluding every future event_date would incorrectly lose them.
Future non-scheduled records are retained as `not_yet_known` audit metadata and excluded
from cash and recurrence inference. A settled record counts as historical/current only
when its settlement date is on or before the request date. Current-day settled activity
is treated as included in the profile balance because no intraday balance timestamp exists.

Scheduled income/category=salary is the dataset's structured representation of a
confirmed next salary. Other scheduled credits remain uncertain. A past-due scheduled
credit does not become settled merely because time passed. Phase 3 must resolve
contradictory salary/bonus/commission evidence rather than promoting uncertain funds.

Pending debits keep their expected settlement date, clamped to the request date when
overdue or undated. Missing dates and inconsistent statuses are flagged. All supplied
schedules are retained even beyond 90 days; the future simulator chooses its horizon.

The 58 linked rows in the complete participant dataset show these distinct lifecycles:

| Link | Treatment |
| --- | --- |
| Settled purchase -> settled or pending refund | Separate opposite-direction flows; pending refund is never spendable |
| Cancelled card authorization -> settled purchase | Authorization excluded, purchase retained |
| Failed payment -> scheduled retry | Failed attempt excluded, retry is an obligation |
| Investment purchase -> unrealized valuation | Valuation is non-cash; never treated as income |
| Investment purchase -> settled sale | Separate historical cash flows, already reflected in balance |
| Settled charge -> pending possible extra charge | Reserve the extra debit and flag ambiguity; a link does not prove reversal |

The general rule also resolves pending/scheduled authorization chains when a linked
same-type/category/currency/direction terminal settlement/cancellation/failure is known.
It preserves the supersession ID for audit. A future settlement cannot erase a current
pending obligation. It never deduplicates unrelated equal amounts, or treats an entire
investment lifecycle as a single cash flow. Invalid links remain visible as warnings.

## Recurrence inference

1. Use only historical/current settled income, expense, subscription and debt-payment
   records; exclude linked lifecycle rows, pending, cancelled, failed and non-cash items.
2. Group by event type, category, direction, currency and flexibility, then exact source
   description. At least three distinct dates must establish identical calendar-month
   gaps or identical day gaps. Month-end and leap-day schedules preserve their anchor.
3. For remaining debit records only, a homogeneous category group with at least four
   observations can establish a category spending cadence. This handles changing
   merchant descriptions in essential variable spending. A source event is never used
   in two patterns. Irregular/insufficient history is retained without inventing a cadence.
4. Use the maximum observed debit or minimum observed credit amount within the series.
   If any supporting amount is missing, the inferred amount remains unknown. Preserve
   all source IDs and the amount policy; do not sum different currencies.
5. A missed expected occurrence marks the pattern stale. Stale income becomes inactive;
   stale debit patterns remain conservative obligations until cancellation evidence.
   Staleness does not fabricate an end date or historical arrears.
6. Explicit scheduled/pending cash occurrences replace inferred occurrences when the
   source matches, or the date/currency/category cadence matches exactly one pattern.
   `explicit_occurrence_dates` tells the simulator which inferred occurrences to skip.
   Ambiguous sources are not silently merged.

Inference confidence is `derived_source_history`, `derived_category_history`, or their
stale counterparts. Even a stable income series is not automatically confirmed. This
is intentionally a conservative interface: Phase 3 can establish continuation, new
terms or termination. Pattern inference is not a promise of future income.

## Phase 3 evidence integration

```python
from datetime import date
from decimal import Decimal
from code.financial_state import EvidenceUpdate
from code.evidence import apply_evidence_updates

# IDs must be genuine scoped sources/targets from this state.
update = EvidenceUpdate(
    source_type="image", source_id=image_id,
    target_type="event", target_id=event_id,
    field="amount", new_value=Decimal("120.50"),
    effective_date=event_date, observed_date=known_date,
    confidence="confirmed", operation="resolve",
)
new_state = apply_evidence_updates(state, [update])
```

`resolve` only fills a missing structured value. Overwriting a supplied fact requires
an explicit `amend` with the matching `old_value`; conflicts raise ValueError. This
implements the problem statement's explicit-amendment priority without allowing arbitrary
evidence to replace known values. Simultaneous conflicting facts must be resolved by
Phase 3 first. Updates are ordered by effective/observation date and stable source IDs,
idempotent, and retain provenance. Future known amendments are validated immediately,
stored with effective dates, and do not alter today's terms. Uncertain or not-yet-observed
updates are retained without changing financial facts.

Event fields allowed: amount, status, settlement_date, minimum_allowed_amount.
For salary/rent changes affecting a continuing series, target the recurrence's `amount`
explicitly; changing a historical receipt alone is not an instruction to change a contract.
Recurrence fields allowed: amount, end_date (inclusive final date). To introduce a new
confirmed future payment, use `operation="add"`, target_type event, field event, and a
typed new FinancialEvent whose event_date equals the effective date. Addition must use
a new ID for the same user and a scoped source. No update can change protected categories,
flexibility or payment preferences. Image sources without files cannot establish facts.

The source must appear in `state.evidence`. Message metadata is filtered to the user,
the current request or user-wide messages, and sent_at on/before the request date.
Images have no timestamp; Phase 3 must explicitly supply their observation/effective
dates. Raw text and embedded instructions are never interpreted by this layer.

## Phase 5 integration

The future simulator can read the fields in the state contract directly without
opening CSVs. Use pending/scheduled/confirmed events once, and recurring patterns once;
skip each pattern's explicit_occurrence_dates. Do not replay settled history against
the authoritative starting balance. Derived income requires a conservative confirmation
policy; do not concatenate it blindly with future_confirmed_income.

`event_on_date(state, event_id, occurrence_date)` and
`recurrence_on_date(state, recurrence_id, occurrence_date)` materialize effective-dated
evidence terms. The latter sets active=False after a known end date. Use the returned
terms for that date and retain their source references.

For FX, call `normalize_money(amount, currency, state.currency, settlement_date,
state.exchange_rates)`. The state contains the supplied rate table. Original amounts
and currencies survive normalization; rate direction/date and the exact Decimal rate
are retained. Missing conversion never means 1:1 or zero. Each future recurrence needs
its **own** settlement-date rate; a historical rate must not be reused. Unresolved
amounts, unsupported currencies and missing rates must remain unresolved downstream.

## Diagnostics and issue categories

`evaluation/state_report.md` contains the current full-evaluation reconstruction counts
and property-selected examples. `IMPLEMENTATION ISSUE` denotes a failed invariant or
reconstruction error. `DATASET ISSUE` denotes contradictory/missing structured facts,
including unsupported preferences and impossible monetary bounds. `UNRESOLVED EVIDENCE`
denotes missing image amounts, unparsed content, stale recurrence and disputed links.
Warnings are not silently repaired. No final-run token usage report is claimed here:
Phase 2 produces no predictions and makes zero model calls.
