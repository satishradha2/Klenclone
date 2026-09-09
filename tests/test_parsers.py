from pathlib import Path

from klen_clone.parsers import infer_entity, presentation_row, source_keys


def test_specific_entity_rules_precede_generic_sales_rule():
    assert infer_entity(Path("product_sales_detail_2026-04.csv")) == "sales_line"
    assert infer_entity(Path("sales_payments_2026.csv")) == "sales_payment"
    assert infer_entity(Path("sales_2026.csv")) == "sale"


def test_presentation_rows_are_quarantined_not_dropped():
    assert presentation_row({"Date": "Total:", "Amount": "AED 10.00"})
    assert presentation_row({"Product": "Select All Delete Selected"})
    assert presentation_row({"Product": "Bulk Edit Add to location WooCommerce Sync"})
    assert presentation_row({"Report title": "Account", "column_2": "Debit", "column_3": "Credit"})
    assert not presentation_row({"Invoice No.": "AK2026-0001", "Amount": "10.00"})
    assert not presentation_row({"role": "Cashier", "controls": [{"label": "Select all"}]})


def test_source_keys_support_structured_and_detail_payloads():
    assert source_keys({"Invoice No.": "AK2026-0001"}) == (None, "AK2026-0001")
    assert source_keys({"Purchase No": "PO2026/0001"}) == (None, "PO2026/0001")
    _, document = source_keys({"text": "Stock transfer details (Reference No: #ST2026/0005)"})
    assert document == "ST2026/0005"
