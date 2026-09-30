import json

from klen_clone.auth import hash_password
from klen_clone.provisioned_users import load_provisioned_users


def test_provisioned_preview_roles_separate_refund_maker_and_checker(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "maker", "password_hash": hash_password("maker test password"),
         "roles": ["operations_administrator"], "permissions": ["clone.read"],
         "allowed_locations": ["MAIN"]},
        {"id": 2, "username": "checker", "password_hash": hash_password("checker test password"),
         "roles": ["independent_approver"], "permissions": ["clone.read"],
         "allowed_locations": ["MAIN"]},
    ]}), encoding="utf-8")
    users, _ = load_provisioned_users(str(users_file), "", "")
    maker = set(users["maker"].permissions)
    checker = set(users["checker"].permissions)
    for document in ("customer_price_credit", "customer_refund", "customer_refund_recovery"):
        assert {f"{document}.create", f"{document}.submit", f"{document}.cancel"} <= maker
        assert {f"{document}.approve", f"{document}.rehearse"} <= checker
        assert f"{document}.approve" not in maker
        assert f"{document}.create" not in checker
