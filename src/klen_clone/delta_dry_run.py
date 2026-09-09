from __future__ import annotations

import hashlib
import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


MONEY = re.compile(r"AED\s*(-?[0-9,]+(?:\.[0-9]+)?)")
PAYMENT_REFERENCE = re.compile(r"SP2026/\d+")
PROTECTED_DATABASE_NAMES = {
    "klen_staging.db",
    "klen_uat_validation.db",
    "klen_uat_reviews.db",
}
REQUIRED_FILES = {
    "sales_details.json",
    "master_purchase_details.json",
    "financial_effects.json",
    "stock_report_98081.csv",
}


class DeltaEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Validation:
    code: str
    passed: bool
    expected: str
    actual: str
    details: str = ""


def _decimal(value: Any) -> Decimal:
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value or "")
    matches = MONEY.findall(text)
    if matches:
        return Decimal(matches[-1].replace(",", ""))
    cleaned = re.sub(r"[^0-9.-]", "", text)
    return Decimal(cleaned or "0")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise DeltaEvidenceError(f"Expected a JSON object: {path.name}")
    return value


def _verify_manifest(source: Path) -> dict[str, str]:
    manifest_path = source / "SHA256SUMS.txt"
    if not manifest_path.is_file():
        raise DeltaEvidenceError("Missing SHA256SUMS.txt")
    entries: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9A-Fa-f]{64})\s+(.+)", line.strip())
        if not match:
            raise DeltaEvidenceError(f"Invalid checksum line: {line}")
        expected, name = match.groups()
        path = source / name
        if not path.is_file():
            raise DeltaEvidenceError(f"Manifest file missing: {name}")
        actual = _sha256(path)
        if actual != expected.upper():
            raise DeltaEvidenceError(f"Checksum mismatch: {name}")
        entries[name] = actual
    missing = REQUIRED_FILES - entries.keys()
    if missing:
        raise DeltaEvidenceError(f"Manifest does not cover: {', '.join(sorted(missing))}")
    return entries


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE dry_run_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE delta_customer (
            contact_id TEXT PRIMARY KEY,
            business_name TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE delta_product (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            purchase_price NUMERIC NOT NULL,
            selling_price NUMERIC NOT NULL,
            current_stock NUMERIC NOT NULL,
            stock_unit TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE delta_stock_balance (
            sku TEXT NOT NULL,
            location TEXT NOT NULL,
            product_name TEXT NOT NULL,
            unit TEXT NOT NULL,
            available_quantity NUMERIC NOT NULL,
            total_transferred NUMERIC NOT NULL,
            purchase_value NUMERIC NOT NULL,
            sale_value NUMERIC NOT NULL,
            raw_json TEXT NOT NULL,
            PRIMARY KEY (sku, location)
        );
        CREATE TABLE delta_purchase (
            document_no TEXT PRIMARY KEY,
            supplier_reference TEXT,
            supplier_name TEXT,
            total_amount NUMERIC NOT NULL,
            payment_status TEXT,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE delta_sale (
            invoice TEXT PRIMARY KEY,
            transaction_at TEXT,
            payment_status TEXT,
            total_payable NUMERIC NOT NULL,
            total_paid NUMERIC NOT NULL,
            total_remaining NUMERIC NOT NULL,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE delta_sale_line_evidence (
            invoice TEXT NOT NULL REFERENCES delta_sale(invoice),
            line_no INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            PRIMARY KEY (invoice, line_no)
        );
        CREATE TABLE delta_sale_payment_evidence (
            invoice TEXT NOT NULL REFERENCES delta_sale(invoice),
            row_no INTEGER NOT NULL,
            reference_no TEXT,
            amount NUMERIC NOT NULL,
            raw_text TEXT NOT NULL,
            PRIMARY KEY (invoice, row_no)
        );
        CREATE TABLE delta_sales_payment (
            reference_no TEXT PRIMARY KEY,
            paid_on TEXT,
            amount NUMERIC NOT NULL,
            parent_sale TEXT,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE delta_output_vat (
            invoice_no TEXT PRIMARY KEY,
            transaction_at TEXT,
            net_amount NUMERIC NOT NULL,
            gross_amount NUMERIC NOT NULL,
            vat_amount NUMERIC NOT NULL,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE delta_cash_flow (
            payment_reference TEXT PRIMARY KEY,
            transaction_at TEXT,
            account_name TEXT,
            debit NUMERIC NOT NULL,
            credit NUMERIC NOT NULL,
            account_balance NUMERIC,
            total_balance NUMERIC,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE validation_result (
            code TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('pass', 'fail')),
            expected TEXT NOT NULL,
            actual TEXT NOT NULL,
            details TEXT NOT NULL
        );
        """
    )


def run_delta_dry_run(source_dir: Path, output_path: Path) -> dict[str, Any]:
    source = source_dir.resolve()
    output = output_path.resolve()
    if not source.is_dir():
        raise DeltaEvidenceError(f"Source directory not found: {source}")
    if output.name.lower() in PROTECTED_DATABASE_NAMES:
        raise DeltaEvidenceError(f"Protected database name refused: {output.name}")
    if output.exists():
        raise DeltaEvidenceError(f"Output already exists; overwrite refused: {output}")
    if output.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise DeltaEvidenceError("Dry-run output must be a SQLite database file")

    hashes_before = _verify_manifest(source)
    sales_doc = _load_json(source / "sales_details.json")
    master_doc = _load_json(source / "master_purchase_details.json")
    finance_doc = _load_json(source / "financial_effects.json")
    with (source / "stock_report_98081.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        stock_report_rows = [row for row in csv.DictReader(handle) if row.get("SKU") == "98081"]
    documents = (sales_doc, master_doc, finance_doc)
    validations: list[Validation] = []

    def check(code: str, condition: bool, expected: Any, actual: Any, details: str = "") -> None:
        validations.append(Validation(code, bool(condition), str(expected), str(actual), details))

    check(
        "EVIDENCE_FLAGS",
        all(doc.get("atomic") is False and doc.get("source_mutation") is False and doc.get("clone_mutation") is False for doc in documents),
        "atomic=false, source_mutation=false, clone_mutation=false",
        "; ".join(f"{doc.get('atomic')}/{doc.get('source_mutation')}/{doc.get('clone_mutation')}" for doc in documents),
    )

    sales = sales_doc.get("sales") or []
    invoices = [str(row.get("invoice") or "") for row in sales]
    expected_invoices = {f"AK2026-{number:05d}" for number in range(3607, 3622)}
    line_count = sum(len(row.get("products") or []) for row in sales)
    detail_payment_count = sum(len(row.get("payments") or []) for row in sales)
    payable = sum((_decimal(row.get("total_payable")) for row in sales), Decimal("0"))
    paid = sum((_decimal(row.get("total_paid")) for row in sales), Decimal("0"))
    remaining = sum((_decimal(row.get("total_remaining")) for row in sales), Decimal("0"))
    check("SALE_KEYS", len(invoices) == 15 and len(set(invoices)) == 15 and set(invoices) == expected_invoices, "15 unique AK2026-03607..03621", f"{len(invoices)} rows/{len(set(invoices))} unique")
    check("SALE_LINE_COUNT", line_count == 35, 35, line_count)
    check("SALE_DETAIL_PAYMENT_COUNT", detail_payment_count == 8, 8, detail_payment_count)
    check("SALE_BALANCE_EQUATION", payable == paid + remaining, payable, paid + remaining)
    check("SALE_TOTAL_PAYABLE", payable == Decimal("1784.75"), "1784.75", payable)
    check("SALE_TOTAL_PAID", paid == Decimal("591.00"), "591.00", paid)
    check("SALE_TOTAL_REMAINING", remaining == Decimal("1193.75"), "1193.75", remaining)
    unbalanced_sales = [row["invoice"] for row in sales if _decimal(row.get("total_payable")) != _decimal(row.get("total_paid")) + _decimal(row.get("total_remaining"))]
    check("SALE_ROW_BALANCES", not unbalanced_sales, "all rows balanced", ", ".join(unbalanced_sales) or "all rows balanced")

    customer = master_doc["customer"]["record"]
    product = master_doc["product"]
    purchase = master_doc["purchase"]
    relationships = master_doc["relationships"]
    purchase_totals = purchase["detail_tables"][2]
    purchase_net = _decimal(next(row for row in purchase_totals if row.startswith("Net Total Amount:")))
    purchase_vat = _decimal(next(row for row in purchase_totals if row.startswith("Purchase Tax:")))
    purchase_total = _decimal(next(row for row in purchase_totals if row.startswith("Purchase Total:")))
    check("CUSTOMER_SALE_LINK", relationships["customer_sale"]["contact_id"] == customer["Contact ID"] and relationships["customer_sale"]["invoice"] in expected_invoices, f"{customer['Contact ID']} linked to captured sale", relationships["customer_sale"])
    check("PRODUCT_PURCHASE_LINK", relationships["product_purchase"]["sku"] == product["record"]["SKU"] and relationships["product_purchase"]["purchase"] == purchase["header"]["Purchase No"], "product and purchase keys match", relationships["product_purchase"])
    check("PURCHASE_TOTAL", purchase_net + purchase_vat == purchase_total == Decimal("65.00"), "61.90 + 3.10 = 65.00", f"{purchase_net} + {purchase_vat} = {purchase_total}")
    check("PURCHASE_UNPAID", purchase["header"]["Payment Status"] == "Due" and any("No payments found" in row for row in purchase["detail_tables"][1]), "Due with no payments", purchase["header"]["Payment Status"])
    stock_rows = product.get("stock_rows") or []
    check("PRODUCT_DXB_STOCK", any("DXB" in row and "1.00Carton" in row for row in stock_rows), "1.00 Carton at DXB", stock_rows[-1] if stock_rows else "missing")
    stock_locations = {row.get("Location") for row in stock_report_rows}
    stock_available = sum((_decimal(row.get("Available Stock")) for row in stock_report_rows), Decimal("0"))
    stock_transferred = sum((_decimal(row.get("Total Unit Transfered")) for row in stock_report_rows), Decimal("0"))
    check("STOCK_REPORT_LOCATIONS", len(stock_report_rows) == 2 and stock_locations == {"Asas General Trading LLC", "DXB"}, "two authoritative location rows", sorted(str(item) for item in stock_locations))
    check("STOCK_REPORT_QUANTITIES", stock_available == Decimal("1.00") and stock_transferred == Decimal("1.00"), "available 1.00 / transferred 1.00", f"available {stock_available} / transferred {stock_transferred}")
    check("STOCK_REPORT_PRODUCT", all(row.get("Product") == product["record"]["Product"] and row.get("Unit") == "Carton" for row in stock_report_rows), "product and unit match master", [row.get("Product") for row in stock_report_rows])
    check("PRODUCT_TRANSFER_LINK", relationships["product_transfer"] == {"sku": "98081", "reference": "ST2026/0927", "from": "Asas General Trading LLC", "to": "DXB", "quantity": "1.00 Carton", "preserved_evidence": "source_exports/2026-09-08/stock_transfer_details_0001_0050.json"}, "ST2026/0927 moves 1.00 Carton to DXB", relationships["product_transfer"])

    controls = finance_doc["controls"]
    payment_rows = finance_doc.get("sales_payment_rows") or []
    payment_refs = [row.get("Reference No") for row in payment_rows]
    payment_total = sum((_decimal(row.get("Amount")) for row in payment_rows), Decimal("0"))
    detail_payment_refs = set()
    detail_payment_total = Decimal("0")
    for sale in sales:
        for raw in sale.get("payments") or []:
            match = PAYMENT_REFERENCE.search(raw)
            if match:
                detail_payment_refs.add(match.group(0))
            detail_payment_total += _decimal(raw)
    new_sale_payment_rows = [row for row in payment_rows if row.get("Sales") in expected_invoices]
    prior_sale_payment_rows = [row for row in payment_rows if row.get("Sales") not in expected_invoices]
    check("PAYMENT_KEYS", len(payment_refs) == 12 and len(set(payment_refs)) == 12, "12 unique payment references", f"{len(payment_refs)} rows/{len(set(payment_refs))} unique")
    check("PAYMENT_TOTAL", payment_total == Decimal("934.50"), "934.50", payment_total)
    check("NEW_SALE_PAYMENTS", len(new_sale_payment_rows) == 8 and sum((_decimal(row.get("Amount")) for row in new_sale_payment_rows), Decimal("0")) == Decimal("591.00"), "8 rows / 591.00", f"{len(new_sale_payment_rows)} rows / {sum((_decimal(row.get('Amount')) for row in new_sale_payment_rows), Decimal('0'))}")
    check("PRIOR_SALE_PAYMENTS", len(prior_sale_payment_rows) == 4 and sum((_decimal(row.get("Amount")) for row in prior_sale_payment_rows), Decimal("0")) == Decimal("343.50"), "4 rows / 343.50", f"{len(prior_sale_payment_rows)} rows / {sum((_decimal(row.get('Amount')) for row in prior_sale_payment_rows), Decimal('0'))}")
    check("DETAIL_PAYMENT_LINKS", detail_payment_refs == {row["Reference No"] for row in new_sale_payment_rows} and detail_payment_total == Decimal("591.00"), "8 detail references / 591.00", f"{len(detail_payment_refs)} references / {detail_payment_total}")

    cash_rows = finance_doc.get("cash_flow_rows") or []
    cash_refs = []
    for row in cash_rows:
        match = PAYMENT_REFERENCE.search(str(row.get("Description") or ""))
        cash_refs.append(match.group(0) if match else None)
    cash_credit = sum((_decimal(row.get("Credit")) for row in cash_rows), Decimal("0"))
    cash_debit = sum((_decimal(row.get("Debit")) for row in cash_rows), Decimal("0"))
    check("CASH_PAYMENT_LINKS", set(cash_refs) == set(payment_refs) and None not in cash_refs, "cash references equal payment references", f"{len(set(cash_refs))} cash / {len(set(payment_refs))} payments")
    check("CASH_MOVEMENT", cash_credit == payment_total == Decimal("934.50") and cash_debit == 0, "credit 934.50 / debit 0", f"credit {cash_credit} / debit {cash_debit}")
    cash_control = controls["cash_flow"]
    check("CASH_BALANCE_MOVEMENT", _decimal(cash_control["live_final_balance_aed"]) - _decimal(cash_control["baseline_final_balance_aed"]) == Decimal("934.50"), "934.50", _decimal(cash_control["live_final_balance_aed"]) - _decimal(cash_control["baseline_final_balance_aed"]))

    vat_rows = finance_doc.get("output_vat_rows") or []
    vat_invoices = {row.get("Invoice No.") for row in vat_rows}
    vat_total = sum((_decimal(row.get("VAT")) for row in vat_rows), Decimal("0"))
    expected_vat_invoices = {f"AK2026-{number:05d}" for number in range(3610, 3622)}
    check("VAT_KEYS", vat_invoices == expected_vat_invoices and len(vat_rows) == 12, "AK2026-03610..03621", f"{len(vat_rows)} rows")
    check("VAT_TOTAL", vat_total == Decimal("62.81"), "62.81", vat_total)
    vat_control = controls["vat"]
    check("VAT_REPORT_COUNTS", vat_control["input_delta_rows"] == 0 and vat_control["output_delta_rows"] == 12, "input +0 / output +12", f"input {vat_control['input_delta_rows']} / output {vat_control['output_delta_rows']}")

    profit = controls["profit_loss"]
    vat_net = sum((_decimal(row.get("Total Amount (Exc. Tax)")) for row in vat_rows), Decimal("0"))
    vat_gross = sum((_decimal(row.get("Total amount with tax")) for row in vat_rows), Decimal("0"))
    check("PROFIT_SALES_NET_DELTA", vat_net == _decimal(profit["sales_ex_tax"]["delta_aed"]), vat_net, profit["sales_ex_tax"]["delta_aed"])
    check("PROFIT_SALES_GROSS_DELTA", vat_gross == _decimal(profit["sales_inc_tax"]["delta_aed"]), vat_gross, profit["sales_inc_tax"]["delta_aed"])
    trial = controls["trial_balance_view"]
    imbalance = _decimal(trial["debit_total_aed"]) - _decimal(trial["credit_total_aed"])
    check("TRIAL_BALANCE_BLOCKED", trial["promoted_to_opening_gl"] is False and imbalance == _decimal(trial["out_of_balance_aed"]) and imbalance != 0, "not promoted and imbalance retained", f"promoted={trial['promoted_to_opening_gl']}, imbalance={imbalance}")

    hashes_after = _verify_manifest(source)
    check("SOURCE_IMMUTABLE_DURING_RUN", hashes_before == hashes_after, hashes_before, hashes_after)

    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        _create_schema(connection)
        meta = {
            "source_directory": str(source),
            "source_atomic": "false",
            "validation_only": "true",
            "posting_enabled": "false",
            "promotion_allowed": "false",
            "opening_gl_allowed": "false",
            "captured_on": str(sales_doc.get("captured_on") or ""),
            "manifest_hashes": _json(hashes_before),
        }
        connection.executemany("INSERT INTO dry_run_meta(key, value) VALUES (?, ?)", meta.items())
        connection.execute("INSERT INTO delta_customer VALUES (?, ?, ?)", (customer["Contact ID"], customer["Business Name"], _json(customer)))
        product_record = product["record"]
        stock_match = re.match(r"([0-9,.]+)\s+(.+)", product_record["Current stock"])
        connection.execute("INSERT INTO delta_product VALUES (?, ?, ?, ?, ?, ?, ?)", (product_record["SKU"], product_record["Product"], str(_decimal(product_record["Unit Purchase Price"])), str(_decimal(product_record["Selling Price"])), stock_match.group(1).replace(",", "") if stock_match else "0", stock_match.group(2) if stock_match else product["detail"]["unit"], _json(product)))
        for row in stock_report_rows:
            connection.execute(
                "INSERT INTO delta_stock_balance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["SKU"], row["Location"], row["Product"], row["Unit"],
                    str(_decimal(row["Available Stock"])), str(_decimal(row["Total Unit Transfered"])),
                    str(_decimal(row["Current Stock Value (By purchase price)"])),
                    str(_decimal(row["Current Stock Value (By sale price)"])), _json(row),
                ),
            )
        purchase_header = purchase["header"]
        connection.execute("INSERT INTO delta_purchase VALUES (?, ?, ?, ?, ?, ?)", (purchase_header["Purchase No"], purchase_header["Supplier Ref"], purchase_header["Supplier"], str(_decimal(purchase_header["Grand Total"])), purchase_header["Payment Status"], _json(purchase)))
        for sale in sales:
            connection.execute("INSERT INTO delta_sale VALUES (?, ?, ?, ?, ?, ?, ?)", (sale["invoice"], sale.get("date_time"), sale.get("payment_status"), str(_decimal(sale.get("total_payable"))), str(_decimal(sale.get("total_paid"))), str(_decimal(sale.get("total_remaining"))), _json(sale)))
            for line_no, raw in enumerate(sale.get("products") or [], 1):
                connection.execute("INSERT INTO delta_sale_line_evidence VALUES (?, ?, ?)", (sale["invoice"], line_no, raw))
            for row_no, raw in enumerate(sale.get("payments") or [], 1):
                match = PAYMENT_REFERENCE.search(raw)
                connection.execute("INSERT INTO delta_sale_payment_evidence VALUES (?, ?, ?, ?, ?)", (sale["invoice"], row_no, match.group(0) if match else None, str(_decimal(raw)), raw))
        for row in payment_rows:
            connection.execute("INSERT INTO delta_sales_payment VALUES (?, ?, ?, ?, ?)", (row["Reference No"], row.get("Paid on"), str(_decimal(row.get("Amount"))), row.get("Sales"), _json(row)))
        for row in vat_rows:
            connection.execute("INSERT INTO delta_output_vat VALUES (?, ?, ?, ?, ?, ?)", (row["Invoice No."], row.get("Date"), str(_decimal(row.get("Total Amount (Exc. Tax)"))), str(_decimal(row.get("Total amount with tax"))), str(_decimal(row.get("VAT"))), _json(row)))
        for row, reference in zip(cash_rows, cash_refs, strict=True):
            connection.execute("INSERT INTO delta_cash_flow VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (reference, row.get("Date"), row.get("Account"), str(_decimal(row.get("Debit"))), str(_decimal(row.get("Credit"))), str(_decimal(row.get("Account Balance"))), str(_decimal(row.get("Total Balance"))), _json(row)))
        connection.executemany(
            "INSERT INTO validation_result VALUES (?, ?, ?, ?, ?)",
            [(item.code, "pass" if item.passed else "fail", item.expected, item.actual, item.details) for item in validations],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        output.unlink(missing_ok=True)
        raise
    finally:
        if output.exists():
            connection.close()

    failed = [item.code for item in validations if not item.passed]
    return {
        "status": "passed" if not failed else "failed",
        "database": str(output),
        "validation_only": True,
        "posting_enabled": False,
        "promotion_allowed": False,
        "checks": len(validations),
        "passed": len(validations) - len(failed),
        "failed": len(failed),
        "failed_checks": failed,
        "rows": {
            "customers": 1,
            "products": 1,
            "stock_balances": len(stock_report_rows),
            "purchases": 1,
            "sales": len(sales),
            "sale_lines": line_count,
            "sale_detail_payments": detail_payment_count,
            "sales_payments": len(payment_rows),
            "output_vat": len(vat_rows),
            "cash_flow": len(cash_rows),
        },
    }
