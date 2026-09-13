# Buy or Wait? judge summary

## Problem

Decide how a user can safely fund a purchase while preserving essential commitments and a requested
minimum balance.

## Solution

The project builds a date-aware financial state, validates image/message evidence, simulates 90 days
of cash flow, evaluates affordability, ranks provider payment options, and optionally evaluates up to
three user-approved recurring-expense changes.

## Safety guarantees

- Pending debits are reserved; pending income and unrealized value are not spendable cash.
- Every selected scenario is simulated against the minimum-balance invariant.
- Protected categories cannot be changed; reductions/stops require both event and user permission.
- Final CSV validation checks schema, request mapping, methods, plans, dates, amounts and changes.
- Explanations are guarded against contradictory financial claims and fall back deterministically.

## Evaluation

The final production batch processed 250 evaluation requests, emitted 250 rows, and applied 11
validated evidence updates. See `final_evaluation_report.md` for distributions and timing.

No external financial data or financial-decision model call is used.
