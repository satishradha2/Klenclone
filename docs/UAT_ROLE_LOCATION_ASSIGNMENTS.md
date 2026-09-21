# Read-only UAT role and location assignments

This sheet is the approval record for future human UAT access. It intentionally contains no passwords. Existing BizModo credentials must never be copied.

## Synthetic draft approvers

| Function | Display name | Draft alias | Location | Authority |
|---|---|---|---|---|
| Data owner | UAT Data Steward | `uat.data.steward` | MAIN | Draft only; no production authority |
| Finance controller | UAT Finance Controller | `uat.finance.controller` | MAIN | Draft only; no production authority |
| Inventory controller | UAT Inventory Controller | `uat.inventory.controller` | MAIN | Draft only; no production authority |
| System administrator | UAT Security Administrator | `uat.security.administrator` | MAIN | Draft only; cannot approve own access |

These are governance design aliases, not sign-in accounts or representations of real people. They cannot approve, post, activate, or change business data.

| UAT login | Person | Read-only role | Allowed location(s) | Modules | Approver | Approval date | Provisioned | Revoked |
|---|---|---|---|---|---|---|---|---|
| `synthetic.uat.reader` | Automated validation only | Synthetic UAT Reader | One isolated validation location | Customers, suppliers, products/UOM, sales, purchases, inventory, accounting summary | System test | 2026-09-09 | Yes, isolated copy only | On service stop |
| _unassigned_ |  |  |  |  |  |  | No |  |

Production or business-user provisioning remains blocked until the named person, exact role, allowed locations, and approver are recorded above. Complete HRM is in scope through separately authorized HR manager, HR officer, and employee-self-service roles; payroll remains excluded.
