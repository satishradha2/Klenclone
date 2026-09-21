from klen_clone.security import permission_module, role_code


def test_permission_classifier_includes_hrm_and_excludes_payroll():
    assert permission_module("essentials.view_all_payroll", "View payroll") == "payroll"
    assert permission_module("essentials.approve_leave", "Approve Leave") == "hrm"
    assert permission_module("purchase.create", "Add purchase") == "purchase"


def test_role_code_is_stable_and_not_display_dependent():
    assert role_code("Stock Transfer Coordinator") == "stock_transfer_coordinator"
