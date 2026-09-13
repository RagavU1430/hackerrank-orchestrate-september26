# Final Evaluation Report

## Dataset validation

PASS — Phase 1 validated before final processing.

## Requests processed

250

## Successful

250

## Failed

0

## Affordability distribution

- affordable_later: 39
- affordable_now: 25
- affordable_with_plan: 39
- not_affordable: 147

## Payment-method distribution

- full_payment: 36
- installments: 27
- not_recommended: 147
- partial_payment: 1
- wait: 39

## Spending-change distribution

Rows with changes: 24

## Evidence

Validated updates applied: 11
Unresolved/rejected evidence issues retained: 0

## Safety invariant

PASS — every emitted payment plan was selected by the deterministic optimizer and final row validation passed.

## Output schema

PASS — exact required columns and order.

## Output row count

PASS — 250 rows.

## Determinism

PASS — two independent in-memory batches matched before write.

## Performance

Total runtime: 273.010 seconds
Peak traced Python memory: not collected during the two-pass reproducibility run. A preceding single-batch audit measured 22,772,400 bytes.
