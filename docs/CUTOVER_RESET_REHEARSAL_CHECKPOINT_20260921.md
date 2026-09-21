# Cutover reset rehearsal checkpoint — 2026-09-21

The target ERP now has a **Cutover rehearsal** workspace that inventories every operational table and its current row count, inspects foreign-key dependencies, and calculates a child-first test-data purge sequence. It does not expose an execution endpoint and cannot delete rows, import files, write to BizModo, post accounting, file VAT or activate production.

Each frozen rehearsal includes:

- the operational-table inventory and dependency-safe purge order;
- a distinction between disposable test rows and control records retained until external archival;
- current posting-lock evidence;
- explicit blockers for the final frozen BizModo capture, uploaded-file archive, target backup/restore test, final row-count manifest and named business authorization;
- the controlled sequence for source freeze, target backup, evidence archival, full test-data purge, fresh import, reconciliation, business acceptance and separate production activation; and
- a rollback plan that restores only the target ERP backup and never changes BizModo.

The rehearsal follows maker-checker approval. Approval accepts only the documented plan; it is not authority to execute a purge or import. Excel and JSON exports remain locked until independent approval.

The actual reset remains prohibited until the ERP build is accepted and every blocked gate is cleared. At that later cutover, all target business test data will be deleted and the complete BizModo dataset will be imported afresh. HRM is included; payroll remains excluded.
