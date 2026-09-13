# Architecture

Buy or Wait? keeps financial decisions deterministic. Evidence extraction and natural-language
explanations are constrained inputs and outputs around the financial engines; neither can select
or override a payment recommendation.

```text
CSV data -> Phase 1 validation/indexes -> Phase 2 state -> Phase 3 validated evidence
        -> Phase 4 90-day simulation -> Phase 5 affordability -> Phase 6 payment plans
        -> Phase 7 spending adjustments -> Phase 8 guarded explanation -> Phase 9 CSV validator
        -> output.csv
```

Phase 1 loads typed rows, validates references and builds indexes. Phase 2 creates a
request-date-aware state, separates pending and non-cash facts, preserves provenance and infers
recurrence conservatively. Phase 3 extracts messages/images into typed evidence updates, validates
them, and applies only confirmed scoped updates. Phase 4 simulates daily balances over 90 days.

Phase 5 calculates `amount_safe_to_pay`, status and earliest safe full-payment date. Phase 6
generates seller payment options and ranks safe options. Phase 7 evaluates up to three permitted
recurring-spending changes and re-simulates each candidate. Phase 8 creates a customer explanation
from the deterministic context and uses a deterministic fallback if the response conflicts with it.

Phase 9 runs every evaluation request through the production chain, validates every final field,
then atomically writes `output.csv`. Phase 10 provides documentation, audit artefacts, demo mode
and operational checks.

## Decision traceability

| Submission field | Deterministic source |
| --- | --- |
| `amount_safe_to_pay` | Phase 5 baseline forecast headroom |
| `affordability_status` | Phase 5/7 scenario status |
| `recommended_payment_method`, `payment_plan` | Phase 6/7 safe selected plan |
| `earliest_date_for_full_payment` | Phase 5 date search |
| `spending_changes_needed` | Phase 7 eligible, user-approved recurring changes |
| `decision_explanation` | Phase 8 guarded explanation/fallback |

## AI boundary

AI/VLM functionality is limited to evidence extraction, message interpretation and explanation.
All balance math, FX, recurrence, affordability, ranking, spending changes and final validation are
deterministic Python code. Prompt-like text is data; it must pass Phase 3 validation before it can
become a typed evidence update.
