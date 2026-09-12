# 90-Day Forecast Report

## Simulation Coverage

Total evaluation requests: 250
Forecasts generated: 250
Failures: 0
Window: 90 days (91 calendar snapshots incl. start date) per request

## Invariant Summary

Invariant PASS (balance never below minimum): 173
Invariant BREACH: 77

## Minimum Balance Statistics

Minimum observed balance (across forecasts) min: -50028782.13 max: 58155864.28
Minimum headroom min: -79608582.13 max: 29354257.75 avg: 39679.48

## Total Flow Statistics

Aggregate inflows: 2384508585.18
Aggregate outflows: 3257843560.08

## Income Classifications

Total confirmed future inflows projected: 507
Baseline excludes pending/uncertain/unrealized income per challenge rules.

## Expense Classifications

Total outflow entries projected: 10965
Includes pending, scheduled, unsettled, and recurring debits. Flexible spending still occurs in baseline.

## Warnings

| Kind | Code | Count |
| --- | --- | ---: |
| UNRESOLVED EVIDENCE | unresolved_amount | 2 |

## Unresolved Events

Warnings total: 2
Unresolved amounts/rates remain explicit and are not substituted with zero.

## State Validation
PASS

Failures: 0

## Example Forecasts

| Request | User | Start | End | Starting Balance | Ending Balance | Min Headroom | First Breach |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| request_100 | user_100 | 2024-06-06 | 2024-09-04 | 68363.53 | 74816.14 | 23915.92 | NONE |
| request_101 | user_101 | 2025-11-03 | 2026-02-01 | 465868.5 | 806486.82 | 155944.02 | NONE |
| request_102 | user_102 | 2026-04-05 | 2026-07-04 | 4643.74 | 1977.24 | 1077.24 | NONE |
| request_103 | user_103 | 2024-09-07 | 2024-12-06 | 168749 | 230066.61 | -3885.16 | 2024-09-14 |
| request_104 | user_104 | 2025-02-04 | 2025-05-05 | 64021.7 | 29077.48 | 883.88 | NONE |
| request_105 | user_105 | 2026-06-08 | 2026-09-06 | 147831.8 | 216201.22 | 50290.12 | NONE |
| request_106 | user_106 | 2024-12-03 | 2025-03-03 | 2601.7 | -1561.85 | -2761.85 | 2025-01-03 |
| request_107 | user_107 | 2025-05-05 | 2025-08-03 | 5054.52 | -1333.51 | -2933.51 | 2025-06-16 |

## Diagnostics

Run `python -m code.main --simulate <request_id>` for per-request verbose ledger.

