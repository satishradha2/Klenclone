from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


KEY_COLUMNS = {
    "customers": "Contact ID",
    "products": "SKU",
    "purchase_payments": "Reference No",
    "purchase_returns": "Reference No",
    "purchases": "Purchase No",
    "sales": "Invoice No.",
    "sales_payments": "Reference No",
    "sales_returns": "Invoice No.",
    "stock_transfers": "Reference No",
    "suppliers": "Contact ID",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _manifest(capture: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in (capture / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        entries.append((digest.upper(), relative.strip().lstrip("*")))
    return entries


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def stage_browser_delta(capture: Path, output: Path) -> dict[str, object]:
    capture = capture.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite staging output: {output}")
    if capture == output or capture in output.parents:
        raise ValueError("Staging output must be outside the immutable capture directory")

    manifest = _manifest(capture)
    failures: list[str] = []
    for expected, relative in manifest:
        source = capture / Path(relative)
        if not source.is_file():
            failures.append(f"missing:{relative}")
        elif _sha256(source) != expected:
            failures.append(f"checksum:{relative}")
    if failures:
        raise ValueError("Capture integrity validation failed: " + ", ".join(failures))

    reconciliation = json.loads((capture / "delta" / "DELTA_RECONCILIATION.json").read_text(encoding="utf-8"))
    expected_counts = reconciliation["new_rows"]
    delta_sets: dict[str, set[str]] = {}
    delta_rows: list[tuple[str, str, str]] = []
    validations: list[tuple[str, str, str]] = []
    for entity, key_column in KEY_COLUMNS.items():
        rows = _read_csv(capture / "delta" / f"{entity}_delta.csv")
        keys = [row.get(key_column, "").strip() for row in rows]
        delta_sets[entity] = set(keys)
        count_ok = len(rows) == int(expected_counts[entity])
        unique_ok = bool(keys) and all(keys) and len(keys) == len(set(keys))
        validations.append((f"{entity}.row_count", "passed" if count_ok else "failed", f"expected={expected_counts[entity]},actual={len(rows)}"))
        validations.append((f"{entity}.unique_source_key", "passed" if unique_ok else "failed", f"key={key_column},unique={len(set(keys))}"))
        delta_rows.extend((entity, key, json.dumps(row, ensure_ascii=False, sort_keys=True)) for key, row in zip(keys, rows))

    details = capture / "details"
    sales_lines = _read_csv(details / "sales_product_lines_current_business_day.csv")
    purchase_lines = _read_csv(details / "purchase_product_lines_2026-09-09.csv")
    stock_rows = _read_csv(details / "stock_by_location.csv")
    selected_sales = [r for r in sales_lines if r.get("Invoice No.", "").strip() in delta_sets["sales"]]
    selected_purchases = [r for r in purchase_lines if r.get("Reference No", "").strip() in delta_sets["purchases"]]

    transfer_docs = json.loads((details / "stock_transfer_details_ST2026_0931_0947.json").read_text(encoding="utf-8"))
    return_docs = json.loads((details / "sales_return_details_CN2026_0040_0043.json").read_text(encoding="utf-8"))
    purchase_return = json.loads((details / "purchase_return_2026_0013_form_evidence.json").read_text(encoding="utf-8"))
    supplemental_purchase_path = details / "purchase_detail_documents_PO2026_0460_0465.json"
    purchase_docs = json.loads(supplemental_purchase_path.read_text(encoding="utf-8")) if supplemental_purchase_path.exists() else []
    document_groups = {
        "stock_transfers": transfer_docs,
        "sales_returns": return_docs,
        "purchase_returns": [purchase_return],
        "purchases": purchase_docs,
    }
    for entity, docs in document_groups.items():
        refs = [str(doc.get("reference", "")).strip() for doc in docs]
        expected = delta_sets[entity]
        if entity == "purchases":
            ok = all(refs) and len(refs) == len(set(refs)) and set(refs).issubset(expected)
            validations.append((f"{entity}.supplemental_detail_documents", "passed" if ok else "failed", f"delta={len(expected)},supplemental={len(refs)}"))
        else:
            ok = set(refs) == expected and len(refs) == len(expected)
            validations.append((f"{entity}.detail_documents", "passed" if ok else "failed", f"expected={len(expected)},actual={len(refs)}"))

    sales_parents = {r.get("Invoice No.", "").strip() for r in selected_sales}
    purchase_parents = {r.get("Reference No", "").strip() for r in selected_purchases}
    supplemental_purchase_lines = []
    for document in purchase_docs:
        reference = str(document.get("reference", "")).strip()
        if reference in delta_sets["purchases"] and reference not in purchase_parents:
            for line in document.get("lines", []):
                supplemental_purchase_lines.append((reference, line))
            purchase_parents.add(reference)
    validations.append(("sales.detail_parent_coverage", "passed" if sales_parents == delta_sets["sales"] else "exception", f"covered={len(sales_parents)},expected={len(delta_sets['sales'])}"))
    validations.append(("purchases.detail_parent_coverage", "passed" if purchase_parents == delta_sets["purchases"] else "exception", f"covered={len(purchase_parents)},expected={len(delta_sets['purchases'])}"))

    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.executescript("""
        CREATE TABLE staging_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE source_manifest (relative_path TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
        CREATE TABLE delta_rows (entity TEXT NOT NULL, source_key TEXT NOT NULL, raw_json TEXT NOT NULL, PRIMARY KEY(entity, source_key));
        CREATE TABLE detail_rows (detail_type TEXT NOT NULL, parent_key TEXT NOT NULL, raw_json TEXT NOT NULL);
        CREATE TABLE detail_documents (entity TEXT NOT NULL, source_key TEXT NOT NULL, raw_json TEXT NOT NULL, PRIMARY KEY(entity, source_key));
        CREATE TABLE validation_results (check_name TEXT PRIMARY KEY, status TEXT NOT NULL, evidence TEXT NOT NULL);
        """)
        metadata = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "capture_path": str(capture),
            "validation_only": "true",
            "production_merge_allowed": "false",
            "posting_enabled": "false",
            "source_mutation": "false",
        }
        connection.executemany("INSERT INTO staging_metadata VALUES (?, ?)", metadata.items())
        connection.executemany("INSERT INTO source_manifest VALUES (?, ?)", ((r, h) for h, r in manifest))
        connection.executemany("INSERT INTO delta_rows VALUES (?, ?, ?)", delta_rows)
        connection.executemany("INSERT INTO detail_rows VALUES (?, ?, ?)", (("sales_line", r["Invoice No."].strip(), json.dumps(r, ensure_ascii=False, sort_keys=True)) for r in selected_sales))
        connection.executemany("INSERT INTO detail_rows VALUES (?, ?, ?)", (("purchase_line", r["Reference No"].strip(), json.dumps(r, ensure_ascii=False, sort_keys=True)) for r in selected_purchases))
        connection.executemany("INSERT INTO detail_rows VALUES (?, ?, ?)", (("purchase_line", reference, json.dumps(line, ensure_ascii=False, sort_keys=True)) for reference, line in supplemental_purchase_lines))
        connection.executemany("INSERT INTO detail_rows VALUES (?, ?, ?)", (("stock_position", r.get("SKU", "").strip(), json.dumps(r, ensure_ascii=False, sort_keys=True)) for r in stock_rows))
        for entity, docs in document_groups.items():
            connection.executemany("INSERT INTO detail_documents VALUES (?, ?, ?)", ((entity, str(d["reference"]).strip(), json.dumps(d, ensure_ascii=False, sort_keys=True)) for d in docs))
        connection.executemany("INSERT INTO validation_results VALUES (?, ?, ?)", validations)
        connection.commit()
    finally:
        connection.close()

    failed = [name for name, status, _ in validations if status == "failed"]
    return {
        "status": "passed" if not failed else "failed",
        "database": str(output),
        "manifest_files_verified": len(manifest),
        "delta_rows": len(delta_rows),
        "detail_rows": {"sales": len(selected_sales), "purchases": len(selected_purchases) + len(supplemental_purchase_lines), "stock_positions": len(stock_rows)},
        "detail_documents": {key: len(value) for key, value in document_groups.items()},
        "exceptions": [name for name, status, _ in validations if status == "exception"],
        "failed_checks": failed,
        "production_merge_allowed": False,
        "posting_enabled": False,
    }
