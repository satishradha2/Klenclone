from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from klen_clone.close_reporting import (generate_report_package, pdf_bytes,
    report_package_payload, reporting_workspace_payload, transition_report_package, workbook_bytes)
from klen_clone.finance_foundation import initialize_finance_foundation
from klen_clone.operational import OperationalFiscalPeriod, initialize_operational_database, make_operational_engine
from klen_clone.period_close import (create_close_adjustment, create_period_close,
    decide_close_adjustment, rehearse_period_close, transition_period_close)
from klen_clone.posting_integration import OperationalIntegratedJournalLine, OperationalIntegratedPostingBatch


def approved_close():
    engine = make_operational_engine("sqlite:///:memory:"); initialize_operational_database(engine); session = Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026,9,1), ends_on=date(2026,9,30),
        status="open", rehearsal_enabled=True, approval_reference="test", configured_by="controller")); session.commit()
    close = create_period_close(session, fiscal_period_key="2026-09", actor="maker")
    item = create_close_adjustment(session, close, adjustment_type="accrual", adjustment_date=date(2026,9,30),
        debit_account="Utilities expense", credit_account="Accrued liabilities", amount="125.50",
        reversal_on=date(2026,10,1), evidence_reference="TEST-1", reason="September utility accrual", actor="maker")
    decide_close_adjustment(session, item, action="approve", expected_revision=1, note="Approved evidence", actor="checker")
    transition_period_close(session, close, action="submit", expected_revision=1, actor="maker", note="VAT warning test")
    transition_period_close(session, close, action="approve", expected_revision=2, actor="checker", note="Approved close")
    rehearse_period_close(session, close, actor="checker")
    return session, close


def test_close_report_is_balanced_controlled_and_exportable_after_approval():
    session, close = approved_close(); package = generate_report_package(session, close, actor="report-maker")
    report = report_package_payload(package)["report"]
    assert Decimal(str(report["trial_balance"]["debit"])) == Decimal("0.00")
    assert Decimal(str(report["trial_balance"]["credit"])) == Decimal("0.00")
    assert Decimal(str(report["profit_and_loss"]["profit"])) == Decimal("0.00")
    assert report["unposted_work"]["approved_close_adjustments"] == 1
    assert Decimal(str(report["unposted_work"]["close_adjustment_total"])) == Decimal("125.50")
    assert report["retained_earnings"]["closing"] is None
    assert Decimal(str(report["balance_sheet"]["difference"])) == Decimal("0.00")
    transition_report_package(session, package, action="submit", expected_revision=1, note="", actor="report-maker")
    with pytest.raises(PermissionError):
        transition_report_package(session, package, action="approve", expected_revision=2, note="Self approve", actor="report-maker")
    session.rollback()
    transition_report_package(session, package, action="approve", expected_revision=2,
        note="Independent reporting approval", actor="report-checker")
    payload = report_package_payload(package); assert payload["exports_enabled"] is True
    workbook = load_workbook(filename=__import__("io").BytesIO(workbook_bytes(package)))
    assert {"Trial Balance", "Profit and Loss", "Balance Sheet", "Cash Flow", "Retained Earnings"}.issubset(workbook.sheetnames)
    assert pdf_bytes(package).startswith(b"%PDF-1.4")


def test_reporting_requires_approved_close():
    session, close = approved_close(); close.status = "submitted"; session.commit()
    with pytest.raises(ValueError, match="approved frozen"):
        generate_report_package(session, close, actor="maker")


def add_posted_batch(session, key, lines):
    batch = OperationalIntegratedPostingBatch(batch_key=key, idempotency_key=key,
        resource_type="customer_invoice", resource_key=key, resource_revision=1,
        posting_sequence=1, batch_kind="posting", posting_fingerprint=key,
        fiscal_period_key="2026-09", status="posted", posted_by="synthetic-poster")
    session.add(batch); session.flush()
    for number, (account, debit, credit) in enumerate(lines, 1):
        session.add(OperationalIntegratedJournalLine(batch_id=batch.id, line_no=number,
            account_code=account, debit=Decimal(debit), credit=Decimal(credit)))
    session.commit()


def test_statements_use_posted_target_ledger_and_keep_unposted_work_separate():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    session = Session(engine)
    initialize_finance_foundation(session)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026,9,1),
        ends_on=date(2026,9,30), status="open", rehearsal_enabled=True,
        approval_reference="synthetic ledger", configured_by="controller"))
    session.commit()
    add_posted_batch(session, "synthetic-invoice", [
        ("1200", "105.00", "0"), ("4000", "0", "100.00"), ("2120", "0", "5.00")])
    add_posted_batch(session, "synthetic-recovery", [
        ("1110", "2.00", "0"), ("2130", "0", "2.00")])
    close = create_period_close(session, fiscal_period_key="2026-09", actor="close-maker")
    adjustment = create_close_adjustment(session, close, adjustment_type="accrual",
        adjustment_date=date(2026,9,30), debit_account="Utilities expense",
        credit_account="Accrued liabilities", amount="125.50", reversal_on=date(2026,10,1),
        evidence_reference="SYNTHETIC-ACCRUAL", reason="Unposted close adjustment",
        actor="close-maker")
    decide_close_adjustment(session, adjustment, action="approve", expected_revision=1,
        note="Approved for rehearsal only", actor="close-checker")
    transition_period_close(session, close, action="submit", expected_revision=1,
        actor="close-maker", note="VAT warning for synthetic case")
    transition_period_close(session, close, action="approve", expected_revision=2,
        actor="close-checker", note="Synthetic close review")
    package = generate_report_package(session, close, actor="report-maker")
    report = report_package_payload(package)["report"]
    assert report["ledger_controls"]["integrated_batches"] == 2
    assert Decimal(str(report["trial_balance"]["debit"])) == Decimal("107.00")
    assert Decimal(str(report["trial_balance"]["credit"])) == Decimal("107.00")
    assert Decimal(str(report["profit_and_loss"]["profit"])) == Decimal("100.00")
    assert Decimal(str(report["balance_sheet"]["difference"])) == Decimal("0.00")
    assert Decimal(str(report["cash_flow"]["net_change"])) == Decimal("2.00")
    assert report["cash_flow"]["operating"] is None
    assert report["unposted_work"]["approved_close_adjustments"] == 1
    assert not any(row["account_code"] == "Utilities expense" for row in report["trial_balance"]["rows"])
    assert {"synthetic-invoice", "synthetic-recovery"} == {
        source for row in report["trial_balance"]["rows"] for source in row["sources"]}

    transition_report_package(session, package, action="submit", expected_revision=1,
        note="", actor="report-maker")
    add_posted_batch(session, "late-recovery", [("1110", "1.00", "0"), ("2130", "0", "1.00")])
    with pytest.raises(ValueError, match="stale close"):
        transition_report_package(session, package, action="approve", expected_revision=2,
            note="Would certify stale ledger", actor="report-checker")
    with pytest.raises(ValueError, match="stale close"):
        generate_report_package(session, close, actor="report-maker")
    workspace_package = reporting_workspace_payload(session)["packages"][0]
    assert workspace_package["exports_enabled"] is False
    assert "stale close" in workspace_package["source_warning"]


def test_unmapped_posted_account_cannot_be_silently_classified_as_asset():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    session = Session(engine)
    initialize_finance_foundation(session)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026,9,1),
        ends_on=date(2026,9,30), status="open", rehearsal_enabled=True,
        approval_reference="synthetic ledger", configured_by="controller"))
    session.commit()
    add_posted_batch(session, "unmapped-batch", [
        ("1110", "1.00", "0"), ("Unknown suspense", "0", "1.00")])
    close = create_period_close(session, fiscal_period_key="2026-09", actor="close-maker")
    transition_period_close(session, close, action="submit", expected_revision=1,
        actor="close-maker", note="Synthetic VAT exception")
    transition_period_close(session, close, action="approve", expected_revision=2,
        actor="close-checker", note="Synthetic close review")
    with pytest.raises(ValueError, match="no approved ASAS chart mapping"):
        generate_report_package(session, close, actor="report-maker")
