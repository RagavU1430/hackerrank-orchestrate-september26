# Financial State Report

## Requests Processed

250 / 250 requests reconstructed. Counts below are request-scoped.

## Users Processed

250

## Income Classification

- confirmed_future_income: 42
- non_cash: 8
- pending_income: 7
- settled_income: 1518

Historical/current settled income is already reflected in the profile balance. Inferred income is derived metadata, not confirmed future money.

## Expense Classification

- excluded: 39
- pending_debit: 55
- scheduled_debit: 20
- settled_debit: 21365

## Pending Obligations

Pending debits: 55. Disputed linked charges remain reserved until confirmed evidence resolves them.

## Recurring Obligations

Active derived inflow patterns: 167.
Active derived outflow patterns: 2228.

## Flexible Spending

Active recurring expenses eligible for later adjustment: 557.
Eligibility requires recurrence, event flexibility, profile permission and no protection. No changes are proposed.

## Currency Conversion

- known: 23043
- unresolved_amount: 11

Rates use exact settlement date and direction. Future recurrence occurrences must be converted at their own dates with the rate table retained in the state.

## Evidence

Request-scoped metadata references: 209. No NLP, image extraction or model calls were performed.

## Warnings

| Classification | Code | Count |
| --- | --- | ---: |
| UNRESOLVED EVIDENCE | ambiguous_linked_charge | 6 |
| UNRESOLVED EVIDENCE | stale_recurrence | 98 |
| UNRESOLVED EVIDENCE | unparsed_image | 11 |
| UNRESOLVED EVIDENCE | unparsed_message | 198 |
| UNRESOLVED EVIDENCE | unresolved_amount | 11 |

## State Validation

PASS WITH WARNINGS

IMPLEMENTATION ISSUE: 0 reconstruction failures.

## Example Diagnostic States

Examples are selected by state properties, never by evaluation answers. Balances and raw transaction details are omitted from this aggregate report.

| Situation | Request | Future inflows | Pending debits | Recurring outflows | Unknown amounts |
| --- | --- | ---: | ---: | ---: | ---: |
| normal income | request_100 | 1 | 1 | 9 | 0 |
| largest expense history | request_48 | 0 | 0 | 10 | 1 |
| pending payment | request_100 | 1 | 1 | 9 | 0 |
| missing amount | request_101 | 0 | 1 | 10 | 1 |
| multiple currencies | request_109 | 1 | 0 | 10 | 0 |
| flexible expense | request_100 | 1 | 1 | 9 | 0 |
| lowest balance/reserve ratio | request_97 | 1 | 0 | 7 | 0 |
| below minimum (not present; synthetic tests cover it) | - | - | - | - | - |
