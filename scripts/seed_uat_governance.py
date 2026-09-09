from __future__ import annotations

import json
import os

from klen_clone.review_store import UatReviewStore


ASSIGNMENTS = (
    {
        "function_code": "data_owner",
        "display_name": "UAT Data Steward",
        "login_alias": "uat.data.steward",
        "threshold_rule": "All migration exceptions; no automatic approval",
    },
    {
        "function_code": "finance_controller",
        "display_name": "UAT Finance Controller",
        "login_alias": "uat.finance.controller",
        "threshold_rule": "All financial values; no automatic approval",
    },
    {
        "function_code": "inventory_controller",
        "display_name": "UAT Inventory Controller",
        "login_alias": "uat.inventory.controller",
        "threshold_rule": "All opening quantities and values; no automatic approval",
    },
    {
        "function_code": "system_administrator",
        "display_name": "UAT Security Administrator",
        "login_alias": "uat.security.administrator",
        "threshold_rule": "Technical activation check only; cannot approve own access",
    },
)


def main() -> None:
    store = UatReviewStore(os.getenv("KLEN_UAT_REVIEW_DATABASE", "var/klen_uat_reviews.db"))
    existing = store.latest_governance_assignments()
    created = []
    for item in ASSIGNMENTS:
        if item["function_code"] in existing:
            continue
        created.append(store.add_governance_assignment(
            **item, location_codes=["MAIN"], delegation_rule="No delegation; business owner must name a substitute",
            created_by="codex_synthetic_design",
        ))
    print(json.dumps({"status": "seeded", "created": created,
                      "active_assignments": store.latest_governance_assignments(),
                      "production_authority_enabled": False}, indent=2))


if __name__ == "__main__":
    main()
