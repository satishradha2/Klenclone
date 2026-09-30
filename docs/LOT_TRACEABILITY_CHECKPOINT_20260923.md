# Receipt-to-customer lot traceability checkpoint

Date: 2026-09-23
Environment: controlled local staging at `127.0.0.1:18082`
Source rule: BizModo remains strictly read-only.

## Implemented path

- Independent acceptance of a target goods receipt registers accepted batch quantities as immutable receipt-lot provenance. Rejected quantity is excluded. Products marked lot-tracked require a batch; expiry-tracked products also require an expiry date.
- Delivery pickers can assign one or more accepted receipt lots to each allocated delivery line, up to both the receipt-lot quantity and delivery-line quantity. A tracked line cannot be picked or dispatched without complete lot assignment. Expired, quarantined, and actively recalled lots are blocked.
- Dispatch consumes the lot assignments alongside the existing aggregate stock issue; cancellation releases assignments. Delivery note, proof of delivery, and invoice retain their existing document controls.
- Warehouse Controls provides a supplier-to-customer lot lookup. The trace joins accepted receipt, delivery line, customer, and the invoice line linked to that delivery. Recall entries can target a receipt lot key or registered batch identity.

## Boundary and outstanding gate

Receipt acceptance remains non-posting and does **not** credit the aggregate operational stock position. The lot assignment is therefore an auditable operator assertion bounded by accepted receipt quantity and the existing aggregate stock availability check; it is not yet a fully reconciled physical lot-stock subledger. Historical source-era lots also have no automatically proven receipt-to-customer chain. Reconciliation of lot balances to warehouse stock, source-era provenance import, named warehouse UAT, and production cutover authorization remain open. No accounting posting or BizModo source write is enabled by this increment.
