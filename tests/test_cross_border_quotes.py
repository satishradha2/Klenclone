import base64
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from klen_clone.commercial_pricing import (
    approve_price_list, assign_customer_price_group, create_customer_price_group,
    create_price_list,
)
from klen_clone.fx_controls import decide_fx_rate, prepare_fx_rate
from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.operational_masters import OperationalPartyMaster
from klen_clone.quote_trade_controls import (
    approved_trade_decision, decide_trade_decision, prepare_trade_decision,
)
from klen_clone.sales_orders import create_sales_quotation, convert_sales_quotation
from klen_clone.cross_border_order_controls import (
    prepare_order_release, decide_order_release, quotation_fingerprint,
)
from klen_clone.credit_management import OperationalCustomerCreditProfile, customer_exposure
from klen_clone.delivery_fulfillment import OperationalDeliveryFulfillment, allocate_sales_order
from klen_clone.delivery_fulfillment import transition_delivery
from klen_clone.cross_border_delivery_readiness import prepare_readiness, decide_readiness
from klen_clone.cross_border_dispatch_release import prepare_dispatch_release, decide_dispatch_release
from klen_clone.operational import OperationalStockPosition
from klen_clone.customer_invoices import create_customer_invoice
from klen_clone.customer_invoices import transition_customer_invoice
from klen_clone.cross_border_invoice_tax import (
    OperationalExportEvidenceDocument, prepare_export_tax_decision,
    decide_export_tax_decision, approved_export_tax_decision,
)


@pytest.fixture
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def line(price="10", tax="0"):
    return {"sku": "SKU-001", "product_name_snapshot": "Test product",
            "quantity": Decimal("2"), "uom": "Piece", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "quantity_base": Decimal("2"),
            "unit_price": Decimal(price), "tax_rate": Decimal(tax),
            "net_amount": Decimal(price) * 2, "tax_amount": Decimal("0"),
            "gross_amount": Decimal(price) * 2}


def quote(session, **changes):
    values = dict(customer_code="C-SA", customer_name_snapshot="Saudi Customer",
        customer_country_code="SA", location_code="SHJ", quotation_date=date.today(),
        valid_until=date.today() + timedelta(days=30), currency_code="SAR",
        discount_amount=Decimal("0"), payment_terms=None, delivery_terms=None,
        notes=None, actor="sales-user", lines=[line()], trade_decision_key=None)
    values.update(changes)
    return create_sales_quotation(session, **values)


def test_cross_border_quote_needs_approved_price_fx_and_trade_decision(session):
    session.add(OperationalPartyMaster(party_key="foreign-party", party_code="C-SA",
        party_kind="customer", legal_or_business_name="Saudi Customer",
        country_code="SA", preferred_currency_code="SAR", status="active",
        source_snapshot_name="test", source_checksum="0" * 64,
        created_by="test", updated_by="test"))
    session.commit()
    create_customer_price_group(session, group_code="GCC", name="GCC customers", actor="pricing-maker")
    assign_customer_price_group(session, customer_code="C-SA", group_code="GCC", actor="pricing-maker")
    price_list = create_price_list(session, name="Saudi price list", customer_group="GCC",
        currency_code="SAR", effective_from=date.today(), effective_to=None,
        max_discount_percent=Decimal("5"), items=[{"sku": "SKU-001", "unit_price": Decimal("10")}],
        actor="pricing-maker")
    with pytest.raises(ValueError, match="approved effective price list"):
        quote(session)
    approve_price_list(session, key=price_list.price_list_key, actor="pricing-checker")
    with pytest.raises(ValueError, match="trade decision"):
        quote(session)
    decision = prepare_trade_decision(session, customer_code="C-SA",
        destination_country_code="SA", currency_code="SAR", quotation_date=date.today(),
        line_tax_rates=[{"sku": "SKU-001", "tax_rate": "0"}],
        provisional_tax_basis="Export quotation assumption pending documentary proof",
        trade_terms="FCA Dubai", evidence_reference="TRADE-001", actor="tax-maker")
    with pytest.raises(PermissionError, match="self-approval"):
        decide_trade_decision(session, decision, action="approve", expected_revision=1,
            note="Review complete", actor="tax-maker")
    with pytest.raises(ValueError, match="trade decision"):
        quote(session, trade_decision_key=decision.decision_key)
    decide_trade_decision(session, decision, action="approve", expected_revision=1,
        note="Independent provisional tax review", actor="tax-checker")
    with pytest.raises(ValueError, match="FX reference"):
        quote(session, trade_decision_key=decision.decision_key)
    rate = prepare_fx_rate(session, currency_code="SAR", rate_date=date.today(),
        aed_per_unit=Decimal("0.97930000"), source_name="Commercial source",
        source_reference="FX-001", reason="Quote planning", actor="fx-maker")
    decide_fx_rate(session, rate, action="approve", expected_revision=1,
        note="Independent FX check", actor="fx-checker")
    with pytest.raises(ValueError, match="tax rates must match"):
        approved_trade_decision(session, decision_key=decision.decision_key,
            customer_code="C-SA", destination_country_code="SA", currency_code="SAR",
            quotation_date=date.today(), lines=[line(tax="5")])
    with pytest.raises(ValueError, match="approved limit"):
        quote(session, trade_decision_key=decision.decision_key, discount_amount=Decimal("1.01"))
    document = quote(session, trade_decision_key=decision.decision_key, discount_amount=Decimal("1"))
    assert document.currency_code == "SAR"
    assert document.fx_rate_key == rate.rate_key
    assert document.trade_decision_key == decision.decision_key
    assert document.lines[0].discount_amount == Decimal("1.00")
    assert document.total_amount == Decimal("19.00")
    assert document.aed_total_snapshot == Decimal("18.61")
    assert document.posting_enabled is False
    document.status = "accepted"
    session.commit()
    with pytest.raises(ValueError, match="approved cross-border order release"):
        convert_sales_quotation(session, document, expected_revision=1, actor="sales-user")
    release = prepare_order_release(session, document, expected_revision=1,
        order_tax_review_basis="Order-stage review of provisional quote tax",
        fulfillment_evidence_required="Customs and export evidence before delivery",
        evidence_reference="ORDER-REVIEW-001", valid_until=document.valid_until,
        actor="tax-maker")
    document.delivery_terms = "Altered after review request"
    with pytest.raises(ValueError, match="Quotation changed"):
        decide_order_release(session, release, expected_revision=1, action="approve",
            note="Independent review", actor="finance-checker")
    document.delivery_terms = None
    session.commit()
    with pytest.raises(PermissionError, match="Independent order reviewer"):
        decide_order_release(session, release, expected_revision=1, action="approve",
            note="Independent review", actor="tax-maker")
    with pytest.raises(PermissionError, match="Independent order reviewer"):
        decide_order_release(session, release, expected_revision=1, action="approve",
            note="Independent review", actor="sales-user")
    decide_order_release(session, release, expected_revision=1, action="approve",
        note="Reviewed order-stage risk", actor="finance-checker")
    with pytest.raises(ValueError, match="credit profile"):
        convert_sales_quotation(session, document, expected_revision=1, actor="sales-user")
    session.add(OperationalCustomerCreditProfile(profile_key="credit-sa", party_code="C-SA",
        party_name_snapshot="Saudi Customer", credit_limit=Decimal("18.60"),
        payment_terms_days=30, status="active", posting_enabled=False,
        created_by="credit-maker", approved_by="credit-checker", updated_by="credit-checker"))
    session.commit()
    with pytest.raises(ValueError, match="AED credit commitment blocked"):
        convert_sales_quotation(session, document, expected_revision=1, actor="sales-user")
    profile = session.query(OperationalCustomerCreditProfile).filter_by(party_code="C-SA").one()
    profile.credit_limit = Decimal("100")
    session.commit()
    assert quotation_fingerprint(document) == release.quotation_fingerprint
    order = convert_sales_quotation(session, document, expected_revision=1, actor="sales-user")
    assert order.currency_code == "SAR"
    assert order.aed_total_snapshot == Decimal("18.61")
    assert order.order_release_key == release.release_key
    assert release.status == "consumed"
    assert customer_exposure(session, "C-SA", as_of=date.today())["open_order_commitment"] == Decimal("18.61")
    assert convert_sales_quotation(session, document, expected_revision=1, actor="sales-user").id == order.id
    with pytest.raises(ValueError, match="approved delivery readiness"):
        allocate_sales_order(session, order, actor="warehouse-user", note="Test allocation")
    readiness = prepare_readiness(session, order, transport_plan="Road freight via carrier",
        customs_evidence_plan="Declaration and shipment records before dispatch",
        evidence_reference="SHIP-PLAN-001", valid_until=date.today() + timedelta(days=7),
        actor="warehouse-user")
    with pytest.raises(PermissionError, match="Independent reviewer"):
        decide_readiness(session, readiness, expected_revision=1, action="approve",
            note="Attempted self approval", actor="warehouse-user")
    decide_readiness(session, readiness, expected_revision=1, action="approve",
        note="Reviewed reservation and pick plan", actor="finance-checker")
    session.add(OperationalStockPosition(location_code="SHJ", sku="SKU-001", canonical_uom="piece",
        quantity_on_hand=Decimal("5"), quantity_reserved=Decimal("0"),
        average_unit_cost=Decimal("4"), revision=1, source_batch_key="test",
        source_status="operational", availability_enabled=True))
    session.commit()
    delivery = allocate_sales_order(session, order, actor="warehouse-user", note="Approved staging reservation")
    assert delivery.status == "allocated" and delivery.posting_enabled is False
    delivery = transition_delivery(session, delivery, expected_revision=1, action="pick",
        actor="picker", note="Picked approved order")
    with pytest.raises(ValueError, match="approved shipment/clearance dispatch release"):
        transition_delivery(session, delivery, expected_revision=2, action="dispatch",
            actor="dispatcher", note="Premature dispatch")
    session.rollback()
    shipment = prepare_dispatch_release(session, delivery, carrier_name="Test Road Carrier",
        transport_reference="BOOKING-SA-001", packing_list_reference="PACK-SA-001",
        customs_declaration_reference="CUSTOMS-SA-001",
        destination_consignment_reference="DEST-SA-001",
        valid_until=date.today() + timedelta(days=5), actor="warehouse-user")
    with pytest.raises(PermissionError, match="Independent reviewer"):
        decide_dispatch_release(session, shipment, expected_revision=1, action="approve",
            note="Attempted own shipment approval", actor="warehouse-user")
    decide_dispatch_release(session, shipment, expected_revision=1, action="approve",
        note="Checked shipment and clearance references", actor="finance-checker")
    delivery = transition_delivery(session, delivery, expected_revision=2, action="dispatch",
        actor="dispatcher", note="Cleared shipment handoff", vehicle_number="ROAD-SA-01")
    assert shipment.status == "consumed" and delivery.status == "dispatched"
    assert delivery.posting_enabled is False
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Customer receipt checked", received_by="Customer Receiver",
        pod_reference="POD-SA-001")
    assert delivery.status == "delivered"
    with pytest.raises(ValueError, match="approved export tax decision"):
        create_customer_invoice(session, delivery, actor="billing-user",
            invoice_date=date.today(), due_date=date.today())
    phantom_delivery = OperationalDeliveryFulfillment(sales_order=order, status="delivered",
        delivered_at=datetime.now(), delivery_note_no="DUMMY-FOREIGN",
        pod_reference="POD-FOREIGN", received_by="Receiver")
    with pytest.raises(ValueError, match="physical dispatch release"):
        create_customer_invoice(session, phantom_delivery, actor="billing-user",
            invoice_date=date.today(), due_date=date.today())
    document_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    evidence = lambda kind: {"kind": kind, "filename": f"{kind}.pdf",
        "content_type": "application/pdf",
        "content_base64": base64.b64encode(document_bytes).decode()}
    with pytest.raises(ValueError, match="evidence pair|evidence combination|Zero-rating"):
        prepare_export_tax_decision(session, delivery, tax_treatment="zero_rated",
            tax_basis="Actual exported goods reviewed for zero rating", valid_until=date.today()+timedelta(days=5),
            documents=[evidence("customs_declaration")], actor="tax-maker")
    review = prepare_export_tax_decision(session, delivery, tax_treatment="zero_rated",
        tax_basis="Actual exported goods reviewed for zero rating", valid_until=date.today()+timedelta(days=5),
        documents=[evidence("customs_declaration"), evidence("commercial_transport")], actor="tax-maker")
    assert len(review.documents) == 2
    assert all(isinstance(doc, OperationalExportEvidenceDocument) and doc.content_sha256 for doc in review.documents)
    with pytest.raises(PermissionError, match="independent"):
        decide_export_tax_decision(session, review, expected_revision=1, action="approve",
            note="I inspected both export documents and the tax basis", actor="tax-maker")
    with pytest.raises(ValueError, match="revision conflict"):
        decide_export_tax_decision(session, review, expected_revision=2, action="approve",
            note="I inspected both export documents and the tax basis", actor="tax-checker")
    decide_export_tax_decision(session, review, expected_revision=1, action="approve",
        note="I inspected both export documents and the tax basis", actor="tax-checker")
    assert approved_export_tax_decision(session, delivery, invoice_date=date.today()).id == review.id
    review.documents[0].content = b"%PDF-1.4\nchanged after approval"
    with pytest.raises(ValueError, match="integrity"):
        approved_export_tax_decision(session, delivery, invoice_date=date.today())
    session.rollback()
    invoice = create_customer_invoice(session, delivery, actor="billing-user",
        invoice_date=date.today(), due_date=date.today()+timedelta(days=30))
    assert invoice.status == "draft" and invoice.posting_enabled is False
    assert invoice.currency_code == "SAR" and invoice.tax_amount == Decimal("0")
    assert review.status == "consumed"
    with pytest.raises(ValueError, match="remain held"):
        transition_customer_invoice(session, invoice, expected_revision=1, action="submit",
            actor="billing-user", note="Try to submit")
    assert order.posting_enabled is False


@pytest.mark.parametrize(("country", "currency"), [("BH", "BHD"), ("KW", "KWD"), ("OM", "OMR")])
def test_three_decimal_gcc_quotation_retains_minor_units(session, country, currency):
    customer = f"C-{country}"
    session.add(OperationalPartyMaster(party_key=f"foreign-{country}", party_code=customer,
        party_kind="customer", legal_or_business_name=f"{country} Customer",
        country_code=country, preferred_currency_code=currency, status="active",
        source_snapshot_name="test", source_checksum="0" * 64,
        created_by="test", updated_by="test"))
    session.commit()
    create_customer_price_group(session, group_code="GCC3", name="Three-decimal GCC", actor="pricing-maker")
    assign_customer_price_group(session, customer_code=customer, group_code="GCC3", actor="pricing-maker")
    price_list = create_price_list(session, name=f"{currency} prices", customer_group="GCC3",
        currency_code=currency, effective_from=date.today(), effective_to=None,
        max_discount_percent=Decimal("10"),
        items=[{"sku": "SKU-001", "unit_price": Decimal("1.234")}], actor="pricing-maker")
    approve_price_list(session, key=price_list.price_list_key, actor="pricing-checker")
    decision = prepare_trade_decision(session, customer_code=customer,
        destination_country_code=country, currency_code=currency, quotation_date=date.today(),
        line_tax_rates=[{"sku": "SKU-001", "tax_rate": "5"}],
        provisional_tax_basis="Quotation assumption pending evidence",
        trade_terms="FCA Dubai", evidence_reference=f"TRADE-{country}", actor="tax-maker")
    decide_trade_decision(session, decision, action="approve", expected_revision=1,
        note="Independent quote review", actor="tax-checker")
    rate = prepare_fx_rate(session, currency_code=currency, rate_date=date.today(),
        aed_per_unit=Decimal("10"), source_name="Synthetic test source",
        source_reference=f"FX-{country}", reason="Quotation test", actor="fx-maker")
    decide_fx_rate(session, rate, action="approve", expected_revision=1,
        note="Independent FX test", actor="fx-checker")
    item = line(price="1.234", tax="5")
    item.update(tax_amount=Decimal("0.123"), gross_amount=Decimal("2.591"))
    with pytest.raises(ValueError, match="minor-unit precision"):
        quote(session, customer_code=customer, customer_country_code=country,
            currency_code=currency, lines=[item], trade_decision_key=decision.decision_key,
            discount_amount=Decimal("0.0001"))
    document = quote(session, customer_code=customer, customer_country_code=country,
        currency_code=currency, lines=[item], trade_decision_key=decision.decision_key,
        discount_amount=Decimal("0.001"))
    assert document.subtotal == Decimal("2.468")
    assert document.lines[0].discount_amount == Decimal("0.001")
    assert document.lines[0].tax_amount == Decimal("0.123")
    assert document.total_amount == document.lines[0].gross_amount == Decimal("2.590")
    assert document.aed_total_snapshot == Decimal("25.90")
    document.status = "accepted"
    session.add(OperationalCustomerCreditProfile(profile_key=f"credit-{country}", party_code=customer,
        party_name_snapshot=f"{country} Customer", credit_limit=Decimal("100"),
        payment_terms_days=30, status="active", posting_enabled=False,
        created_by="credit-maker", approved_by="credit-checker", updated_by="credit-checker"))
    session.commit()
    release = prepare_order_release(session, document, expected_revision=1,
        order_tax_review_basis="Order-stage review of quotation tax",
        fulfillment_evidence_required="Documentary proof before separate delivery release",
        evidence_reference=f"ORDER-{country}-001", valid_until=document.valid_until,
        actor="tax-maker")
    decide_order_release(session, release, expected_revision=1, action="approve",
        note="Independent order review", actor="finance-checker")
    order = convert_sales_quotation(session, document, expected_revision=1, actor="sales-user")
    session.expire_all()
    assert order.total_amount == order.lines[0].gross_amount == Decimal("2.590")
    assert order.discount_amount == order.lines[0].discount_amount == Decimal("0.001")
    assert customer_exposure(session, customer, as_of=date.today())["open_order_commitment"] == Decimal("25.90")
