import csv
import hashlib
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.opening_stock_import import import_opening_stock
from klen_clone.operational import (
    OperationalFiscalPeriod, OperationalOpeningStockBatch,
    OperationalStockMigrationException, OperationalStockPosition,
    initialize_operational_database, make_operational_engine,
)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_checksum_bound_opening_stock_import_is_reconciled_quarantined_and_idempotent(tmp_path):
    capture = tmp_path / "capture"
    capture.mkdir()
    products = capture / "products_current.csv"
    stock = capture / "stock_snapshot_all_locations_current.csv"
    write_csv(products, ["SKU", "Unit Purchase Price", "Current stock"], [
        {"SKU": "SKU-1", "Unit Purchase Price": "AED 2.50", "Current stock": "3.00 Pieces"},
        {"SKU": "SKU-2", "Unit Purchase Price": "AED 4.00", "Current stock": "-1.00 Pack"},
    ])
    write_csv(stock, ["SKU", "Location", "Unit", "Available Stock"], [
        {"SKU": "SKU-1", "Location": "SHJ", "Unit": "Pieces", "Available Stock": "3.00 Pieces"},
        {"SKU": "SKU-2", "Location": "Asas General Trading LLC", "Unit": "Pack", "Available Stock": "-1.00 Pack"},
    ])
    status = tmp_path / "PACKAGE_STATUS.json"
    status.write_text(json.dumps({
        "source_capture_atomicity": "NON_ATOMIC", "stock": {"reconciled": True, "net_quantity": "2.00"},
        "source_manifest": [
            {"name": products.name, "sha256": sha(products)},
            {"name": stock.name, "sha256": sha(stock)},
        ],
    }), encoding="utf-8")
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'operational.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        result = import_opening_stock(
            session, capture=capture, package_status=status,
            actor="owner", approval_reference="test-approval",
        )
        assert result["positive_rows"] == 1
        assert result["exception_rows"] == 1
        assert result["net_quantity"] == 2
        position = session.scalar(select(OperationalStockPosition))
        assert position.location_code == "SHJ"
        assert position.quantity_on_hand == 3
        assert position.average_unit_cost == 2.5
        assert position.availability_enabled is True
        exception = session.scalar(select(OperationalStockMigrationException))
        assert exception.location_code == "MAIN"
        assert exception.quantity_base == -1
        assert exception.status == "quarantined"
        assert session.scalar(select(OperationalFiscalPeriod)).period_key == "2026-09"
        repeated = import_opening_stock(
            session, capture=capture, package_status=status,
            actor="owner", approval_reference="test-approval",
        )
        assert repeated["status"] == "already_imported"
        assert session.scalar(select(func.count(OperationalOpeningStockBatch.id))) == 1
        assert session.scalar(select(func.count(OperationalStockPosition.id))) == 1
