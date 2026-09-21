from klen_clone.coverage import reference_identity, residual_class


def test_residual_class_keeps_hrm_archival_and_sales_workflow_pending():
    assert residual_class("attendance") == ("operational_pending", "structured_promotion_required")
    assert residual_class("sales_quotation") == ("operational_pending", "structured_promotion_required")


def test_reference_identity_prefers_source_code():
    assert reference_identity("category", {"Category Code": "CAT-1", "Category": "Paper"}, 5) == ("CAT-1", "Paper")
    assert reference_identity("brand", {"Brands": "Acme"}, 5) == ("ACME", "Acme")
