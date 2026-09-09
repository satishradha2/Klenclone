from klen_clone.resolve import normalize_name


def test_name_normalization_handles_source_spacing_and_punctuation():
    assert normalize_name("Tea Gallery Cafeteria,   Sidhick") == normalize_name("Tea Gallery Cafeteria, Sidhick")
    assert normalize_name("Rukn Al Samaa LLC,") == normalize_name("RUKN AL SAMAA LLC")
