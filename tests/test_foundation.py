from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from klen_clone.foundation import ARCHIVAL_ONLY_MODULES, OPERATIONAL_MODULES, _business_control, canonical_content_hash, parse_reference, source_entity_counts_statement


def test_parse_reference_preserves_prefix_and_width():
    assert parse_reference("AK2026-00361") == ("AK2026-", 361, 5)
    assert parse_reference("NUVO-0003") == ("NUVO-", 3, 4)
    assert parse_reference("no-number") is None


def test_canonical_content_hash_is_key_order_independent():
    left = SimpleNamespace(payload={"b": 2, "a": 1}, payload_text=None)
    right = SimpleNamespace(payload={"a": 1, "b": 2}, payload_text=None)
    assert canonical_content_hash(left) == canonical_content_hash(right)


def test_hrm_is_operational_and_payroll_remains_archival_only():
    assert "hrm" in OPERATIONAL_MODULES
    assert set(ARCHIVAL_ONLY_MODULES) == {"payroll"}
    assert not set(ARCHIVAL_ONLY_MODULES) & set(OPERATIONAL_MODULES)


def test_business_control_extracts_named_value_without_guessing():
    record = SimpleNamespace(manifest=SimpleNamespace(entity_type="business_setting"), payload={"controls": [
        {"name": "tax_label_1", "value": "TRN"}, {"name": "tax_number_1", "value": "12345"}
    ]})
    assert _business_control([record], "tax_number_1") == "12345"
    assert _business_control([record], "tax_number_2") is None


def test_source_entity_business_count_is_postgresql_compatible():
    compiled = str(source_entity_counts_statement(1).compile(dialect=postgresql.dialect()))
    assert "CASE WHEN" in compiled
    assert "sum(CAST" not in compiled
