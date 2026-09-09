from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
import sys
from zipfile import ZipFile

import httpx


BASE_URL = os.getenv("KLEN_UAT_BASE_URL", "http://127.0.0.1:18082").rstrip("/")
USERNAME = os.getenv("KLEN_UAT_USERNAME", "synthetic.uat.reader")
PASSWORD = os.getenv("KLEN_UAT_PASSWORD")
FORBIDDEN_FIELDS = {"email", "mobile", "address", "tax_number", "payload", "evidence", "password_hash"}
ENDPOINTS = {
    "customers": "/api/v1/secure/parties",
    "suppliers": "/api/v1/secure/suppliers",
    "products": "/api/v1/secure/products",
    "sales": "/api/v1/secure/sales",
    "purchases": "/api/v1/secure/purchases",
    "inventory": "/api/v1/secure/inventory",
    "accounting": "/api/v1/secure/accounting-summary",
    "workflows": "/api/v1/secure/workflows",
    "discrepancies": "/api/v1/secure/discrepancies",
    "governance": "/api/v1/secure/approval-governance",
    "segregation": "/api/v1/secure/segregation-controls",
}
SEARCH_KEYS = {
    "customers": "party_code",
    "suppliers": "party_code",
    "products": "sku",
    "sales": "document_no",
    "purchases": "document_no",
}
DETAIL_MODULES = {"customers", "suppliers", "products", "sales", "purchases", "inventory"}


def check(condition: bool, code: str, results: list[dict], detail: str) -> None:
    results.append({"check": code, "status": "passed" if condition else "failed", "detail": detail})


def all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(item) for item in value)) if value else set()
    return set()


def main() -> int:
    if not PASSWORD:
        print("KLEN_UAT_PASSWORD is required", file=sys.stderr)
        return 2
    results: list[dict] = []
    module_results: dict[str, dict] = {}
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        unauthenticated = client.get(ENDPOINTS["customers"])
        check(unauthenticated.status_code == 401, "AUTH-001", results,
              f"Unauthenticated protected request returned {unauthenticated.status_code}")
        unauthenticated_export = client.get("/api/v1/secure/exports/customers")
        check(unauthenticated_export.status_code == 401, "EXPORT-AUTH-001", results,
              f"Unauthenticated export request returned {unauthenticated_export.status_code}")

        login = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        check(login.status_code == 200, "AUTH-002", results, f"Synthetic sign-in returned {login.status_code}")
        if login.status_code != 200:
            print(json.dumps({"status": "failed", "checks": results}, indent=2))
            return 1
        authentication = login.json()
        principal = authentication["principal"]
        location_ids = {item["id"] for item in principal["locations"]}
        check(principal.get("synthetic_uat") is True, "AUTH-003", results,
              "Authenticated principal is explicitly synthetic")
        check(bool(location_ids), "SCOPE-001", results,
              f"Active location IDs: {sorted(location_ids)}")

        for module, path in ENDPOINTS.items():
            response = client.get(path, params={"limit": 25, "offset": 0} if module != "accounting" else None)
            payload = response.json()
            items = payload.get("items", [])
            module_results[module] = {
                "http_status": response.status_code,
                "total": payload.get("total"),
                "returned_rows": len(items),
            }
            check(response.status_code == 200, f"MODULE-{module.upper()}-001", results,
                  f"Protected {module} endpoint returned {response.status_code}")
            forbidden = FORBIDDEN_FIELDS - ({"evidence"} if module == "discrepancies" else set())
            check(not (all_keys(payload) & forbidden), f"REDACT-{module.upper()}-001", results,
                  f"Forbidden fields absent: {sorted(forbidden)}")
            if items:
                check(len(items) <= 25, f"PAGE-{module.upper()}-001", results,
                      f"Returned {len(items)} rows with page limit 25")
            if module in {"sales", "purchases", "inventory"}:
                scoped = all(item.get("location_id") in location_ids for item in items)
                check(scoped, f"SCOPE-{module.upper()}-001", results,
                      "Every returned location is within the principal scope")
                check(payload.get("posting_enabled") is False, f"WRITE-{module.upper()}-001", results,
                      "Endpoint reports posting disabled")
            if module == "governance":
                aliases = {item.get("draft_login_alias") for item in items}
                check(payload.get("synthetic_draft_assignments") == 4,
                      "GOVERNANCE-SYNTHETIC-001", results,
                      "Exactly four synthetic draft approver functions are recorded")
                check(aliases == {
                    "uat.data.steward",
                    "uat.finance.controller",
                    "uat.inventory.controller",
                    "uat.security.administrator",
                }, "GOVERNANCE-SYNTHETIC-002", results,
                      "Every approval step maps to one of the four controlled UAT aliases")
                check(all(item.get("draft_locations") == "MAIN" and
                          item.get("synthetic_assignment_status") == "draft_synthetic"
                          for item in items),
                      "GOVERNANCE-SYNTHETIC-003", results,
                      "All synthetic assignments are draft-only and restricted to MAIN")
                check(payload.get("real_user_bindings") == 0 and
                      payload.get("assignment_enabled") is False and
                      payload.get("approval_actions_enabled") is False,
                      "GOVERNANCE-DISABLED-001", results,
                      "No real binding, assignment activation, or approval action is enabled")
            if module in SEARCH_KEYS and items:
                key = SEARCH_KEYS[module]
                needle = str(items[0][key])
                searched = client.get(path, params={"limit": 25, "offset": 0, "q": needle})
                searched_items = searched.json().get("items", [])
                check(searched.status_code == 200 and searched_items and all(
                    needle.casefold() in str(item[key]).casefold() for item in searched_items),
                    f"SEARCH-{module.upper()}-001", results, f"Search matched {key}={needle}")
            if module in DETAIL_MODULES and items:
                detail = client.get(f"{path}/{items[0]['id']}")
                detail_payload = detail.json()
                check(detail.status_code == 200, f"DETAIL-{module.upper()}-001", results,
                      f"Protected detail returned {detail.status_code}")
                check(not (all_keys(detail_payload) & FORBIDDEN_FIELDS),
                      f"DETAIL-REDACT-{module.upper()}-001", results,
                      "Protected detail excludes confidential evidence fields")
                if module in {"sales", "purchases", "inventory"}:
                    record = detail_payload.get("document") or detail_payload.get("movement") or {}
                    check(record.get("location_id") in location_ids,
                          f"DETAIL-SCOPE-{module.upper()}-001", results,
                          "Detail record remains inside active location scope")

        catalog = client.get("/api/v1/secure/export-catalog")
        catalog_items = catalog.json().get("items", []) if catalog.status_code == 200 else []
        check(catalog.status_code == 200 and len(catalog_items) == 7,
              "EXPORT-CATALOG-001", results,
              f"Protected catalog exposed {len(catalog_items)} controlled module packages")
        for item in catalog_items:
            module = item["module"]
            package = client.get(item["package_path"])
            archive_names: set[str] = set()
            manifest = {}
            if package.status_code == 200:
                with ZipFile(BytesIO(package.content)) as archive:
                    archive_names = set(archive.namelist())
                    manifest = json.loads(archive.read("manifest.json"))
            valid = (package.status_code == 200 and
                     package.headers.get("x-content-sha256") == hashlib.sha256(package.content).hexdigest() and
                     {"manifest.json", "reconciliation.json", "REVIEW_INSTRUCTIONS.txt"}.issubset(archive_names) and
                     manifest.get("module") == module and
                     manifest.get("sensitive_fields_redacted") is True and
                     manifest.get("source_or_clone_mutated") is False)
            check(valid, f"EXPORT-{module.upper()}-001", results,
                  f"{module} package is checksummed, redacted, scoped, and read-only")
        business_reviews = client.get("/api/v1/secure/business-reviews")
        review_payload = business_reviews.json() if business_reviews.status_code == 200 else {}
        check(business_reviews.status_code == 200 and
              review_payload.get("production_signoff_enabled") is False and
              review_payload.get("source_mutation_enabled") is False,
              "BUSINESS-REVIEW-001", results,
              "Business review register is protected, synthetic-only, and cannot sign off production")

        mutation = client.post("/api/v1/summary", json={})
        check(mutation.status_code == 405, "WRITE-ALL-001", results,
              f"Business POST returned {mutation.status_code}")
        reset = client.post("/api/v1/auth/reset-request", json={"username": USERNAME})
        check(reset.status_code == 200 and reset.json().get("delivery_performed") is False,
              "AUTH-RESET-001", results, "Password reset remained a no-change dry run")
        bad_logout = client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": "invalid"})
        check(bad_logout.status_code == 403, "AUTH-CSRF-001", results,
              f"Logout with invalid CSRF token returned {bad_logout.status_code}")
        logout = client.post("/api/v1/auth/logout", json={}, headers={
            "X-CSRF-Token": authentication["csrf_token"]})
        check(logout.status_code == 200, "AUTH-LOGOUT-001", results,
              f"Logout returned {logout.status_code}")
        after_logout = client.get(ENDPOINTS["customers"])
        check(after_logout.status_code == 401, "AUTH-LOGOUT-002", results,
              f"Revoked session returned {after_logout.status_code} on protected access")

        second_login = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        check(second_login.status_code == 200, "AUTH-RESET-002", results,
              "Original synthetic password still works after reset dry run")
        if second_login.status_code == 200:
            client.post("/api/v1/auth/logout", json={}, headers={
                "X-CSRF-Token": second_login.json()["csrf_token"]})

    failed = [item for item in results if item["status"] == "failed"]
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "principal": USERNAME,
        "status": "failed" if failed else "passed",
        "passed_checks": len(results) - len(failed),
        "failed_checks": len(failed),
        "modules": module_results,
        "checks": results,
    }
    print(json.dumps(report, indent=2, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
