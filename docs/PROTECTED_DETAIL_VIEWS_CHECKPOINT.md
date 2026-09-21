# Protected ERP detail views checkpoint

Date: 2026-09-09

## Outcome

Authenticated UAT list rows now open protected read-only detail views for customers, suppliers, products, sales, purchases, and inventory movements.

## Detail coverage

- Customer/supplier: code, kind, business name, contact name, and migration state; telephone, email, address, tax number, and raw evidence remain redacted.
- Product: SKU, name, type, category, brand, migration state, canonical UOM, and factor-to-base snapshot.
- Sale/purchase: scoped document header, totals, status, related lines, and payments.
- Inventory: scoped movement, product reference, document reference, entered quantity/UOM, factor-to-base snapshot, base quantity/UOM, and migration state.

Every transaction and inventory detail is re-authorized and re-filtered by the active location scope. Guessing an ID outside that scope returns not found rather than revealing the record.

## Safety boundary

- No edit, delete, posting, approval, number reservation, or source-write endpoint exists.
- Raw payloads and internal evidence dictionaries are excluded.
- HRM is included; payroll remains excluded.
- Master detail is read-only and operationally disabled.

## Verification

- Reproducible authenticated UAT: 68 passed, 0 failed.
- Local application suite: 54 passed, 1 PostgreSQL-only test skipped outside its profile.
- Fresh isolated PostgreSQL integration: 1 passed, including scoped document detail and out-of-scope/not-found behavior.
- Browser: a sale rendered with 2 related lines and 1 payment; a product rendered with its canonical UOM and factor-to-base snapshot.
- The temporary PostgreSQL validation containers, network, and volume were removed after the successful test. The verified PostgreSQL clone was not used or changed.
