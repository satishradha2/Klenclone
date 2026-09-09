# UAT discrepancy register

Date: 2026-09-09

This register records discrepancies without changing source evidence. Counts come from the isolated read-only UAT copy. A discrepancy can be resolved only through an approved transformation rule or a documented business decision; source rows must never be overwritten.

## Summary

| Area | Open records | UAT disposition |
|---|---:|---|
| Finance and accounting | 90 | Blocks financial activation and posting |
| Inventory and UOM | 61 | Blocks opening stock and inventory activation |
| Transaction/master relationships | 37 | Blocks affected document activation |
| **Total** | **188** | **All retained in review queues; none auto-corrected** |

## Finance and accounting

| Code | Severity | Count | Required resolution |
|---|---|---:|---|
| `FINANCIAL_DOCUMENT_REVIEW` | Critical | 28 | Reconcile document totals, paid values, and outstanding balances |
| `FINANCIAL_ALLOCATION_RESIDUAL` | High | 16 | Approve allocation rules or match the residual manually |
| `SETTLEMENT_RESIDUAL` | High | 13 | Match settlement evidence to the correct document/account |
| `PAYMENT_WITHOUT_CASH_FLOW` | High | 10 | Recover cash-flow evidence or approve an opening adjustment |
| `JOURNAL_BLUEPRINT_REVIEW` | High | 8 | Approve debit/credit derivation before journal creation |
| `ACCOUNTING_CONTROL_VARIANCE` | Critical | 6 | Reconcile control account variance |
| `CASH_FLOW_PAYMENT_UNMATCHED` | High | 4 | Link cash-flow row to payment evidence |
| `TAX_EVIDENCE_UNMATCHED` | High | 4 | Match tax evidence to document and tax profile |
| `TRIAL_BALANCE_LABEL_MISSING` | Critical | 1 | Assign an approved target ledger label |

## Inventory and UOM

| Code | Severity | Count | Required resolution |
|---|---|---:|---|
| `INVENTORY_MOVEMENT_READINESS` | Critical | 40 | Resolve product, location, direction, and base-quantity readiness |
| `OPENING_STOCK_BLOCKED` | Critical | 5 | Resolve blocked opening-stock controls |
| `UOM_REGISTRY_CONFLICT` | Critical | 5 | Approve one canonical UOM mapping per conflicting source unit |
| `UOM_CONVERSION_UNRESOLVED` | Critical | 4 | Supply and approve the factor-to-base snapshot |
| `NEGATIVE_STOCK` | High | 4 | Validate timing, missing receipts, or approved opening balance |
| `MISSING_STOCK_LOCATION` | High | 3 | Assign an approved target location |

## Transaction and master relationships

| Code | Severity | Count | Required resolution |
|---|---|---:|---|
| `TRANSACTION_LINE_RELATIONSHIP` | Critical | 22 | Link line evidence to the correct header/product |
| `AMBIGUOUS_RELATIONSHIP` | Critical | 5 | Business owner must choose the supported relationship |
| `DETAIL_HEADER_DRIFT` | Critical | 4 | Reconcile detail totals/status against the source header |
| `PAYMENT_PARENT_RELATIONSHIP` | Critical | 3 | Link payment to the supported parent document |
| `DUPLICATE_DOCUMENT_NUMBER` | Critical | 2 | Preserve source IDs and approve the target display-number rule |
| `MASTER_SNAPSHOT_DRIFT` | Critical | 1 | Reconcile master evidence across extraction points |

## Technical UAT findings

| ID | Finding | Status | Evidence |
|---|---|---|---|
| `UAT-UI-001` | Login completed but the browser form event expired before the record workspace rendered | Resolved | Form reference is captured before the asynchronous request |
| `UAT-UI-002` | Logout initially left stale identity/status text visible | Resolved | Signed-out state now clears identity and status |

No unresolved technical defect was found in the automated authenticated UAT run. Business acceptance and the 188 source-data discrepancies remain open.

## Approval rule

For every open discrepancy, record the responsible business owner, approved resolution, supporting evidence, approver, and approval date. Corrections must be represented as target-side transformation decisions with an audit trail. Never amend the BizModo source or the verified raw clone.
