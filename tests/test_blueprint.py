from klen_clone.blueprint import location_key


def test_location_key_is_case_and_spacing_tolerant_but_not_fuzzy():
    assert location_key("  Asas General   Trading LLC ") == "asas general trading llc"
    assert location_key("SHJ") != location_key("Sharjah")
