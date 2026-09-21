from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CutoverReadinessError(RuntimeError):
    pass


PROTECTED_OUTPUT_NAMES = {
    "klen_staging.db",
    "klen_uat_validation.db",
    "klen_uat_reviews.db",
}

REQUIRED_BASELINE_FILES = {
    "products_all.csv": "product_master",
    "customers_all.csv": "customer_master",
    "suppliers_all.csv": "supplier_master",
    "purchases_2026.csv": "purchases",
    "sales_2026.csv": "sales",
    "pos_sales_2026.csv": "pos_sales",
    "sales_payments_2026.csv": "sales_payments",
    "purchase_payments_2026.csv": "purchase_payments",
    "sales_returns_2026.csv": "sales_returns",
    "purchase_returns_2026.csv": "purchase_returns",
    "stock_snapshot_all_locations.csv": "stock",
    "stock_transfers_2026.csv": "stock_transfers",
    "tax_input_2026.csv": "input_vat",
    "tax_output_2026.csv": "output_vat",
    "trial_balance_2026.xlsx": "trial_balance",
    "users.csv": "users",
    "hrm_attendance_2026.csv": "hrm_attendance",
    "hrm_shifts.csv": "hrm_shifts",
    "hrm_sales_targets.csv": "hrm_sales_targets",
    "configuration_inventories.json": "configuration",
    "business_settings_redacted.json": "configuration",
    "sales_return_details.json": "return_details",
    "purchase_return_details.json": "return_details",
}

REQUIRED_DELTA_FILES = {
    "sales_details.json",
    "master_purchase_details.json",
    "financial_effects.json",
    "stock_report_98081.csv",
    "SHA256SUMS.txt",
}

CUTOVER_EXPORT_FAMILIES = [
    {"family": "masters", "datasets": ["products", "customers", "suppliers", "units", "categories", "brands", "industries", "zones"]},
    {"family": "purchasing", "datasets": ["purchases", "purchase payments", "purchase returns", "purchase-return details"]},
    {"family": "sales", "datasets": ["sales", "POS sales", "sales payments", "sales returns", "sales-return details", "drafts", "quotations", "shipments"]},
    {"family": "inventory", "datasets": ["all-location stock", "stock transfers", "stock-transfer details", "item traceability"]},
    {"family": "finance", "datasets": ["payment accounts", "cash flow", "input VAT", "output VAT", "trial balance", "profit by product"]},
    {"family": "configuration_security", "datasets": ["business settings", "users", "roles and permissions", "CRM configuration"]},
    {"family": "hrm", "datasets": ["employees", "attendance", "shifts", "leave controls", "sales targets"], "target_operational": True, "payroll_included": False},
    {"family": "uploaded_files", "datasets": ["purchase attachments", "sales attachments", "contact documents and notes"], "browser_exportable": False},
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


def _sqlite_one(path: Path, query: str) -> tuple[Any, ...]:
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute(query).fetchone()
    if row is None:
        raise CutoverReadinessError(f"Expected control row missing from {path.name}")
    return row


def build_cutover_readiness(
    baseline_dir: Path,
    delta_dir: Path,
    clone_path: Path,
    delta_database: Path,
    simulation_database: Path,
    output_path: Path,
) -> dict[str, Any]:
    baseline = baseline_dir.resolve()
    delta = delta_dir.resolve()
    clone = clone_path.resolve()
    delta_db = delta_database.resolve()
    simulation_db = simulation_database.resolve()
    output = output_path.resolve()

    for directory in (baseline, delta):
        if not directory.is_dir():
            raise CutoverReadinessError(f"Evidence directory not found: {directory}")
    for database in (clone, delta_db, simulation_db):
        if not database.is_file():
            raise CutoverReadinessError(f"Database not found: {database}")
    if output.exists():
        raise CutoverReadinessError(f"Output already exists; overwrite refused: {output}")
    if output.name.lower() in PROTECTED_OUTPUT_NAMES or output.suffix.lower() != ".json":
        raise CutoverReadinessError("Readiness output must be a new JSON file with a non-protected name")

    baseline_inventory = _inventory(baseline)
    delta_inventory = _inventory(delta)
    baseline_names = {item["relative_path"] for item in baseline_inventory}
    delta_names = {item["relative_path"] for item in delta_inventory}
    missing_baseline = sorted(set(REQUIRED_BASELINE_FILES) - baseline_names)
    missing_delta = sorted(REQUIRED_DELTA_FILES - delta_names)

    clone_hash_before = _sha256(clone)
    delta_hash_before = _sha256(delta_db)
    simulation_hash_before = _sha256(simulation_db)

    delta_failed = int(_sqlite_one(delta_db, "SELECT COUNT(*) FROM validation_result WHERE status='fail'")[0])
    simulation_status, merge_allowed, posting_enabled, source_changed = _sqlite_one(
        simulation_db,
        "SELECT status, merge_allowed, posting_enabled, source_business_tables_changed FROM delta_merge_run",
    )
    simulation_conflicts = int(_sqlite_one(simulation_db, "SELECT COUNT(*) FROM delta_merge_plan WHERE action='conflict'")[0])

    evidence_complete = not missing_baseline and not missing_delta and delta_failed == 0 and simulation_conflicts == 0
    gates = [
        {"gate": "required_baseline_evidence", "status": "pass" if not missing_baseline else "fail", "missing": missing_baseline},
        {"gate": "required_delta_evidence", "status": "pass" if not missing_delta else "fail", "missing": missing_delta},
        {"gate": "delta_validation", "status": "pass" if delta_failed == 0 else "fail", "failed_controls": delta_failed},
        {"gate": "zero_conflict_merge_simulation", "status": "pass" if simulation_status == "passed" and simulation_conflicts == 0 else "fail", "conflicts": simulation_conflicts},
        {"gate": "transaction_free_window", "status": "blocked", "reason": "No source freeze attestation is available from username/password access."},
        {"gate": "fresh_full_cutover_exports", "status": "blocked", "reason": "Current evidence is a baseline plus UI delta, not one frozen full capture."},
        {"gate": "uploaded_file_backup", "status": "blocked", "reason": "The browser UI exposes no complete attachment archive."},
        {"gate": "atomic_source_backup", "status": "blocked", "reason": "No hosting-provider database and uploaded-file backup is available."},
    ]

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_cutover_preflight",
        "source_mutation": False,
        "clone_mutation": False,
        "posting_enabled": False,
        "merge_allowed": False,
        "status": "blocked_pending_frozen_capture",
        "evidence_controls_passed": evidence_complete,
        "inputs": {
            "baseline": str(baseline),
            "delta": str(delta),
            "clone": {"path": str(clone), "sha256": clone_hash_before},
            "validated_delta": {"path": str(delta_db), "sha256": delta_hash_before},
            "merge_simulation": {"path": str(simulation_db), "sha256": simulation_hash_before},
        },
        "inventory": {
            "baseline_file_count": len(baseline_inventory),
            "baseline_total_bytes": sum(item["size_bytes"] for item in baseline_inventory),
            "baseline_extension_counts": dict(sorted(Counter(Path(item["relative_path"]).suffix.lower() for item in baseline_inventory).items())),
            "baseline_files": baseline_inventory,
            "delta_file_count": len(delta_inventory),
            "delta_total_bytes": sum(item["size_bytes"] for item in delta_inventory),
            "delta_files": delta_inventory,
        },
        "cutover_export_families": CUTOVER_EXPORT_FAMILIES,
        "gates": gates,
        "next_action": "Establish a transaction-free window, repeat all browser-exportable families into one timestamped capture, and obtain hosting assistance for uploaded files if possible.",
        "limitations": [
            "Username/password access cannot create an atomic database snapshot.",
            "Browser exports cannot prove completeness for uploaded files that have no exposed download link.",
            "HRM is included in the target ERP and requires a fresh full employee, attendance, shift and leave-control capture; payroll remains excluded.",
        ],
    }

    if _sha256(clone) != clone_hash_before or _sha256(delta_db) != delta_hash_before or _sha256(simulation_db) != simulation_hash_before:
        raise CutoverReadinessError("An input changed during preflight; output refused")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": report["status"],
        "output": str(output),
        "merge_allowed": False,
        "posting_enabled": False,
        "evidence_controls_passed": evidence_complete,
        "baseline_files": len(baseline_inventory),
        "delta_files": len(delta_inventory),
        "passed_gates": sum(item["status"] == "pass" for item in gates),
        "blocked_gates": sum(item["status"] == "blocked" for item in gates),
        "failed_gates": sum(item["status"] == "fail" for item in gates),
    }
