from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx


DECISIONS = {
    "customers": ("conditionally_accepted_for_uat",
                  "Technical row-count package prepared; business owner confirmation remains required."),
    "suppliers": ("conditionally_accepted_for_uat",
                  "Technical row-count package prepared; business owner confirmation remains required."),
    "products": ("conditionally_accepted_for_uat",
                 "Product and UOM package prepared; business owner validation remains required."),
    "sales": ("evidence_requested",
              "Review 120 included discrepancies and control-total differences before UAT acceptance."),
    "purchases": ("evidence_requested",
                  "Review 109 included discrepancies and control-total differences before UAT acceptance."),
    "inventory": ("evidence_requested",
                  "Review 40 included discrepancies and 12 incomplete quantity formula source-evidence rows."),
    "accounting": ("evidence_requested",
                   "Review 126 included discrepancies despite the zero debit-credit blueprint variance."),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic UAT package-review decisions")
    parser.add_argument("index", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:18082")
    parser.add_argument("--username", default="synthetic.uat.reader")
    args = parser.parse_args()
    password = os.getenv("KLEN_UAT_PASSWORD")
    if not password:
        raise SystemExit("KLEN_UAT_PASSWORD is required")
    index = json.loads(args.index.read_text(encoding="utf-8"))
    packages = {item["module"]: item["sha256"] for item in index["packages"]}
    recorded, skipped = [], []
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30) as client:
        login = client.post("/api/v1/auth/login", json={"username": args.username, "password": password})
        login.raise_for_status()
        csrf = login.json()["csrf_token"]
        existing_response = client.get("/api/v1/secure/business-reviews")
        existing_response.raise_for_status()
        existing = {(item["module_code"], item["package_sha256"])
                    for item in existing_response.json()["items"]}
        for module, (decision_code, rationale) in DECISIONS.items():
            digest = packages[module]
            if (module, digest) in existing:
                skipped.append(module)
                continue
            response = client.post(f"/api/v1/uat/business-reviews/{module}", json={
                "package_sha256": digest, "decision_code": decision_code, "rationale": rationale,
            }, headers={"X-CSRF-Token": csrf})
            response.raise_for_status()
            recorded.append(module)
        client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf}).raise_for_status()
    print(json.dumps({"status": "complete", "recorded": recorded, "skipped": skipped,
                      "synthetic_only": True, "production_signoff": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
