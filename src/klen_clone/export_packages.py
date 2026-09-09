from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from io import BytesIO, StringIO
import json
import re
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ErpInventoryMovement,
    ErpJournalBlueprint,
    ErpLocation,
    ErpMigrationExceptionQueue,
    ErpParty,
    ErpProductMaster,
    ErpProductUom,
    ErpTransactionDocument,
    ErpTransactionLine,
    ErpTransactionPayment,
    SourceSnapshot,
)


EXPORT_MODULES = {
    "customers": "customer.view",
    "suppliers": "supplier.view",
    "products": "product.view",
    "sales": "sell.view",
    "purchases": "purchase.view",
    "inventory": "stock_report.view",
    "accounting": "accounting.view_reports",
}
SENSITIVE_FIELDS_EXCLUDED = (
    "address", "email", "evidence", "mobile", "password_hash", "payload",
    "source_raw_record_id", "tax_number",
)
EXCEPTION_KINDS = {
    "customers": (),
    "suppliers": (),
    "products": (),
    "sales": ("sale_line", "document_line", "payment", "reconciliation_exception"),
    "purchases": ("document_line", "payment", "reconciliation_exception"),
    "inventory": ("inventory_movement",),
    "accounting": ("financial_allocation", "payment", "reconciliation_exception"),
}


def _plain(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _csv_safe(value) -> str:
    rendered = _plain(value)
    if isinstance(value, str) and rendered.startswith(("=", "+", "-", "@")):
        return "'" + rendered
    return rendered


def _csv_bytes(rows: list[dict]) -> bytes:
    fields = list(rows[0]) if rows else ["no_rows"]
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_safe(row.get(field)) for field in fields})
    return output.getvalue().encode("utf-8-sig")


def _mapped(session: Session, statement) -> list[dict]:
    return [dict(row) for row in session.execute(statement).mappings().all()]


def _sum(rows: list[dict], field: str) -> str:
    total = sum((Decimal(str(row[field])) for row in rows if row.get(field) is not None), Decimal("0"))
    return format(total, "f")


def _status_counts(rows: list[dict]) -> dict[str, dict[str, int]]:
    candidates = ("master_status", "migration_status", "relation_status", "conversion_status")
    return {field: dict(sorted(Counter(str(row[field]) for row in rows if row.get(field)).items()))
            for field in candidates if any(row.get(field) for row in rows)}


def _datasets(session: Session, snapshot: SourceSnapshot, module: str,
              location_ids: list[int]) -> dict[str, list[dict]]:
    sid = snapshot.id
    if module in {"customers", "suppliers"}:
        kinds = ("customer", "both") if module == "customers" else ("supplier", "both")
        rows = _mapped(session, select(
            ErpParty.id, ErpParty.party_code, ErpParty.party_kind,
            ErpParty.legal_or_business_name, ErpParty.contact_name, ErpParty.master_status,
        ).where(ErpParty.snapshot_id == sid, ErpParty.party_kind.in_(kinds)).order_by(ErpParty.id))
        return {module: rows}
    if module == "products":
        products = _mapped(session, select(
            ErpProductMaster.id, ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.product_type, ErpProductMaster.category_name,
            ErpProductMaster.brand_name, ErpProductMaster.master_status,
        ).where(ErpProductMaster.snapshot_id == sid).order_by(ErpProductMaster.id))
        uoms = _mapped(session, select(
            ErpProductUom.id, ErpProductUom.product_id, ErpProductUom.source_base_uom,
            ErpProductUom.canonical_base_uom, ErpProductUom.factor_to_base_snapshot,
            ErpProductUom.conversion_status,
        ).where(ErpProductUom.snapshot_id == sid).order_by(ErpProductUom.product_id, ErpProductUom.id))
        return {"products": products, "product_uoms": uoms}
    if module in {"sales", "purchases"}:
        kinds = (("sale", "sell", "sell_return") if module == "sales"
                 else ("purchase", "purchase_return"))
        documents = _mapped(session, select(
            ErpTransactionDocument.id, ErpTransactionDocument.source_kind,
            ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
            ErpTransactionDocument.party_id, ErpTransactionDocument.location_id,
            ErpTransactionDocument.parent_document_id, ErpTransactionDocument.total_amount,
            ErpTransactionDocument.paid_amount, ErpTransactionDocument.due_amount,
            ErpTransactionDocument.return_due_amount, ErpTransactionDocument.source_status,
            ErpTransactionDocument.migration_status,
        ).where(ErpTransactionDocument.snapshot_id == sid,
                ErpTransactionDocument.location_id.in_(location_ids),
                ErpTransactionDocument.source_kind.in_(kinds)).order_by(ErpTransactionDocument.id))
        document_ids = [row["id"] for row in documents]
        lines = _mapped(session, select(
            ErpTransactionLine.id, ErpTransactionLine.document_id,
            ErpTransactionLine.source_line_no, ErpTransactionLine.product_id,
            ErpTransactionLine.entered_quantity, ErpTransactionLine.entered_uom,
            ErpTransactionLine.unit_price, ErpTransactionLine.subtotal,
            ErpTransactionLine.relation_status,
        ).where(ErpTransactionLine.snapshot_id == sid,
                ErpTransactionLine.document_id.in_(document_ids)).order_by(
                    ErpTransactionLine.document_id, ErpTransactionLine.source_line_no,
                    ErpTransactionLine.id)) if document_ids else []
        payments = _mapped(session, select(
            ErpTransactionPayment.id, ErpTransactionPayment.document_id,
            ErpTransactionPayment.reference_no, ErpTransactionPayment.paid_at,
            ErpTransactionPayment.method, ErpTransactionPayment.amount,
            ErpTransactionPayment.relation_status,
        ).where(ErpTransactionPayment.snapshot_id == sid,
                ErpTransactionPayment.document_id.in_(document_ids)).order_by(
                    ErpTransactionPayment.document_id, ErpTransactionPayment.id)) if document_ids else []
        return {"documents": documents, "lines": lines, "payments": payments}
    if module == "inventory":
        rows = _mapped(session, select(
            ErpInventoryMovement.id, ErpInventoryMovement.movement_type,
            ErpInventoryMovement.occurred_at, ErpInventoryMovement.location_id,
            ErpLocation.code.label("location_code"), ErpInventoryMovement.product_id,
            ErpProductMaster.sku, ErpInventoryMovement.document_id,
            ErpTransactionDocument.document_no, ErpInventoryMovement.entered_quantity,
            ErpInventoryMovement.entered_uom, ErpInventoryMovement.factor_to_base_snapshot,
            ErpInventoryMovement.quantity_base, ErpInventoryMovement.canonical_uom,
            ErpInventoryMovement.source_posting_status, ErpInventoryMovement.migration_status,
        ).outerjoin(ErpLocation, ErpLocation.id == ErpInventoryMovement.location_id).outerjoin(
            ErpProductMaster, ErpProductMaster.id == ErpInventoryMovement.product_id).outerjoin(
            ErpTransactionDocument, ErpTransactionDocument.id == ErpInventoryMovement.document_id).where(
            ErpInventoryMovement.snapshot_id == sid,
            ErpInventoryMovement.location_id.in_(location_ids)).order_by(ErpInventoryMovement.id))
        return {"inventory_movements": rows}
    journals = _mapped(session, select(
        ErpJournalBlueprint.id, ErpJournalBlueprint.source_kind,
        ErpJournalBlueprint.source_key, ErpJournalBlueprint.document_no,
        ErpJournalBlueprint.occurred_at, ErpJournalBlueprint.description,
        ErpJournalBlueprint.debit_total, ErpJournalBlueprint.credit_total,
        ErpJournalBlueprint.migration_status,
    ).where(ErpJournalBlueprint.snapshot_id == sid).order_by(ErpJournalBlueprint.id))
    return {"journal_blueprints": journals}


def _reconciliation(module: str, datasets: dict[str, list[dict]]) -> dict:
    result = {
        "module": module,
        "dataset_row_counts": {name: len(rows) for name, rows in datasets.items()},
        "status_counts": {name: _status_counts(rows) for name, rows in datasets.items()},
        "control_totals": {},
        "posting_enabled": False,
    }
    controls = result["control_totals"]
    if "documents" in datasets:
        rows = datasets["documents"]
        controls["documents"] = {field: _sum(rows, field) for field in
                                 ("total_amount", "paid_amount", "due_amount", "return_due_amount")}
        controls["lines"] = {"subtotal": _sum(datasets["lines"], "subtotal")}
        controls["payments"] = {"amount": _sum(datasets["payments"], "amount")}
    if "inventory_movements" in datasets:
        rows = datasets["inventory_movements"]
        outbound_types = {"sale_issue", "purchase_return_issue", "transfer_out"}
        complete_rows = [row for row in rows if row.get("entered_quantity") is not None and
                         row.get("factor_to_base_snapshot") is not None and
                         row.get("quantity_base") is not None]
        controls["inventory_movements"] = {
            "entered_quantity": _sum(rows, "entered_quantity"),
            "quantity_base": _sum(rows, "quantity_base"),
            "quantity_formula_mismatches": sum(
                1 for row in complete_rows if
                abs(Decimal(str(row["quantity_base"])) -
                    Decimal(str(row["entered_quantity"])) *
                    Decimal(str(row["factor_to_base_snapshot"])) *
                    (Decimal("-1") if row["movement_type"] in outbound_types else Decimal("1"))) >
                Decimal("0.000001")),
            "quantity_formula_incomplete_rows": len(rows) - len(complete_rows),
            "formula_rule": "quantity_base = entered_quantity * factor_to_base_snapshot * movement_sign",
            "outbound_negative_types": sorted(outbound_types),
        }
    if "journal_blueprints" in datasets:
        rows = datasets["journal_blueprints"]
        debit, credit = Decimal(_sum(rows, "debit_total")), Decimal(_sum(rows, "credit_total"))
        controls["journal_blueprints"] = {
            "debit_total": format(debit, "f"), "credit_total": format(credit, "f"),
            "debit_credit_variance": format(debit - credit, "f"),
        }
    return result


def build_review_package(session: Session, snapshot: SourceSnapshot, module: str,
                         location_ids: list[int], location_codes: list[str],
                         generated_by: str) -> dict:
    if module not in EXPORT_MODULES:
        raise ValueError(f"Unsupported export module: {module}")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    datasets = _datasets(session, snapshot, module, location_ids)
    exception_kinds = EXCEPTION_KINDS[module]
    exceptions = (_mapped(session, select(
        ErpMigrationExceptionQueue.id, ErpMigrationExceptionQueue.source_kind,
        ErpMigrationExceptionQueue.source_id, ErpMigrationExceptionQueue.exception_code,
        ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status,
        ErpMigrationExceptionQueue.activation_blocked,
    ).where(ErpMigrationExceptionQueue.snapshot_id == snapshot.id,
            ErpMigrationExceptionQueue.source_kind.in_(exception_kinds)).order_by(
                ErpMigrationExceptionQueue.id)) if exception_kinds else [])
    datasets["open_discrepancies"] = exceptions
    files = {f"data/{name}.csv": _csv_bytes(rows) for name, rows in datasets.items()}
    reconciliation = _reconciliation(module, datasets)
    reconciliation["discrepancy_count"] = len(exceptions)
    reconciliation_bytes = json.dumps(reconciliation, indent=2, sort_keys=True).encode("utf-8")
    files["reconciliation.json"] = reconciliation_bytes
    manifest = {
        "schema_version": 1,
        "package_type": "permission_protected_business_review",
        "module": module,
        "snapshot": snapshot.name,
        "generated_at": generated_at,
        "generated_by": generated_by,
        "required_permission": EXPORT_MODULES[module],
        "location_scope": {"ids": sorted(location_ids), "codes": sorted(location_codes)},
        "row_location_filter_applicable": module in {"sales", "purchases", "inventory"},
        "sensitive_fields_redacted": True,
        "excluded_fields": list(SENSITIVE_FIELDS_EXCLUDED),
        "posting_enabled": False,
        "approval_performed": False,
        "source_or_clone_mutated": False,
        "files": {name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                  for name, content in sorted(files.items())},
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    files["manifest.json"] = manifest_bytes
    review_note = (
        f"Klen ERP {module.title()} Business Review Package\n\n"
        f"Snapshot: {snapshot.name}\nGenerated: {generated_at}\n"
        f"Requested by: {generated_by}\nLocation scope: {', '.join(sorted(location_codes))}\n\n"
        "Review the row counts, control totals, status breakdowns, and open discrepancies.\n"
        "This package is read-only evidence. It does not authorize posting, approvals, or source changes.\n"
    ).encode("utf-8")
    files["REVIEW_INSTRUCTIONS.txt"] = review_note
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    content = output.getvalue()
    safe_snapshot = re.sub(r"[^A-Za-z0-9._-]+", "-", snapshot.name).strip("-")
    filename = f"{safe_snapshot}-{module}-business-review.zip"
    return {"content": content, "filename": filename,
            "sha256": hashlib.sha256(content).hexdigest(), "manifest": manifest,
            "reconciliation": reconciliation}
