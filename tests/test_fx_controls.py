from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.fx_controls import (
    OperationalFxRate, approved_fx_rate, decide_fx_rate,
    foreign_invoice_fx_exposure, prepare_fx_rate,
)
from klen_clone.operational import (
    OperationalAuditEvent, initialize_operational_database, make_operational_engine,
)


@pytest.fixture
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def prepare(session, *, actor="maker", currency="USD", day=None):
    return prepare_fx_rate(session, actor=actor, currency_code=currency,
        rate_date=day or date.today(), aed_per_unit=Decimal("3.67250000"),
        source_name="Published reference", source_reference="Evidence document 123",
        reason="Foreign supplier planning")


def test_fx_is_pending_until_independent_approval_and_exact_date_lookup(session):
    day = date.today()
    row = prepare(session, day=day)
    assert approved_fx_rate(session, "USD", day) is None
    with pytest.raises(PermissionError, match="self-approval"):
        decide_fx_rate(session, row, action="approve", expected_revision=1,
                       note="Source checked", actor="maker")
    with pytest.raises(ValueError, match="revision conflict"):
        decide_fx_rate(session, row, action="approve", expected_revision=2,
                       note="Source checked", actor="checker")
    decided = decide_fx_rate(session, row, action="approve", expected_revision=1,
                             note="Evidence independently checked", actor="checker")
    assert decided.revision == 2
    assert approved_fx_rate(session, "USD", day).rate_key == row.rate_key
    assert approved_fx_rate(session, "USD", day - timedelta(days=1)) is None
    assert approved_fx_rate(session, "EUR", day) is None
    events = session.scalars(select(OperationalAuditEvent).where(
        OperationalAuditEvent.resource_key == row.rate_key)).all()
    assert {event.event_type for event in events} == {"fx_rate.prepared", "fx_rate.approve"}


def test_duplicate_approved_currency_day_rejected_without_changing_pending(session):
    first = prepare(session)
    decide_fx_rate(session, first, action="approve", expected_revision=1,
                   note="Evidence checked", actor="checker")
    second = prepare(session, actor="other maker")
    with pytest.raises(ValueError, match="already exists"):
        decide_fx_rate(session, second, action="approve", expected_revision=1,
                       note="Other source checked", actor="checker")
    assert session.get(OperationalFxRate, second.id).status == "pending"


def test_invalid_currency_future_date_and_invalid_rate_rejected(session):
    with pytest.raises(ValueError, match="foreign currency"):
        prepare(session, currency="AED")
    with pytest.raises(ValueError, match="Future-dated"):
        prepare(session, day=date.today() + timedelta(days=1))
    with pytest.raises(ValueError, match="eight decimal"):
        prepare_fx_rate(session, actor="maker", currency_code="USD",
            rate_date=date.today(), aed_per_unit=Decimal("0.123456789"),
            source_name="Source", source_reference="Ref", reason="Valid reason")
    assert session.scalar(select(OperationalFxRate.id)) is None


def test_rejected_rate_cannot_be_used_or_decided_again(session):
    row = prepare(session)
    decide_fx_rate(session, row, action="reject", expected_revision=1,
                   note="Evidence not sufficient", actor="checker")
    assert approved_fx_rate(session, "USD", date.today()) is None
    with pytest.raises(ValueError, match="pending"):
        decide_fx_rate(session, row, action="approve", expected_revision=2,
                       note="Changed my mind", actor="checker")


def test_foreign_draft_exposure_requires_approved_exact_date_rate(session):
    day = date.today()
    invoice = SimpleNamespace(currency_code="KWD", invoice_date=day,
                              total_amount=Decimal("12.345"))
    missing = foreign_invoice_fx_exposure(session, invoice)
    assert missing["state"] == "rate_missing"
    assert missing["aed_reference_amount"] is None
    assert missing["settlement_enabled"] is False
    row = prepare_fx_rate(session, actor="maker", currency_code="KWD",
        rate_date=day, aed_per_unit=Decimal("12.34567890"),
        source_name="Published reference", source_reference="Evidence 456",
        reason="Invoice exposure reference")
    assert foreign_invoice_fx_exposure(session, invoice)["state"] == "rate_missing"
    decide_fx_rate(session, row, action="approve", expected_revision=1,
                   note="Evidence independently checked", actor="checker")
    exposure = foreign_invoice_fx_exposure(session, invoice)
    assert exposure["foreign_amount"] == Decimal("12.345")
    assert exposure["aed_reference_amount"] == Decimal("152.41")
    assert exposure["rate_key"] == row.rate_key
    assert exposure["posting_enabled"] is False
    assert foreign_invoice_fx_exposure(session, SimpleNamespace(
        currency_code="KWD", invoice_date=day - timedelta(days=1),
        total_amount=Decimal("12.345")))["state"] == "rate_missing"


def test_aed_denominated_foreign_draft_does_not_require_fx(session):
    exposure = foreign_invoice_fx_exposure(session, SimpleNamespace(
        currency_code="AED", invoice_date=date.today(),
        total_amount=Decimal("10.00")))
    assert exposure["state"] == "aed_denominated"
    assert exposure["aed_reference_amount"] == Decimal("10.00")
    assert exposure["settlement_enabled"] is False
