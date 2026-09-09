from __future__ import annotations

from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), default="BizModo V7.5.1", nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    extraction_timezone: Mapped[str] = mapped_column(String(80), default="Asia/Dubai", nullable=False)
    is_atomic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    files: Mapped[list[RawFileManifest]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class RawFileManifest(Base):
    __tablename__ = "raw_file_manifests"
    __table_args__ = (UniqueConstraint("snapshot_id", "relative_path", name="uq_snapshot_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    snapshot: Mapped[SourceSnapshot] = relationship(back_populates="files")
    records: Mapped[list[RawRecord]] = relationship(back_populates="manifest", cascade="all, delete-orphan")


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (UniqueConstraint("manifest_id", "ordinal", name="uq_manifest_ordinal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manifest_id: Mapped[int] = mapped_column(ForeignKey("raw_file_manifests.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_document_number: Mapped[str | None] = mapped_column(String(255), index=True)
    is_presentation_row: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payload: Mapped[dict | list | None] = mapped_column(JSON)
    payload_text: Mapped[str | None] = mapped_column(Text)

    manifest: Mapped[RawFileManifest] = relationship(back_populates="records")


class ReconciliationException(Base):
    __tablename__ = "reconciliation_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_key: Mapped[str | None] = mapped_column(String(255), index=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class StagedMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), unique=True, nullable=False)


class StgContact(StagedMixin, Base):
    __tablename__ = "stg_contacts"

    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    contact_id: Mapped[str | None] = mapped_column(String(80), index=True)
    business_name: Mapped[str | None] = mapped_column(String(300))
    name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    mobile: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    tax_number: Mapped[str | None] = mapped_column(String(120))
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    advance_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    return_due: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgProduct(StagedMixin, Base):
    __tablename__ = "stg_products"

    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(200))
    tax_name: Mapped[str | None] = mapped_column(String(120))
    locations: Mapped[str | None] = mapped_column(Text)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    current_stock: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    stock_unit: Mapped[str | None] = mapped_column(String(80))


class StgSale(StagedMixin, Base):
    __tablename__ = "stg_sales"

    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    payment_status: Mapped[str | None] = mapped_column(String(80))
    payment_method: Mapped[str | None] = mapped_column(String(120))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    total_paid: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    return_due: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    added_by: Mapped[str | None] = mapped_column(String(200))


class StgPurchase(StagedMixin, Base):
    __tablename__ = "stg_purchases"

    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    supplier_reference: Mapped[str | None] = mapped_column(String(160))
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    purchase_status: Mapped[str | None] = mapped_column(String(80))
    payment_status: Mapped[str | None] = mapped_column(String(80))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    added_by: Mapped[str | None] = mapped_column(String(200))


class StgPayment(StagedMixin, Base):
    __tablename__ = "stg_payments"

    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reference_no: Mapped[str | None] = mapped_column(String(160), index=True)
    parent_document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(500))
    method: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgReturn(StagedMixin, Base):
    __tablename__ = "stg_returns"

    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    parent_document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    payment_status: Mapped[str | None] = mapped_column(String(80))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgStockBalance(StagedMixin, Base):
    __tablename__ = "stg_stock_balances"

    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    sub_location: Mapped[str | None] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(80))
    available_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    purchase_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    sale_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgStockTransfer(StagedMixin, Base):
    __tablename__ = "stg_stock_transfers"

    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    location_from: Mapped[str | None] = mapped_column(String(200), index=True)
    location_to: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[str | None] = mapped_column(String(80))
    shipping_charge: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    notes: Mapped[str | None] = mapped_column(Text)


class StgDocumentLine(Base):
    __tablename__ = "stg_document_lines"
    __table_args__ = (UniqueConstraint("raw_record_id", "source_entity", "line_no", name="uq_raw_entity_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    parent_document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(500))
    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    location_from: Mapped[str | None] = mapped_column(String(200))
    location_to: Mapped[str | None] = mapped_column(String(200))
    raw_columns: Mapped[dict] = mapped_column(JSON, nullable=False)


class StgSaleLine(StagedMixin, Base):
    __tablename__ = "stg_sale_lines"

    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    contact_id: Mapped[str | None] = mapped_column(String(80), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(500))
    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit: Mapped[str | None] = mapped_column(String(80))
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    gross_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgPurchaseLine(StagedMixin, Base):
    __tablename__ = "stg_purchase_lines"

    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(500))
    supplier_reference: Mapped[str | None] = mapped_column(String(160))
    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit: Mapped[str | None] = mapped_column(String(80))
    adjusted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgItemTrace(StagedMixin, Base):
    __tablename__ = "stg_item_traces"

    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)
    purchase_document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    sale_document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(500))
    customer_name: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit: Mapped[str | None] = mapped_column(String(80))
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))


class StgEntityLink(Base):
    __tablename__ = "stg_entity_links"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_kind", "source_id", "target_kind", name="uq_resolved_link"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    match_method: Mapped[str | None] = mapped_column(String(80))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgDocumentReconciliation(Base):
    __tablename__ = "stg_document_reconciliations"
    __table_args__ = (UniqueConstraint("snapshot_id", "document_kind", "header_id", name="uq_document_reconciliation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    header_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    header_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    payment_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    return_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    header_line_variance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    settlement_variance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    return_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgUomDefinition(StagedMixin, Base):
    __tablename__ = "stg_uom_definitions"

    source_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    source_short_name: Mapped[str | None] = mapped_column(String(160), index=True)
    allow_decimal: Mapped[bool | None] = mapped_column(Boolean)
    canonical_uom: Mapped[str | None] = mapped_column(String(80), index=True)
    contained_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    contained_uom: Mapped[str | None] = mapped_column(String(80))
    parse_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgProductUomProfile(Base):
    __tablename__ = "stg_product_uom_profiles"
    __table_args__ = (UniqueConstraint("snapshot_id", "product_id", name="uq_product_uom_profile"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("stg_products.id"), nullable=False, index=True)
    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    source_base_uom: Mapped[str | None] = mapped_column(String(80))
    canonical_base_uom: Mapped[str | None] = mapped_column(String(80), index=True)
    observed_uoms: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    conversion_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgInventoryMovement(Base):
    __tablename__ = "stg_inventory_movements"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "source_kind", "source_id", "movement_type", "location", name="uq_inventory_movement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("stg_products.id"), index=True)
    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    movement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    counterparty_location: Mapped[str | None] = mapped_column(String(200))
    source_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    source_uom: Mapped[str | None] = mapped_column(String(80))
    canonical_uom: Mapped[str | None] = mapped_column(String(80), index=True)
    factor_to_base_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    quantity_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    conversion_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    posting_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgTaxEvidence(StagedMixin, Base):
    __tablename__ = "stg_tax_evidence"

    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    party_name: Mapped[str | None] = mapped_column(String(500))
    tax_number: Mapped[str | None] = mapped_column(String(120))
    amount_ex_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_with_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    payment_method: Mapped[str | None] = mapped_column(String(120))
    link_kind: Mapped[str | None] = mapped_column(String(40), index=True)
    link_id: Mapped[int | None] = mapped_column(Integer, index=True)
    link_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    match_method: Mapped[str | None] = mapped_column(String(80))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgFinancialAllocation(Base):
    __tablename__ = "stg_financial_allocations"
    __table_args__ = (UniqueConstraint("snapshot_id", "document_kind", "header_id", name="uq_financial_allocation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    header_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    header_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    amount_ex_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    payment_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    due_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    return_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    tax_control_variance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    allocation_residual: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    settlement_residual: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    tax_link_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgPaymentAccount(StagedMixin, Base):
    __tablename__ = "stg_payment_accounts"

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    account_type: Mapped[str | None] = mapped_column(String(120))
    account_sub_type: Mapped[str | None] = mapped_column(String(120))
    account_number: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    balance: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    added_by: Mapped[str | None] = mapped_column(String(200))


class StgCashFlowEntry(StagedMixin, Base):
    __tablename__ = "stg_cash_flow_entries"

    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    account_name: Mapped[str | None] = mapped_column(String(300), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(String(120))
    payment_details: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    account_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    total_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    entry_kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    linked_payment_id: Mapped[int | None] = mapped_column(ForeignKey("stg_payments.id"), index=True)
    payment_link_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    transfer_group: Mapped[str | None] = mapped_column(String(120), index=True)
    transfer_pair_status: Mapped[str | None] = mapped_column(String(30), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgTrialBalanceEntry(StagedMixin, Base):
    __tablename__ = "stg_trial_balance_entries"

    row_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    account_name: Mapped[str | None] = mapped_column(String(500), index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    label_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgAccountingControl(Base):
    __tablename__ = "stg_accounting_controls"
    __table_args__ = (UniqueConstraint("snapshot_id", "control_code", name="uq_accounting_control"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    control_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount_a: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_b: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgCoaAccount(Base):
    __tablename__ = "stg_coa_accounts"
    __table_args__ = (UniqueConstraint("snapshot_id", "account_code", name="uq_coa_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(300), nullable=False)
    account_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    account_sub_type: Mapped[str | None] = mapped_column(String(80))
    source_name: Mapped[str | None] = mapped_column(String(300))
    mapping_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgJournalBlueprint(Base):
    __tablename__ = "stg_journal_blueprints"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_kind", "source_key", name="uq_journal_blueprint_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    debit_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    credit_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgJournalBlueprintLine(Base):
    __tablename__ = "stg_journal_blueprint_lines"
    __table_args__ = (UniqueConstraint("journal_id", "line_no", name="uq_journal_blueprint_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("stg_journal_blueprints.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"), nullable=False)
    memo: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class StgInventoryOpeningControl(Base):
    __tablename__ = "stg_inventory_opening_controls"
    __table_args__ = (UniqueConstraint("snapshot_id", "control_key", name="uq_inventory_opening_control"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    control_key: Mapped[str] = mapped_column(String(500), nullable=False)
    stock_balance_id: Mapped[int | None] = mapped_column(ForeignKey("stg_stock_balances.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("stg_products.id"), index=True)
    sku: Mapped[str | None] = mapped_column(String(160), index=True)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    sub_location: Mapped[str | None] = mapped_column(String(200))
    canonical_uom: Mapped[str | None] = mapped_column(String(80))
    closing_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    net_supported_movement: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    implied_opening_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unresolved_movement_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpOrganization(Base):
    __tablename__ = "erp_organizations"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_key", name="uq_erp_organization_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(300), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), nullable=False)
    inventory_cost_method: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_registration_number: Mapped[str | None] = mapped_column(String(120))
    operational_status: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpLocation(Base):
    __tablename__ = "erp_locations"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_key", name="uq_erp_location_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("erp_organizations.id"), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    operational_status: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpFiscalPeriod(Base):
    __tablename__ = "erp_fiscal_periods"
    __table_args__ = (UniqueConstraint("snapshot_id", "period_code", name="uq_erp_fiscal_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("erp_organizations.id"), nullable=False, index=True)
    period_code: Mapped[str] = mapped_column(String(30), nullable=False)
    starts_on: Mapped[datetime] = mapped_column(Date, nullable=False)
    ends_on: Mapped[datetime] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpNumberSequence(Base):
    __tablename__ = "erp_number_sequences"
    __table_args__ = (UniqueConstraint("snapshot_id", "sequence_code", name="uq_erp_number_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    sequence_code: Mapped[str] = mapped_column(String(80), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    source_prefix: Mapped[str | None] = mapped_column(String(80))
    digit_width: Mapped[int | None] = mapped_column(Integer)
    last_observed_value: Mapped[int | None] = mapped_column(BigInteger)
    next_candidate_value: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reservation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpModulePolicy(Base):
    __tablename__ = "erp_module_policies"
    __table_args__ = (UniqueConstraint("snapshot_id", "module_code", name="uq_erp_module_policy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    module_code: Mapped[str] = mapped_column(String(80), nullable=False)
    source_observed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    target_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class ErpSourceKeyRegistry(Base):
    __tablename__ = "erp_source_key_registry"
    __table_args__ = (UniqueConstraint("raw_record_id", name="uq_erp_source_key_raw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_document_number: Mapped[str | None] = mapped_column(String(255), index=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str] = mapped_column(String(700), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ErpApprovalPolicy(Base):
    __tablename__ = "erp_approval_policies"
    __table_args__ = (UniqueConstraint("snapshot_id", "policy_code", name="uq_erp_approval_policy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    policy_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scope: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpApprovalStep(Base):
    __tablename__ = "erp_approval_steps"
    __table_args__ = (UniqueConstraint("policy_id", "step_no", name="uq_erp_approval_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("erp_approval_policies.id"), nullable=False, index=True)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role_code: Mapped[str] = mapped_column(String(80), nullable=False)
    decision_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ErpMigrationBatch(Base):
    __tablename__ = "erp_migration_batches"
    __table_args__ = (UniqueConstraint("snapshot_id", "batch_code", name="uq_erp_migration_batch"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    batch_code: Mapped[str] = mapped_column(String(180), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    atomic_source: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ErpMigrationBatchEntity(Base):
    __tablename__ = "erp_migration_batch_entities"
    __table_args__ = (UniqueConstraint("batch_id", "source_entity", name="uq_erp_batch_entity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("erp_migration_batches.id"), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False)
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False)
    business_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)


class ErpAuditEvent(Base):
    __tablename__ = "erp_audit_events"
    __table_args__ = (UniqueConstraint("snapshot_id", "event_key", name="uq_erp_audit_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpParty(Base):
    __tablename__ = "erp_parties"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_contact_id", name="uq_erp_party_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_contact_id: Mapped[int] = mapped_column(ForeignKey("stg_contacts.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    legal_or_business_name: Mapped[str] = mapped_column(String(500), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    mobile: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    tax_number: Mapped[str | None] = mapped_column(String(120))
    master_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpProductMaster(Base):
    __tablename__ = "erp_product_masters"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_product_id", name="uq_erp_product_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_product_id: Mapped[int] = mapped_column(ForeignKey("stg_products.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(80))
    category_name: Mapped[str | None] = mapped_column(String(200))
    brand_name: Mapped[str | None] = mapped_column(String(200))
    source_location_text: Mapped[str | None] = mapped_column(Text)
    purchase_price_evidence: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    selling_price_evidence: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    tax_profile_id: Mapped[int | None] = mapped_column(ForeignKey("erp_tax_profiles.id"), index=True)
    master_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpUomMaster(Base):
    __tablename__ = "erp_uom_masters"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_uom_id", name="uq_erp_uom_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_uom_id: Mapped[int] = mapped_column(ForeignKey("stg_uom_definitions.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    uom_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_short_name: Mapped[str | None] = mapped_column(String(160))
    canonical_uom: Mapped[str | None] = mapped_column(String(80), index=True)
    allow_decimal: Mapped[bool | None] = mapped_column(Boolean)
    contained_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    contained_uom: Mapped[str | None] = mapped_column(String(80))
    master_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpProductUom(Base):
    __tablename__ = "erp_product_uoms"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_profile_id", name="uq_erp_product_uom_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_profile_id: Mapped[int] = mapped_column(ForeignKey("stg_product_uom_profiles.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("erp_product_masters.id"), nullable=False, index=True)
    source_base_uom: Mapped[str | None] = mapped_column(String(80))
    canonical_base_uom: Mapped[str | None] = mapped_column(String(80), index=True)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("1"), nullable=False)
    conversion_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpTaxProfile(Base):
    __tablename__ = "erp_tax_profiles"
    __table_args__ = (UniqueConstraint("snapshot_id", "tax_code", name="uq_erp_tax_profile"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    tax_code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpOpeningBalanceQueue(Base):
    __tablename__ = "erp_opening_balance_queue"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_kind", "source_id", "balance_kind", name="uq_erp_opening_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    balance_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    uom: Mapped[str | None] = mapped_column(String(80))
    queue_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    approval_policy_id: Mapped[int | None] = mapped_column(ForeignKey("erp_approval_policies.id"), index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpTransactionDocument(Base):
    __tablename__ = "erp_transaction_documents"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_kind", "source_id", name="uq_erp_transaction_document_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("erp_parties.id"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("erp_locations.id"), index=True)
    counterparty_location_id: Mapped[int | None] = mapped_column(ForeignKey("erp_locations.id"), index=True)
    parent_document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    due_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    return_due_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    source_status: Mapped[str | None] = mapped_column(String(120))
    migration_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpTransactionLine(Base):
    __tablename__ = "erp_transaction_lines"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_kind", "source_id", name="uq_erp_transaction_line_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("erp_product_masters.id"), index=True)
    source_line_no: Mapped[int | None] = mapped_column(Integer)
    entered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    entered_uom: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    relation_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpTransactionPayment(Base):
    __tablename__ = "erp_transaction_payments"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_payment_id", name="uq_erp_transaction_payment_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_payment_id: Mapped[int] = mapped_column(ForeignKey("stg_payments.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    reference_no: Mapped[str | None] = mapped_column(String(160), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    method: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    relation_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpInventoryMovement(Base):
    __tablename__ = "erp_inventory_movements"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_movement_id", name="uq_erp_inventory_movement_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_movement_id: Mapped[int] = mapped_column(ForeignKey("stg_inventory_movements.id"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("erp_product_masters.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("erp_locations.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    entered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    entered_uom: Mapped[str | None] = mapped_column(String(80))
    factor_to_base_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    quantity_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    canonical_uom: Mapped[str | None] = mapped_column(String(80))
    source_posting_status: Mapped[str] = mapped_column(String(40), nullable=False)
    migration_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpMigrationExceptionQueue(Base):
    __tablename__ = "erp_migration_exception_queue"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_kind", "source_id", "exception_code", name="uq_erp_migration_exception"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    exception_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    queue_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    activation_blocked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpGlAccount(Base):
    __tablename__ = "erp_gl_accounts"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_account_id", name="uq_erp_gl_account_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_account_id: Mapped[int] = mapped_column(ForeignKey("stg_coa_accounts.id"), nullable=False, index=True)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(300), nullable=False)
    account_type: Mapped[str] = mapped_column(String(60), nullable=False)
    account_sub_type: Mapped[str | None] = mapped_column(String(80))
    source_name: Mapped[str | None] = mapped_column(String(300))
    migration_status: Mapped[str] = mapped_column(String(40), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpJournalBlueprint(Base):
    __tablename__ = "erp_journal_blueprints"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_journal_id", name="uq_erp_journal_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_journal_id: Mapped[int] = mapped_column(ForeignKey("stg_journal_blueprints.id"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    source_kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(180), nullable=False)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    debit_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    credit_total: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    migration_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    approval_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpJournalBlueprintLine(Base):
    __tablename__ = "erp_journal_blueprint_lines"
    __table_args__ = (UniqueConstraint("journal_id", "line_no", name="uq_erp_journal_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("erp_journal_blueprints.id"), nullable=False, index=True)
    source_line_id: Mapped[int] = mapped_column(ForeignKey("stg_journal_blueprint_lines.id"), nullable=False, unique=True, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    gl_account_id: Mapped[int] = mapped_column(ForeignKey("erp_gl_accounts.id"), nullable=False, index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    memo: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSubledgerControl(Base):
    __tablename__ = "erp_subledger_controls"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_contact_id", name="uq_erp_subledger_contact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_contact_id: Mapped[int] = mapped_column(ForeignKey("stg_contacts.id"), nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("erp_parties.id"), nullable=False, index=True)
    ledger_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    gross_due: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    return_due: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    net_due: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    explicit_opening_balance: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    advance_balance: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpTaxLedgerEvidence(Base):
    __tablename__ = "erp_tax_ledger_evidence"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_tax_id", name="uq_erp_tax_ledger_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_tax_id: Mapped[int] = mapped_column(ForeignKey("stg_tax_evidence.id"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    document_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    amount_ex_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount_with_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    relation_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpCashLedgerEvidence(Base):
    __tablename__ = "erp_cash_ledger_evidence"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_cash_id", name="uq_erp_cash_ledger_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_cash_id: Mapped[int] = mapped_column(ForeignKey("stg_cash_flow_entries.id"), nullable=False, index=True)
    gl_account_id: Mapped[int | None] = mapped_column(ForeignKey("erp_gl_accounts.id"), index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_payments.id"), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    entry_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    relation_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpTrialBalanceEvidence(Base):
    __tablename__ = "erp_trial_balance_evidence"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_trial_id", name="uq_erp_trial_balance_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_trial_id: Mapped[int] = mapped_column(ForeignKey("stg_trial_balance_entries.id"), nullable=False, index=True)
    row_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(500))
    debit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    label_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reconciliation_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpFinancialActivationGate(Base):
    __tablename__ = "erp_financial_activation_gates"
    __table_args__ = (UniqueConstraint("snapshot_id", "gate_code", name="uq_erp_financial_gate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    gate_code: Mapped[str] = mapped_column(String(100), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSecurityRole(Base):
    __tablename__ = "erp_security_roles"
    __table_args__ = (UniqueConstraint("snapshot_id", "role_code", name="uq_erp_security_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(100), nullable=False)
    role_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"), index=True)
    migration_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    assignment_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSecurityPermission(Base):
    __tablename__ = "erp_security_permissions"
    __table_args__ = (UniqueConstraint("snapshot_id", "permission_code", name="uq_erp_security_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    permission_code: Mapped[str] = mapped_column(String(180), nullable=False)
    label: Mapped[str | None] = mapped_column(String(500))
    module_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    grant_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSecurityRolePermission(Base):
    __tablename__ = "erp_security_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_erp_role_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("erp_security_roles.id"), nullable=False, index=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("erp_security_permissions.id"), nullable=False, index=True)
    source_granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    target_granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class ErpSecurityUser(Base):
    __tablename__ = "erp_security_users"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_user_id", name="uq_erp_security_user_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_user_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(200), index=True)
    display_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    source_role_name: Mapped[str | None] = mapped_column(String(200))
    account_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    password_material_copied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authentication_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSecurityUserRole(Base):
    __tablename__ = "erp_security_user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_erp_security_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("erp_security_users.id"), nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("erp_security_roles.id"), nullable=False, index=True)
    source_observed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    assignment_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpSecurityLocationScope(Base):
    __tablename__ = "erp_security_location_scopes"
    __table_args__ = (UniqueConstraint("snapshot_id", "user_id", name="uq_erp_user_location_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("erp_security_users.id"), nullable=False, index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("erp_locations.id"), index=True)
    scope_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    access_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpApprovalRoleBinding(Base):
    __tablename__ = "erp_approval_role_bindings"
    __table_args__ = (UniqueConstraint("approval_step_id", name="uq_erp_approval_role_binding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_step_id: Mapped[int] = mapped_column(ForeignKey("erp_approval_steps.id"), nullable=False, index=True)
    target_role_id: Mapped[int | None] = mapped_column(ForeignKey("erp_security_roles.id"), index=True)
    binding_status: Mapped[str] = mapped_column(String(50), nullable=False)
    assignment_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSegregationRule(Base):
    __tablename__ = "erp_segregation_rules"
    __table_args__ = (UniqueConstraint("snapshot_id", "rule_code", name="uq_erp_segregation_rule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(300), nullable=False)
    maker_capability: Mapped[str] = mapped_column(String(180), nullable=False)
    checker_capability: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    enforcement_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpSecurityPolicy(Base):
    __tablename__ = "erp_security_policies"
    __table_args__ = (UniqueConstraint("snapshot_id", "policy_code", name="uq_erp_security_policy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    policy_code: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    enforcement_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSecurityActivationGate(Base):
    __tablename__ = "erp_security_activation_gates"
    __table_args__ = (UniqueConstraint("snapshot_id", "gate_code", name="uq_erp_security_gate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    gate_code: Mapped[str] = mapped_column(String(100), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_status: Mapped[str] = mapped_column(String(40), nullable=False)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpReferenceMaster(Base):
    __tablename__ = "erp_reference_masters"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_reference_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    reference_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    reference_code: Mapped[str] = mapped_column(String(160), nullable=False)
    reference_name: Mapped[str] = mapped_column(String(500), nullable=False)
    migration_status: Mapped[str] = mapped_column(String(40), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpResidualBusinessRecord(Base):
    __tablename__ = "erp_residual_business_records"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_residual_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    evidence_class: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    migration_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSourceCoverage(Base):
    __tablename__ = "erp_source_coverage"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_source_coverage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    coverage_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_kind: Mapped[str | None] = mapped_column(String(120))
    target_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    required_action: Mapped[str | None] = mapped_column(Text)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpCoverageGate(Base):
    __tablename__ = "erp_coverage_gates"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_entity", name="uq_erp_coverage_gate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(120), nullable=False)
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_count: Mapped[int] = mapped_column(Integer, nullable=False)
    residual_count: Mapped[int] = mapped_column(Integer, nullable=False)
    presentation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpPortalIdentity(Base):
    __tablename__ = "erp_portal_identities"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_portal_identity_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("erp_parties.id"), index=True)
    username: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    department: Mapped[str | None] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(200))
    party_link_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    credential_status: Mapped[str] = mapped_column(String(50), nullable=False)
    authentication_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSalesWorkflowDocument(Base):
    __tablename__ = "erp_sales_workflow_documents"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_sales_workflow_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    workflow_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reference_no: Mapped[str | None] = mapped_column(String(160), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("erp_parties.id"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("erp_locations.id"), index=True)
    source_total_items: Mapped[str | None] = mapped_column(String(120))
    relationship_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    conversion_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpShipmentRecord(Base):
    __tablename__ = "erp_shipment_records"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_shipment_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    sale_document_id: Mapped[int | None] = mapped_column(ForeignKey("erp_transaction_documents.id"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("erp_locations.id"), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_shipping_status: Mapped[str | None] = mapped_column(String(120))
    source_payment_status: Mapped[str | None] = mapped_column(String(120))
    relationship_status: Mapped[str] = mapped_column(String(50), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpSalesTargetEvidence(Base):
    __tablename__ = "erp_sales_target_evidence"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_sales_target_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("erp_security_users.id"), index=True)
    source_user_name: Mapped[str | None] = mapped_column(String(300))
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    relationship_status: Mapped[str] = mapped_column(String(50), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpStockTransferDetailArtifact(Base):
    __tablename__ = "erp_stock_transfer_detail_artifacts"
    __table_args__ = (UniqueConstraint("snapshot_id", "source_raw_record_id", name="uq_erp_transfer_artifact_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(700))
    source_document_number: Mapped[str | None] = mapped_column(String(160))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(50), nullable=False)
    operational_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpResidualWorkflowGate(Base):
    __tablename__ = "erp_residual_workflow_gates"
    __table_args__ = (UniqueConstraint("snapshot_id", "gate_code", name="uq_erp_residual_workflow_gate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    gate_code: Mapped[str] = mapped_column(String(100), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_status: Mapped[str] = mapped_column(String(50), nullable=False)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpAuthPrincipal(Base):
    __tablename__ = "erp_auth_principals"
    __table_args__ = (UniqueConstraint("snapshot_id", "security_user_id", name="uq_erp_auth_principal_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    security_user_id: Mapped[int] = mapped_column(ForeignKey("erp_security_users.id"), nullable=False, index=True)
    login_name: Mapped[str | None] = mapped_column(String(200), index=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authentication_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpWorkflowDefinition(Base):
    __tablename__ = "erp_workflow_definitions"
    __table_args__ = (UniqueConstraint("snapshot_id", "workflow_code", name="uq_erp_workflow_definition"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    workflow_code: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(300), nullable=False)
    initial_state: Mapped[str] = mapped_column(String(50), nullable=False)
    states: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    transitions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(40), nullable=False)
    execution_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ErpRuntimeModule(Base):
    __tablename__ = "erp_runtime_modules"
    __table_args__ = (UniqueConstraint("snapshot_id", "module_code", name="uq_erp_runtime_module"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    module_code: Mapped[str] = mapped_column(String(80), nullable=False)
    module_name: Mapped[str] = mapped_column(String(200), nullable=False)
    route_prefix: Mapped[str] = mapped_column(String(160), nullable=False)
    module_status: Mapped[str] = mapped_column(String(40), nullable=False)
    operation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpRuntimeActivationGate(Base):
    __tablename__ = "erp_runtime_activation_gates"
    __table_args__ = (UniqueConstraint("snapshot_id", "gate_code", name="uq_erp_runtime_gate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    gate_code: Mapped[str] = mapped_column(String(100), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_status: Mapped[str] = mapped_column(String(50), nullable=False)
    activation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpApprovalRequest(Base):
    __tablename__ = "erp_approval_requests"
    __table_args__ = (UniqueConstraint("snapshot_id", "request_key", name="uq_erp_approval_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(180), nullable=False)
    workflow_definition_id: Mapped[int] = mapped_column(ForeignKey("erp_workflow_definitions.id"), nullable=False, index=True)
    resource_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    current_state: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_by_principal_id: Mapped[int | None] = mapped_column(ForeignKey("erp_auth_principals.id"), index=True)
    execution_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ErpApprovalDecision(Base):
    __tablename__ = "erp_approval_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_request_id: Mapped[int] = mapped_column(ForeignKey("erp_approval_requests.id"), nullable=False, index=True)
    principal_id: Mapped[int | None] = mapped_column(ForeignKey("erp_auth_principals.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


def _reject_append_only_mutation(mapper, connection, target) -> None:
    raise RuntimeError(f"Append-only record cannot be changed or deleted: {type(target).__name__}#{target.id}")


for _append_only_model in (ErpSourceKeyRegistry, ErpAuditEvent):
    event.listen(_append_only_model, "before_update", _reject_append_only_mutation)
    event.listen(_append_only_model, "before_delete", _reject_append_only_mutation)
