from __future__ import annotations

import calendar
import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now


ASSET_CATEGORIES = {
    "motor_vehicles": ("Motor vehicles", "1500", "1590", "6500", 60),
    "computer_equipment": ("Computer equipment", "1510", "1591", "6510", 36),
    "office_equipment": ("Office equipment", "1520", "1592", "6520", 60),
    "furniture_fixtures": ("Furniture and fixtures", "1530", "1593", "6530", 60),
    "leasehold_improvements": ("Leasehold improvements", "1540", "1594", "6540", 60),
}


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _month_end(value: date, offset: int = 0) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


class OperationalFixedAsset(OperationalBase):
    __tablename__ = "operational_fixed_assets"
    __table_args__ = (
        UniqueConstraint("asset_no", name="uq_fixed_asset_no"),
        CheckConstraint("depreciation_method = 'straight_line'", name="ck_fixed_asset_method"),
        CheckConstraint("status IN ('draft','submitted','active','rejected','cancelled','disposal_pending','disposed')", name="ck_fixed_asset_status"),
        CheckConstraint("cost_amount > 0 AND residual_value >= 0 AND residual_value < cost_amount", name="ck_fixed_asset_values"),
        CheckConstraint("useful_life_months BETWEEN 1 AND 600", name="ck_fixed_asset_life"),
        CheckConstraint("posting_enabled = false", name="ck_fixed_asset_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    asset_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    asset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_code: Mapped[str] = mapped_column(String(80), nullable=False)
    category_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_account_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    accumulated_depreciation_account_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    depreciation_expense_account_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_reference: Mapped[str | None] = mapped_column(String(120))
    acquisition_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    available_for_use_date: Mapped[date] = mapped_column(Date, nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cost_center: Mapped[str] = mapped_column(String(80), nullable=False)
    custodian: Mapped[str | None] = mapped_column(String(200))
    serial_number: Mapped[str | None] = mapped_column(String(160))
    depreciation_method: Mapped[str] = mapped_column(String(30), default="straight_line", nullable=False)
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    residual_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    disposal_requested_by: Mapped[str | None] = mapped_column(String(200))
    disposal_date: Mapped[date | None] = mapped_column(Date)
    disposal_proceeds: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    disposal_reason: Mapped[str | None] = mapped_column(Text)
    disposal_approved_by: Mapped[str | None] = mapped_column(String(200))
    disposal_decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule: Mapped[list["OperationalAssetDepreciationSchedule"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="OperationalAssetDepreciationSchedule.period_no")


class OperationalAssetDepreciationSchedule(OperationalBase):
    __tablename__ = "operational_asset_depreciation_schedule"
    __table_args__ = (
        UniqueConstraint("asset_id", "period_no", name="uq_asset_depreciation_period"),
        CheckConstraint("depreciation_amount >= 0 AND accumulated_amount >= 0 AND net_book_value >= 0", name="ck_asset_schedule_amounts"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("operational_fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    period_no: Mapped[int] = mapped_column(Integer, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    depreciation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    accumulated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_book_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    asset: Mapped[OperationalFixedAsset] = relationship(back_populates="schedule")


class OperationalAssetRehearsal(OperationalBase):
    __tablename__ = "operational_asset_rehearsals"
    __table_args__ = (
        UniqueConstraint("asset_id", "asset_revision", "stage", "period_key", name="uq_asset_rehearsal_stage_period"),
        CheckConstraint("stage IN ('capitalization','depreciation','disposal')", name="ck_asset_rehearsal_stage"),
        CheckConstraint("posting_enabled = false", name="ck_asset_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("operational_fixed_assets.id"), nullable=False, index=True)
    asset_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def asset_categories_payload() -> list[dict]:
    return [{"category_code": code, "category_name": values[0], "asset_account": values[1],
             "accumulated_depreciation_account": values[2], "depreciation_expense_account": values[3],
             "default_life_months": values[4]} for code, values in ASSET_CATEGORIES.items()]


def create_fixed_asset(session: Session, *, asset_name: str, category_code: str,
                       supplier_reference: str | None, acquisition_reference: str,
                       acquisition_date: date, available_for_use_date: date,
                       location_code: str, cost_center: str, custodian: str | None,
                       serial_number: str | None, useful_life_months: int,
                       cost_amount, residual_value, actor: str) -> OperationalFixedAsset:
    if category_code not in ASSET_CATEGORIES:
        raise ValueError("Fixed-asset category is not approved")
    if not asset_name.strip() or not acquisition_reference.strip() or not cost_center.strip():
        raise ValueError("Asset name, acquisition reference and cost centre are required")
    if available_for_use_date < acquisition_date:
        raise ValueError("Available-for-use date cannot precede acquisition")
    cost, residual = _money(cost_amount), _money(residual_value)
    if cost <= 0 or residual < 0 or residual >= cost:
        raise ValueError("Asset cost must be positive and residual value must be below cost")
    if not 1 <= int(useful_life_months) <= 600:
        raise ValueError("Useful life must be between 1 and 600 months")
    category = ASSET_CATEGORIES[category_code]
    key = str(uuid.uuid4())
    row = OperationalFixedAsset(asset_key=key, asset_no=f"FA-{key[:8].upper()}",
        asset_name=asset_name.strip(), category_code=category_code,
        category_name_snapshot=category[0], asset_account_snapshot=category[1],
        accumulated_depreciation_account_snapshot=category[2],
        depreciation_expense_account_snapshot=category[3],
        supplier_reference=(supplier_reference or "").strip() or None,
        acquisition_reference=acquisition_reference.strip(), acquisition_date=acquisition_date,
        available_for_use_date=available_for_use_date, location_code=location_code.strip().upper(),
        cost_center=cost_center.strip().upper(), custodian=(custodian or "").strip() or None,
        serial_number=(serial_number or "").strip() or None, depreciation_method="straight_line",
        useful_life_months=int(useful_life_months), cost_amount=cost, residual_value=residual,
        status="draft", created_by=actor, state_changed_by=actor, posting_enabled=False)
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="fixed_asset.created",
        actor=actor, resource_key=row.asset_key,
        detail=f"{row.asset_no}; AED {cost}; draft capitalization; posting disabled"))
    session.commit()
    return row


def _generate_schedule(row: OperationalFixedAsset) -> None:
    depreciable = _money(row.cost_amount - row.residual_value)
    regular = _money(depreciable / Decimal(row.useful_life_months))
    accumulated = Decimal("0.00")
    for period_no in range(1, row.useful_life_months + 1):
        amount = regular if period_no < row.useful_life_months else _money(depreciable - accumulated)
        accumulated = _money(accumulated + amount)
        row.schedule.append(OperationalAssetDepreciationSchedule(period_no=period_no,
            period_end=_month_end(row.available_for_use_date, period_no - 1),
            depreciation_amount=amount, accumulated_amount=accumulated,
            net_book_value=_money(row.cost_amount - accumulated)))


def transition_fixed_asset(session: Session, row: OperationalFixedAsset, *, action: str,
                           expected_revision: int, actor: str,
                           note: str | None = None) -> OperationalFixedAsset:
    transitions = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "approve"): "active", ("submitted", "reject"): "rejected"}
    if row.revision != expected_revision:
        raise ValueError(f"Fixed-asset revision conflict; current revision is {row.revision}")
    target = transitions.get((row.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    if action in {"approve", "reject"}:
        if row.created_by == actor:
            raise PermissionError("Maker-checker control prevents the creator from deciding this asset")
        if len((note or "").strip()) < 5:
            raise ValueError("A capitalization decision note is required")
        row.approved_by = actor if action == "approve" else None
        row.approval_note = note.strip()
        if action == "approve" and not row.schedule:
            _generate_schedule(row)
    prior = row.status
    row.status, row.revision = target, row.revision + 1
    row.state_changed_by, row.state_changed_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"fixed_asset.{action}",
        actor=actor, resource_key=row.asset_key,
        detail=f"{prior} to {target}; revision {row.revision}; posting disabled"))
    session.commit()
    return row


def request_asset_disposal(session: Session, row: OperationalFixedAsset, *, disposal_date: date,
                           disposal_proceeds, reason: str, expected_revision: int,
                           actor: str) -> OperationalFixedAsset:
    if row.revision != expected_revision:
        raise ValueError(f"Fixed-asset revision conflict; current revision is {row.revision}")
    if row.status != "active":
        raise ValueError("Only an active asset can be submitted for disposal")
    if disposal_date < row.available_for_use_date:
        raise ValueError("Disposal date cannot precede the available-for-use date")
    proceeds = _money(disposal_proceeds)
    if proceeds < 0 or len(reason.strip()) < 5:
        raise ValueError("Disposal proceeds cannot be negative and a reason is required")
    row.disposal_requested_by, row.disposal_date = actor, disposal_date
    row.disposal_proceeds, row.disposal_reason = proceeds, reason.strip()
    row.status, row.revision = "disposal_pending", row.revision + 1
    row.state_changed_by, row.state_changed_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="fixed_asset.disposal_requested",
        actor=actor, resource_key=row.asset_key,
        detail=f"{row.asset_no}; proceeds AED {proceeds}; approval required; posting disabled"))
    session.commit()
    return row


def decide_asset_disposal(session: Session, row: OperationalFixedAsset, *, action: str,
                          expected_revision: int, actor: str, note: str) -> OperationalFixedAsset:
    if row.revision != expected_revision:
        raise ValueError(f"Fixed-asset revision conflict; current revision is {row.revision}")
    if row.status != "disposal_pending" or action not in {"approve", "reject"}:
        raise ValueError("Only a pending disposal can be approved or rejected")
    if row.disposal_requested_by == actor:
        raise PermissionError("Maker-checker control prevents the disposal requester from deciding it")
    if len(note.strip()) < 5:
        raise ValueError("A disposal decision note is required")
    row.status = "disposed" if action == "approve" else "active"
    row.disposal_approved_by = actor if action == "approve" else None
    row.disposal_decision_note = note.strip()
    row.revision += 1
    row.state_changed_by, row.state_changed_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"fixed_asset.disposal_{action}",
        actor=actor, resource_key=row.asset_key,
        detail=f"{row.asset_no}; {row.status}; revision {row.revision}; posting disabled"))
    session.commit()
    return row


def _open_period(session: Session, value: date) -> OperationalFiscalPeriod:
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= value, OperationalFiscalPeriod.ends_on >= value,
        OperationalFiscalPeriod.status == "open", OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if not period:
        raise ValueError("Asset event date is not in an open rehearsal-enabled fiscal period")
    return period


def rehearse_fixed_asset(session: Session, row: OperationalFixedAsset, *, stage: str,
                         as_of_date: date, actor: str) -> dict:
    if stage not in {"capitalization", "depreciation", "disposal"}:
        raise ValueError("Fixed-asset rehearsal stage is invalid")
    if stage == "capitalization" and row.status not in {"active", "disposal_pending", "disposed"}:
        raise ValueError("Only an approved asset can rehearse capitalization")
    if stage == "depreciation" and row.status not in {"active", "disposal_pending"}:
        raise ValueError("Only an active asset can rehearse depreciation")
    if stage == "disposal" and row.status != "disposed":
        raise ValueError("Only an approved disposal can be rehearsed")
    effective_date = row.acquisition_date if stage == "capitalization" else as_of_date
    if stage == "disposal":
        effective_date = row.disposal_date
    period = _open_period(session, effective_date)
    existing = session.scalar(select(OperationalAssetRehearsal).where(
        OperationalAssetRehearsal.asset_id == row.id,
        OperationalAssetRehearsal.asset_revision == row.revision,
        OperationalAssetRehearsal.stage == stage,
        OperationalAssetRehearsal.period_key == period.period_key))
    if existing:
        return asset_rehearsal_payload(existing, idempotent_replay=True)
    if stage == "capitalization":
        amount = _money(row.cost_amount)
        journal = [{"account": row.asset_account_snapshot, "debit": amount, "credit": Decimal("0")},
                   {"account": "Asset Acquisition Clearing", "debit": Decimal("0"), "credit": amount}]
    elif stage == "depreciation":
        scheduled = next((item for item in row.schedule if item.period_end.year == as_of_date.year
                          and item.period_end.month == as_of_date.month), None)
        if not scheduled:
            raise ValueError("No depreciation schedule line exists for the selected month")
        amount = _money(scheduled.depreciation_amount)
        effective_date = scheduled.period_end
        journal = [{"account": row.depreciation_expense_account_snapshot, "debit": amount, "credit": Decimal("0")},
                   {"account": row.accumulated_depreciation_account_snapshot, "debit": Decimal("0"), "credit": amount}]
    else:
        accumulated = _money(sum((item.depreciation_amount for item in row.schedule
                                  if item.period_end <= row.disposal_date), Decimal("0")))
        proceeds = _money(row.disposal_proceeds or 0)
        book_value = _money(row.cost_amount - accumulated)
        journal = []
        if proceeds:
            journal.append({"account": "Asset Disposal Receivable", "debit": proceeds, "credit": Decimal("0")})
        if accumulated:
            journal.append({"account": row.accumulated_depreciation_account_snapshot,
                            "debit": accumulated, "credit": Decimal("0")})
        if proceeds < book_value:
            journal.append({"account": "Loss on Asset Disposal", "debit": _money(book_value - proceeds), "credit": Decimal("0")})
        elif proceeds > book_value:
            journal.append({"account": "Gain on Asset Disposal", "debit": Decimal("0"), "credit": _money(proceeds - book_value)})
        journal.append({"account": row.asset_account_snapshot, "debit": Decimal("0"), "credit": _money(row.cost_amount)})
        amount = _money(row.cost_amount)
    debit = _money(sum((line["debit"] for line in journal), Decimal("0")))
    credit = _money(sum((line["credit"] for line in journal), Decimal("0")))
    if debit != credit:
        raise RuntimeError("Fixed-asset rehearsal is not balanced")
    source = json.dumps({"asset": row.asset_key, "revision": row.revision, "stage": stage,
                         "period": period.period_key, "journal": journal},
                        default=str, sort_keys=True, separators=(",", ":"))
    rehearsal = OperationalAssetRehearsal(rehearsal_key=str(uuid.uuid4()), asset_id=row.id,
        asset_revision=row.revision, stage=stage, period_key=period.period_key,
        as_of_date=effective_date, amount=amount,
        fingerprint=hashlib.sha256(source.encode()).hexdigest(),
        journal_json=json.dumps(journal, default=str, sort_keys=True),
        posting_enabled=False, generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"fixed_asset.{stage}_rehearsed",
        actor=actor, resource_key=row.asset_key,
        detail=f"{row.asset_no}; {period.period_key}; AED {amount}; no posting"))
    session.commit()
    return asset_rehearsal_payload(rehearsal)


def asset_rehearsal_payload(row: OperationalAssetRehearsal, *, idempotent_replay: bool = False) -> dict:
    return {"rehearsal_key": row.rehearsal_key, "stage": row.stage, "period_key": row.period_key,
            "as_of_date": row.as_of_date, "amount": row.amount, "fingerprint": row.fingerprint,
            "journal": json.loads(row.journal_json), "posting_enabled": False,
            "posting_performed": False, "idempotent_replay": idempotent_replay}


def fixed_asset_payload(session: Session, row: OperationalFixedAsset) -> dict:
    rehearsals = list(session.scalars(select(OperationalAssetRehearsal).where(
        OperationalAssetRehearsal.asset_id == row.id).order_by(OperationalAssetRehearsal.id)))
    next_line = next((item for item in row.schedule if not any(
        rehearsal.stage == "depreciation" and rehearsal.as_of_date.year == item.period_end.year
        and rehearsal.as_of_date.month == item.period_end.month for rehearsal in rehearsals)), None)
    accumulated = _money(sum((item.depreciation_amount for item in row.schedule
                              if any(rehearsal.stage == "depreciation"
                                     and rehearsal.as_of_date.year == item.period_end.year
                                     and rehearsal.as_of_date.month == item.period_end.month
                                     for rehearsal in rehearsals)), Decimal("0")))
    return {"asset_key": row.asset_key, "asset_no": row.asset_no, "asset_name": row.asset_name,
        "category_code": row.category_code, "category_name": row.category_name_snapshot,
        "asset_account": row.asset_account_snapshot,
        "accumulated_depreciation_account": row.accumulated_depreciation_account_snapshot,
        "depreciation_expense_account": row.depreciation_expense_account_snapshot,
        "supplier_reference": row.supplier_reference, "acquisition_reference": row.acquisition_reference,
        "acquisition_date": row.acquisition_date, "available_for_use_date": row.available_for_use_date,
        "location_code": row.location_code, "cost_center": row.cost_center,
        "custodian": row.custodian, "serial_number": row.serial_number,
        "depreciation_method": row.depreciation_method, "useful_life_months": row.useful_life_months,
        "cost_amount": row.cost_amount, "residual_value": row.residual_value,
        "accumulated_depreciation": accumulated, "net_book_value": _money(row.cost_amount - accumulated),
        "status": row.status, "created_by": row.created_by, "approved_by": row.approved_by,
        "approval_note": row.approval_note, "disposal_requested_by": row.disposal_requested_by,
        "disposal_date": row.disposal_date, "disposal_proceeds": row.disposal_proceeds,
        "disposal_reason": row.disposal_reason, "disposal_approved_by": row.disposal_approved_by,
        "disposal_decision_note": row.disposal_decision_note, "revision": row.revision,
        "schedule": [{"period_no": item.period_no, "period_end": item.period_end,
                      "depreciation_amount": item.depreciation_amount,
                      "accumulated_amount": item.accumulated_amount,
                      "net_book_value": item.net_book_value} for item in row.schedule],
        "next_depreciation": ({"period_end": next_line.period_end,
                               "amount": next_line.depreciation_amount} if next_line else None),
        "rehearsals": [asset_rehearsal_payload(item) for item in rehearsals],
        "posting_enabled": False}


def fixed_asset_workspace_payload(session: Session) -> dict:
    assets = list(session.scalars(select(OperationalFixedAsset).order_by(OperationalFixedAsset.created_at.desc())))
    return {"categories": asset_categories_payload(),
            "assets": [fixed_asset_payload(session, row) for row in assets],
            "controls": {"assets": len(assets),
                "pending_capitalization": sum(row.status == "submitted" for row in assets),
                "active_assets": sum(row.status == "active" for row in assets),
                "pending_disposals": sum(row.status == "disposal_pending" for row in assets),
                "scheduled_lines": session.scalar(select(func.count(OperationalAssetDepreciationSchedule.id))) or 0,
                "rehearsals": session.scalar(select(func.count(OperationalAssetRehearsal.id))) or 0,
                "permanent_postings": 0}}
