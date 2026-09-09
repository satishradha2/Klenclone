from decimal import Decimal

from klen_clone.export_packages import _csv_bytes, _reconciliation


def test_csv_export_neutralizes_formula_text_without_changing_negative_numbers():
    content = _csv_bytes([{"label": "=2+2", "quantity": Decimal("-2.5")}]).decode("utf-8-sig")

    assert "'=2+2" in content
    assert ",-2.5" in content
    assert "'-2.5" not in content


def test_inventory_reconciliation_applies_directional_movement_sign():
    datasets = {"inventory_movements": [
        {"movement_type": "sale_issue", "entered_quantity": Decimal("2"),
         "factor_to_base_snapshot": Decimal("3"), "quantity_base": Decimal("-6")},
        {"movement_type": "purchase_receipt", "entered_quantity": Decimal("2"),
         "factor_to_base_snapshot": Decimal("3"), "quantity_base": Decimal("6")},
        {"movement_type": "sale_return_receipt", "entered_quantity": None,
         "factor_to_base_snapshot": None, "quantity_base": None},
    ]}

    controls = _reconciliation("inventory", datasets)["control_totals"]["inventory_movements"]

    assert controls["quantity_formula_mismatches"] == 0
    assert controls["quantity_formula_incomplete_rows"] == 1
