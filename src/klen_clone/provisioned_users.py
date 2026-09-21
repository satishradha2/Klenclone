from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProvisionedUser:
    id: int
    username: str
    password_hash: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    allowed_locations: tuple[str, ...]


def load_provisioned_users(path: str | None, fallback_username: str, fallback_hash: str) -> tuple[dict[str, ProvisionedUser], dict[int, ProvisionedUser]]:
    if path:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_users = document.get("users") or []
    elif fallback_username and fallback_hash:
        raw_users = [{
            "id": 1, "username": fallback_username, "password_hash": fallback_hash,
            "roles": ["operations_administrator"],
            "permissions": ["clone.read", "migration.review", "draft.create", "draft.edit", "draft.submit", "draft.cancel",
                            "inventory.create", "inventory.edit", "inventory.submit", "inventory.cancel",
                            "goods_receipt.create", "goods_receipt.edit", "goods_receipt.submit", "goods_receipt.cancel",
                            "sales_return.create", "sales_return.edit", "sales_return.submit", "sales_return.cancel",
                            "purchase_return.create", "purchase_return.edit", "purchase_return.submit", "purchase_return.cancel",
                            "payment.create", "payment.edit", "payment.submit", "payment.cancel",
                            "credit.limit.prepare", "credit.override.prepare", "collection.manage", "collection.escalation.prepare",
                            "cash.account.prepare", "bank.statement.import", "bank.reconcile.prepare",
                            "financial_report.read", "posting.execute", "posting.reverse", "enterprise.setup", "enterprise.approve"],
            "allowed_locations": ["*"],
        }]
    else:
        raw_users = []
    by_login: dict[str, ProvisionedUser] = {}
    by_id: dict[int, ProvisionedUser] = {}
    for raw in raw_users:
        roles = tuple(raw.get("roles") or ())
        permissions = set(raw.get("permissions") or ())
        if "operations_administrator" in roles:
            permissions.update({"hrm.read", "hrm.manage", "hrm.lifecycle.prepare"})
            permissions.update({"pos.read", "pos.manage", "pos.sale", "cash.close.prepare"})
            permissions.update({"van.read", "van.route.prepare", "van.shift", "van.sale",
                                "van.return", "van.offline_sync", "van.close.prepare"})
            permissions.update({"crm.read", "crm.lead.prepare", "crm.activity.prepare", "crm.proposal.prepare"})
            permissions.update({"expense.prepare", "expense.submit", "expense.rehearse",
                                "petty_cash.prepare", "petty_cash.manage",
                                "fixed_asset.prepare", "fixed_asset.submit",
                                "fixed_asset.disposal.prepare", "fixed_asset.rehearse",
                                "vat.period.prepare", "vat.period.submit",
                                "vat.adjustment.prepare", "vat.rehearse",
                                "close.prepare", "close.submit", "close.adjustment.prepare", "close.rehearse"})
            permissions.update({"financial_report.prepare", "financial_report.submit", "financial_report.export"})
            permissions.update({"price_list.manage", "discount.approve"})
            permissions.update({"audit_compliance.read", "audit_compliance.prepare",
                                "audit_compliance.submit", "audit_compliance.export"})
            permissions.update({"cutover_rehearsal.read", "cutover_rehearsal.prepare",
                                "cutover_rehearsal.submit", "cutover_rehearsal.export"})
        if {"finance_approver", "independent_approver"}.intersection(roles):
            permissions.update({"expense.approve", "expense.rehearse", "petty_cash.approve",
                                "fixed_asset.approve", "fixed_asset.disposal.approve",
                                "fixed_asset.rehearse", "vat.period.approve",
                                "vat.adjustment.approve", "vat.rehearse",
                                "close.approve", "close.adjustment.approve", "close.rehearse"})
            permissions.update({"financial_report.approve", "financial_report.export"})
            permissions.update({"crm.read", "crm.proposal.approve"})
            permissions.update({"audit_compliance.read", "audit_compliance.approve",
                                "audit_compliance.export"})
            permissions.update({"cutover_rehearsal.read", "cutover_rehearsal.approve",
                                "cutover_rehearsal.export"})
        if "independent_approver" in roles:
            permissions.update({"hrm.read", "hrm.lifecycle.approve"})
            permissions.update({"pos.read", "cash.close.approve"})
            permissions.update({"van.read", "van.shift.approve", "van.stock.approve", "van.close.approve"})
            permissions.update({"crm.read", "crm.proposal.approve"})
        user = ProvisionedUser(
            id=int(raw["id"]), username=str(raw["username"]).strip(),
            password_hash=str(raw["password_hash"]), roles=roles,
            permissions=tuple(sorted(permissions)),
            allowed_locations=tuple(str(value).strip().upper() for value in (raw.get("allowed_locations") or ())),
        )
        if (not user.username or not user.password_hash.startswith("pbkdf2_sha256$")
                or not user.allowed_locations):
            raise RuntimeError("Invalid provisioned Asas user")
        key = user.username.casefold()
        if key in by_login or user.id in by_id:
            raise RuntimeError("Duplicate provisioned Asas user identity")
        by_login[key], by_id[user.id] = user, user
    return by_login, by_id
