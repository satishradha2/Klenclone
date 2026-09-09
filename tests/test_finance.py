from decimal import Decimal

import pytest

from datetime import datetime
from zoneinfo import ZoneInfo

from klen_clone.finance import choose_line_semantics, controlled_return_offset, controlled_rounding_adjustment, controlled_settlement_rounding, expected_document_total, local_datetime_key, normalize_party


def test_sales_lines_already_include_tax_and_only_header_discount_is_removed():
    assert expected_document_total("sale", Decimal("105.00"), Decimal("5.00"), Decimal("2.00")) == Decimal("103.00")


def test_purchase_lines_receive_document_vat_and_discount():
    assert expected_document_total("purchase", Decimal("100.00"), Decimal("5.00"), Decimal("2.00")) == Decimal("103.00")


def test_unknown_document_kind_is_rejected():
    with pytest.raises(ValueError):
        expected_document_total("other", Decimal("1"), Decimal("0"), Decimal("0"))


def test_party_normalization_is_exact_but_format_tolerant():
    assert normalize_party("  Oman Plastic LLC, ") == "oman plastic llc"


def test_local_timestamp_key_matches_sqlite_naive_and_parsed_dubai_time():
    naive = datetime(2026, 8, 17, 10, 37)
    aware = naive.replace(tzinfo=ZoneInfo("Asia/Dubai"))
    assert local_datetime_key(naive) == local_datetime_key(aware)


def test_return_offsets_only_an_equal_nonzero_sales_settlement_residual():
    assert controlled_return_offset("sale", Decimal("-31.50"), Decimal("31.50")) == Decimal("31.50")
    assert controlled_return_offset("sale", Decimal("0"), Decimal("31.50")) == Decimal("0")
    assert controlled_return_offset("purchase", Decimal("-31.50"), Decimal("31.50")) == Decimal("0")


def test_purchase_line_semantics_switch_only_when_inclusive_total_exactly_matches_header():
    total, semantics = choose_line_semantics("purchase", Decimal("7287"), Decimal("7287"), Decimal("347.0122"), Decimal("0"))
    assert total == Decimal("7287")
    assert semantics == "includes_tax"


def test_sales_discount_is_not_subtracted_twice_when_line_total_matches_header():
    total, semantics = choose_line_semantics("sale", Decimal("100"), Decimal("100"), Decimal("4.76"), Decimal("8.70"))
    assert total == Decimal("100")
    assert semantics == "includes_tax_and_header_discount"


def test_small_difference_is_rounding_only_when_tax_control_matches():
    assert controlled_rounding_adjustment(Decimal("0.05"), Decimal("0")) == Decimal("0.05")
    assert controlled_rounding_adjustment(Decimal("0.11"), Decimal("0")) == Decimal("0")
    assert controlled_rounding_adjustment(Decimal("0.05"), None) == Decimal("0")
    assert controlled_settlement_rounding(Decimal("-0.10")) == Decimal("-0.10")
    assert controlled_settlement_rounding(Decimal("-0.11")) == Decimal("0")
