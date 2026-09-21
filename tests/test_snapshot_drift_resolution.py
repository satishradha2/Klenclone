from pathlib import Path

from klen_clone.resolve_snapshot_drift import build_resolution_evidence, resolution_code


def test_builds_only_checksum_proven_snapshot_relationship_resolutions():
    evidence = build_resolution_evidence(Path("source_exports"))

    assert len(evidence) == 168
    assert evidence[151]["control_disposition"] == "invalid_hierarchical_row_sum_not_a_ledger_balance"
    assert evidence[151]["supplier_parent_aed"] == evidence[151]["supplier_children_net_aed"] == "38953.43"
    assert evidence[152]["control_disposition"] == "non_atomic_capture_timing_reconciled"
    assert evidence[152]["later_activity_aed"] == "373.50"
    assert evidence[152]["mismatched_accounts"]["RAK 1 - Suveesh"]["later_cash_flow_net_aed"] == "231.00"
    assert evidence[160]["journal_disposition"] == "balanced_gross_cost_without_input_vat_claim"
    assert evidence[160]["header_total_aed"] == evidence[160]["line_total_aed"] == "100.00"
    assert evidence[164]["input_vat_claim_aed"] == "0.00"
    assert evidence[136]["settlement_disposition"] == "embedded_return_settlement_preserved_without_synthetic_payment"
    assert evidence[136]["settlement_amount_aed"] == "31.50"
    assert evidence[137]["return_document"] == "2026/0001"
    assert evidence[138]["parent_document"] is None
    assert evidence[139]["canonical_cash_flow_rows"] == 1
    assert evidence[140]["payment_capture_rows"] == 3
    assert evidence[140]["cash_flow_candidate_rows"] == 0
    assert evidence[146]["parent_document"] == "AK2026-01088"
    assert evidence[149]["settlement_disposition"] == "preserve_as_historical_nonposting_payment_without_synthetic_cash_event"
    assert 141 not in evidence
    assert 50 not in evidence
    assert 64 not in evidence
    assert 65 not in evidence
    assert 81 not in evidence
    assert 83 not in evidence
    assert 84 not in evidence
    assert 85 not in evidence
    assert 92 not in evidence
    assert evidence[165]["positive_positions"] == 579
    assert evidence[165]["negative_positions_quarantined"] == 4
    assert evidence[169]["net_quantity"] == "29124.02"
    assert len(evidence[94]["source_definitions"]) == 6
    assert len(evidence[95]["source_definitions"]) == 25
    assert evidence[98]["conversion_policy"] == "require_product_specific_factor_to_base_snapshot"
    assert evidence[183]["supporting_evidence_ids"] == [23, 128]
    assert evidence[186]["supporting_evidence_ids"] == [12]
    assert evidence[125]["unclaimed_vat_component_aed"] == "79.50"
    assert evidence[127]["gross_purchase_total_aed"] == "472.50"
    assert evidence[157]["supporting_evidence_ids"] == [125]
    assert evidence[159]["input_vat_claim_aed"] == "0.00"
    assert evidence[172]["availability_enabled"] is False
    assert evidence[175]["quantity_base_quarantined"] == "-1.00"
    assert evidence[99]["supporting_evidence_ids"] == [40, 44, 45, 47, 49]
    assert evidence[102]["supporting_evidence_ids"] == [58, 59, 60, 61]
    assert evidence[176]["quantity_base"] == "0.00"
    assert evidence[69]["supporting_evidence_ids"] == [110]
    assert evidence[71]["supporting_evidence_ids"] == [112, 113]
    assert evidence[86]["supporting_evidence_ids"] == [128]
    assert evidence[93]["supporting_evidence_ids"] == [135]
    assert evidence[37]["quantity_base"] == "-1.00"
    assert evidence[40]["factor_to_base_snapshot"] == "20"
    assert evidence[42]["quantity_base"] == "-18.00"
    assert evidence[47]["quantity_base"] == "6.00"
    assert evidence[49]["quantity_base"] == "21.20"
    assert evidence[58]["factor_to_base_snapshot"] == "1"
    assert evidence[62]["quantity_base"] == "-120.00"
    assert evidence[26]["document_no"] == "AK2026-03609"
    assert evidence[26]["location"] == "RAK"
    assert evidence[36]["document_no"] == "AK2026-03607"
    assert evidence[36]["location"] == "SHJ"
    assert evidence[56]["direction"] == "transfer_out"
    assert evidence[57]["direction"] == "transfer_in"
    assert evidence[188]["location_quantity"] == evidence[188]["master_quantity"] == "1.00"
    assert evidence[66]["paid_aed"] == evidence[66]["header_total_aed"] == "29.50"
    assert evidence[107]["due_aed"] == "0.00"
    assert evidence[12]["sku"] == "92142"
    assert evidence[12]["line_disposition"] == "exclude_from_posting_zero_quantity"
    assert evidence[14]["sku"] == "92882"
    assert evidence[14]["line_disposition"] == "eligible_for_controlled_mapping"
    assert evidence[16]["sku"] == "92899"
    assert evidence[19]["parent_document"] == "AK2026-02777"
    assert evidence[22]["document_no"] == "ST2026/0927"
    assert evidence[22]["sku"] == "98081"
    assert evidence[23]["payment_reference"] == "PP2026/0346"
    assert evidence[23]["candidate_count_after_multi_field_match"] == 1
    assert evidence[24]["parent_residual_aed"] == "0.30"
    assert evidence[25]["parent_document"] == "AK2026-03080"
    assert evidence[25]["payment_amount_aed"] == "83.00"
    assert evidence[114]["payment_reference"] == "SP2026/3240"
    assert evidence[114]["settlement_disposition"] == "payment_allocation_relationship_proven"
    assert evidence[128]["payment_reference"] == "PP2026/0346"
    assert evidence[129]["parent_residual_aed"] == "0.30"
    assert evidence[113]["settlement_disposition"] == "balanced_with_customer_return_credit"
    assert evidence[113]["net_sale_aed"] == "0.05"
    assert evidence[118]["sell_return_due_aed"] == "0.25"
    assert evidence[120]["return_total_aed"] == "62.8425"
    assert evidence[124]["receipt_total_aed"] == "90.00"
    assert evidence[116]["settlement_disposition"] == "later_receipts_reconciled"
    assert evidence[116]["receipt_total_aed"] == "250.00"
    assert evidence[110]["allocation_disposition"] == "balanced_as_fully_returned_sale"
    assert evidence[110]["net_sale_aed"] == "-0.10"
    assert evidence[121]["return_total_aed"] == "39.90"
    assert evidence[130]["allocation_disposition"] == "return_adjusted_purchase_lines_reconciled"
    assert evidence[130]["returned_line_gap_aed"] == "370.00"
    assert evidence[135]["purchase_total_aed"] == "7799.41"
    assert resolution_code(26) == "DETERMINISTIC_MOVEMENT_MAPPING_PROVEN"
    assert resolution_code(103) == "TAX_DOCUMENT_RELATIONSHIP_PROVEN"
    assert resolution_code(66) == "LATER_CAPTURE_SETTLEMENT_RECONCILED"
    assert resolution_code(12) == "ZERO_QUANTITY_RETURN_PLACEHOLDER_CLASSIFIED"
    assert resolution_code(14) == "RETURN_LINE_PRODUCT_RELATIONSHIP_PROVEN"
    assert resolution_code(22) == "TRANSFER_LINE_RELATIONSHIP_PROVEN"
    assert resolution_code(23) == "PAYMENT_PARENT_MULTI_FIELD_MATCH_PROVEN"
    assert resolution_code(114) == "PAYMENT_PARENT_SETTLEMENT_RECONCILED"
    assert resolution_code(113) == "SALES_RETURN_DUE_SETTLEMENT_RECONCILED"
    assert resolution_code(116) == "LATER_PAYMENT_SETTLEMENT_RECONCILED"
    assert resolution_code(110) == "SALES_RETURN_NET_ALLOCATION_RECONCILED"
    assert resolution_code(130) == "PURCHASE_RETURN_LINE_GAP_RECONCILED"
    assert resolution_code(151) == "HIERARCHICAL_TRIAL_BALANCE_AGGREGATION_CLASSIFIED"
    assert resolution_code(152) == "NON_ATOMIC_ACCOUNT_CAPTURE_DRIFT_RECONCILED"
    assert resolution_code(160) == "GROSS_COST_JOURNAL_WITHOUT_INPUT_VAT_APPROVED"
    assert resolution_code(136) == "RETURN_REGISTER_EMBEDDED_SETTLEMENT_PROVEN"
    assert resolution_code(140) == "NONPOSTING_PAYMENT_REGISTER_SETTLEMENT_PRESERVED"
    assert resolution_code(37) == "PRODUCT_SPECIFIC_UOM_MOVEMENT_PROVEN"
    assert resolution_code(63) == "PRODUCT_SPECIFIC_UOM_MOVEMENT_PROVEN"
    assert resolution_code(69) == "FINANCIAL_DOCUMENT_REVIEW_RECONCILED"
    assert resolution_code(165) == "OPENING_STOCK_APPROVED_RECONCILED_IMPORT"
    assert resolution_code(94) == "GLOBAL_UOM_ALIAS_BLOCKED_PRODUCT_SPECIFIC_FACTORS_REQUIRED"
    assert resolution_code(183) == "MULTI_FIELD_AMBIGUOUS_RELATIONSHIP_RESOLVED"
    assert resolution_code(125) == "GROSS_COST_ALLOCATION_WITH_UNCLAIMED_VAT_CLASSIFIED"
    assert resolution_code(157) == "GROSS_COST_JOURNAL_BLUEPRINT_CLASSIFIED"
    assert resolution_code(172) == "NEGATIVE_STOCK_QUARANTINED_NOT_AVAILABLE"
    assert resolution_code(99) == "PRODUCT_SPECIFIC_UOM_CONVERSION_GROUP_RECONCILED"
    assert resolution_code(176) == "ZERO_QUANTITY_LOCATIONLESS_STOCK_EXCLUDED"
