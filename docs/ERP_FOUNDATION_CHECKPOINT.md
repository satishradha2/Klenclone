# ERP foundation checkpoint

## Result

The target ERP foundation has been created in the confidential local staging database for snapshot `bizmodo-2026-09-08-browser`. It is migration-locked and non-posting. The operation reads only previously captured evidence and does not connect to or modify BizModo.

| Control | Verified result |
|---|---:|
| Organization | 1 — Asas General Trading LLC |
| Locations | 4 — BL0001, BL0004, BL0003, BL0002 |
| Fiscal periods | 1 — FY2026, locked |
| Raw source-key registrations | 41,444 |
| Raw rows without a registry entry | 0 |
| Frozen numbering-evidence sequences | 10 |
| Module policies | 10 |
| Draft approval policies / steps | 4 / 9 |
| Migration batches / entity controls | 1 / 43 |
| Foundation audit events | 1 |
| Posting-enabled records | 0 |

The manifest digest is `267a604a17ded07f5c45862b6b18d91814c5970378651be98f7c8b04c4a09371`. A repeated build created zero new records, proving the bootstrap is idempotent for this evidence set.

## Configuration carried forward

- Legal entity: Asas General Trading LLC.
- Currency and timezone: AED and Asia/Dubai.
- Fiscal year: January through December.
- Inventory costing: FIFO.
- Precision: two decimal places for currency and quantity.
- Default VAT evidence: 5%.
- The captured primary tax-registration number is retained in the confidential organization record and intentionally omitted from this report.
- Source POS rounding evidence: nearest AED 0.25; it is not activated as a target posting rule.
- Source invoice schemes: default `AK2026-` and VAN `NUVO-`; their observed/configured counters are frozen evidence, not active reservations.

## HRM and payroll boundary

HRM and payroll are explicitly `archival_only`, with `target_enabled=false` and `posting_enabled=false`. Their captured source rows remain protected in raw/staging evidence so exclusion from the operational ERP does not mean data deletion.

## Safety controls

- All operational modules remain `draft_disabled`.
- The source-key registry links every raw row to the source entity, source keys, file/ordinal locator, manifest SHA-256 and canonical row SHA-256.
- Source-key registry and audit events reject update and delete operations through the application mapper.
- Number sequences are `frozen_pending_cutover`; reservation is disabled.
- Approval policies are `draft_locked`; activation is disabled and no monetary thresholds were invented.
- The migration batch is `staged_nonposting` and records that the source snapshot is non-atomic.

## Verification

`python -m pytest -q` passes 29 tests. Compilation succeeds. Repeated foundation commands create no rows, and the main reconciliation reports all expected foundation counts.

The existing controlled exceptions remain visible: four negative-stock rows, three stock rows without location, five ambiguous relationships, one later stock-transfer header, three later sales headers and one product-master drift row. These are evidence of browser-export timing or source quality and have not been silently corrected.

## Remaining cutover gate

This foundation is not authorization to post, transact or replace the live system. Username/password exports cannot prove an atomic final copy. The last migration still requires a transaction-free window, repeat/delta exports, file-hash comparison, attachment coverage checks, reconciliation sign-off and explicit activation approval. A hosting/database and uploaded-file backup would remain stronger evidence if it becomes available.
