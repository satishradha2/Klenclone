from datetime import date, timedelta

from fastapi.testclient import TestClient
from klen_clone.auth import hash_password
from klen_clone.customer_invoices import create_customer_invoice, transition_customer_invoice
from klen_clone.delivery_fulfillment import allocate_sales_order, transition_delivery
from klen_clone.erp_preview import create_app
from klen_clone.operational import OperationalStockPosition
from klen_clone.operational_masters import OperationalLocationMaster
from decimal import Decimal
from sqlalchemy import select
from klen_clone.sales_orders import (
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    transition_sales_quotation,
)
from test_erp_preview import preview_client, seed_operational_controls


def test_target_invoice_is_selectable_and_return_credit_is_discount_aware(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'returns-operational.db'}")
    client = preview_client(tmp_path)
    seed_operational_controls(client)
    with client.app.state.operational_sessions() as session:
        quote = create_sales_quotation(session, customer_code="CO-001",
            customer_name_snapshot="Test Customer", location_code="SHJ",
            quotation_date=date.today(), valid_until=date.today() + timedelta(days=30),
            discount_amount=1, payment_terms="30 days", delivery_terms="Delivered",
            notes=None, actor="sales-maker", lines=[{
                "sku": "SKU-001", "product_name_snapshot": "Source product",
                "quantity": 2, "uom": "Piece", "canonical_uom": "piece",
                "factor_to_base_snapshot": 1, "quantity_base": 2,
                "unit_price": 10, "tax_rate": 5, "net_amount": 20,
                "tax_amount": 1, "gross_amount": 21}])
        quote = transition_sales_quotation(session, quote, expected_revision=1,
            action="submit", actor="sales-maker")
        quote = transition_sales_quotation(session, quote, expected_revision=2,
            action="approve", actor="sales-checker", note="Commercial check")
        quote = accept_sales_quotation(session, quote, expected_revision=3,
            actor="sales-maker", acceptance_reference="Customer confirmation")
        order = convert_sales_quotation(session, quote, expected_revision=4, actor="sales-maker")
        delivery = allocate_sales_order(session, order, actor="warehouse", note="Allocated")
        delivery = transition_delivery(session, delivery, expected_revision=1,
            action="pick", actor="picker", note="Picked")
        delivery = transition_delivery(session, delivery, expected_revision=2,
            action="dispatch", actor="dispatcher", note="Dispatched")
        delivery = transition_delivery(session, delivery, expected_revision=3,
            action="deliver", actor="pod-checker", note="POD verified",
            received_by="Customer receiver", pod_reference="POD-RETURN-API")
        invoice = create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=delivery.delivered_at.date(),
            due_date=delivery.delivered_at.date() + timedelta(days=30))
        invoice = transition_customer_invoice(session, invoice, expected_revision=1,
            action="submit", actor="sales-maker")
        invoice = transition_customer_invoice(session, invoice, expected_revision=2,
            action="approve", actor="sales-manager", note="POD and totals verified")
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == "SHJ", OperationalStockPosition.sku == "SKU-001"))
        original_issue_cost = position.average_unit_cost
        position.average_unit_cost = Decimal(original_issue_cost) + Decimal("3")
        session.commit()
        invoice_no = invoice.invoice_no
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password"})
    assert login.status_code == 200
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    selected = client.get("/api/v1/selectors/sales-invoices?customer_code=CO-001")
    assert selected.status_code == 200
    assert any(row["document_no"] == invoice_no and row["source_origin"] == "target_erp"
               for row in selected.json()["items"])
    assert next(row for row in selected.json()["items"] if row["document_no"] == invoice_no)["location_code"] == "SHJ"
    return_body = {
        "customer_code": "CO-001", "location_code": "SHJ",
        "original_invoice_reference": invoice_no, "return_date": date.today().isoformat(),
        "reason_code": "customer_return", "lines": [{
            "sku": "SKU-001", "quantity": "1", "restock_quantity": "1",
            "writeoff_quantity": "0", "uom": "Piece", "tax_rate": "5"}]}
    returned = client.post("/api/v1/sales-returns", headers=csrf, json=return_body)
    assert returned.status_code == 201, returned.text
    wrong_location = client.post("/api/v1/sales-returns", headers=csrf,
        json=return_body | {"location_code": "MAIN"})
    assert wrong_location.status_code == 422
    assert "location" in wrong_location.json()["detail"].lower()
    pricing_only = client.post("/api/v1/sales-returns", headers=csrf,
        json=return_body | {"reason_code": "pricing_correction"})
    assert pricing_only.status_code == 422
    body = returned.json()
    assert body["original_invoice_origin"] == "target_erp"
    assert body["total_amount"] == 9.98
    assert body["lines"][0]["unit_cost_snapshot"] == float(original_issue_cost)
    stale = client.post("/api/v1/sales-returns", headers=csrf, json=return_body)
    assert stale.status_code == 201, stale.text
    submitted = client.post(f"/api/v1/sales-returns/{body['return_key']}/submit",
        headers=csrf, json={"expected_revision": 1, "note": "Invoice-linked return"})
    assert submitted.status_code == 200, submitted.text
    remaining = client.get("/api/v1/selectors/sales-invoices?customer_code=CO-001").json()["items"]
    target = next(item for item in remaining if item["document_no"] == invoice_no)
    assert target["lines"][0]["quantity"] == 1
    stale_submit = client.post(f"/api/v1/sales-returns/{stale.json()['return_key']}/submit",
        headers=csrf, json={"expected_revision": 1, "note": "Stale parallel return"})
    assert stale_submit.status_code == 409
    assert "pricing is stale" in stale_submit.json()["detail"]

    # A future target-ERP-only deployment need not retain a BizModo snapshot.
    with client.app.state.operational_sessions() as session:
        session.add(OperationalLocationMaster(
            location_key="target-location-SHJ", location_code="SHJ", name="Sharjah",
            status="active", source_snapshot_name="target-only",
            source_checksum="b" * 64, created_by="test"))
        session.commit()
    target_only_client = TestClient(create_app(
        f"sqlite:///{tmp_path / 'erp-preview.db'}", "missing-source-snapshot"))
    target_login = target_only_client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password"})
    assert target_login.status_code == 200
    target_only_return = target_only_client.post("/api/v1/sales-returns",
        headers={"X-CSRF-Token": target_login.json()["csrf_token"]}, json=return_body)
    assert target_only_return.status_code == 201, target_only_return.text
    assert target_only_return.json()["original_invoice_origin"] == "target_erp"
