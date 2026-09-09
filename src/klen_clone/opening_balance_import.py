from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .operational import (
    OperationalAuditEvent,
    OperationalFinancialMigrationException,
    OperationalOpeningBalanceBatch,
    OperationalOpeningPartyBalance,
    initialize_operational_database,
    make_operational_engine,
)


SOURCE_FILES = (
    "customers_current.csv",
    "suppliers_current.csv",
    "sales_2026_current.csv",
    "sales_returns_2026_current.csv",
    "purchases_2026_current.csv",
    "purchase_returns_2026_current.csv",
    "customer_supplier_report_ytd.csv",
)
MONEY = Decimal("0.01")


class OpeningBalanceImportError(RuntimeError):
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


def _number(value: str) -> Decimal:
    matches = re.findall(r"-?[\d,]+(?:\.\d+)?", value or "")
    return Decimal(matches[-1].replace(",", "")) if matches else Decimal("0")


def _name(row: dict[str, str]) -> str:
    return (row.get("Business Name") or row.get("Name") or row.get("Contact ID") or "").strip()


def import_opening_balances(session: Session, *, capture: Path, package_status: Path,
                            actor: str, approval_reference: str) -> dict:
    capture = capture.resolve()
    status_path = package_status.resolve()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("source_capture_atomicity") != "NON_ATOMIC" or status.get("posting_enabled") is not False:
        raise OpeningBalanceImportError("The source package is not the expected non-posting, non-atomic capture")
    manifest = {item["name"]: item for item in status.get("source_manifest", [])}
    hashes: dict[str, str] = {}
    for name in SOURCE_FILES:
        path = capture / name
        actual, expected = _sha(path), manifest.get(name, {}).get("sha256")
        if not expected or actual != expected:
            raise OpeningBalanceImportError(f"Source checksum mismatch: {name}")
        hashes[name] = actual
    manifest_sha = hashlib.sha256(status_path.read_bytes()).hexdigest().upper()
    batch_key = hashlib.sha256(":".join(hashes[name] for name in SOURCE_FILES).encode("ascii")).hexdigest()
    existing = session.scalar(select(OperationalOpeningBalanceBatch).where(
        OperationalOpeningBalanceBatch.batch_key == batch_key))
    if existing:
        return {
            "status": "already_imported", "batch_key": batch_key,
            "receivable_rows": existing.receivable_rows, "receivable_amount": existing.receivable_amount,
            "customer_advance_rows": existing.customer_advance_rows,
            "customer_advance_amount": existing.customer_advance_amount,
            "payable_rows": existing.payable_rows, "payable_amount": existing.payable_amount,
            "supplier_advance_rows": existing.supplier_advance_rows,
            "supplier_advance_amount": existing.supplier_advance_amount,
        }
    if session.scalar(select(func.count(OperationalOpeningPartyBalance.id))) or session.scalar(
            select(func.count(OperationalFinancialMigrationException.id))):
        raise OpeningBalanceImportError("Operational opening-balance target is not empty")

    balances: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for party_type, filename, due_column, return_column in (
        ("customer", "customers_current.csv", "Total Sale Due", "Total Sell Return Due"),
        ("supplier", "suppliers_current.csv", "Total Purchase Due", "Total Purchase Return Due"),
    ):
        for row in _rows(capture / filename):
            code = row.get("Contact ID", "").strip()
            amount = (_number(row.get(due_column, "")) - _number(row.get(return_column, ""))).quantize(MONEY)
            if not code:
                if amount:
                    raise OpeningBalanceImportError(f"Non-zero {party_type} balance is missing Contact ID")
                continue
            key = (party_type, code)
            if key in seen:
                raise OpeningBalanceImportError(f"Duplicate {party_type} Contact ID: {code}")
            seen.add(key)
            if not amount:
                continue
            if party_type == "customer":
                balance_type = "receivable" if amount > 0 else "customer_advance"
                control, offset = (("1100", "3100") if amount > 0 else ("2300", "3100"))
            else:
                balance_type = "payable" if amount > 0 else "supplier_advance"
                control, offset = (("2000", "3100") if amount > 0 else ("1300", "3100"))
            balances.append({
                "party_type": party_type, "party_code": code, "party_name_snapshot": _name(row),
                "balance_type": balance_type, "amount": abs(amount),
                "control_account_code": control, "offset_account_code": offset,
            })

    totals = {kind: sum((row["amount"] for row in balances if row["balance_type"] == kind), Decimal("0"))
              for kind in ("receivable", "customer_advance", "payable", "supplier_advance")}
    counts = {kind: len([row for row in balances if row["balance_type"] == kind]) for kind in totals}
    declared = status.get("balances", {})
    expected = {
        "receivable": (declared.get("receivables_rows"), Decimal(str(declared.get("receivables_aed")))),
        "customer_advance": (declared.get("customer_advance_partners"), Decimal(str(declared.get("customer_advances_aed")))),
        "payable": (declared.get("payables_rows"), Decimal(str(declared.get("payables_aed")))),
        "supplier_advance": (declared.get("supplier_advance_partners"), Decimal(str(declared.get("supplier_advances_aed")))),
    }
    for kind, (expected_rows, expected_amount) in expected.items():
        if counts[kind] != expected_rows or totals[kind] != expected_amount:
            raise OpeningBalanceImportError(
                f"{kind} control mismatch: calculated {counts[kind]}/{totals[kind]}, "
                f"declared {expected_rows}/{expected_amount}")

    customer_net = totals["receivable"] - totals["customer_advance"]
    supplier_net = totals["payable"] - totals["supplier_advance"]
    sales_headers = sum((_number(row.get("Sell Due", "")) for row in _rows(capture / "sales_2026_current.csv")), Decimal("0"))
    sales_returns = sum((_number(row.get("Payment due", "")) for row in _rows(capture / "sales_returns_2026_current.csv")), Decimal("0"))
    purchase_headers = sum((_number(row.get("Payment due", "")) for row in _rows(capture / "purchases_2026_current.csv")), Decimal("0"))
    purchase_returns = sum((_number(row.get("Payment due", "")) for row in _rows(capture / "purchase_returns_2026_current.csv")), Decimal("0"))
    report_due = sum((_number(row.get("Due", "")) for row in _rows(capture / "customer_supplier_report_ytd.csv")), Decimal("0"))
    comparisons = (
        ("customer_header_due", customer_net, sales_headers - sales_returns),
        ("supplier_header_due", supplier_net, purchase_headers - purchase_returns),
        ("combined_ytd_due", customer_net - supplier_net, report_due),
    )
    declared_checks = status.get("secondary_report_checks", {})
    if customer_net != Decimal(str(declared_checks.get("customer_master_net_aed"))) or \
            supplier_net != Decimal(str(declared_checks.get("supplier_master_net_aed"))):
        raise OpeningBalanceImportError("Contact-master net controls do not match the sealed package")

    batch = OperationalOpeningBalanceBatch(
        batch_key=batch_key, source_capture=str(capture), source_manifest_sha256=manifest_sha,
        source_atomic=False, approval_reference=approval_reference, imported_by=actor,
        receivable_rows=counts["receivable"], receivable_amount=totals["receivable"],
        customer_advance_rows=counts["customer_advance"], customer_advance_amount=totals["customer_advance"],
        payable_rows=counts["payable"], payable_amount=totals["payable"],
        supplier_advance_rows=counts["supplier_advance"], supplier_advance_amount=totals["supplier_advance"],
        status="approved_contact_control_non_atomic_nonposting",
    )
    session.add(batch)
    session.flush()
    for row in balances:
        session.add(OperationalOpeningPartyBalance(
            batch_id=batch.id, **row, currency_code="AED", posting_enabled=False,
            source_status="approved_contact_control_non_atomic_nonposting"))
    for name, authoritative, comparison in comparisons:
        session.add(OperationalFinancialMigrationException(
            batch_id=batch.id, control_name=name, authoritative_amount=authoritative,
            comparison_amount=comparison, variance_amount=authoritative - comparison,
            reason="Non-atomic browser exports differ by source report semantics or capture timing; invoice allocation is not asserted",
            status="open"))
    session.add(OperationalAuditEvent(
        event_key=os.urandom(16).hex(), event_type="opening_balances.imported", actor=actor,
        resource_key=batch_key,
        detail=(f"AR {counts['receivable']}/{totals['receivable']}; customer advances "
                f"{counts['customer_advance']}/{totals['customer_advance']}; AP "
                f"{counts['payable']}/{totals['payable']}; supplier advances "
                f"{counts['supplier_advance']}/{totals['supplier_advance']}; non-posting")))
    session.commit()
    return {
        "status": "imported_nonposting", "batch_key": batch_key,
        "receivables": {"rows": counts["receivable"], "amount": totals["receivable"]},
        "customer_advances": {"rows": counts["customer_advance"], "amount": totals["customer_advance"]},
        "payables": {"rows": counts["payable"], "amount": totals["payable"]},
        "supplier_advances": {"rows": counts["supplier_advance"], "amount": totals["supplier_advance"]},
        "exceptions": [{"control": name, "authoritative": authoritative,
                        "comparison": comparison, "variance": authoritative - comparison}
                       for name, authoritative, comparison in comparisons],
        "source_atomic": False, "posting_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import checksum-bound Asas opening AR/AP controls")
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
        report = import_opening_balances(session, capture=args.capture,
                                         package_status=args.package_status,
                                         actor=args.actor, approval_reference=args.approval_reference)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
