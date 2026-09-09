from klen_clone.accounting import classify_cash_flow, extract_document_no, extract_payment_reference


def test_cash_flow_description_classification():
    assert classify_cash_flow("SalesCustomer: Example") == "sale_receipt"
    assert classify_cash_flow("PurchaseSupplier: Example") == "purchase_payment"
    assert classify_cash_flow("Purchase returnReference No: 2026/0001") == "purchase_return_receipt"
    assert classify_cash_flow("Fund Transfer ( To: Cash Collect)") == "internal_transfer"
    assert classify_cash_flow("Sell returnInvoice No.: AK1") == "sale_return_payment"


def test_concatenated_payment_reference_is_bounded_by_added_by_label():
    description = "SalesCustomer: ExampleInvoice No.: AK2026-00015Pay reference no.: SP2026/0019Added By: User"
    assert extract_payment_reference(description) == "SP2026/0019"
    assert extract_document_no(description, "sale_receipt") == "AK2026-00015"


def test_purchase_document_reference_is_extracted_without_mutating_text():
    description = "PurchaseSupplier: Example, Reference No: PO2026/0013Pay reference no.: PP2026/0003Added By: User"
    assert extract_document_no(description, "purchase_payment") == "PO2026/0013"
