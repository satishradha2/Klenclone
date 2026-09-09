from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTECTED_DATABASE_NAMES = {
    "klen_staging.db",
    "klen_uat_validation.db",
    "klen_uat_reviews.db",
}
PAYMENT_REFERENCE = re.compile(r"SP2026/\d+")


class MergeSimulationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlanItem:
    entity_type: str
    source_key: str
    action: str
    reason: str
    incoming: Any
    existing: Any = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _rows(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _one_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _table_counts(connection: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    return {table: _one_count(connection, table) for table in tables}


def _create_plan_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE delta_merge_run (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            source_clone_path TEXT NOT NULL,
            source_clone_sha256 TEXT NOT NULL,
            delta_database_path TEXT NOT NULL,
            delta_database_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            merge_allowed INTEGER NOT NULL CHECK (merge_allowed IN (0, 1)),
            posting_enabled INTEGER NOT NULL CHECK (posting_enabled = 0),
            source_business_tables_changed INTEGER NOT NULL CHECK (source_business_tables_changed = 0)
        );
        CREATE TABLE delta_merge_plan (
            id INTEGER PRIMARY KEY,
            entity_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('insert', 'reuse_existing', 'update', 'conflict')),
            reason TEXT NOT NULL,
            incoming_json TEXT NOT NULL,
            existing_json TEXT,
            UNIQUE(entity_type, source_key)
        );
        CREATE TABLE delta_merge_control (
            code TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('pass', 'fail', 'blocked')),
            expected TEXT NOT NULL,
            actual TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        CREATE TABLE delta_merge_projection (
            target_table TEXT PRIMARY KEY,
            before_count INTEGER NOT NULL,
            projected_insert_count INTEGER NOT NULL,
            projected_after_count INTEGER NOT NULL,
            actual_after_simulation_count INTEGER NOT NULL
        );
        """
    )


def _append_identity_plan(
    plan: list[PlanItem], entity: str, key: str, incoming: dict[str, Any],
    existing: list[dict[str, Any]], comparable: tuple[str, ...],
) -> None:
    if not existing:
        plan.append(PlanItem(entity, key, "insert", "Source key is absent from the preserved clone", incoming))
        return
    if len(existing) > 1:
        plan.append(PlanItem(entity, key, "conflict", "Source key resolves to multiple clone rows", incoming, existing))
        return
    row = existing[0]
    equivalent = all(str(row.get(field) or "").strip() == str(incoming.get(field) or "").strip() for field in comparable)
    plan.append(PlanItem(
        entity, key, "reuse_existing" if equivalent else "conflict",
        "Existing row is equivalent" if equivalent else "Existing source key has materially different values",
        incoming, row,
    ))


def simulate_delta_merge(clone_path: Path, delta_path: Path, output_path: Path) -> dict[str, Any]:
    clone = clone_path.resolve()
    delta = delta_path.resolve()
    output = output_path.resolve()
    if not clone.is_file():
        raise MergeSimulationError(f"Clone database not found: {clone}")
    if not delta.is_file():
        raise MergeSimulationError(f"Delta database not found: {delta}")
    if output.name.lower() in PROTECTED_DATABASE_NAMES:
        raise MergeSimulationError(f"Protected database name refused: {output.name}")
    if output.exists():
        raise MergeSimulationError(f"Output already exists; overwrite refused: {output}")
    if output in {clone, delta}:
        raise MergeSimulationError("Output must be separate from clone and delta databases")
    if output.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise MergeSimulationError("Simulation output must be a SQLite database file")

    clone_hash_before = _sha256(clone)
    delta_hash_before = _sha256(delta)
    output.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(f"file:{clone.as_posix()}?mode=ro", uri=True)
    source.execute("PRAGMA query_only=ON")
    target = sqlite3.connect(output)
    try:
        source.backup(target)
    except Exception:
        target.close()
        source.close()
        output.unlink(missing_ok=True)
        raise
    finally:
        if source:
            source.close()

    delta_connection = sqlite3.connect(f"file:{delta.as_posix()}?mode=ro", uri=True)
    delta_connection.execute("PRAGMA query_only=ON")
    try:
        failed_delta_checks = _rows(delta_connection, "SELECT code FROM validation_result WHERE status <> 'pass'")
        delta_meta = dict(delta_connection.execute("SELECT key, value FROM dry_run_meta").fetchall())
        if failed_delta_checks or delta_meta.get("posting_enabled") != "false" or delta_meta.get("promotion_allowed") != "false":
            raise MergeSimulationError("Delta validation database is not safe for merge simulation")

        original_tables = [row[0] for row in target.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        before_counts = _table_counts(target, original_tables)
        plan: list[PlanItem] = []

        customer = _rows(delta_connection, "SELECT contact_id, business_name, raw_json FROM delta_customer")[0]
        _append_identity_plan(
            plan, "customer", customer["contact_id"],
            {"contact_id": customer["contact_id"], "business_name": customer["business_name"]},
            _rows(target, "SELECT contact_id, business_name FROM stg_contacts WHERE contact_id=?", (customer["contact_id"],)),
            ("contact_id", "business_name"),
        )

        product = _rows(delta_connection, "SELECT sku, name, purchase_price, selling_price, current_stock, stock_unit FROM delta_product")[0]
        _append_identity_plan(
            plan, "product", product["sku"], product,
            _rows(target, "SELECT sku, name, purchase_price, selling_price, current_stock, stock_unit FROM stg_products WHERE sku=?", (product["sku"],)),
            ("sku", "name"),
        )

        purchase = _rows(delta_connection, "SELECT document_no, supplier_reference, supplier_name, total_amount, payment_status FROM delta_purchase")[0]
        _append_identity_plan(
            plan, "purchase", purchase["document_no"], purchase,
            _rows(target, "SELECT document_no, supplier_reference, supplier_name, total_amount, payment_status FROM stg_purchases WHERE document_no=?", (purchase["document_no"],)),
            ("document_no", "supplier_reference", "total_amount"),
        )
        purchase_lines = _rows(target, "SELECT document_no, sku, product_name, quantity, unit, subtotal FROM stg_purchase_lines WHERE document_no=? AND sku=?", (purchase["document_no"], product["sku"]))
        plan.append(PlanItem(
            "purchase_line", f"{purchase['document_no']}#1", "reuse_existing" if purchase_lines else "insert",
            "Matching purchase line already exists" if purchase_lines else "Purchase line is absent from the preserved clone",
            {"document_no": purchase["document_no"], "sku": product["sku"], "quantity": "1.00", "unit": "Carton", "subtotal": "61.90"},
            purchase_lines or None,
        ))

        delta_sales = _rows(delta_connection, "SELECT invoice, transaction_at, payment_status, total_payable, total_paid, total_remaining FROM delta_sale ORDER BY invoice")
        for sale in delta_sales:
            _append_identity_plan(
                plan, "sale", sale["invoice"], sale,
                _rows(target, "SELECT document_no AS invoice, transaction_at, payment_status, total_amount AS total_payable, total_paid, amount_due AS total_remaining FROM stg_sales WHERE document_no=?", (sale["invoice"],)),
                ("invoice", "total_payable", "total_paid", "total_remaining"),
            )

        delta_lines = _rows(delta_connection, "SELECT invoice, line_no, raw_text FROM delta_sale_line_evidence ORDER BY invoice, line_no")
        existing_by_invoice: dict[str, list[dict[str, Any]]] = {}
        matched_existing: set[int] = set()
        for line in delta_lines:
            existing = existing_by_invoice.setdefault(
                line["invoice"],
                _rows(target, "SELECT id, document_no, sku, product_name, quantity, unit, total FROM stg_sale_lines WHERE document_no=? ORDER BY id", (line["invoice"],)),
            )
            match = next((row for row in existing if row["id"] not in matched_existing and f" {row['sku']} " in line["raw_text"] and row["product_name"] in line["raw_text"]), None)
            if match:
                matched_existing.add(match["id"])
            plan.append(PlanItem(
                "sale_line", f"{line['invoice']}#{line['line_no']}", "reuse_existing" if match else "insert",
                "Equivalent later-captured line already exists" if match else "Sale line is absent from the preserved clone",
                line, match,
            ))

        payments = _rows(delta_connection, "SELECT reference_no, paid_on, amount, parent_sale FROM delta_sales_payment ORDER BY reference_no")
        for payment in payments:
            _append_identity_plan(
                plan, "sales_payment", payment["reference_no"], payment,
                _rows(target, "SELECT reference_no, paid_at AS paid_on, amount, parent_document_no AS parent_sale FROM stg_payments WHERE direction='sale' AND reference_no=?", (payment["reference_no"],)),
                ("reference_no", "amount", "parent_sale"),
            )

        vat_rows = _rows(delta_connection, "SELECT invoice_no, transaction_at, net_amount, gross_amount, vat_amount FROM delta_output_vat ORDER BY invoice_no")
        for vat in vat_rows:
            _append_identity_plan(
                plan, "output_vat", vat["invoice_no"], vat,
                _rows(target, "SELECT document_no AS invoice_no, transaction_at, amount_ex_tax AS net_amount, amount_with_tax AS gross_amount, vat_amount FROM stg_tax_evidence WHERE direction='output' AND document_no=?", (vat["invoice_no"],)),
                ("invoice_no", "net_amount", "gross_amount", "vat_amount"),
            )

        cash_rows = _rows(delta_connection, "SELECT payment_reference, transaction_at, account_name, debit, credit, account_balance, total_balance FROM delta_cash_flow ORDER BY payment_reference")
        for cash in cash_rows:
            _append_identity_plan(
                plan, "cash_flow", cash["payment_reference"], cash,
                _rows(target, "SELECT payment_reference, transaction_at, account_name, debit, credit, account_balance, total_balance FROM stg_cash_flow_entries WHERE payment_reference=?", (cash["payment_reference"],)),
                ("payment_reference", "debit", "credit"),
            )

        transfer_key = "ST2026/0927"
        transfer_header = _rows(target, "SELECT document_no, location_from, location_to, status, total_amount FROM stg_stock_transfers WHERE document_no=?", (transfer_key,))
        plan.append(PlanItem(
            "stock_transfer", transfer_key, "reuse_existing" if transfer_header else "insert",
            "Transfer header already exists" if transfer_header else "Header is absent although its detail evidence is preserved",
            {"document_no": transfer_key, "from": "Asas General Trading LLC", "to": "DXB", "status": "Completed", "total_amount": "61.90"},
            transfer_header or None,
        ))
        transfer_lines = _rows(target, "SELECT parent_document_no, sku, product_name, quantity, unit FROM stg_document_lines WHERE parent_document_no=? AND sku=?", (transfer_key, product["sku"]))
        plan.append(PlanItem(
            "stock_transfer_line", f"{transfer_key}#1", "reuse_existing" if len(transfer_lines) == 1 else "conflict",
            "Single equivalent transfer-detail line is already preserved" if len(transfer_lines) == 1 else "Expected exactly one preserved transfer-detail line",
            {"document_no": transfer_key, "sku": product["sku"], "quantity": "1.00", "unit": "Carton"},
            transfer_lines or None,
        ))

        stock_evidence = _rows(
            delta_connection,
            "SELECT sku, location, product_name, unit, available_quantity, total_transferred, purchase_value, sale_value FROM delta_stock_balance WHERE sku=? ORDER BY location",
            (product["sku"],),
        )
        stock_evidence_valid = (
            len(stock_evidence) == 2
            and {row["location"] for row in stock_evidence} == {"Asas General Trading LLC", "DXB"}
            and sum(float(row["available_quantity"]) for row in stock_evidence) == float(product["current_stock"])
        )
        if not stock_evidence_valid:
            plan.append(PlanItem(
                "stock_balance_evidence", f"{product['sku']}@locations", "conflict",
                "Validated delta lacks complete location-wise stock evidence",
                stock_evidence,
            ))
        for evidence in stock_evidence:
            location = evidence["location"]
            stock = _rows(target, "SELECT sku, product_name, location, available_quantity, unit FROM stg_stock_balances WHERE sku=? AND location=?", (product["sku"], location))
            plan.append(PlanItem(
                "stock_balance_location", f"{product['sku']}@{location}", "reuse_existing" if stock else "insert",
                "Location stock already exists" if stock else "Location stock row is absent from the preserved clone",
                evidence,
                stock or None,
            ))
        unlocated_stock = _rows(target, "SELECT id, sku, product_name, location, available_quantity, unit FROM stg_stock_balances WHERE sku=? AND (location IS NULL OR TRIM(location)='')", (product["sku"],))
        if unlocated_stock:
            zero_only = all(float(row["available_quantity"] or 0) == 0 for row in unlocated_stock)
            plan.append(PlanItem(
                "stock_balance_legacy_evidence", f"{product['sku']}@<unlocated>", "reuse_existing" if stock_evidence_valid and zero_only else "conflict",
                "Preserve the earlier zero-quantity unlocated row as legacy evidence; authoritative location rows reconcile the current total" if stock_evidence_valid and zero_only else "Unlocated stock cannot be reconciled safely",
                {"authoritative_locations": stock_evidence, "retention": "preserve_without_posting"}, unlocated_stock,
            ))

        actions = Counter(item.action for item in plan)
        expected_actions = {"insert": 82, "reuse_existing": 13, "update": 0, "conflict": 0}
        plan_shape_ok = all(actions.get(action, 0) == count for action, count in expected_actions.items())

        _create_plan_schema(target)
        target.executemany(
            "INSERT INTO delta_merge_plan(entity_type, source_key, action, reason, incoming_json, existing_json) VALUES (?, ?, ?, ?, ?, ?)",
            [(item.entity_type, item.source_key, item.action, item.reason, _json(item.incoming), _json(item.existing) if item.existing is not None else None) for item in plan],
        )

        insert_targets = {
            "customer": "stg_contacts",
            "product": "stg_products",
            "purchase": "stg_purchases",
            "purchase_line": "stg_purchase_lines",
            "sale": "stg_sales",
            "sale_line": "stg_sale_lines",
            "sales_payment": "stg_payments",
            "output_vat": "stg_tax_evidence",
            "cash_flow": "stg_cash_flow_entries",
            "stock_transfer": "stg_stock_transfers",
            "stock_balance_location": "stg_stock_balances",
        }
        projected = Counter(insert_targets[item.entity_type] for item in plan if item.action == "insert")
        after_counts = _table_counts(target, original_tables)
        business_unchanged = before_counts == after_counts
        for table, increment in sorted(projected.items()):
            target.execute(
                "INSERT INTO delta_merge_projection VALUES (?, ?, ?, ?, ?)",
                (table, before_counts[table], increment, before_counts[table] + increment, after_counts[table]),
            )

        controls = [
            ("DELTA_VALIDATED", "pass", "zero failed delta checks", "zero failed delta checks", {"delta_meta": delta_meta}),
            ("PLAN_ACTION_COUNTS", "pass" if plan_shape_ok else "fail", _json(expected_actions), _json(dict(actions)), {}),
            ("BUSINESS_TABLES_UNCHANGED", "pass" if business_unchanged else "fail", "all original row counts unchanged", "unchanged" if business_unchanged else "changed", {"before": before_counts, "after": after_counts}),
            ("STOCK_LOCATION_RECONCILED", "pass" if stock_evidence_valid and not actions.get("conflict", 0) else "fail", "two authoritative location rows and zero unresolved conflicts", f"{len(stock_evidence)} location rows / {actions.get('conflict', 0)} conflicts", {"legacy_unlocated_rows_preserved": len(unlocated_stock)}),
            ("POSTING_DISABLED", "pass", "false", "false", {}),
        ]
        target.executemany(
            "INSERT INTO delta_merge_control VALUES (?, ?, ?, ?, ?)",
            [(code, status, expected, actual, _json(details)) for code, status, expected, actual, details in controls],
        )
        status = "passed" if plan_shape_ok and business_unchanged and not actions.get("conflict", 0) else "failed"
        target.execute(
            "INSERT INTO delta_merge_run VALUES (1, ?, ?, ?, ?, ?, 0, 0, 0)",
            (str(clone), clone_hash_before, str(delta), delta_hash_before, status),
        )
        target.commit()
    except Exception:
        target.rollback()
        target.close()
        delta_connection.close()
        output.unlink(missing_ok=True)
        raise
    finally:
        delta_connection.close()
        if output.exists():
            target.close()

    clone_hash_after = _sha256(clone)
    delta_hash_after = _sha256(delta)
    if clone_hash_after != clone_hash_before or delta_hash_after != delta_hash_before:
        output.unlink(missing_ok=True)
        raise MergeSimulationError("Source database changed during simulation")

    return {
        "status": status,
        "database": str(output),
        "merge_allowed": False,
        "posting_enabled": False,
        "source_clone_unchanged": True,
        "delta_database_unchanged": True,
        "plan_rows": len(plan),
        "actions": {action: actions.get(action, 0) for action in ("insert", "reuse_existing", "update", "conflict")},
        "projected_inserts": dict(sorted(projected.items())),
        "blockers": [],
    }
