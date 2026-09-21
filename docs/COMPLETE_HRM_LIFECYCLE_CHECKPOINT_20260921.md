# Complete HRM lifecycle checkpoint

Date: 2026-09-21  
Environment: controlled local staging  
Data classification: test-only; final fresh import still required

## Implemented scope

- Existing employee profiles, departments, designations, attendance corrections, leave, holidays and shift assignments.
- Maker-checker workforce requests for new positions, replacements and temporary headcount.
- Candidate pipeline from application through screening, interview, offer and acceptance/rejection, bound to an approved workforce request.
- Employee document metadata for passports, visas, Emirates ID, work permits, contracts and certificates, including issue/expiry validation and 90-day expiry controls.
- Governed onboarding, performance, training, disciplinary, separation and end-of-service cases.
- Independent approval/rejection and revision checks for workforce and lifecycle cases.
- Append-only audit events for every creation, stage change and decision.

## Payroll boundary

Payroll remains excluded. End-of-service cases record clearance, evidence and an approved outcome, but this module does not calculate salary, gratuity, deductions, benefits or payment journals.

## Document boundary

Employee document metadata and archive references are controlled here. Durable binary upload, malware scanning, versioning and retention remain part of the separate enterprise document-management gap.

## Safety

No BizModo record is changed. No HRM record posts accounting. All current operational records are test-only and will be deleted before the final fresh import.
