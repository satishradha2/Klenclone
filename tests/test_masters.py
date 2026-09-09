from types import SimpleNamespace

from klen_clone.masters import party_master_status, product_master_status


def test_party_master_requires_source_code_and_name():
    assert party_master_status(SimpleNamespace(contact_id="CO0001", business_name="Acme", name=None)) == "migration_locked_ready"
    assert party_master_status(SimpleNamespace(contact_id=None, business_name="Acme", name=None)) == "review_required"


def test_product_without_tax_is_preserved_but_requires_review():
    assert product_master_status(SimpleNamespace(sku="1001", name="Paper", tax_name="VAT")) == "migration_locked_ready"
    assert product_master_status(SimpleNamespace(sku="1002", name="Tape", tax_name=None)) == "review_required_tax_unassigned"
