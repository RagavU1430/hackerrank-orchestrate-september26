# Dataset Quality Report

Automated Phase 1 Data Foundation & Ingestion Verification.

## Files & Row Counts

| Dataset | File Name | Records | Columns | Status |
| :--- | :--- | :--- | :--- | :--- |
| Financial Profiles | `financial_profiles.csv` | 275 | 10 | Validated |
| Financial Events | `financial_events.csv` | 25342 | 14 | Validated |
| Evaluation Requests | `requests.csv` | 250 | 8 | Validated |
| Sample Requests | `sample_requests.csv` | 25 | 15 | Validated |
| Payment Options | `request_payment_options.csv` | 790 | 9 | Validated |
| Exchange Rates | `exchange_rates.csv` | 134 | 4 | Validated |
| Messages | `messages.csv` | 215 | 7 | Validated |
| Images | `images.csv` | 16 | 4 | Validated |

## Duplicate Identifiers

Zero duplicate primary identifiers found across all 8 datasets.

## Missing Values Analysis

- **Financial Events missing amount**: `16` records (all mapped to evidence queue).
- **Financial Events missing settlement_date**: `10` records (unrealized investments).
- **Financial Events with linked_event_id**: `58` records.
- **Profiles without installment preference**: `119` users (`max_installment_months` is blank).
- **Payment Options without frequency**: `275` options (single full payment options).

## Cross-Reference Integrity

All foreign key relationships are strictly intact:
- Every request references a valid user in `financial_profiles.csv`.
- Every financial event references a valid user in `financial_profiles.csv`.
- Every payment option references a valid request in `requests.csv` or `sample_requests.csv`.
- Every message references a valid user.
- Every image references a valid user, valid event, and existing PNG file.

## Dynamic Image Evidence Queue

Total events requiring image amount extraction in Phase 3: **16**

| Event ID | User ID | Category | Event Date | Linked Image | Image Path Exists |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `event_253` | `user_03` | `salary` | `2019-08-31` | `image_01` | Yes |
| `event_1442` | `user_16` | `rent` | `2023-08-11` | `image_02` | Yes |
| `event_1545` | `user_17` | `groceries` | `2026-02-27` | `image_03` | Yes |
| `event_1700` | `user_19` | `groceries` | `2024-09-03` | `image_04` | Yes |
| `event_1786` | `user_20` | `utilities` | `2026-02-06` | `image_05` | Yes |
| `event_3051` | `user_33` | `groceries` | `2026-01-06` | `image_06` | Yes |
| `event_3231` | `user_35` | `dining` | `2025-10-29` | `image_07` | Yes |
| `event_4535` | `user_48` | `housing` | `2026-07-24` | `image_08` | Yes |
| `event_5170` | `user_55` | `utilities` | `2026-06-07` | `image_09` | Yes |
| `event_6033` | `user_64` | `groceries` | `2024-06-03` | `image_10` | Yes |
| `event_6859` | `user_73` | `healthcare` | `2023-01-19` | `image_11` | Yes |
| `event_7307` | `user_78` | `transport` | `2025-10-01` | `image_12` | Yes |
| `event_7941` | `user_84` | `shopping` | `2026-04-03` | `image_13` | Yes |
| `event_9421` | `user_101` | `healthcare` | `2025-11-02` | `image_14` | Yes |
| `event_9806` | `user_105` | `transport` | `2026-06-07` | `image_15` | Yes |
| `event_10521` | `user_113` | `transport` | `2026-09-03` | `image_16` | Yes |

## Currency Distribution

### User Home Currencies
| Currency | Count | Percentage |
| :--- | :--- | :--- |
| `INR` | 67 | 24.4% |
| `EUR` | 62 | 22.5% |
| `IDR` | 55 | 20.0% |
| `ZAR` | 51 | 18.5% |
| `USD` | 40 | 14.5% |

### Exchange Rate Currency Pairs
| Currency Pair | Rates Count | Date Range |
| :--- | :--- | :--- |
| `USD` -> `INR` | 33 | 2024-01-15 to 2026-11-15 |
| `USD` -> `IDR` | 30 | 2023-10-15 to 2026-06-15 |
| `USD` -> `EUR` | 25 | 2023-10-15 to 2026-03-15 |
| `EUR` -> `USD` | 24 | 2024-04-15 to 2026-09-15 |
| `EUR` -> `ZAR` | 22 | 2023-10-15 to 2026-01-15 |

## Date Coverage

- **Evaluation Requests**: `2023-01-20` to `2026-09-04`
- **Sample Requests**: `2019-09-03` to `2026-07-07`
- **Financial Events**: `2019-03-09` to `2026-09-03`

## Status & Flexibility Distributions

### Event Status
| Status | Count | Share |
| :--- | :--- | :--- |
| `settled` | 25148 | 99.23% |
| `pending` | 71 | 0.28% |
| `scheduled` | 70 | 0.28% |
| `cancelled` | 22 | 0.09% |
| `failed` | 21 | 0.08% |
| `unrealized` | 10 | 0.04% |

### Event Flexibility
| Flexibility | Count | Share |
| :--- | :--- | :--- |
| `fixed` | 21138 | 83.41% |
| `reducible` | 2682 | 10.58% |
| `stoppable` | 1297 | 5.12% |
| `reducible_or_stoppable` | 225 | 0.89% |

## Overall Status

**Status: PASS (All Structural & Relational Checks Verified)**

---
*Report generated automatically by Phase 1 Data Foundation Ingestion engine.*
