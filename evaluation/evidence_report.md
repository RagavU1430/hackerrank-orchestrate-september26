# Multimodal Evidence Intelligence Report

Phase 3 Evidence Extraction, Validation, and State Resolution Audit.

## Image Evidence Summary

| Metric | Count | Status |
| :--- | :--- | :--- |
| Images Discovered in Queue | `16` | Verified |
| Amounts Successfully Resolved | `16` | Accepted |
| Failed / Unreadable Files | `0` | None |
| Ambiguous Documents | `0` | None |

### Image Extractions Detail

| Image ID | User ID | Event ID | Doc Type | Extracted Amount | Currency | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `image_01` | `user_03` | `event_253` | `payslip` | `4,365,000.00` | `IDR` | ACCEPTED |
| `image_02` | `user_16` | `event_1442` | `rent_receipt` | `100,000.00` | `INR` | ACCEPTED |
| `image_03` | `user_17` | `event_1545` | `grocery_bill` | `41,272.00` | `INR` | ACCEPTED |
| `image_04` | `user_19` | `event_1700` | `grocery_delivery_order` | `2,854.00` | `INR` | ACCEPTED |
| `image_05` | `user_20` | `event_1786` | `utility_bill` | `704.05` | `INR` | ACCEPTED |
| `image_06` | `user_33` | `event_3051` | `grocery_invoice` | `1,995.00` | `INR` | ACCEPTED |
| `image_07` | `user_35` | `event_3231` | `restaurant_bill` | `8,528.00` | `INR` | ACCEPTED |
| `image_08` | `user_48` | `event_4535` | `society_maintenance_receipt` | `15,339.00` | `INR` | ACCEPTED |
| `image_09` | `user_55` | `event_5170` | `water_utility_receipt` | `723.00` | `INR` | ACCEPTED |
| `image_10` | `user_64` | `event_6033` | `grocery_invoice` | `79,679.26` | `INR` | ACCEPTED |
| `image_11` | `user_73` | `event_6859` | `hospital_bill` | `3,650.00` | `INR` | ACCEPTED |
| `image_12` | `user_78` | `event_7307` | `taxi_receipt` | `33.50` | `USD` | ACCEPTED |
| `image_13` | `user_84` | `event_7941` | `store_receipt` | `2,298.00` | `INR` | ACCEPTED |
| `image_14` | `user_101` | `event_9421` | `pharmacy_slip` | `4,543.00` | `INR` | ACCEPTED |
| `image_15` | `user_105` | `event_9806` | `flight_invoice` | `9,968.00` | `INR` | ACCEPTED |
| `image_16` | `user_113` | `event_10521` | `ev_charging_invoice` | `393.22` | `INR` | ACCEPTED |

## Message Evidence Summary

| Metric | Count |
| :--- | :--- |
| Total Messages Processed | `215` |
| Structured Updates Extracted | `215` |

### Message Categories Breakdown

| Category | Count | Description |
| :--- | :--- | :--- |
| `pending_hold` | 37 | Structured pattern extracted |
| `salary_update` | 31 | Structured pattern extracted |
| `other` | 31 | Structured pattern extracted |
| `salary_reduced` | 25 | Structured pattern extracted |
| `salary_first` | 25 | Structured pattern extracted |
| `invoice_confirmed` | 15 | Structured pattern extracted |
| `contract_end` | 12 | Structured pattern extracted |
| `salary_date_change` | 7 | Structured pattern extracted |
| `rent_increase` | 7 | Structured pattern extracted |
| `internal_transfer` | 6 | Structured pattern extracted |
| `unrealized_investment` | 6 | Structured pattern extracted |
| `disputed_charge` | 6 | Structured pattern extracted |
| `failed_debit` | 4 | Structured pattern extracted |
| `reimbursement_closed` | 3 | Structured pattern extracted |

## Conflicts & Precedence Resolution

Zero contradictory simultaneous evidence conflicts detected.
Precedence rule enforced: `structured settled data > image evidence > message evidence`.

## Unresolved Evidence

Zero unresolved extraction issues. All 16 dynamic image events successfully resolved.

## Overall Status

**Status: PASS (All Multimodal Evidence Extracted & Reconciled)**

---
*Report generated automatically by Phase 3 Multimodal Evidence Intelligence engine.*
