# Affordability Decision Report

## Summary

- **Requests Evaluated**: 250 / 250
- **Failures / Errors**: 0
- **Safety Invariant Check (0 <= safe <= requested)**: PASS

## Status Distribution

| Affordability Status | Count | Percentage |
| --- | ---: | ---: |
| `affordable_now` | 26 | 10.4% |
| `affordable_with_plan` | 5 | 2.0% |
| `affordable_later` | 69 | 27.6% |
| `not_affordable` | 150 | 60.0% |

## Affordability Breakdown

- **Fully Affordable Today (`safe == requested`)**: 31
- **Partially Affordable Today (`0 < safe < requested`)**: 142
- **Zero Safe Today (`safe == 0`)**: 77
- **Future Full Payment Safe Date Found**: 69
- **No Safe Full Payment Date in 90 Days**: 150

## Sample Decisions

| Request ID | User | Requested | Safe Today | Earliest Full Date | Status |
| --- | --- | ---: | ---: | --- | --- |
| `request_100` | `user_100` | 37114 | 23915.92 | 2024-08-15 | `affordable_later` |
| `request_101` | `user_101` | 143500 | 143500 | 2025-11-03 | `affordable_now` |
| `request_102` | `user_102` | 1716 | 1077.24 | none | `not_affordable` |
| `request_103` | `user_103` | 368300 | 0 | none | `not_affordable` |
| `request_104` | `user_104` | 17204 | 883.88 | none | `not_affordable` |
| `request_105` | `user_105` | 53500 | 50290.12 | 2026-06-15 | `affordable_later` |
| `request_106` | `user_106` | 2207.7 | 0 | none | `not_affordable` |
| `request_107` | `user_107` | 2534.4 | 0 | none | `not_affordable` |
| `request_108` | `user_108` | 55308 | 785.24 | none | `not_affordable` |
| `request_109` | `user_109` | 1863.4 | 359.04 | none | `not_affordable` |
| `request_110` | `user_110` | 22352 | 19445.06 | none | `not_affordable` |
| `request_111` | `user_111` | 16625000 | 13667973.25 | none | `not_affordable` |
| `request_112` | `user_112` | 271.7 | 0 | none | `not_affordable` |
| `request_113` | `user_113` | 36500 | 19295.63 | 2026-10-15 | `affordable_later` |
| `request_114` | `user_114` | 65300 | 0 | none | `not_affordable` |
