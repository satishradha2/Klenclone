from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .inventory import canonical_uom
from .operational import (
    OperationalAuditEvent,
    OperationalFiscalPeriod,
    OperationalOpeningStockBatch,
    OperationalStockMigrationException,
    OperationalStockPosition,
    initialize_operational_database,
    make_operational_engine,
)


LOCATION_MAP = {
    "Asas General Trading LLC": "MAIN",
    "SHJ": "SHJ",
    "RAK": "RAK",
    "DXB": "DXB",
}
MONEY = Decimal("0.01")


class OpeningStockImportError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{str(key): str(value or "").strip() for key, value in row.items() if key is not None}
                for row in csv.DictReader(handle)]


def _number(value: str, *, first: bool = False) -> Decimal:
    matches = re.findall(r"-?[\d,]+(?:\.\d+)?", value or "")
    if not matches:
        return Decimal("0")
    return Decimal(matches[0 if first else -1].replace(",", ""))


def import_opening_stock(session: Session, *, capture: Path, package_status: Path,
                         actor: str, approval_reference: str) -> dict:
    capture = capture.resolve()
    status = json.loads(package_status.resolve().read_text(encoding="utf-8"))
    if status.get("source_capture_atomicity") != "NON_ATOMIC" or status.get("stock", {}).get("reconciled") is not True:
        raise OpeningStockImportError("The source package is not the expected reconciled non-atomic stock capture")
    manifest = {item["name"]: item for item in status.get("source_manifest", [])}
    stock_path, product_path = capture / "stock_snapshot_all_locations_current.csv", capture / "products_current.csv"
    for path in (stock_path, product_path):
        expected = manifest.get(path.name, {}).get("sha256")
        actual = _sha(path)
        if not expected or actual != expected:
            raise OpeningStockImportError(f"Source checksum mismatch: {path.name}")

    stock_sha, products_sha = _sha(stock_path), _sha(product_path)
    batch_key = hashlib.sha256(f"{stock_sha}:{products_sha}".encode("ascii")).hexdigest()
    existing = session.scalar(select(OperationalOpeningStockBatch).where(
        OperationalOpeningStockBatch.batch_key == batch_key))
    if existing:
        return {"status": "already_imported", "batch_key": batch_key,
                "positive_rows": existing.positive_rows, "exception_rows": existing.exception_rows,
                "net_quantity": existing.net_quantity, "stock_value": existing.stock_value}
    if session.scalar(select(func.count(OperationalStockPosition.id))) or session.scalar(
            select(func.count(OperationalStockMigrationException.id))):
        raise OpeningStockImportError("Operational opening stock target is not empty")

    products = _rows(product_path)
    product_cost = {row.get("SKU", ""): _number(row.get("Unit Purchase Price", "")) for row in products}
    product_quantity = {row.get("SKU", ""): _number(row.get("Current stock", ""), first=True)
                        for row in products}
    location_quantity: dict[str, Decimal] = {}
    positives: list[dict] = []
    negatives: list[dict] = []
    for row in _rows(stock_path):
        sku, source_location = row.get("SKU", ""), row.get("Location", "")
        quantity = _number(row.get("Available Stock", ""), first=True)
        if not sku:
            if quantity:
                raise OpeningStockImportError("Non-zero stock row is missing SKU")
            continue
        location_quantity[sku] = location_quantity.get(sku, Decimal("0")) + quantity
        if quantity == 0:
            continue
        location = LOCATION_MAP.get(source_location)
        if not location:
            raise OpeningStockImportError(f"Unmapped non-zero source location: {source_location}")
        cost = product_cost.get(sku)
        unit = canonical_uom(row.get("Unit"))
        if cost is None or cost <= 0 or not unit:
            raise OpeningStockImportError(f"Invalid opening cost or UOM for {sku}")
        target = {"location_code": location, "sku": sku, "canonical_uom": unit,
                  "quantity_base": quantity, "unit_cost": cost}
        (positives if quantity > 0 else negatives).append(target)

    differences = {sku: location_quantity.get(sku, Decimal("0")) - quantity
                   for sku, quantity in product_quantity.items()
                   if location_quantity.get(sku, Decimal("0")) != quantity}
    extra = set(location_quantity) - set(product_quantity)
    if differences or extra:
        raise OpeningStockImportError(f"Stock report does not reconcile to product register: {len(differences) + len(extra)} SKU(s)")
    positive_quantity = sum((row["quantity_base"] for row in positives), Decimal("0"))
    exception_quantity = sum((row["quantity_base"] for row in negatives), Decimal("0"))
    net_quantity = positive_quantity + exception_quantity
    declared = Decimal(str(status["stock"]["net_quantity"]))
    if net_quantity != declared:
        raise OpeningStockImportError(f"Net quantity mismatch: calculated {net_quantity}, declared {declared}")
    stock_value = sum((row["quantity_base"] * row["unit_cost"] for row in positives),
                      Decimal("0")).quantize(MONEY, rounding=ROUND_HALF_UP)

    batch = OperationalOpeningStockBatch(
        batch_key=batch_key, source_capture=str(capture), source_stock_sha256=stock_sha,
        source_products_sha256=products_sha, source_atomic=False,
        approval_reference=approval_reference, imported_by=actor,
        positive_rows=len(positives), exception_rows=len(negatives),
        positive_quantity=positive_quantity, exception_quantity=exception_quantity,
        net_quantity=net_quantity, stock_value=stock_value,
        status="approved_reconciled_non_atomic",
    )
    session.add(batch)
    session.flush()
    for row in positives:
        session.add(OperationalStockPosition(
            location_code=row["location_code"], sku=row["sku"],
            canonical_uom=row["canonical_uom"], quantity_on_hand=row["quantity_base"],
            quantity_reserved=Decimal("0"), average_unit_cost=row["unit_cost"],
            source_batch_key=batch_key, source_status="approved_reconciled_non_atomic",
            availability_enabled=True,
        ))
    for row in negatives:
        session.add(OperationalStockMigrationException(
            batch_id=batch.id, location_code=row["location_code"], sku=row["sku"],
            canonical_uom=row["canonical_uom"], quantity_base=row["quantity_base"],
            unit_cost=row["unit_cost"], reason="Source negative stock quarantined; operational balance not created",
            status="quarantined",
        ))
    period = OperationalFiscalPeriod(
        period_key="2026-09", starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30),
        status="open", rehearsal_enabled=True, approval_reference=approval_reference,
        configured_by=actor,
    )
    session.add(period)
    session.add(OperationalAuditEvent(
        event_key=os.urandom(16).hex(), event_type="opening_stock.imported", actor=actor,
        resource_key=batch_key,
        detail=(f"{len(positives)} positive positions {positive_quantity}; "
                f"{len(negatives)} negatives quarantined {exception_quantity}; "
                f"net {net_quantity}; non-atomic approved staging evidence"),
    ))
    session.commit()
    return {"status": "imported", "batch_key": batch_key, "positive_rows": len(positives),
            "exception_rows": len(negatives), "positive_quantity": positive_quantity,
            "exception_quantity": exception_quantity, "net_quantity": net_quantity,
            "stock_value": stock_value, "period_key": period.period_key,
            "source_atomic": False, "posting_enabled": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import checksum-bound Asas opening stock")
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--package-status", required=True, type=Path)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--approval-reference", required=True)
    args = parser.parse_args()
    url = os.getenv("ASAS_OPERATIONAL_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("ASAS_OPERATIONAL_DATABASE_URL is required")
    engine = make_operational_engine(url)
    initialize_operational_database(engine)
    with Session(engine) as session:
        report = import_opening_stock(session, capture=args.capture,
                                      package_status=args.package_status,
                                      actor=args.actor, approval_reference=args.approval_reference)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
