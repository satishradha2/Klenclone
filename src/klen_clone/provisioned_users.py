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
                            "financial_report.read", "posting.execute", "posting.reverse"],
            "allowed_locations": ["*"],
        }]
    else:
        raw_users = []
    by_login: dict[str, ProvisionedUser] = {}
    by_id: dict[int, ProvisionedUser] = {}
    for raw in raw_users:
        user = ProvisionedUser(
            id=int(raw["id"]), username=str(raw["username"]).strip(),
            password_hash=str(raw["password_hash"]), roles=tuple(raw.get("roles") or ()),
            permissions=tuple(raw.get("permissions") or ()),
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
