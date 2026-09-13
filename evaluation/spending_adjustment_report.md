# Spending Adjustment Optimization Report

**Generated:** 2026-09-13T14:22:39.908156
**Total Requests Evaluated:** 250

## Executive Summary

- **Requests requiring spending changes:** 25 (10.0%)
- **Requests requiring no changes:** 225 (90.0%)
- **Average changes per request:** 0.15
- **Maximum changes on any request:** 3
- **STOP usage (total occurrences):** 6
- **REDUCE usage (total occurrences):** 32
- **No feasible scenario (wait / not recommended):** 184 (73.6%)
- **Safety violations (invariant failures in chosen plans):** 0

## Status Distribution

| Affordability Status | Count | Percentage |
|---|---|---|
| `affordable_later` | 38 | 15.2% |
| `affordable_now` | 26 | 10.4% |
| `affordable_with_plan` | 40 | 16.0% |
| `not_affordable` | 146 | 58.4% |

## Payment Method Distribution

| Recommended Method | Count | Percentage |
|---|---|---|
| `full_payment` | 37 | 14.8% |
| `installments` | 28 | 11.2% |
| `not_recommended` | 146 | 58.4% |
| `partial_payment` | 1 | 0.4% |
| `wait` | 38 | 15.2% |

## Spending Changes Breakdown

- **0 changes (`none`):** 225
- **1 change:** 15
- **2 changes:** 7
- **3 changes:** 3
- **> 3 changes:** 0 (MUST BE 0)

## Rejected Change Reasons

- Protected categories protected by user profile (`expense_categories_to_protect`)
- Category not in user willingness list (`expense_categories_user_is_willing_to_stop` / `reduce`)
- Expense not flexible (`can_stop` / `can_reduce` is False)
- Exceeds maximum limit of 3 changes
- Mutual exclusivity violation (STOP and REDUCE on same event)
- 90-day simulation balance falls below `minimum_balance_to_keep`

## Safety Violations

Total safety breaches in selected scenarios: 0

All selected scenarios strictly maintain `closing_balance >= minimum_balance_to_keep` across all 90 days.
