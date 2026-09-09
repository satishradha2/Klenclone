# Role and permission inventory

The role forms were opened read-only. No checkbox, radio button, Save, Update or Delete control was used.

| Role | Assigned users | Controls exposed | Checked controls |
|---|---|---:|---:|
| Accounts | Anandhu | 266 | 89 |
| Admin | Asas Trading, Mahi | Protected role; no edit form | Not exposed |
| Cashier | None visible | 266 | 26 |
| Field Sales Team | Aji, Kathija, Nithin, Stany, Roy, ligin Enose Joys, Prabhath Ramachandran | 266 | 51 |
| Manager | Hari Ram, Satish Radha | 266 | 131 |
| Stock Transfer Coordinator | Mugesh | 266 | 55 |
| Van Sales | Suveesh, Vishnu Sayi, Febin | 266 | 67 |

The six editable matrices are preserved as source evidence in `source_exports/2026-09-08/role_permissions_*.json`. Each file retains every control's type, internal name, value, label and checked state so that the clone can reproduce the source before least-privilege remediation.

The Admin role must be recreated as a protected system role and reviewed separately. The absence of an edit form is not evidence that it has a particular permission set.
