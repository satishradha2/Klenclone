from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from .data_governance import resolve_promotion_exception
from .operational import make_operational_engine


BATCH_KEY = "HISTORY-D7AB786EB3D6-A42462C335C2"
ACTOR = "exception-resolver:verified-later-capture-2026-09-12"
SALES = {
    180: ("AK2026-03607", 7),
    181: ("AK2026-03608", 1),
    182: ("AK2026-03609", 3),
}
SALE_LINE_EXCEPTIONS = {
    1: ("AK2026-03609", "92056"), 2: ("AK2026-03609", "92057"),
    3: ("AK2026-03609", "92326"), 4: ("AK2026-03608", "92965"),
    5: ("AK2026-03607", "92212"), 6: ("AK2026-03607", "92222"),
    7: ("AK2026-03607", "76116"), 8: ("AK2026-03607", "76118"),
    9: ("AK2026-03607", "93439"), 10: ("AK2026-03607", "92336"),
    11: ("AK2026-03607", "93293"),
}
TAX_EXCEPTIONS = {
    103: ("purchase", "PO2026/0456"),
    104: ("sale", "AK2026-03609"),
    105: ("sale", "AK2026-03608"),
    106: ("sale", "AK2026-03607"),
}
FINANCIAL_SETTLEMENT_EXCEPTIONS = {
    "AK2026-03599": (66, 107),
    "AK2026-03468": (67, 108),
    "AK2026-03465": (68, 109),
}


def resolution_code(exception_id: int) -> str:
    if exception_id in {value for pair in FINANCIAL_SETTLEMENT_EXCEPTIONS.values() for value in pair}:
        return "LATER_CAPTURE_SETTLEMENT_RECONCILED"
    if 26 <= exception_id <= 36 or exception_id in {56, 57}:
        return "DETERMINISTIC_MOVEMENT_MAPPING_PROVEN"
    if exception_id in TAX_EXCEPTIONS:
        return "TAX_DOCUMENT_RELATIONSHIP_PROVEN"
    if exception_id in SALE_LINE_EXCEPTIONS:
        return "TRANSACTION_LINE_PARENT_PROVEN"
    return "LATER_CAPTURE_RELATIONSHIP_PROVEN"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def money(value: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    return Decimal(cleaned or "0")


def quantity(value: str) -> Decimal:
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value or "")
    return Decimal(match.group(0)) if match else Decimal("0")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build_resolution_evidence(source_root: Path) -> dict[int, dict]:
    frozen = source_root / "2026-09-10-frozen-browser-cutover"
    sales_path = frozen / "sales_last_30_days.csv"
    lines_path = frozen / "details" / "sales_product_lines_current_business_day.csv"
    transfers_path = frozen / "stock_transfers_2026.csv"
    transfer_details_path = source_root / "2026-09-08" / "stock_transfer_details_0001_0050.json"
    products_path = frozen / "products.csv"
    stock_path = frozen / "details" / "stock_by_location.csv"
    status_path = frozen / "CAPTURE_STATUS.json"
    purchases_path = frozen / "purchases_2026.csv"
    tax_input_path = source_root / "2026-09-08" / "tax_input_2026.csv"
    tax_output_path = source_root / "2026-09-08" / "tax_output_2026.csv"

    status = json.loads(status_path.read_text(encoding="utf-8"))
    require(status.get("source_mutation") is False, "capture status does not prove read-only access")
    require(status.get("zero_drift_observed") is True, "capture status does not prove zero observed drift")
    declared_hashes = {item["file"]: item["sha256"].upper() for item in status["exports"]}
    for path in (sales_path, purchases_path, transfers_path, products_path):
        require(declared_hashes.get(path.name) == sha256(path), f"capture checksum mismatch: {path.name}")

    sales_rows = rows(sales_path)
    line_rows = rows(lines_path)
    result: dict[int, dict] = {}
    for exception_id, (invoice, expected_lines) in SALES.items():
        headers = [row for row in sales_rows if row["Invoice No."] == invoice]
        details = [row for row in line_rows if row["Invoice No."] == invoice]
        require(len(headers) == 1, f"{invoice}: expected one later-capture header, found {len(headers)}")
        require(len(details) == expected_lines, f"{invoice}: expected {expected_lines} lines, found {len(details)}")
        header_total = money(headers[0]["Total amount"])
        line_total = sum((money(row["Total"]) for row in details), Decimal("0"))
        require(header_total == line_total, f"{invoice}: header {header_total} != line total {line_total}")
        require(money(headers[0]["Total paid"]) + money(headers[0]["Sell Due"]) == header_total,
                f"{invoice}: payment allocation does not reconcile")
        result[exception_id] = {
            "source_key": invoice,
            "relationship": "later capture contains one matching header and all preserved sale lines",
            "header_rows": 1,
            "line_rows": len(details),
            "header_total_aed": str(header_total),
            "line_total_aed": str(line_total),
            "payment_status": headers[0]["Payment Status"],
            "paid_aed": str(money(headers[0]["Total paid"])),
            "due_aed": str(money(headers[0]["Sell Due"])),
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    for invoice, exception_ids in FINANCIAL_SETTLEMENT_EXCEPTIONS.items():
        headers = [row for row in sales_rows if row["Invoice No."] == invoice]
        details = [row for row in line_rows if row["Invoice No."] == invoice]
        require(len(headers) == 1 and details, f"{invoice}: settlement evidence is incomplete")
        header = headers[0]
        header_total = money(header["Total amount"])
        paid_total = money(header["Total paid"])
        due_total = money(header["Sell Due"])
        return_due = money(header["Sell Return Due"])
        line_total = sum((money(row["Total"]) for row in details), Decimal("0"))
        require(header["Payment Status"] == "Paid", f"{invoice}: later status is not Paid")
        require(header_total == paid_total and due_total == 0 and return_due == 0,
                f"{invoice}: later settlement does not reconcile")
        require(line_total == header_total, f"{invoice}: line and header totals differ")
        evidence = {
            "source_key": invoice,
            "relationship": "later frozen register and preserved item lines prove a fully settled invoice",
            "payment_status": header["Payment Status"],
            "header_total_aed": str(header_total),
            "line_total_aed": str(line_total),
            "paid_aed": str(paid_total),
            "due_aed": str(due_total),
            "return_due_aed": str(return_due),
            "line_rows": len(details),
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }
        for exception_id in exception_ids:
            result[exception_id] = evidence

    for exception_id, (invoice, sku) in SALE_LINE_EXCEPTIONS.items():
        headers = [row for row in sales_rows if row["Invoice No."] == invoice]
        details = [row for row in line_rows if row["Invoice No."] == invoice and row["SKU"] == sku]
        require(len(headers) == 1 and len(details) == 1,
                f"{invoice}/{sku}: line-to-header relationship is not unique")
        detail = details[0]
        result[exception_id] = {
            "source_key": f"{invoice}:{sku}",
            "relationship": "preserved sale line has one checksum-verified later-capture parent header",
            "document_no": invoice,
            "sku": sku,
            "quantity": detail["Quantity"],
            "line_total_aed": str(money(detail["Total"])),
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }
        movement_exception_id = exception_id + 25
        result[movement_exception_id] = {
            "source_key": f"movement:{invoice}:{sku}",
            "relationship": "sale issue movement has a unique later-capture header location and identity UOM",
            "source_movement_id": 7427 + exception_id,
            "document_no": invoice,
            "sku": sku,
            "location": headers[0]["Location"],
            "entered_quantity": str(quantity(detail["Quantity"])),
            "entered_uom": re.sub(r"^-?[0-9]+(?:\.[0-9]+)?\s*", "", detail["Quantity"]).strip(),
            "direction": "issue",
            "files": {
                str(sales_path.relative_to(source_root)): sha256(sales_path),
                str(lines_path.relative_to(source_root)): sha256(lines_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    purchase_rows = rows(purchases_path)
    tax_inputs = rows(tax_input_path)
    tax_outputs = rows(tax_output_path)
    for exception_id, (kind, document_no) in TAX_EXCEPTIONS.items():
        if kind == "sale":
            headers = [row for row in sales_rows if row["Invoice No."] == document_no]
            taxes = [row for row in tax_outputs if row["Invoice No."] == document_no]
            require(len(headers) == 1 and len(taxes) == 1,
                    f"{document_no}: tax-to-sale relationship is not unique")
            gross = money(taxes[0]["Total amount with tax"])
            header_total = money(headers[0]["Total amount"])
            tax_file = tax_output_path
        else:
            headers = [row for row in purchase_rows if row["Purchase No"] == document_no]
            taxes = [row for row in tax_inputs if row["Reference No"] == document_no]
            require(len(headers) == 1 and len(taxes) == 1,
                    f"{document_no}: tax-to-purchase relationship is not unique")
            gross = money(taxes[0]["Total amount"]) + money(taxes[0]["VAT"])
            header_total = money(headers[0]["Grand Total"])
            tax_file = tax_input_path
        require(gross == header_total, f"{document_no}: tax gross {gross} != document total {header_total}")
        header_file = sales_path if kind == "sale" else purchases_path
        result[exception_id] = {
            "source_key": document_no,
            "relationship": f"preserved tax {kind} row has one checksum-verified later-capture document header",
            "document_kind": kind,
            "document_total_aed": str(header_total),
            "tax_gross_aed": str(gross),
            "vat_aed": str(money(taxes[0]["VAT"])),
            "files": {
                str(header_file.relative_to(source_root)): sha256(header_file),
                str(tax_file.relative_to(source_root)): sha256(tax_file),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    transfer_headers = [row for row in rows(transfers_path) if row["Reference No"] == "ST2026/0927"]
    transfer_details = [item for item in json.loads(transfer_details_path.read_text(encoding="utf-8"))
                        if "Reference No: #ST2026/0927" in item.get("text", "")]
    require(len(transfer_headers) == 1, "ST2026/0927: expected one later-capture header")
    require(len(transfer_details) == 1, "ST2026/0927: expected one preserved detail document")
    transfer = transfer_headers[0]
    text = transfer_details[0]["text"]
    require(transfer["Status"] == "Completed" and "Status: Completed" in text,
            "ST2026/0927: status is not consistently completed")
    require(transfer["Location (From)"] == "Asas General Trading LLC" and transfer["Location (To)"] == "DXB",
            "ST2026/0927: transfer locations differ")
    require("98081" in text and "1.00 Carton" in text and "Purchase Total:\t\t61.9000" in text,
            "ST2026/0927: preserved detail does not prove the expected line and total")
    require(money(transfer["Total Amount"]) == Decimal("61.90"), "ST2026/0927: header total differs")
    result[179] = {
        "source_key": "ST2026/0927",
        "relationship": "later capture contains the matching completed transfer header; preserved detail contains its line",
        "header_rows": 1,
        "detail_documents": 1,
        "sku": "98081",
        "quantity": "1.00 Carton",
        "from": transfer["Location (From)"],
        "to": transfer["Location (To)"],
        "total_aed": "61.90",
        "files": {
            str(transfers_path.relative_to(source_root)): sha256(transfers_path),
            str(transfer_details_path.relative_to(source_root)): sha256(transfer_details_path),
            str(status_path.relative_to(source_root)): sha256(status_path),
        },
    }
    for exception_id, source_movement_id, direction, location, counterparty in (
        (56, 9585, "transfer_out", "Asas General Trading LLC", "DXB"),
        (57, 9586, "transfer_in", "DXB", "Asas General Trading LLC"),
    ):
        result[exception_id] = {
            "source_key": f"movement:ST2026/0927:{direction}",
            "relationship": "transfer movement has a completed header, stable product master and preserved line detail",
            "source_movement_id": source_movement_id,
            "document_no": "ST2026/0927",
            "sku": "98081",
            "location": location,
            "counterparty_location": counterparty,
            "entered_quantity": "1.00",
            "entered_uom": "Carton",
            "direction": direction,
            "files": {
                str(transfers_path.relative_to(source_root)): sha256(transfers_path),
                str(transfer_details_path.relative_to(source_root)): sha256(transfer_details_path),
                str(products_path.relative_to(source_root)): sha256(products_path),
                str(status_path.relative_to(source_root)): sha256(status_path),
            },
        }

    products = [row for row in rows(products_path) if row["SKU"] == "98081"]
    stock_rows = [row for row in rows(stock_path) if row["SKU"] == "98081"]
    require(len(products) == 1, "98081: expected one product master")
    require(len(stock_rows) == 2, "98081: expected exactly two location stock rows")
    require({row["Location"] for row in stock_rows} == {"Asas General Trading LLC", "DXB"},
            "98081: unexpected stock locations")
    master_qty = quantity(products[0]["Current stock"])
    location_qty = sum((quantity(row["Available Stock"]) for row in stock_rows), Decimal("0"))
    require(master_qty == Decimal("1") and location_qty == master_qty,
            "98081: product and location stock do not reconcile")
    result[188] = {
        "source_key": "98081",
        "relationship": "later capture contains one stable product master and reconciled location stock",
        "product_rows": 1,
        "stock_location_rows": 2,
        "master_quantity": str(master_qty),
        "location_quantity": str(location_qty),
        "locations": {row["Location"]: str(quantity(row["Available Stock"])) for row in stock_rows},
        "files": {
            str(products_path.relative_to(source_root)): sha256(products_path),
            str(stock_path.relative_to(source_root)): sha256(stock_path),
            str(status_path.relative_to(source_root)): sha256(status_path),
        },
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve only checksum-proven earlier-snapshot drift exceptions")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    evidence = build_resolution_evidence(args.source_root)
    output = {"mode": "apply" if args.apply else "dry-run", "batch_key": BATCH_KEY,
              "proven_exception_ids": sorted(evidence), "evidence": evidence,
              "source_mutation": False, "posting_enabled": False}
    if args.apply:
        url = os.getenv("ASAS_OPERATIONAL_DATABASE_URL", "").strip()
        if not url:
            raise SystemExit("ASAS_OPERATIONAL_DATABASE_URL is required for --apply")
        engine = make_operational_engine(url)
        with Session(engine) as session:
            output["resolutions"] = [resolve_promotion_exception(
                session, batch_key=BATCH_KEY, source_exception_id=exception_id, actor=ACTOR,
                resolution_code=resolution_code(exception_id), evidence=evidence[exception_id],
            ) for exception_id in sorted(evidence)]
            session.commit()
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
