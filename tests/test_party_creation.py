import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.operational_masters import OperationalPartyMaster
from klen_clone.party_creation import (
    OperationalPartyCreationRequest, decide_party, propose_party,
)


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_customer_is_not_selectable_until_independent_approval(session):
    request = propose_party(session, party_code="C-NEW", party_kind="customer",
        legal_or_business_name="New Customer LLC", tax_number="100000000000001", actor="sales-maker",
        country_code="AE", preferred_currency_code="AED", tax_registration_type="vat", tax_country_code="AE")
    assert request.status == "pending"
    assert session.scalar(select(OperationalPartyMaster).where(
        OperationalPartyMaster.party_code == "C-NEW")) is None
    with pytest.raises(ValueError, match="Maker cannot"):
        decide_party(session, request.request_key, action="approve", actor="sales-maker", note="Self approval")
    approved = decide_party(session, request.request_key, action="approve",
        actor="sales-checker", note="Verified legal documents")
    assert approved.status == "approved"
    record = session.scalar(select(OperationalPartyMaster).where(
        OperationalPartyMaster.party_code == "C-NEW"))
    assert record.status == "active"
    assert record.party_kind == "customer"
    assert record.source_promoted is False
    assert record.source_snapshot_name == "target-created"
    assert record.country_code == "AE"
    assert record.preferred_currency_code == "AED"
    assert record.tax_registration_type == "vat"


def test_supplier_duplicate_code_name_and_trn_are_blocked(session):
    request = propose_party(session, party_code="S-NEW", party_kind="supplier",
        legal_or_business_name="Supplier One", tax_number="100000000000002", actor="buyer",
        country_code="AE", preferred_currency_code="AED", tax_registration_type="vat", tax_country_code="AE")
    with pytest.raises(ValueError, match="code already has a pending"):
        propose_party(session, party_code="s-new", party_kind="supplier",
            legal_or_business_name="Different Name", actor="buyer",
            country_code="AE", preferred_currency_code="AED")
    with pytest.raises(ValueError, match="Business name already has a pending"):
        propose_party(session, party_code="S-OTHER", party_kind="supplier",
            legal_or_business_name="supplier one", actor="buyer",
            country_code="AE", preferred_currency_code="AED")
    with pytest.raises(ValueError, match="Tax number already has a pending"):
        propose_party(session, party_code="S-OTHER", party_kind="supplier",
            legal_or_business_name="Different Name", tax_number="100000000000002", actor="buyer",
            country_code="AE", preferred_currency_code="AED", tax_registration_type="vat", tax_country_code="AE")
    decide_party(session, request.request_key, action="approve", actor="buyer-checker", note="Documents verified")
    with pytest.raises(ValueError, match="Party code already exists"):
        propose_party(session, party_code="S-NEW", party_kind="supplier",
            legal_or_business_name="Different Name", actor="buyer",
            country_code="AE", preferred_currency_code="AED")


def test_rejected_supplier_does_not_enter_master(session):
    request = propose_party(session, party_code="S-REJECT", party_kind="supplier",
        legal_or_business_name="Unverified Supplier", actor="buyer",
        country_code="GB", preferred_currency_code="GBP")
    rejected = decide_party(session, request.request_key, action="reject",
        actor="reviewer", note="Tax evidence was missing")
    assert rejected.status == "rejected"
    assert session.scalar(select(OperationalPartyMaster)) is None
    assert session.scalar(select(OperationalPartyCreationRequest.status)) == "rejected"


def test_gcc_customer_and_international_supplier_are_classified_without_tax_assumptions(session):
    from klen_clone.country_catalog import market_scope
    from klen_clone.procurement import _supplier
    gcc = propose_party(session, party_code="C-GCC", party_kind="customer",
        legal_or_business_name="GCC Customer", actor="sales-maker",
        country_code="SA", preferred_currency_code="SAR")
    international = propose_party(session, party_code="S-INT", party_kind="supplier",
        legal_or_business_name="International Supplier", actor="buyer",
        country_code="DE", preferred_currency_code="EUR")
    decide_party(session, gcc.request_key, action="approve", actor="sales-checker", note="Identity verified")
    decide_party(session, international.request_key, action="approve", actor="buyer-checker", note="Identity verified")
    rows = {row.party_code: row for row in session.scalars(select(OperationalPartyMaster))}
    assert market_scope(rows["C-GCC"].country_code) == "gcc"
    assert market_scope(rows["S-INT"].country_code) == "international"
    assert rows["C-GCC"].tax_number is None
    assert rows["S-INT"].tax_registration_type is None
    with pytest.raises(ValueError, match="Cross-border supplier sourcing is held"):
        _supplier(session, "S-INT")


def test_country_currency_and_tax_issuer_are_validated(session):
    base = dict(party_code="S-VALID", party_kind="supplier",
        legal_or_business_name="Validated Supplier", actor="buyer")
    with pytest.raises(ValueError, match="Country and preferred currency"):
        propose_party(session, **base)
    with pytest.raises(ValueError, match="valid two-letter country"):
        propose_party(session, **base, country_code="ZZ", preferred_currency_code="USD")
    with pytest.raises(ValueError, match="valid three-letter currency"):
        propose_party(session, **base, country_code="US", preferred_currency_code="QQQ")
    with pytest.raises(ValueError, match="registration type"):
        propose_party(session, **base, country_code="US", preferred_currency_code="USD", tax_number="123")
    with pytest.raises(ValueError, match="issuing country"):
        propose_party(session, **base, country_code="US", preferred_currency_code="USD",
            tax_number="123", tax_registration_type="other")
