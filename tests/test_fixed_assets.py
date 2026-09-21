from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.fixed_assets import (
    OperationalAssetDepreciationSchedule, OperationalAssetRehearsal,
    create_fixed_asset, decide_asset_disposal, fixed_asset_workspace_payload,
    rehearse_fixed_asset, request_asset_disposal, transition_fixed_asset,
)
from klen_clone.operational import (
    OperationalFiscalPeriod, initialize_operational_database, make_operational_engine,
)


def asset_session(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'fixed-assets.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
        ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
        approval_reference="Fixed asset UAT", configured_by="controller"))
    session.commit()
    return session


def test_fixed_asset_capitalization_schedule_and_rehearsals(tmp_path):
    session = asset_session(tmp_path)
    asset = create_fixed_asset(session, asset_name="Testing delivery laptop",
        category_code="computer_equipment", supplier_reference="SUP-TEST",
        acquisition_reference="UAT-FA-001", acquisition_date=date(2026, 9, 21),
        available_for_use_date=date(2026, 9, 21), location_code="MAIN",
        cost_center="DELIVERY", custodian="Test Employee", serial_number="UAT-SERIAL",
        useful_life_months=12, cost_amount=Decimal("1000"), residual_value=Decimal("100"),
        actor="maker")
    asset = transition_fixed_asset(session, asset, action="submit", expected_revision=1,
                                   actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_fixed_asset(session, asset, action="approve", expected_revision=2,
                               actor="maker", note="Self approval attempt")
    session.rollback()
    asset = transition_fixed_asset(session, asset, action="approve", expected_revision=2,
        actor="approver", note="Independent capitalization approval")
    assert asset.status == "active" and len(asset.schedule) == 12
    assert sum((line.depreciation_amount for line in asset.schedule), Decimal("0")) == Decimal("900.00")
    assert asset.schedule[-1].net_book_value == Decimal("100.00")
    assert session.scalar(select(func.count(OperationalAssetDepreciationSchedule.id))) == 12

    capitalization = rehearse_fixed_asset(session, asset, stage="capitalization",
        as_of_date=date(2026, 9, 21), actor="approver")
    depreciation = rehearse_fixed_asset(session, asset, stage="depreciation",
        as_of_date=date(2026, 9, 30), actor="approver")
    assert capitalization["posting_performed"] is False
    assert depreciation["amount"] == Decimal("75.00")
    for plan in (capitalization, depreciation):
        assert sum(Decimal(str(line["debit"])) for line in plan["journal"]) == \
               sum(Decimal(str(line["credit"])) for line in plan["journal"])
    assert rehearse_fixed_asset(session, asset, stage="depreciation",
        as_of_date=date(2026, 9, 30), actor="approver")["idempotent_replay"] is True


def test_fixed_asset_disposal_requires_independent_approval_and_balances(tmp_path):
    session = asset_session(tmp_path)
    asset = create_fixed_asset(session, asset_name="Testing office equipment",
        category_code="office_equipment", supplier_reference=None,
        acquisition_reference="UAT-FA-002", acquisition_date=date(2026, 9, 1),
        available_for_use_date=date(2026, 9, 1), location_code="MAIN",
        cost_center="ADMIN", custodian=None, serial_number=None,
        useful_life_months=12, cost_amount=Decimal("1200"), residual_value=Decimal("0"),
        actor="maker")
    asset = transition_fixed_asset(session, asset, action="submit", expected_revision=1,
                                   actor="maker")
    asset = transition_fixed_asset(session, asset, action="approve", expected_revision=2,
        actor="approver", note="Independent capitalization approval")
    asset = request_asset_disposal(session, asset, disposal_date=date(2026, 9, 30),
        disposal_proceeds=Decimal("950"), reason="Testing controlled asset disposal",
        expected_revision=3, actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        decide_asset_disposal(session, asset, action="approve", expected_revision=4,
                              actor="maker", note="Self disposal approval")
    session.rollback()
    asset = decide_asset_disposal(session, asset, action="approve", expected_revision=4,
        actor="approver", note="Independent disposal approval")
    plan = rehearse_fixed_asset(session, asset, stage="disposal",
        as_of_date=date(2026, 9, 30), actor="approver")
    assert asset.status == "disposed" and plan["posting_enabled"] is False
    assert sum(Decimal(str(line["debit"])) for line in plan["journal"]) == Decimal("1200.00")
    assert sum(Decimal(str(line["credit"])) for line in plan["journal"]) == Decimal("1200.00")
    assert session.scalar(select(func.count(OperationalAssetRehearsal.id))) == 1
    controls = fixed_asset_workspace_payload(session)["controls"]
    assert controls["pending_disposals"] == 0 and controls["permanent_postings"] == 0
