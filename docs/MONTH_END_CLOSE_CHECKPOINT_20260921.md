# Month-end close checkpoint — 2026-09-21

The target ERP now provides a controlled month-end close package for each open, rehearsal-enabled fiscal period.

The package presents a source-derived checklist for VAT approval, pending closing adjustments, negative inventory positions and permanent-journal balance. Accrual, prepayment, foreign-exchange revaluation and inventory-valuation adjustments require documentary evidence and independent approval. Accruals and prepayments require a next-period reversal date.

Submission freezes the checklist and operational snapshot under a SHA-256 fingerprint. An independent approver must accept the frozen package before the system can generate a balanced close rehearsal. The rehearsal is idempotent and retains the proposed debit and credit entries.

This staging checkpoint deliberately does not post journals or lock the fiscal period. Those actions remain fail-closed until final data replacement, production activation and cutover approval.
