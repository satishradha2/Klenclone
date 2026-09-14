from decimal import Decimal

from klen_clone.transform import _parse_purchase_return_snapshot, _parse_tab_lines, clean, datetime_value, decimal_value, quantity_value


def test_value_normalization_uses_decimal_and_dubai_time():
    assert decimal_value("Purchase: AED 1,234.5678") == Decimal("1234.5678")
    assert decimal_value("AED -71.40") == Decimal("-71.40")
    assert quantity_value("0.75 Carton") == (Decimal("0.75"), "Carton")
    assert datetime_value("09/08/2026 19:19").utcoffset().total_seconds() == 14400
    assert clean("  Al   Mas  ") == "Al Mas"


def test_sales_return_and_transfer_lines_are_typed():
    sale_text = "1\tPaper Cup\tAED 45.00\t0.75 Carton\tAED 33.75"
    line = _parse_tab_lines(sale_text, "sales_return")[0]
    assert line["quantity"] == Decimal("0.75") and line["subtotal"] == Decimal("33.75")
    transfer_text = "1\tClear Tape - 98081\tSHJ\tDXB\t-\t1.00 Carton\t61.9"
    line = _parse_tab_lines(transfer_text, "stock_transfer")[0]
    assert line["sku"] == "98081" and line["location_to"] == "DXB"


def test_purchase_return_snapshot_supports_parent_form_rows():
    snapshot = '''
    - row "# Product Name Unit Price Return Quantity Return Subtotal"
    - row "1 Paper Cup AED 10.00 2.00 Carton AED 20.00":
      - cell "1"
      - cell "Paper Cup"
      - cell "AED 10.00"
      - cell "5.00 Carton"
      - cell "3.00 Carton"
      - cell "2.00 Carton"
      - cell "AED 20.00"
'''
    line = _parse_purchase_return_snapshot(snapshot)[0]
    assert line["product_name"] == "Paper Cup"
    assert line["quantity"] == Decimal("2.00")
    assert line["unit"] == "Carton"
    assert line["subtotal"] == Decimal("20.00")


def test_purchase_return_inherits_purchase_uom_when_return_cell_has_quantity_only():
    snapshot = '''
    - row "1 Paper Cup AED 10.00 5.00 Carton 3.00 2.00 AED 20.00":
      - cell "1"
      - cell "Paper Cup"
      - cell "AED 10.00"
      - cell "5.00 Carton"
      - cell "3.00 Carton"
      - cell "2.00"
      - cell "AED 20.00"
'''
    line = _parse_purchase_return_snapshot(snapshot)[0]
    assert line["quantity"] == Decimal("2.00")
    assert line["unit"] == "Carton"
