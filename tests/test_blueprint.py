from decimal import Decimal

from klen_clone.blueprint import gross_cost_purchase_without_input_vat, location_key


def test_location_key_is_case_and_spacing_tolerant_but_not_fuzzy():
    assert location_key("  Asas General   Trading LLC ") == "asas general trading llc"
    assert location_key("SHJ") != location_key("Sharjah")


def test_gross_cost_purchase_requires_balanced_lines_and_claims_no_inferred_vat():
    assert gross_cost_purchase_without_input_vat(
        "purchase", "not_linked", Decimal("100.00"), Decimal("100.00"), Decimal("0.00")
    )
    assert not gross_cost_purchase_without_input_vat(
        "purchase", "not_linked", Decimal("105.00"), Decimal("100.00"), Decimal("5.00")
    )
    assert not gross_cost_purchase_without_input_vat(
        "sale", "not_linked", Decimal("100.00"), Decimal("100.00"), Decimal("0.00")
    )
