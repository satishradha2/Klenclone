# Target-ledger financial reporting checkpoint — 2026-09-30

## Corrected reporting basis

- Month-end close and financial statements now share the same period-scoped permanent-journal evidence. Both legacy and integrated posting batches are included; the close freezes a fingerprint of their journal lines and fails on an imbalance.
- The Financial Statements package uses **posted target-ERP journal lines** for its period trial balance, profit or loss, balance-sheet movement bridge, and cash-account net movement. Approved general-journal plans and close adjustments are shown separately as unposted work; they do not change actual figures.
- Known historical payment labels are mapped transparently to the ASAS chart: `Accounts Receivable` to `1200`, `Accounts Payable` to `2100`, and an active cash/bank account code to its approved GL account. The report lists each alias used. Unknown or unapproved account mappings block package generation instead of being guessed into assets.
- A posted-ledger change after close submission blocks report generation, approval, and export. Older reports without the posted-ledger basis are marked for source review in the workspace. Downstream statutory evidence checks the same report source.
- Cash flow is labelled only as net movement in cash-equivalent accounts; operating/investing/financing classification is not invented. Retained-earnings opening, distributions, and closing are not presented as known when opening balances are unverified.

## Synthetic verification

- A controlled posted-invoice plus bank/recovery ledger fixture produces balanced AED 107.00 period trial-balance sides, AED 100.00 profit, AED 2.00 cash movement, and a zero balance-sheet movement difference. An approved but unposted AED 125.50 close adjustment is excluded from those actual figures.
- The disposable customer-credit/refund route test creates, approves, bank-matches, and directly posts synthetic target documents without opening HTTP posting. Its month-end report now includes the refund-recovery batch, reconciles account 2130, and discloses its legacy payment-account mappings.
- Separate regressions reject an unknown posted account, an imbalanced integrated journal, and a report approval after a late journal changes the frozen close. Focused Python and JavaScript tests pass.

## Release boundary and next gap

These are **period movement reports**, not certified complete financial statements. Opening GL balances are not posted and reconciled, retained earnings are not established, cash-flow activities are not classified, and other posting paths still use free-text accounts (for example GRNI, advances, and some stock/expense journals). Those paths need governed chart mappings and synthetic end-to-end tests before full-ledger statements or statutory readiness can be claimed. Prior period closing balances and comparative periods also remain to be proven. The source BizModo system remains read-only. Shared staging posting is disabled; no production posting, deployment, or GitHub push was performed in this checkpoint.

## Follow-on GL mapping increment

- A central GL preflight now resolves integrated and legacy draft journals to **active, postable ASAS chart accounts** before either activated HTTP posting route can execute. It uses exact, code-defined legacy labels (AR/AP, inventory/GRNI, VAT, revenue/COGS and advances), direction-specific stock-adjustment accounts, and independently approved cash/bank masters. Unknown labels, draft/inactive chart accounts, and unbalanced resolved journals are rejected. Integrated posting previews expose readiness and line-by-line mapping evidence without posting.
- Four missing chart-template accounts were added for supplier advances (`1210`), goods received not invoiced (`2115`), customer advances (`2140`), and inventory adjustment gains (`4020`). They are **draft until finance maker-checker approval**, like the existing chart. Neither seeding nor this preflight activates posting.
- On the activated route, integrated and legacy journal batches persist the resolved numeric chart codes and bind the mapped journal digest into their batch fingerprint. A synthetic payment test proves a draft chart blocks execution, and separate finance and bank checkers can approve the required masters before a correctly coded, balanced batch is written. Existing direct domain-posting fixtures retain their explicit unenforced synthetic path; the application routes always request GL enforcement.
- This gate does not yet replace historical free-text batches, establish opening balances, or certify the full chart and all module mappings. The financial-reporting guard still fails closed for unknown historical accounts. Production posting remains disabled; full release requires an approved chart/mapping audit and a fresh end-to-end cutover rehearsal.
