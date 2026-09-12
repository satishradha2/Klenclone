from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from klen_clone.financial_reports import ageing_bucket, build_accounting_summary, build_ageing_report
from klen_clone.models import (Base, ErpParty, ErpTransactionDocument, RawFileManifest,
                               RawRecord, SourceSnapshot, StgContact)
from klen_clone.operational import (OperationalOpeningBalanceBatch, OperationalOpeningPartyBalance,
                                    initialize_operational_database, make_operational_engine)
from klen_clone.payments import create_payment, transition_payment


def report_sessions(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'financial-reports.db'}")
    Base.metadata.create_all(engine)
    initialize_operational_database(engine)
    clone = Session(engine)
    operational = Session(engine)
    snapshot = SourceSnapshot(name="snapshot", source_system="BizModo", source_url="https://example.invalid", is_atomic=False)
    clone.add(snapshot); clone.flush()
    manifest = RawFileManifest(snapshot_id=snapshot.id, relative_path="contacts.csv", entity_type="contacts",
        sha256="a" * 64, byte_length=1, media_type="text/csv", source_record_count=1)
    clone.add(manifest); clone.flush()
    raw = RawRecord(manifest_id=manifest.id, ordinal=1, source_record_id="1", payload={})
    clone.add(raw); clone.flush()
    contact = StgContact(snapshot_id=snapshot.id, raw_record_id=raw.id, kind="customer",
                         contact_id="CUS-1", business_name="Customer One")
    clone.add(contact); clone.flush()
    party = ErpParty(snapshot_id=snapshot.id, source_contact_id=contact.id, source_raw_record_id=raw.id,
        party_code="CUS-1", party_kind="customer", legal_or_business_name="Customer One",
        master_status="migration_locked_ready", operational_enabled=False)
    clone.add(party); clone.flush()
    for source_id, document_no, occurred_at, due in (
            (1, "INV-NEW", datetime(2026, 9, 1, tzinfo=timezone.utc), Decimal("60")),
            (2, "INV-OLD", datetime(2026, 7, 1, tzinfo=timezone.utc), Decimal("50"))):
        clone.add(ErpTransactionDocument(snapshot_id=snapshot.id, source_kind="sale", source_id=source_id,
            source_raw_record_id=raw.id, document_no=document_no, occurred_at=occurred_at, party_id=party.id,
            total_amount=due, paid_amount=0, due_amount=due, migration_status="migration_locked_ready",
            operational_enabled=False, posting_enabled=False))
    clone.commit()
    batch = OperationalOpeningBalanceBatch(batch_key="b" * 64, source_capture="test", source_manifest_sha256="c" * 64,
        source_atomic=False, approval_reference="test", imported_by="controller", receivable_rows=1,
        receivable_amount=100, customer_advance_rows=1, customer_advance_amount=5,
        payable_rows=0, payable_amount=0, supplier_advance_rows=0, supplier_advance_amount=0,
        status="approved_non_atomic_nonposting")
    operational.add(batch); operational.flush()
    operational.add_all([
        OperationalOpeningPartyBalance(batch_id=batch.id, party_type="customer", party_code="CUS-1",
            party_name_snapshot="Customer One", balance_type="receivable", amount=100, currency_code="AED",
            control_account_code="AR", offset_account_code="Opening", posting_enabled=False, source_status="approved"),
        OperationalOpeningPartyBalance(batch_id=batch.id, party_type="customer", party_code="CUS-1",
            party_name_snapshot="Customer One", balance_type="customer_advance", amount=5, currency_code="AED",
            control_account_code="Advance", offset_account_code="Opening", posting_enabled=False, source_status="approved"),
    ])
    operational.commit()
    payment = create_payment(operational, actor="maker", payment_type="customer_receipt", party_code="CUS-1",
        party_name_snapshot="Customer One", location_code="SHJ", payment_date=date(2026, 9, 9),
        payment_method="cash", cash_bank_account_code="Cash", reference_no=None, amount=30, notes=None,
        lines=[{"source_type": "invoice", "source_reference_key": "INV-NEW",
                "source_document_date": date(2026, 9, 1), "source_outstanding_snapshot": 60,
                "allocation_amount": 20}])
    transition_payment(operational, payment, expected_revision=1, action="submit", actor="maker")
    return clone, operational, snapshot.id


def test_age_bucket_boundaries():
    as_of = date(2026, 9, 9)
    assert ageing_bucket(None, as_of) == "undated"
    assert ageing_bucket(date(2026, 9, 9), as_of) == "days_0_30"
    assert ageing_bucket(date(2026, 8, 9), as_of) == "days_31_60"
    assert ageing_bucket(date(2026, 7, 9), as_of) == "days_61_90"
    assert ageing_bucket(date(2026, 6, 9), as_of) == "days_91_plus"


def test_ageing_keeps_opening_control_and_invoice_evidence_separate(tmp_path):
    clone, operational, snapshot_id = report_sessions(tmp_path)
    report = build_ageing_report(clone, operational, snapshot_id=snapshot_id,
                                 ledger_kind="receivable", as_of=date(2026, 9, 9))
    row = report["items"][0]
    assert row["opening_control"] == Decimal("100.00")
    assert row["submitted_allocation"] == Decimal("20.00")
    assert row["control_outstanding"] == Decimal("80.00")
    assert row["invoice_evidence_outstanding"] == Decimal("90.00")
    assert row["control_variance"] == Decimal("-10.00")
    assert row["days_0_30"] == Decimal("40.00")
    assert row["days_61_90"] == Decimal("50.00")
    assert row["source_advance"] == Decimal("5.00")
    assert row["submitted_advance"] == Decimal("10.00")
    assert row["net_exposure"] == Decimal("65.00")
    assert row["reconciliation_status"] == "review_required"
    assert report["due_date_available"] is False and report["posting_enabled"] is False


def test_accounting_summary_is_evidence_only_and_balanced_at_zero(tmp_path):
    clone, operational, snapshot_id = report_sessions(tmp_path)
    report = build_accounting_summary(clone, operational, snapshot_id=snapshot_id)
    assert report["trial_balance"] == {"rows": 0, "debit": Decimal("0.00"),
        "credit": Decimal("0.00"), "difference": Decimal("0.00"), "status": "balanced"}
    assert report["operational_payment_pipeline"][0]["status"] == "submitted"
    assert report["source_evidence_only"] is True and report["posting_enabled"] is False
