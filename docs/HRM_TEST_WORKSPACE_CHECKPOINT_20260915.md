# HRM test workspace checkpoint — 15 September 2026

## Confirmed boundary

- HRM is included in the target Asas ERP.
- Payroll is excluded and no payroll table, record, permission or UI action is enabled.
- BizModo remains strictly read-only.
- The current HRM rows are test data and must be deleted with the other imported test data before the final fresh BizModo import.

## Implemented HRM

- Operational HRM import batch with a source-snapshot digest and test-data marker.
- Employee directory, attendance register and shift-definition tables in the separate operational database.
- Idempotent initialization from the sealed `users.csv`, `hrm_attendance_2026.csv` and `hrm_shifts.csv` evidence.
- Source clock strings are normalized to their date/time prefix for display. Captured IP addresses, location text and source action controls are not displayed.
- Dedicated HR Manager, HR Officer and Employee Self Service role bundles. HR Officer and HR Manager are a maker/approver segregation pair.
- Permission-controlled `/api/v1/hrm` endpoint and HRM workspace.
- Governed department and designation masters plus operational employee profiles.
- Revision-controlled employee lifecycle change requests with independent maker-checker approval.
- Employee and officer leave requests with overlap validation and independent approval.
- Non-destructive attendance correction requests: approved corrections remain overlays and never alter sealed source evidence.
- Holiday calendar, shift creation and effective-dated employee shift assignments.
- Employee self-service API restricted to the employee identity linked to the signed-in login.
- Audit events for every HR master change, request, approval, rejection and assignment.
- Future cutover readiness now requires employee, attendance, shift, leave-control and sales-target evidence while explicitly excluding payroll.

## Current test-data evidence

- 16 employee/user rows.
- 182 attendance rows.
- 1 shift definition.
- 0 visible payroll rows; payroll remains outside scope regardless of source availability.

## Safety posture

- No BizModo action was performed.
- No accounting, stock or payroll posting is possible from HRM.
- The operational import is checksum-derived and idempotent.
- The final fresh import remains blocked until a frozen capture and the full test-data purge are completed.

## Remaining cutover work

Delete the complete imported test dataset, perform the frozen final BizModo capture, import the fresh HRM dataset, reconcile row counts and source digests, link final employee identities, and complete business UAT. No test approval or correction is carried into the final import, and payroll remains excluded.
