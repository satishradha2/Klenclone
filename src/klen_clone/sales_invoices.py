from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import (
    MONEY,
    OperationalAuditEvent,
    OperationalBase,
    OperationalDraft,
    OperationalFiscalPeriod,
    OperationalStockReservation,
    utc_now,
)


class OperationalSalesInvoicePostingRehearsal(OperationalBase):
    __tablename__ = "operational_sales_invoice_posting_rehearsals"
    __table_args__ = (
        UniqueConstraint("sales_invoice_id", "invoice_revision", name="uq_sales_invoice_rehearsal_revision"),
        CheckConstraint("status = 'verified'", name="ck_sales_invoice_rehearsal_status"),
        CheckConstraint("posting_enabled = false", name="ck_sales_invoice_rehearsal_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    sales_invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_drafts.id"), nullable=False, index=True)
    invoice_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    movements_json: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="verified", nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def sales_invoice_rehearsal_payload(
    rehearsal: OperationalSalesInvoicePostingRehearsal,
    invoice: OperationalDraft,
    *,
    idempotent_replay: bool = False,
) -> dict:
    journal = json.loads(rehearsal.journal_json)
    movements = json.loads(rehearsal.movements_json)
    reversal = json.loads(rehearsal.reversal_json)
    for row in journal:
        row["debit"], row["credit"] = _money(row["debit"]), _money(row["credit"])
    for row in movements:
        row["quantity_base"] = Decimal(row["quantity_base"])
        row["unit_cost"] = Decimal(row["unit_cost"])
        row["unit_cost_snapshot"] = Decimal(row["unit_cost_snapshot"])
        row["value_delta"] = _money(row["value_delta"])
    for row in reversal["journal"]:
        row["debit"], row["credit"] = _money(row["debit"]), _money(row["credit"])
    for row in reversal["movements"]:
        row["quantity_base"] = Decimal(row["quantity_base"])
        row["unit_cost"] = Decimal(row["unit_cost"])
        row["unit_cost_snapshot"] = Decimal(row["unit_cost_snapshot"])
        row["value_delta"] = _money(row["value_delta"])
    reversal["inventory"] = reversal["movements"]
    debit = sum((_money(row["debit"]) for row in journal), Decimal("0"))
    credit = sum((_money(row["credit"]) for row in journal), Decimal("0"))
    cogs = sum((_money(row["debit"]) for row in journal if row["account_code"] == "5000"), Decimal("0"))
    return {
        "rehearsal_key": rehearsal.rehearsal_key,
        "invoice_key": invoice.draft_key,
        "invoice_no": invoice.draft_no,
        "invoice_revision": rehearsal.invoice_revision,
        "period_key": rehearsal.period_key,
        "fiscal_period": rehearsal.period_key,
        "posting_fingerprint": rehearsal.posting_fingerprint,
        "idempotency_key": f"{invoice.draft_key}:{rehearsal.invoice_revision}:{rehearsal.posting_fingerprint[:16]}",
        "journal": journal,
        "movements": movements,
        "inventory": movements,
        "reversal": reversal,
        "debit": debit,
        "credit": credit,
        "cost_of_goods_sold": cogs,
        "rollback_verified": True,
        "posting_performed": False,
        "posting_enabled": False,
        "idempotent_replay": idempotent_replay,
    }


def rehearse_sales_invoice_posting(session: Session, invoice: OperationalDraft, *, actor: str) -> dict:
    if invoice.document_type != "sale":
        raise ValueError("Only a sales invoice can use the sales-invoice posting rehearsal")
    if invoice.status != "approved":
        raise ValueError("Only an approved sales invoice can enter posting rehearsal")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= invoice.created_at.date(),
        OperationalFiscalPeriod.ends_on >= invoice.created_at.date(),
    ).with_for_update())
    if not period or period.status != "open" or not period.rehearsal_enabled:
        raise ValueError(f"Fiscal period is not open for rehearsal on {invoice.created_at.date().isoformat()}")
    existing = session.scalar(select(OperationalSalesInvoicePostingRehearsal).where(
        OperationalSalesInvoicePostingRehearsal.sales_invoice_id == invoice.id,
        OperationalSalesInvoicePostingRehearsal.invoice_revision == invoice.revision,
    ))
    if existing:
        return sales_invoice_rehearsal_payload(existing, invoice, idempotent_replay=True)

    reservations = list(session.scalars(select(OperationalStockReservation).where(
        OperationalStockReservation.draft_id == invoice.id,
        OperationalStockReservation.status == "active",
    )))
    reserved_by_line = {row.draft_line_id: Decimal(row.quantity_base) for row in reservations}
    if any(reserved_by_line.get(line.id) != Decimal(line.quantity_base) for line in invoice.lines):
        raise ValueError("Active stock reservations do not fully cover the approved sales invoice")
    missing_cost = [line.sku for line in invoice.lines
                    if line.unit_cost_snapshot is None or line.unit_cost_snapshot <= 0]
    if missing_cost:
        raise ValueError(f"Cost basis is unavailable for SKU(s): {', '.join(missing_cost)}")

    revenue = _money(invoice.subtotal - invoice.discount_amount)
    total_cogs = sum((_money(line.cost_amount) for line in invoice.lines), Decimal("0"))
    journal = [
        {"account": "Trade receivables", "account_code": "1200", "debit": str(_money(invoice.total_amount)), "credit": "0"},
        {"account": "Sales revenue", "account_code": "4000", "debit": "0", "credit": str(revenue)},
        {"account": "Output VAT payable", "account_code": "2120", "debit": "0", "credit": str(_money(invoice.tax_amount))},
        {"account": "Cost of goods sold", "account_code": "5000", "debit": str(total_cogs), "credit": "0"},
        {"account": "Inventory", "account_code": "1300", "debit": "0", "credit": str(total_cogs)},
    ]
    debit = sum((_money(row["debit"]) for row in journal), Decimal("0"))
    credit = sum((_money(row["credit"]) for row in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError(f"Posting rehearsal is not balanced: debit {debit}, credit {credit}")
    movements = [{
        "line_no": line.line_no,
        "sku": line.sku,
        "location": invoice.location_code,
        "canonical_uom": line.canonical_uom,
        "quantity_base": str(-Decimal(line.quantity_base)),
        "unit_cost": str(Decimal(line.unit_cost_snapshot)),
        "unit_cost_snapshot": str(Decimal(line.unit_cost_snapshot)),
        "value_delta": str(-_money(line.cost_amount)),
    } for line in invoice.lines]
    reversal = {
        "journal": [{**row, "debit": row["credit"], "credit": row["debit"]}
                    for row in reversed(journal)],
        "movements": [{**row, "quantity_base": str(-Decimal(row["quantity_base"])),
                       "value_delta": str(-_money(row["value_delta"]))}
                      for row in reversed(movements)],
    }
    fingerprint_source = json.dumps({"invoice_key": invoice.draft_key, "revision": invoice.revision,
                                     "period_key": period.period_key, "journal": journal,
                                     "movements": movements}, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    rehearsal = OperationalSalesInvoicePostingRehearsal(
        rehearsal_key=str(uuid.uuid4()), sales_invoice_id=invoice.id,
        invoice_revision=invoice.revision, period_key=period.period_key,
        posting_fingerprint=fingerprint,
        journal_json=json.dumps(journal, sort_keys=True),
        movements_json=json.dumps(movements, sort_keys=True),
        reversal_json=json.dumps(reversal, sort_keys=True),
        status="verified", posting_enabled=False, generated_by=actor,
    )
    session.add(rehearsal)
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="sales_invoice.posting_rehearsed", actor=actor,
        resource_key=invoice.draft_key,
        detail=f"balanced {debit}; {len(movements)} stock movements; persistent non-posting rehearsal",
    ))
    session.commit()
    return sales_invoice_rehearsal_payload(rehearsal, invoice)


def sales_invoice_control_counts(session: Session) -> dict:
    return {
        "sales_invoices": session.scalar(select(func.count(OperationalDraft.id)).where(
            OperationalDraft.document_type == "sale")) or 0,
        "posting_rehearsals": session.scalar(select(func.count(OperationalSalesInvoicePostingRehearsal.id))) or 0,
    }
