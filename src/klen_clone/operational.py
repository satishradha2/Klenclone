from __future__ import annotations

import uuid
import json
import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, create_engine, event, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


MONEY = Decimal("0.01")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationalBase(DeclarativeBase):
    pass


class OperationalDraft(OperationalBase):
    __tablename__ = "operational_drafts"
    __table_args__ = (
        CheckConstraint("document_type IN ('sale', 'purchase')", name="ck_operational_draft_type"),
        CheckConstraint("status IN ('draft', 'submitted', 'approved', 'cancelled', 'posted', 'reversed')", name="ck_operational_draft_status"),
        CheckConstraint("posting_enabled = false", name="ck_operational_draft_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    draft_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list["OperationalDraftLine"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", order_by="OperationalDraftLine.line_no"
    )


class OperationalDraftLine(OperationalBase):
    __tablename__ = "operational_draft_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_operational_line_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_operational_line_price"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_operational_line_tax"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("operational_drafts.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    draft: Mapped[OperationalDraft] = relationship(back_populates="lines")


class OperationalAuditEvent(OperationalBase):
    __tablename__ = "operational_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)


class OperationalWorkflowEvent(OperationalBase):
    __tablename__ = "operational_workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    draft_id: Mapped[int] = mapped_column(ForeignKey("operational_drafts.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class OperationalSchemaMigration(OperationalBase):
    __tablename__ = "operational_schema_migrations"

    version: Mapped[str] = mapped_column(String(20), primary_key=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalPostingProbe(OperationalBase):
    __tablename__ = "operational_posting_probes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    probe_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    draft_key: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class OperationalStockPosition(OperationalBase):
    __tablename__ = "operational_stock_positions"
    __table_args__ = (
        UniqueConstraint("location_code", "sku", name="uq_operational_stock_position"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_operational_stock_nonnegative"),
        CheckConstraint("quantity_reserved >= 0 AND quantity_reserved <= quantity_on_hand",
                        name="ck_operational_stock_reservation_bounds"),
        CheckConstraint("average_unit_cost >= 0", name="ck_operational_stock_cost_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    average_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_batch_key: Mapped[str | None] = mapped_column(String(64), index=True)
    source_status: Mapped[str] = mapped_column(String(40), default="operational", nullable=False)
    availability_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalStockReservation(OperationalBase):
    __tablename__ = "operational_stock_reservations"
    __table_args__ = (
        UniqueConstraint("draft_line_id", name="uq_operational_reservation_draft_line"),
        CheckConstraint("quantity_base > 0", name="ck_operational_reservation_quantity"),
        CheckConstraint("status IN ('active','released','consumed')", name="ck_operational_reservation_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    draft_id: Mapped[int] = mapped_column(ForeignKey("operational_drafts.id"), nullable=False, index=True)
    draft_line_id: Mapped[int] = mapped_column(ForeignKey("operational_draft_lines.id"), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalFiscalPeriod(OperationalBase):
    __tablename__ = "operational_fiscal_periods"
    __table_args__ = (
        CheckConstraint("starts_on <= ends_on", name="ck_operational_period_dates"),
        CheckConstraint("status IN ('open','locked')", name="ck_operational_period_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rehearsal_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    approval_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    configured_by: Mapped[str] = mapped_column(String(200), nullable=False)
    configured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalOpeningStockBatch(OperationalBase):
    __tablename__ = "operational_opening_stock_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_capture: Mapped[str] = mapped_column(String(500), nullable=False)
    source_stock_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_products_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_atomic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approval_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    imported_by: Mapped[str] = mapped_column(String(200), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    positive_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    exception_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    exception_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    net_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    stock_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class OperationalStockMigrationException(OperationalBase):
    __tablename__ = "operational_stock_migration_exceptions"
    __table_args__ = (
        UniqueConstraint("batch_id", "location_code", "sku", name="uq_operational_stock_exception"),
        CheckConstraint("quantity_base < 0", name="ck_operational_stock_exception_negative"),
        CheckConstraint("status IN ('quarantined','resolved')", name="ck_operational_stock_exception_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_opening_stock_batches.id"), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="quarantined", nullable=False)


class OperationalOpeningBalanceBatch(OperationalBase):
    __tablename__ = "operational_opening_balance_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_capture: Mapped[str] = mapped_column(String(500), nullable=False)
    source_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_atomic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approval_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    imported_by: Mapped[str] = mapped_column(String(200), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    receivable_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    receivable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    customer_advance_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_advance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payable_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    supplier_advance_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_advance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False)


class OperationalOpeningPartyBalance(OperationalBase):
    __tablename__ = "operational_opening_party_balances"
    __table_args__ = (
        UniqueConstraint("batch_id", "party_type", "party_code", "balance_type",
                         name="uq_operational_opening_party_balance"),
        CheckConstraint("party_type IN ('customer','supplier')",
                        name="ck_operational_opening_party_type"),
        CheckConstraint("balance_type IN ('receivable','payable','customer_advance','supplier_advance')",
                        name="ck_operational_opening_balance_type"),
        CheckConstraint("amount > 0", name="ck_operational_opening_balance_positive"),
        CheckConstraint("posting_enabled = false", name="ck_operational_opening_balance_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_opening_balance_batches.id"), nullable=False, index=True)
    party_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    balance_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    control_account_code: Mapped[str] = mapped_column(String(40), nullable=False)
    offset_account_code: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_status: Mapped[str] = mapped_column(String(60), nullable=False)


class OperationalFinancialMigrationException(OperationalBase):
    __tablename__ = "operational_financial_migration_exceptions"
    __table_args__ = (
        UniqueConstraint("batch_id", "control_name", name="uq_operational_financial_exception"),
        CheckConstraint("status IN ('open','resolved','accepted')",
                        name="ck_operational_financial_exception_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_opening_balance_batches.id"), nullable=False, index=True)
    control_name: Mapped[str] = mapped_column(String(80), nullable=False)
    authoritative_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    comparison_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    variance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)


class OperationalJournalBatch(OperationalBase):
    __tablename__ = "operational_journal_batches"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_operational_journal_idempotency"),
        CheckConstraint("status IN ('posted','reversed')", name="ck_operational_journal_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    draft_key: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    reversed_by_batch_id: Mapped[int | None] = mapped_column(ForeignKey("operational_journal_batches.id"))


class OperationalJournalLine(OperationalBase):
    __tablename__ = "operational_journal_lines"
    __table_args__ = (
        UniqueConstraint("batch_id", "line_no", name="uq_operational_journal_line"),
        CheckConstraint("debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0)",
                        name="ck_operational_journal_line_sides"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_journal_batches.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)


class OperationalSubledgerEntry(OperationalBase):
    __tablename__ = "operational_subledger_entries"
    __table_args__ = (UniqueConstraint("journal_batch_id", "entry_type", "party_code",
                                      name="uq_operational_subledger_entry"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_batch_id: Mapped[int] = mapped_column(ForeignKey("operational_journal_batches.id"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class OperationalInventoryLedgerEntry(OperationalBase):
    __tablename__ = "operational_inventory_ledger_entries"
    __table_args__ = (UniqueConstraint("journal_batch_id", "line_no",
                                      name="uq_operational_inventory_ledger_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_batch_id: Mapped[int] = mapped_column(ForeignKey("operational_journal_batches.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    value_delta: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    prior_quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    prior_average_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    resulting_position_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class OperationalReversalRequest(OperationalBase):
    __tablename__ = "operational_reversal_requests"
    __table_args__ = (CheckConstraint("status IN ('requested','approved','completed','rejected')",
                                     name="ck_operational_reversal_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    original_batch_id: Mapped[int] = mapped_column(ForeignKey("operational_journal_batches.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="requested", nullable=False)


def _reject_audit_mutation(mapper, connection, target) -> None:
    raise RuntimeError("Operational audit events are append-only")


event.listen(OperationalAuditEvent, "before_update", _reject_audit_mutation)
event.listen(OperationalAuditEvent, "before_delete", _reject_audit_mutation)
event.listen(OperationalWorkflowEvent, "before_update", _reject_audit_mutation)
event.listen(OperationalWorkflowEvent, "before_delete", _reject_audit_mutation)


def make_operational_engine(url: str):
    options = {"future": True, "pool_pre_ping": True}
    if url == "sqlite:///:memory:":
        options.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, **options)


def initialize_operational_database(engine) -> None:
    # Import extension models before create_all so every operational entrypoint
    # creates the same schema without relying on import order.
    from . import data_governance as _data_governance  # noqa: F401
    from . import data_reviews as _data_reviews  # noqa: F401
    from . import delivery_fulfillment as _delivery_fulfillment  # noqa: F401
    from . import enterprise_setup as _enterprise_setup  # noqa: F401
    from . import access_control as _access_control  # noqa: F401
    from . import finance_foundation as _finance_foundation  # noqa: F401
    from . import finance_ledger as _finance_ledger  # noqa: F401
    from . import finance_reconciliation as _finance_reconciliation  # noqa: F401
    from . import goods_receipts as _goods_receipts  # noqa: F401
    from . import hrm as _hrm  # noqa: F401
    from . import hrm_operations as _hrm_operations  # noqa: F401
    from . import pos_counter as _pos_counter  # noqa: F401
    from . import van_sales as _van_sales  # noqa: F401
    from . import crm as _crm  # noqa: F401
    from . import commercial_pricing as _commercial_pricing  # noqa: F401
    from . import inventory_operations as _inventory_operations  # noqa: F401
    from . import operational_masters as _operational_masters  # noqa: F401
    from . import payments as _payments  # noqa: F401
    from . import cash_management as _cash_management  # noqa: F401
    from . import expense_management as _expense_management  # noqa: F401
    from . import fixed_assets as _fixed_assets  # noqa: F401
    from . import vat_control as _vat_control  # noqa: F401
    from . import period_close as _period_close  # noqa: F401
    from . import close_reporting as _close_reporting  # noqa: F401
    from . import audit_compliance as _audit_compliance  # noqa: F401
    from . import cutover_rehearsal as _cutover_rehearsal  # noqa: F401
    from . import procurement as _procurement  # noqa: F401
    from . import procurement_matching as _procurement_matching  # noqa: F401
    from . import posting_integration as _posting_integration  # noqa: F401
    from . import purchase_returns as _purchase_returns  # noqa: F401
    from . import customer_invoices as _customer_invoices  # noqa: F401
    from . import credit_management as _credit_management  # noqa: F401
    from . import sales_invoices as _sales_invoices  # noqa: F401
    from . import sales_orders as _sales_orders  # noqa: F401
    from . import sales_returns as _sales_returns  # noqa: F401
    from . import security_runtime as _security_runtime  # noqa: F401
    from . import source_verification as _source_verification  # noqa: F401
    from . import warehouse_controls as _warehouse_controls  # noqa: F401

    OperationalBase.metadata.create_all(engine)
    dialect = engine.dialect.name
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("operational_drafts")}
        draft_additions = {
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "state_changed_at": "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP" if dialect == "postgresql" else "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "state_changed_by": "VARCHAR(200) NOT NULL DEFAULT 'system'",
        }
        for name, definition in draft_additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE operational_drafts ADD COLUMN {name} {definition}"))
        line_columns = {column["name"] for column in inspect(connection).get_columns("operational_draft_lines")}
        line_additions = {
            "canonical_uom": "VARCHAR(80) NOT NULL DEFAULT 'unknown'",
            "factor_to_base_snapshot": "NUMERIC(18,6) NOT NULL DEFAULT 1",
            "quantity_base": "NUMERIC(18,6) NOT NULL DEFAULT 0",
            "unit_cost_snapshot": "NUMERIC(18,6)",
            "cost_amount": "NUMERIC(18,2)",
        }
        for name, definition in line_additions.items():
            if name not in line_columns:
                connection.execute(text(f"ALTER TABLE operational_draft_lines ADD COLUMN {name} {definition}"))
        stock_columns = {column["name"] for column in inspect(connection).get_columns("operational_stock_positions")}
        stock_additions = {
            "source_batch_key": "VARCHAR(64)",
            "source_status": "VARCHAR(40) NOT NULL DEFAULT 'operational'",
            "availability_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        }
        for name, definition in stock_additions.items():
            if name not in stock_columns:
                connection.execute(text(f"ALTER TABLE operational_stock_positions ADD COLUMN {name} {definition}"))
        period_columns = {column["name"] for column in inspect(connection).get_columns("operational_fiscal_periods")}
        period_additions = {
            "approval_reference": "VARCHAR(200) NOT NULL DEFAULT 'legacy-control'",
            "configured_by": "VARCHAR(200) NOT NULL DEFAULT 'system'",
            "configured_at": "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP" if dialect == "postgresql" else "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        for name, definition in period_additions.items():
            if name not in period_columns:
                connection.execute(text(f"ALTER TABLE operational_fiscal_periods ADD COLUMN {name} {definition}"))
        review_columns = {column["name"] for column in inspect(connection).get_columns("operational_data_reviews")}
        review_additions = {
            "supplemental_payload": "TEXT",
            "superseded_correction_payload": "TEXT",
            "source_enrichment_note": "TEXT",
        }
        for name, definition in review_additions.items():
            if name not in review_columns:
                connection.execute(text(f"ALTER TABLE operational_data_reviews ADD COLUMN {name} {definition}"))
        invoice_columns = {column["name"] for column in inspect(connection).get_columns("operational_supplier_invoices")}
        invoice_additions = {
            "state_changed_at": ("TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
                                 if dialect == "postgresql" else "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            "state_changed_by": "VARCHAR(200) NOT NULL DEFAULT 'system'",
        }
        for name, definition in invoice_additions.items():
            if name not in invoice_columns:
                connection.execute(text(f"ALTER TABLE operational_supplier_invoices ADD COLUMN {name} {definition}"))
        adjustment_columns = {column["name"] for column in inspect(connection).get_columns("operational_supplier_adjustments")}
        adjustment_additions = {
            "accounting_treatment": "VARCHAR(40) NOT NULL DEFAULT 'price_variance'",
            "state_changed_at": ("TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
                                 if dialect == "postgresql" else "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            "state_changed_by": "VARCHAR(200) NOT NULL DEFAULT 'system'",
        }
        for name, definition in adjustment_additions.items():
            if name not in adjustment_columns:
                connection.execute(text(f"ALTER TABLE operational_supplier_adjustments ADD COLUMN {name} {definition}"))
        sales_return_columns = {column["name"] for column in inspect(connection).get_columns("operational_sales_returns")}
        sales_return_additions = {
            "original_invoice_source_record_id": "INTEGER NOT NULL DEFAULT 0",
            "original_invoice_total_snapshot": "NUMERIC(18,2) NOT NULL DEFAULT 0",
            "original_invoice_evidence_hash": "VARCHAR(64) NOT NULL DEFAULT 'legacy-unverified'",
        }
        for name, definition in sales_return_additions.items():
            if name not in sales_return_columns:
                connection.execute(text(f"ALTER TABLE operational_sales_returns ADD COLUMN {name} {definition}"))
        sales_return_line_columns = {column["name"] for column in inspect(connection).get_columns("operational_sales_return_lines")}
        sales_return_line_additions = {
            "original_invoice_quantity_snapshot": "NUMERIC(18,6) NOT NULL DEFAULT 0",
            "original_invoice_unit_price_snapshot": "NUMERIC(18,4) NOT NULL DEFAULT 0",
        }
        for name, definition in sales_return_line_additions.items():
            if name not in sales_return_line_columns:
                connection.execute(text(f"ALTER TABLE operational_sales_return_lines ADD COLUMN {name} {definition}"))
        quotation_columns = {column["name"] for column in inspect(connection).get_columns("operational_sales_quotations")}
        quotation_additions = {
            "customer_price_group": "VARCHAR(80)",
            "price_list_key": "VARCHAR(36)",
            "promotion_key": "VARCHAR(36)",
        }
        for name, definition in quotation_additions.items():
            if name not in quotation_columns:
                connection.execute(text(f"ALTER TABLE operational_sales_quotations ADD COLUMN {name} {definition}"))
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE operational_drafts DROP CONSTRAINT IF EXISTS ck_operational_draft_status"))
            connection.execute(text("ALTER TABLE operational_drafts ADD CONSTRAINT ck_operational_draft_status CHECK (status IN ('draft','submitted','approved','cancelled','posted','reversed'))"))
            connection.execute(text("ALTER TABLE operational_supplier_invoices DROP CONSTRAINT IF EXISTS ck_supplier_invoice_status"))
            connection.execute(text("ALTER TABLE operational_supplier_invoices ADD CONSTRAINT ck_supplier_invoice_status CHECK (status IN ('draft','matched','exception','approved','rejected','cancelled','posted','reversed'))"))
            connection.execute(text("ALTER TABLE operational_integrated_posting_batches DROP CONSTRAINT IF EXISTS ck_integrated_posting_resource_type"))
            connection.execute(text("ALTER TABLE operational_integrated_posting_batches ADD CONSTRAINT ck_integrated_posting_resource_type CHECK (resource_type IN ('inventory_document','goods_receipt','sales_invoice','sales_return','purchase_return','payment','supplier_invoice','supplier_adjustment'))"))
            connection.execute(text("ALTER TABLE operational_supplier_adjustments DROP CONSTRAINT IF EXISTS ck_supplier_adjustment_status"))
            connection.execute(text("ALTER TABLE operational_supplier_adjustments ADD CONSTRAINT ck_supplier_adjustment_status CHECK (status IN ('draft','submitted','approved','rejected','cancelled','posted','reversed'))"))
            connection.execute(text("ALTER TABLE operational_supplier_adjustments DROP CONSTRAINT IF EXISTS ck_supplier_adjustment_treatment"))
            connection.execute(text("ALTER TABLE operational_supplier_adjustments ADD CONSTRAINT ck_supplier_adjustment_treatment CHECK (accounting_treatment IN ('price_variance','freight_landed_cost','administrative_expense'))"))
        for table_name in ("operational_branches", "operational_warehouses", "operational_vans"):
            unit_columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
            unit_additions = {
                "created_by": "VARCHAR(200) NOT NULL DEFAULT 'enterprise_setup'",
                "approved_by": "VARCHAR(200)",
                "approval_note": "TEXT",
                "revision": "INTEGER NOT NULL DEFAULT 1",
            }
            for name, definition in unit_additions.items():
                if name not in unit_columns:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))
        applied = {row[0]: row[1] for row in connection.execute(text(
            "SELECT version, checksum FROM operational_schema_migrations"
        ))}
        migrations = {
            "0001": "8c21318ed0a17770dc7a8ff677533b54c63ad7326ef82f0246295879fcba817c",
            "0002": "64ba6abc741950813271ef862617a208c83f326cd77a10960df7ea7585d23c1c",
            "0003": "bb8f683b50225dd2d667dc117eef4baaac7ef3cc1768d34bd6323c66532e816c",
            "0004": "062295ab66b191830cc24d1d3a7e613f6888505b7ed5bc9748780c8e93566d8a",
            "0005": "2b935a6d44d45c792817587850199a4ccf6fc7adab974d98e9438b6422111a1a",
            "0006": "c77d599af8150b68ddbb9b2bd43333f68b1c3c4789cd21d0592eed3b31e6c976",
            "0007": "55781029499896b84935a929368529ba7e6c4fb90cb5d3d371507e65c6c136d4",
            "0008": "9ff8a27c44b69f740d32b8472068469ff4f163925de39a3669bc57c6cdf04a5d",
            "0009": "9c570c5962504739810a1428746697d71532a3995f08d4db29805241a2e40d5c",
            "0010": "09dd2e807ac19aa7768c07be7f0b0b56f41357589ba4bbb8c2eaf9627ee7116c",
            "0011": "322d0b32c0fa45e7ec20ec0c29356914454ad2acebd8aca3f325c5ca6a6fdde3",
            "0012": "6d28757c3618d39573d2e46fe5dc6ad9749f976f640181133460c2ec6d7d53b8",
            "0013": "43234cab9c775993f0b02b33fc015fd80fae3792b32e82fe4af04ef5611648e1",
            "0014": "c71d1557ad8f69f93e6a03920368fba8c94b6d2626dd2b0ffaf79cc663430857",
            "0015": "5225ad92d878ba15ad5e34379c1910b889f20bcd45bc5339df8f794698482612",
            "0016": "934f74cfc0d53db9cfdd7a5d12f392a749a24a3c01a5a1d777d87b0efba1cb3a",
            "0017": "c335e711a4772c9b41878cb7d5571ab84dc979413d941867b121d527c04d39cc",
            "0018": "97bbbaeb89e0b43d3bb9698d380496a23ab8df0366076476191ddbd750ac57e9",
            "0019": "1912f01953c2646c676ba2c4a051ba8aaf7a6dbb46f64e8531aae10cc183abe3",
            "0020": "e4456533b41c72be6ab16d0669224b8168b0b6ace9324ed0afc0b2fb85d2a37e",
            "0021": "802615402795d14f48f7b3f78285eb71786dcfcb1f6d17d4f4f843bddb278379",
            "0022": "bcc6ccc66f97ed6c4c5d4da4f4cea604e16ead085688305f754630960a28acd9",
            "0023": "cb2221253dd2202f566d289dfe42291f679b4973d7637f1517d9e12f78ec2338",
            "0024": "78862fb22ce2b428378b7961ff565614d37d48215cf7f29780166b7744c956e0",
            "0025": "60835c6bcb1ef28d4e8d10cfc66dd8251d043477d2044e8da1141aee9cd289ad",
            "0026": "15bd0d94120f4a42e7967c6ca4f43bc6c5b0f11b9885203881aeb774b26ae07f",
            "0027": "1b47fbe0bb4dd6f7cf36aa7f53a447c6db8b0bb95e209b809f59be8dcff483b5",
            "0028": "bc90c18535fc314ea134fa78d83c919c435411bf3b3d00fdc77de43582de390a",
            "0029": "afd7ce04d12853ecdd3624a493a1787de43212db856d48ed9d4f386c9fd47a16",
            "0030": "40c66393883ff36cd01c5ff324743465229456975585529087db58ec562e9f43",
            "0031": "4d7f2de36b574d95157f30fa13f64236d70dd62bd76a2d7e1ecf22063b912877",
            "0032": "a93c1fd90bf5dffbf57195d0e4ad76bed5bd1f8c05e0d8599c0a47f4ddc9bc55",
            "0033": "8a3c0d50be8d8ec3eef263792265678c862e6b1d56473ec90f74a2b3278e7186",
            "0034": "e5b1c0bb11e6495e10fe824fb29bc320a6cd5a110a5e3a880f78c45e1c63b579",
            "0035": "7f1097eb3208d74e1e8a08a5763ccda74ce7534f74a07dc746e64d6424fdcc5d",
            "0036": "54f1ce8b9457dbd62926462960ac7900a7d70d0124ce4daf88a548c36405a65c",
            "0037": "be7140fe834b9967fd9e1372ec65588fef55c9f87a26d41ee86af70bd010342c",
            "0038": "938f1fd8ae2804d5185ee7e105dc70814f0c795c6bf4245e45dc9c4da24cd9d1",
            "0039": "3f9dd4e98944c1f9b7008031787c92a1e9c7e9562fb364a57df4084af995ce9d",
            "0040": "4c810245458c2a997ca203f6756bd96b0c2bad5b808ecea3f75c250462ebbe25",
            "0041": "824db21a4f21158a2caa31ef29e126005052b77267a0803a2ca2df88597cb962",
            "0042": "1f09bf4345a86919622da9e5efc59e569ed65dd994a382d7ccde08e4b82c2e57",
            "0043": "fa627b36e33b085a646be7264435317ca580536523639c9d58ee785088fa0d4e",
            "0044": "64f7abcf7493ea29d219d4d88e2e48005bacb6fb55facf4e113d21c215735ea3",
            "0045": "8cd76db857e4ee8763ad17b6657d5054a40be5c445ebedab4f184736244b1e5e",
            "0046": "9f265def827f62941a97bc8b32a17459a628ab40d586722fbfa891a7032a2683",
            "0047": "11b9d25d59b2cf786aa33e4e44d539d322b713609f0c4d7f44a2904e0a389b21",
            "0048": "f08e38111cf7257615fe35cf80f02b6a52ff620689155d02944f6f9db987e663",
            "0049": "b203dc9e76f6f2516d4c1f1012b1ec39308bbd0ff5f2b54b30ef5f27ba279815",
            "0050": "3fd76d5094d3c35ae730b2c5fdda66c32b0f6e3bd55c8a73d0d82d9c6d8e67c2",
        }
        for version, checksum in migrations.items():
            if version in applied and applied[version] != checksum:
                raise RuntimeError(f"Operational migration checksum mismatch: {version}")
            if version not in applied:
                connection.execute(text(
                    "INSERT INTO operational_schema_migrations(version, checksum, applied_at) VALUES (:version, :checksum, CURRENT_TIMESTAMP)"
                ), {"version": version, "checksum": checksum})


def operational_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def calculate_line(quantity: Decimal, unit_price: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    net = (quantity * unit_price).quantize(MONEY, rounding=ROUND_HALF_UP)
    tax = (net * tax_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
    return net, tax, net + tax


def create_draft(session: Session, *, document_type: str, party_code: str, party_name: str,
                 location_code: str, discount_amount: Decimal, notes: str | None,
                 actor: str, lines: list[dict]) -> OperationalDraft:
    draft_key = str(uuid.uuid4())
    draft_no = f"DR-{document_type[0].upper()}-{draft_key[:8].upper()}"
    subtotal = sum((line["net_amount"] for line in lines), Decimal("0"))
    tax_amount = sum((line["tax_amount"] for line in lines), Decimal("0"))
    total = (subtotal - discount_amount + tax_amount).quantize(MONEY, rounding=ROUND_HALF_UP)
    if total < 0:
        raise ValueError("Discount cannot exceed the draft gross amount")
    draft = OperationalDraft(
        draft_key=draft_key, draft_no=draft_no, document_type=document_type,
        party_code=party_code, party_name_snapshot=party_name, location_code=location_code,
        currency_code="AED", subtotal=subtotal, discount_amount=discount_amount,
        tax_amount=tax_amount, total_amount=total, status="draft", posting_enabled=False,
        notes=notes, created_by=actor, state_changed_by=actor,
    )
    for number, line in enumerate(lines, 1):
        draft.lines.append(OperationalDraftLine(line_no=number, **line))
    session.add(draft)
    session.flush()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="draft.created", actor=actor,
        resource_key=draft.draft_key,
        detail=f"{document_type} {draft.draft_no}; {len(lines)} lines; posting disabled",
    ))
    session.commit()
    return draft


def list_drafts(session: Session, limit: int = 100,
                allowed_locations: tuple[str, ...] = ("*",)) -> list[OperationalDraft]:
    query = select(OperationalDraft)
    if "*" not in allowed_locations:
        query = query.where(OperationalDraft.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalDraft.created_at.desc()).limit(limit)))


def replace_draft(session: Session, draft: OperationalDraft, *, expected_revision: int,
                  party_code: str, party_name: str, location_code: str,
                  discount_amount: Decimal, notes: str | None, actor: str,
                  lines: list[dict]) -> OperationalDraft:
    if draft.status != "draft":
        raise ValueError("Only draft-state documents can be edited")
    if draft.revision != expected_revision:
        raise ValueError(f"Draft revision conflict; current revision is {draft.revision}")
    subtotal = sum((line["net_amount"] for line in lines), Decimal("0"))
    tax_amount = sum((line["tax_amount"] for line in lines), Decimal("0"))
    total = (subtotal - discount_amount + tax_amount).quantize(MONEY, rounding=ROUND_HALF_UP)
    if total < 0:
        raise ValueError("Discount cannot exceed the draft gross amount")
    draft.party_code, draft.party_name_snapshot = party_code, party_name
    draft.location_code, draft.discount_amount, draft.notes = location_code, discount_amount, notes
    draft.subtotal, draft.tax_amount, draft.total_amount = subtotal, tax_amount, total
    draft.revision += 1
    draft.state_changed_at, draft.state_changed_by = utc_now(), actor
    draft.lines.clear()
    for number, line in enumerate(lines, 1):
        draft.lines.append(OperationalDraftLine(line_no=number, **line))
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="draft.edited", actor=actor,
        resource_key=draft.draft_key, detail=f"{draft.draft_no}; revision {draft.revision}; posting disabled",
    ))
    session.commit()
    return draft


def _reserve_sale_stock(session: Session, draft: OperationalDraft) -> None:
    for line in draft.lines:
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == draft.location_code,
            OperationalStockPosition.sku == line.sku,
        ).with_for_update())
        if not position:
            raise ValueError(f"Reconciled stock position is unavailable for {line.sku} at {draft.location_code}")
        if not position.availability_enabled:
            raise ValueError(f"Stock position is not approved for availability at {draft.location_code}: {line.sku}")
        if position.canonical_uom.casefold() != line.canonical_uom.casefold():
            raise ValueError(f"Stock UOM mismatch for {line.sku} at {draft.location_code}")
        available = position.quantity_on_hand - position.quantity_reserved
        if available < line.quantity_base:
            raise ValueError(
                f"Insufficient available stock for {line.sku} at {draft.location_code}: "
                f"required {line.quantity_base}, available {available}"
            )
        position.quantity_reserved += line.quantity_base
        position.revision += 1
        position.updated_at = utc_now()
        session.add(OperationalStockReservation(
            reservation_key=str(uuid.uuid4()), draft_id=draft.id, draft_line_id=line.id,
            location_code=draft.location_code, sku=line.sku,
            quantity_base=line.quantity_base, status="active",
        ))


def _release_sale_stock(session: Session, draft: OperationalDraft) -> None:
    reservations = list(session.scalars(select(OperationalStockReservation).where(
        OperationalStockReservation.draft_id == draft.id,
        OperationalStockReservation.status == "active",
    ).with_for_update()))
    for reservation in reservations:
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == reservation.location_code,
            OperationalStockPosition.sku == reservation.sku,
        ).with_for_update())
        if not position or position.quantity_reserved < reservation.quantity_base:
            raise RuntimeError(f"Reservation ledger mismatch for {reservation.sku}")
        position.quantity_reserved -= reservation.quantity_base
        position.revision += 1
        position.updated_at = utc_now()
        reservation.status = "released"
        reservation.released_at = utc_now()


def transition_draft(session: Session, draft: OperationalDraft, *, expected_revision: int,
                     action: str, actor: str, note: str | None = None) -> OperationalDraft:
    transitions = {
        ("draft", "submit"): "submitted",
        ("draft", "cancel"): "cancelled",
        ("submitted", "cancel"): "cancelled",
        ("submitted", "approve"): "approved",
    }
    if draft.revision != expected_revision:
        raise ValueError(f"Draft revision conflict; current revision is {draft.revision}")
    target = transitions.get((draft.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {draft.status}")
    if action == "approve" and draft.created_by == actor:
        raise PermissionError("Maker-checker control prevents the draft creator from approving it")
    if action == "submit" and draft.document_type == "sale":
        _reserve_sale_stock(session, draft)
    if action == "cancel" and draft.document_type == "sale" and draft.status == "submitted":
        _release_sale_stock(session, draft)
    prior = draft.status
    draft.status, draft.revision = target, draft.revision + 1
    draft.state_changed_at, draft.state_changed_by = utc_now(), actor
    session.add(OperationalWorkflowEvent(
        event_key=str(uuid.uuid4()), draft_id=draft.id, from_status=prior,
        to_status=target, actor=actor, note=note,
    ))
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"draft.{action}", actor=actor,
        resource_key=draft.draft_key, detail=f"{prior} to {target}; revision {draft.revision}; posting disabled",
    ))
    session.commit()
    return draft


def rehearse_posting(session: Session, draft: OperationalDraft, *, actor: str) -> dict:
    if draft.status != "approved":
        raise ValueError("Only an approved draft can enter posting rehearsal")
    document_date = draft.created_at.date()
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= document_date,
        OperationalFiscalPeriod.ends_on >= document_date,
    ).with_for_update())
    if not period or period.status != "open" or not period.rehearsal_enabled:
        raise ValueError(f"Fiscal period is not open for rehearsal on {document_date.isoformat()}")
    net_after_discount = draft.subtotal - draft.discount_amount
    if draft.document_type == "sale":
        reservations = list(session.scalars(select(OperationalStockReservation).where(
            OperationalStockReservation.draft_id == draft.id,
            OperationalStockReservation.status == "active",
        )))
        reserved_by_line = {row.draft_line_id: row.quantity_base for row in reservations}
        if any(reserved_by_line.get(line.id) != line.quantity_base for line in draft.lines):
            raise ValueError("Active stock reservations do not fully cover the approved sales draft")
        missing_cost = [line.sku for line in draft.lines
                        if line.unit_cost_snapshot is None or line.unit_cost_snapshot <= 0]
        if missing_cost:
            raise ValueError(f"Cost basis is unavailable for SKU(s): {', '.join(missing_cost)}")
        total_cogs = sum((line.cost_amount or Decimal("0") for line in draft.lines), Decimal("0"))
        journal = [
            {"account": "Accounts Receivable", "debit": draft.total_amount, "credit": Decimal("0")},
            {"account": "Sales Revenue", "debit": Decimal("0"), "credit": net_after_discount},
            {"account": "Output VAT", "debit": Decimal("0"), "credit": draft.tax_amount},
            {"account": "Cost of Goods Sold", "debit": total_cogs, "credit": Decimal("0")},
            {"account": "Inventory", "debit": Decimal("0"), "credit": total_cogs},
        ]
        movement_sign = Decimal("-1")
    else:
        if draft.subtotal <= 0:
            raise ValueError("Purchase valuation requires a positive net merchandise value")
        journal = [
            {"account": "Inventory", "debit": net_after_discount, "credit": Decimal("0")},
            {"account": "Input VAT", "debit": draft.tax_amount, "credit": Decimal("0")},
            {"account": "Accounts Payable", "debit": Decimal("0"), "credit": draft.total_amount},
        ]
        movement_sign = Decimal("1")
        total_cogs = Decimal("0")
    debit = sum((row["debit"] for row in journal), Decimal("0"))
    credit = sum((row["credit"] for row in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError(f"Posting rehearsal is not balanced: debit {debit}, credit {credit}")
    if draft.document_type == "purchase":
        allocated_values: list[Decimal] = []
        allocated = Decimal("0")
        for index, line in enumerate(draft.lines):
            value = (net_after_discount - allocated if index == len(draft.lines) - 1
                     else (line.net_amount * net_after_discount / draft.subtotal).quantize(
                         MONEY, rounding=ROUND_HALF_UP))
            allocated_values.append(value)
            allocated += value
    else:
        allocated_values = [-(line.cost_amount or Decimal("0")) for line in draft.lines]
    inventory = [{"sku": line.sku, "location": draft.location_code,
                  "quantity_base": line.quantity_base * movement_sign,
                  "canonical_uom": line.canonical_uom,
                  "unit_cost_snapshot": (line.unit_cost_snapshot if draft.document_type == "sale"
                                         else (allocated_values[index] / line.quantity_base).quantize(
                                             Decimal("0.000001"), rounding=ROUND_HALF_UP)),
                  "value_delta": allocated_values[index]}
                 for index, line in enumerate(draft.lines)]
    reversal = {
        "journal": [{"account": row["account"], "debit": row["credit"], "credit": row["debit"]}
                    for row in reversed(journal)],
        "inventory": [{**row, "quantity_base": -row["quantity_base"],
                        "value_delta": -row["value_delta"]} for row in reversed(inventory)],
    }
    fingerprint_source = json.dumps({"draft_key": draft.draft_key, "revision": draft.revision,
                                     "journal": journal, "inventory": inventory},
                                    default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    plan = {"journal": journal, "inventory": inventory, "reversal": reversal,
            "debit": debit, "credit": credit,
            "valuation_method": "weighted_average_seeded_from_purchase_price_evidence",
            "cost_of_goods_sold": total_cogs, "posting_fingerprint": fingerprint,
            "idempotency_key": f"{draft.draft_key}:{draft.revision}:{fingerprint[:16]}",
            "fiscal_period": period.period_key}
    before = session.scalar(select(func.count(OperationalPostingProbe.id))) or 0
    nested = session.begin_nested()
    try:
        for payload in [*journal, *inventory]:
            session.add(OperationalPostingProbe(
                probe_key=str(uuid.uuid4()), draft_key=draft.draft_key,
                payload=json.dumps(payload, default=str, sort_keys=True),
            ))
        session.flush()
        staged = session.scalar(select(func.count(OperationalPostingProbe.id))) or 0
    finally:
        nested.rollback()
    session.expire_all()
    after = session.scalar(select(func.count(OperationalPostingProbe.id))) or 0
    if before != after or staged <= before:
        raise RuntimeError("Posting rehearsal rollback verification failed")
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="posting.rehearsed", actor=actor,
        resource_key=draft.draft_key,
        detail=f"balanced {debit}; {len(inventory)} inventory probes; rollback verified",
    ))
    session.commit()
    return {**plan, "probe_rows_before": before, "probe_rows_staged": staged,
            "probe_rows_after": after, "rollback_verified": True, "posting_performed": False}


def _batch_payload(batch: OperationalJournalBatch, *, idempotent_replay: bool = False) -> dict:
    return {"batch_key": batch.batch_key, "draft_key": batch.draft_key,
            "draft_revision": batch.draft_revision, "posting_fingerprint": batch.posting_fingerprint,
            "idempotency_key": batch.idempotency_key, "status": batch.status,
            "posted_at": batch.posted_at, "posted_by": batch.posted_by,
            "idempotent_replay": idempotent_replay}


def execute_posting(session: Session, draft: OperationalDraft, *, actor: str,
                    idempotency_key: str) -> dict:
    existing = session.scalar(select(OperationalJournalBatch).where(
        OperationalJournalBatch.idempotency_key == idempotency_key))
    if existing:
        if existing.draft_key != draft.draft_key:
            raise ValueError("Idempotency key is already assigned to another draft")
        return _batch_payload(existing, idempotent_replay=True)
    plan = rehearse_posting(session, draft, actor=actor)
    if idempotency_key != plan["idempotency_key"]:
        raise ValueError("Posting idempotency key does not match the approved draft revision and plan")
    locked = session.scalar(select(OperationalDraft).where(
        OperationalDraft.id == draft.id).with_for_update())
    if not locked or locked.status != "approved" or locked.revision != draft.revision:
        raise ValueError("Approved draft changed before atomic posting")

    batch = OperationalJournalBatch(
        batch_key=str(uuid.uuid4()), idempotency_key=idempotency_key,
        draft_key=locked.draft_key, draft_revision=locked.revision,
        posting_fingerprint=plan["posting_fingerprint"], status="posted",
        posted_at=utc_now(), posted_by=actor,
    )
    session.add(batch)
    session.flush()
    for number, row in enumerate(plan["journal"], 1):
        session.add(OperationalJournalLine(
            batch_id=batch.id, line_no=number, account_code=row["account"],
            debit=row["debit"], credit=row["credit"],
        ))
    for number, (line, movement) in enumerate(zip(locked.lines, plan["inventory"]), 1):
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == locked.location_code,
            OperationalStockPosition.sku == line.sku,
        ).with_for_update())
        if locked.document_type == "sale":
            if not position or not position.availability_enabled:
                raise ValueError(f"Approved stock position is unavailable for {line.sku}")
            reservation = session.scalar(select(OperationalStockReservation).where(
                OperationalStockReservation.draft_line_id == line.id,
                OperationalStockReservation.status == "active",
            ).with_for_update())
            if not reservation or reservation.quantity_base != line.quantity_base:
                raise ValueError(f"Active reservation is unavailable for {line.sku}")
            if position.average_unit_cost != line.unit_cost_snapshot:
                raise ValueError(f"Cost basis changed after draft approval for {line.sku}; revise and reapprove")
            prior_quantity, prior_cost = position.quantity_on_hand, position.average_unit_cost
            position.quantity_on_hand -= line.quantity_base
            position.quantity_reserved -= line.quantity_base
            reservation.status, reservation.released_at = "consumed", utc_now()
        else:
            if position:
                prior_quantity, prior_cost = position.quantity_on_hand, position.average_unit_cost
            else:
                prior_quantity, prior_cost = Decimal("0"), Decimal("0")
                position = OperationalStockPosition(
                    location_code=locked.location_code, sku=line.sku,
                    canonical_uom=line.canonical_uom, quantity_on_hand=0,
                    quantity_reserved=0, average_unit_cost=0, revision=0,
                    source_status="operational_purchase", availability_enabled=True,
                )
                session.add(position)
                session.flush()
            if position.canonical_uom.casefold() != line.canonical_uom.casefold():
                raise ValueError(f"Stock UOM mismatch for {line.sku}")
            incoming_value = Decimal(str(movement["value_delta"]))
            new_quantity = prior_quantity + line.quantity_base
            position.average_unit_cost = ((prior_quantity * prior_cost + incoming_value) / new_quantity).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP)
            position.quantity_on_hand = new_quantity
        position.revision += 1
        position.updated_at = utc_now()
        session.flush()
        session.add(OperationalInventoryLedgerEntry(
            journal_batch_id=batch.id, line_no=number, location_code=locked.location_code,
            sku=line.sku, quantity_base=movement["quantity_base"],
            value_delta=movement["value_delta"], canonical_uom=line.canonical_uom,
            prior_quantity_on_hand=prior_quantity, prior_average_unit_cost=prior_cost,
            resulting_position_revision=position.revision,
        ))
    session.add(OperationalSubledgerEntry(
        journal_batch_id=batch.id,
        entry_type="receivable" if locked.document_type == "sale" else "payable",
        party_code=locked.party_code, amount=locked.total_amount,
    ))
    locked.status = "posted"
    locked.revision += 1
    locked.state_changed_at, locked.state_changed_by = utc_now(), actor
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="posting.executed", actor=actor,
        resource_key=locked.draft_key,
        detail=f"batch {batch.batch_key}; fingerprint {plan['posting_fingerprint']}; atomic permanent posting",
    ))
    session.commit()
    return _batch_payload(batch)


def execute_reversal(session: Session, batch: OperationalJournalBatch, *, actor: str,
                     reason: str) -> dict:
    locked_batch = session.scalar(select(OperationalJournalBatch).where(
        OperationalJournalBatch.id == batch.id).with_for_update())
    if locked_batch.status == "reversed" and locked_batch.reversed_by_batch_id:
        existing = session.get(OperationalJournalBatch, locked_batch.reversed_by_batch_id)
        return _batch_payload(existing, idempotent_replay=True)
    if locked_batch.status != "posted":
        raise ValueError("Only a posted journal batch can be reversed")
    original_inventory = list(session.scalars(select(OperationalInventoryLedgerEntry).where(
        OperationalInventoryLedgerEntry.journal_batch_id == locked_batch.id
    ).order_by(OperationalInventoryLedgerEntry.line_no)))
    positions: list[tuple[OperationalInventoryLedgerEntry, OperationalStockPosition]] = []
    for movement in original_inventory:
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == movement.location_code,
            OperationalStockPosition.sku == movement.sku,
        ).with_for_update())
        if not position or position.revision != movement.resulting_position_revision:
            raise ValueError(f"Later stock activity prevents exact reversal for {movement.sku}")
        if movement.quantity_base > 0 and position.quantity_on_hand - position.quantity_reserved < movement.quantity_base:
            raise ValueError(f"Insufficient unreserved stock to reverse purchase for {movement.sku}")
        positions.append((movement, position))
    fingerprint = hashlib.sha256(f"reverse:{locked_batch.posting_fingerprint}".encode("ascii")).hexdigest()
    reversal = OperationalJournalBatch(
        batch_key=str(uuid.uuid4()), idempotency_key=f"reverse:{locked_batch.idempotency_key}",
        draft_key=locked_batch.draft_key, draft_revision=locked_batch.draft_revision,
        posting_fingerprint=fingerprint, status="posted", posted_at=utc_now(), posted_by=actor,
    )
    session.add(reversal)
    session.flush()
    original_lines = list(session.scalars(select(OperationalJournalLine).where(
        OperationalJournalLine.batch_id == locked_batch.id).order_by(OperationalJournalLine.line_no.desc())))
    for number, line in enumerate(original_lines, 1):
        session.add(OperationalJournalLine(
            batch_id=reversal.id, line_no=number, account_code=line.account_code,
            debit=line.credit, credit=line.debit,
        ))
    for number, (movement, position) in enumerate(reversed(positions), 1):
        current_quantity, current_cost = position.quantity_on_hand, position.average_unit_cost
        position.quantity_on_hand = movement.prior_quantity_on_hand
        position.average_unit_cost = movement.prior_average_unit_cost
        position.revision += 1
        position.updated_at = utc_now()
        session.add(OperationalInventoryLedgerEntry(
            journal_batch_id=reversal.id, line_no=number, location_code=movement.location_code,
            sku=movement.sku, quantity_base=-movement.quantity_base,
            value_delta=-movement.value_delta, canonical_uom=movement.canonical_uom,
            prior_quantity_on_hand=current_quantity, prior_average_unit_cost=current_cost,
            resulting_position_revision=position.revision,
        ))
    original_subledgers = list(session.scalars(select(OperationalSubledgerEntry).where(
        OperationalSubledgerEntry.journal_batch_id == locked_batch.id)))
    for entry in original_subledgers:
        session.add(OperationalSubledgerEntry(
            journal_batch_id=reversal.id, entry_type=entry.entry_type,
            party_code=entry.party_code, amount=-entry.amount,
        ))
    request = OperationalReversalRequest(
        request_key=str(uuid.uuid4()), original_batch_id=locked_batch.id,
        reason=reason, requested_by=actor, status="completed",
    )
    session.add(request)
    locked_batch.status = "reversed"
    locked_batch.reversed_by_batch_id = reversal.id
    draft = session.scalar(select(OperationalDraft).where(
        OperationalDraft.draft_key == locked_batch.draft_key).with_for_update())
    if draft:
        draft.status = "reversed"
        draft.revision += 1
        draft.state_changed_at, draft.state_changed_by = utc_now(), actor
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="posting.reversed", actor=actor,
        resource_key=locked_batch.draft_key,
        detail=f"original {locked_batch.batch_key}; reversal {reversal.batch_key}; {reason}",
    ))
    session.commit()
    return _batch_payload(reversal)
