# Staging data model

This design keeps every browser export immutable and separates evidence from business interpretation. It is suitable for building the clone before a frozen final migration, but it does not make the current non-atomic snapshot final.

## Layers

1. `raw_file_manifest`: filename, SHA-256, byte length, extraction timestamp, source route, filters, displayed count and parser version.
2. `raw_record`: one source row or detail payload with source filename, ordinal, raw JSON/text, raw document number and ingest timestamp.
3. `stg_*`: typed but source-faithful tables. Footer/UI rows are quarantined, never deleted.
4. `erp_*`: canonical ERP entities with generated UUIDs and retained source-system/source-ID keys.
5. `recon_exception`: duplicate keys, unmatched relationships, amount variances, negative stock, missing locations and snapshot drift.

## Required staging tables

| Domain | Tables |
|---|---|
| Provenance | `raw_file_manifest`, `raw_record`, `source_snapshot`, `recon_exception` |
| Organization | `stg_business`, `stg_location`, `stg_user`, `stg_role`, `stg_role_permission` |
| Parties | `stg_contact`, `stg_customer`, `stg_supplier`, `stg_contact_login`, `stg_zone` |
| Products | `stg_product`, `stg_uom_definition`, `stg_product_uom_profile`, `stg_category`, `stg_brand`, `stg_product_location` |
| Purchasing | `stg_purchase`, `stg_purchase_line`, `stg_purchase_payment`, `stg_purchase_return`, `stg_purchase_return_line` |
| Sales | `stg_sale`, `stg_sale_line`, `stg_sale_payment`, `stg_sale_return`, `stg_sale_return_line`, `stg_shipment` |
| Inventory | `stg_stock_balance`, `stg_stock_transfer`, `stg_stock_transfer_line`, `stg_item_trace`, `stg_inventory_movement`, `stg_inventory_opening_control` |
| Finance | `stg_payment_account`, `stg_cash_flow_entry`, `stg_tax_evidence`, `stg_financial_allocation`, `stg_trial_balance_entry`, `stg_accounting_control`, `stg_coa_account`, `stg_journal_blueprint`, `stg_journal_blueprint_line` |
| Configuration | `stg_business_setting`, `stg_invoice_scheme`, `stg_barcode_layout`, `stg_printer`, `stg_notification_template` |
| Documents | `stg_attachment`, `stg_attachment_link`, `missing_attachment_exception` |
| HRM archival preservation | `stg_attendance`, `stg_shift`, `stg_sales_target`, `stg_leave`, `stg_payroll` (not activated in the target ERP) |

## Locked ERP foundation

The first canonical target layer is deliberately non-operational. `erp_organization`, `erp_location`, `erp_fiscal_period`, `erp_number_sequence`, `erp_module_policy`, `erp_source_key_registry`, `erp_approval_policy`, `erp_approval_step`, `erp_migration_batch`, `erp_migration_batch_entity` and `erp_audit_event` establish ownership and traceability without enabling posting.

Every raw record has exactly one registry row containing its manifest hash, canonical content hash and source locator. Registry and audit rows are append-only at the application mapper layer. Number-sequence values are frozen observations and candidate continuations only; they do not reserve or guarantee the live source's next number.

Canonical master promotion uses `erp_party`, `erp_product_master`, `erp_uom_master`, `erp_product_uom`, `erp_tax_profile` and `erp_opening_balance_queue`. Each promoted party, product, UOM and opening control retains its typed staging ID and/or raw-record ID. Promotion does not deduplicate by name, activate masters, post balances or convert unresolved UOM evidence by assumption.

Canonical transaction promotion uses `erp_transaction_document`, `erp_transaction_line`, `erp_transaction_payment`, `erp_inventory_movement` and `erp_migration_exception_queue`. Target records retain staging/raw identities, parent and product relationships, entered quantity/UOM, conversion factor snapshots and base quantity. A source status of `posted` is evidence only and never enables target posting.

Canonical accounting promotion uses `erp_gl_account`, `erp_journal_blueprint`, `erp_journal_blueprint_line`, `erp_subledger_control`, `erp_tax_ledger_evidence`, `erp_cash_ledger_evidence`, `erp_trial_balance_evidence` and `erp_financial_activation_gate`. These are auditable migration candidates and controls, not an active ledger. Balanced source-derived blueprints remain non-posting until every financial gate is approved.

Security promotion uses `erp_security_user`, `erp_security_role`, `erp_security_permission`, `erp_security_role_permission`, `erp_security_user_role`, `erp_security_location_scope`, `erp_approval_role_binding`, `erp_segregation_rule`, `erp_security_policy` and `erp_security_activation_gate`. Source grants are evidence and remain distinct from target grants. Password material is never imported, users cannot authenticate, and missing location scopes deny access by default.

Coverage closure uses `erp_reference_master`, `erp_residual_business_record`, `erp_source_coverage` and `erp_coverage_gate`. Every raw row has exactly one coverage row. A row may be structurally linked, preserved as report/configuration evidence, quarantined as presentation content, retained as HRM archive, or explicitly blocked pending a dedicated workflow model. Residual does not mean discarded; it means the immutable source record is retained without pretending it is ready to operate.

Residual workflow promotion uses `erp_portal_identity`, `erp_sales_workflow_document`, `erp_shipment_record`, `erp_sales_target_evidence`, `erp_stock_transfer_detail_artifact` and `erp_residual_workflow_gate`. Dedicated structure closes entity-level coverage without overriding record-level blockers. Portal credentials are never copied, quote/draft party links must be deterministic, sales targets require amount/period definitions, and unparsed transfer artifacts remain blocked.

## Identity and no-loss rules

- Never use invoice or purchase number alone as a primary key; preserve duplicated legacy references and generate unique ERP IDs.
- Retain `source_system`, `source_entity`, `source_record_id`, `source_document_number`, source filename and row ordinal on every imported record.
- Store entered quantity, entered UOM, conversion snapshot and base quantity separately.
- Use decimal types for money, tax, cost and quantity; never binary floating point.
- Attachments require original filename, MIME type, byte length, content hash, storage object key and links to every related transaction/payment.
- HRM/payroll data is preserved in staging and archival exports even if excluded from the first ERP release.

## Reconciliation gates

- Header counts, distinct source IDs and document-number duplicate counts match the frozen source.
- Every line, payment, return, shipment, attachment and stock movement has a valid parent or a documented exception.
- Header totals reconcile to line net, discount, tax, freight, rounding, returns and payments.
- Stock opening plus movements equals closing stock by product, UOM, sub-location and business location.
- AR, AP, tax, trial balance and balance sheet variances are zero or formally approved opening-balance exceptions.
- File hashes are rechecked before and after every load.

## Final cutover

With username/password only, the safest achievable cutover is a transaction freeze followed by repeated exports and delta reconciliation. A database plus uploaded-file backup remains the only reliable way to prove atomic completeness, hidden/deleted record coverage and attachment preservation.
