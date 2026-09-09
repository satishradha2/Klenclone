from decimal import Decimal

from klen_clone.inventory import canonical_uom, parse_uom_definition, uom_key


def test_common_source_uom_aliases_are_canonicalized_without_changing_dimension():
    assert canonical_uom("Pc(s)") == "piece"
    assert canonical_uom("Pieces") == "piece"
    assert canonical_uom("CTN") == "carton"
    assert canonical_uom("Kg") == "kg"


def test_explicit_contained_quantity_is_parsed_as_evidence():
    parsed = parse_uom_definition("Carton (20Pc(s))", "ctn")
    assert parsed["canonical_uom"] == "carton"
    assert parsed["contained_quantity"] == Decimal("20")
    assert parsed["contained_uom"] == "piece"
    assert parsed["parse_status"] == "parsed"


def test_base_unit_without_factor_remains_identity_only():
    parsed = parse_uom_definition("Box", "box")
    assert parsed["canonical_uom"] == "box"
    assert parsed["contained_quantity"] is None
    assert parsed["parse_status"] == "base_only"


def test_package_name_key_ignores_display_spacing():
    assert uom_key("Carton (20 Pack)") == uom_key("Carton (20Pack)")
