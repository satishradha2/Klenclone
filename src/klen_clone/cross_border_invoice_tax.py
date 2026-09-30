"""Evidence-backed, independent tax review for a delivered foreign sale.

This is a controlled staging decision, not automatic legal classification.
Document categories and a reviewer attestation are required before a non-posting
invoice draft may copy the already approved quotation/order tax snapshots.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .delivery_fulfillment import OperationalDeliveryFulfillment
from .operational import OperationalAuditEvent, OperationalBase, utc_now


EVIDENCE_KINDS = frozenset({"customs_declaration", "commercial_transport", "shipping_certificate", "official_exit", "tax_memo"})
MIME_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


class OperationalExportTaxDecision(OperationalBase):
    __tablename__ = "operational_export_tax_decisions"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','consumed')", name="ck_export_tax_status"),
                      CheckConstraint("tax_treatment IN ('zero_rated','standard_rated')", name="ck_export_tax_treatment"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    fulfillment_key: Mapped[str] = mapped_column(String(36), nullable=False)
    delivery_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(20), nullable=False)
    tax_basis: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    consumed_by: Mapped[str | None] = mapped_column(String(200))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documents: Mapped[list["OperationalExportEvidenceDocument"]] = relationship(back_populates="decision")


class OperationalExportEvidenceDocument(OperationalBase):
    __tablename__ = "operational_export_evidence_documents"
    __table_args__ = (UniqueConstraint("decision_id", "kind", name="uq_export_evidence_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("operational_export_tax_decisions.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    uploaded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    decision: Mapped[OperationalExportTaxDecision] = relationship(back_populates="documents")


class OperationalExportTaxInvoiceUse(OperationalBase):
    __tablename__ = "operational_export_tax_invoice_uses"
    __table_args__ = (UniqueConstraint("decision_id", name="uq_export_tax_decision_use"),
                      UniqueConstraint("invoice_id", name="uq_export_tax_invoice_use"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("operational_export_tax_decisions.id"), nullable=False)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_invoices.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


def delivery_fingerprint(fulfillment: OperationalDeliveryFulfillment) -> str:
    order = fulfillment.sales_order
    payload = [fulfillment.fulfillment_key, fulfillment.status, fulfillment.revision,
               fulfillment.delivery_note_no, fulfillment.pod_reference, fulfillment.received_by,
               fulfillment.delivered_at.isoformat() if fulfillment.delivered_at else None,
               order.order_key, order.customer_code, order.customer_country_code,
               order.currency_code, str(order.subtotal), str(order.discount_amount),
               str(order.tax_amount), str(order.total_amount),
               [[line.line_no, line.sku, str(line.delivered_quantity_base)] for line in fulfillment.lines]]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _check_delivery(session: Session, fulfillment: OperationalDeliveryFulfillment) -> None:
    if fulfillment.status != "delivered" or not fulfillment.delivered_at or not fulfillment.pod_reference:
        raise ValueError("A delivered foreign order with proof of delivery is required")
    if fulfillment.sales_order.customer_country_code in (None, "AE"):
        raise ValueError("This review is only for a non-UAE customer order")
    from .cross_border_dispatch_release import OperationalCrossBorderDispatchRelease
    release = session.scalar(select(OperationalCrossBorderDispatchRelease.id).where(
        OperationalCrossBorderDispatchRelease.fulfillment_id == fulfillment.id,
        OperationalCrossBorderDispatchRelease.status == "consumed"))
    if not release:
        raise ValueError("A consumed independent physical dispatch release is required")


def _decode_document(item: dict) -> tuple[str, str, str, bytes]:
    kind = str(item.get("kind", "")).strip()
    filename = str(item.get("filename", "")).replace("\\", "/").split("/")[-1].strip()
    content_type = str(item.get("content_type", "")).strip().lower()
    if kind not in EVIDENCE_KINDS or not filename or len(filename) > 200 or content_type not in MIME_TYPES:
        raise ValueError("A supported evidence category, filename and PDF/PNG/JPEG type are required")
    try:
        encoded = str(item.get("content_base64", ""))
        if len(encoded) > 4 * ((MAX_DOCUMENT_BYTES + 2) // 3):
            raise ValueError("Evidence file exceeds 2 MiB")
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Evidence file is not valid base64") from exc
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Each evidence file must be between 1 byte and 2 MiB")
    if not ((content_type == "application/pdf" and content.startswith(b"%PDF-")) or
            (content_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
            (content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))):
        raise ValueError("Evidence file content does not match its declared type")
    return kind, filename, content_type, content


def _evidence_combination(kinds: set[str]) -> bool:
    # UAE FTA VATP040, Article 30: alternative documentary combinations.
    # Presence does not prove authenticity; an independent reviewer must attest.
    return ({"customs_declaration", "commercial_transport"} <= kinds or
            {"shipping_certificate", "official_exit"} <= kinds)


def tax_decision_payload(row: OperationalExportTaxDecision) -> dict:
    return {"decision_key": row.decision_key, "fulfillment_key": row.fulfillment_key,
            "customer_country_code": row.customer_country_code, "currency_code": row.currency_code,
            "tax_treatment": row.tax_treatment, "tax_basis": row.tax_basis,
            "valid_until": row.valid_until, "status": row.status, "revision": row.revision,
            "created_by": row.created_by, "decided_by": row.decided_by,
            "decision_note": row.decision_note, "invoice_key": None,
            "documents": [{"document_key": doc.document_key, "kind": doc.kind,
                           "filename": doc.filename, "content_sha256": doc.content_sha256,
                           "content_size": doc.content_size} for doc in row.documents],
            "posting_enabled": False}


def prepare_export_tax_decision(session: Session, fulfillment: OperationalDeliveryFulfillment, *,
                                tax_treatment: str, tax_basis: str, valid_until: date,
                                documents: list[dict], actor: str) -> OperationalExportTaxDecision:
    _check_delivery(session, fulfillment)
    if tax_treatment not in {"zero_rated", "standard_rated"} or len(tax_basis.strip()) < 20:
        raise ValueError("Choose a tax treatment and explain the basis in at least 20 characters")
    if valid_until < date.today():
        raise ValueError("Tax review validity must include today")
    existing = session.scalar(select(OperationalExportTaxDecision.id).where(
        OperationalExportTaxDecision.fulfillment_id == fulfillment.id,
        OperationalExportTaxDecision.status.in_(("pending", "approved", "consumed"))))
    if existing:
        raise ValueError("An active or consumed tax review already exists for this delivery")
    if not 1 <= len(documents) <= 5:
        raise ValueError("Attach one to five actual evidence files")
    decoded = [_decode_document(item) for item in documents]
    kinds = {kind for kind, _, _, _ in decoded}
    if len(kinds) != len(decoded):
        raise ValueError("Attach only one file per evidence category")
    if tax_treatment == "zero_rated" and not _evidence_combination(kinds):
        raise ValueError("Zero-rating requires customs declaration plus commercial transport evidence, or shipping certificate plus official exit evidence")
    if tax_treatment == "standard_rated" and "tax_memo" not in kinds:
        raise ValueError("Standard-rated foreign treatment requires an attached tax memo")
    expected_rate = Decimal("0") if tax_treatment == "zero_rated" else Decimal("5")
    if any(Decimal(line.tax_rate) != expected_rate for line in fulfillment.sales_order.lines):
        raise ValueError("Final tax rate differs from the approved quotation; revise the commercial document before invoicing")
    row = OperationalExportTaxDecision(decision_key=str(uuid.uuid4()), fulfillment_id=fulfillment.id,
        fulfillment_key=fulfillment.fulfillment_key, delivery_fingerprint=delivery_fingerprint(fulfillment),
        customer_country_code=fulfillment.sales_order.customer_country_code,
        currency_code=fulfillment.sales_order.currency_code, tax_treatment=tax_treatment,
        tax_basis=tax_basis.strip(), valid_until=valid_until, created_by=actor)
    for kind, filename, content_type, content in decoded:
        row.documents.append(OperationalExportEvidenceDocument(document_key=str(uuid.uuid4()),
            kind=kind, filename=filename, content_type=content_type,
            content_sha256=hashlib.sha256(content).hexdigest(), content_size=len(content),
            content=content, uploaded_by=actor))
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="export_tax.prepared",
        actor=actor, resource_key=row.decision_key,
        detail=f"{fulfillment.fulfillment_no}; {tax_treatment}; {len(decoded)} immutable evidence files; invoice held"))
    session.commit()
    return row


def decide_export_tax_decision(session: Session, row: OperationalExportTaxDecision, *,
                               expected_revision: int, action: str, note: str,
                               actor: str) -> OperationalExportTaxDecision:
    if row.status != "pending" or action not in {"approve", "reject"}:
        raise ValueError("Only pending export tax reviews can be decided")
    if row.revision != expected_revision:
        raise ValueError(f"Export tax revision conflict; current revision is {row.revision}")
    fulfillment = session.get(OperationalDeliveryFulfillment, row.fulfillment_id)
    _check_delivery(session, fulfillment)
    if row.delivery_fingerprint != delivery_fingerprint(fulfillment) or row.valid_until < date.today():
        raise ValueError("Tax review expired or delivery/order evidence changed")
    if actor in {row.created_by, fulfillment.created_by, fulfillment.sales_order.created_by,
                 fulfillment.sales_order.quotation.created_by}:
        raise PermissionError("Tax reviewer must be independent of the dossier, delivery, order and quotation makers")
    if len(note.strip()) < 20:
        raise ValueError("An independent document and tax assessment of at least 20 characters is required")
    if action == "approve":
        kinds = {document.kind for document in row.documents}
        if row.tax_treatment == "zero_rated" and not _evidence_combination(kinds):
            raise ValueError("Required export evidence combination is incomplete")
        if any(hashlib.sha256(document.content).hexdigest() != document.content_sha256
               for document in row.documents):
            raise ValueError("Stored evidence integrity check failed")
    row.status = "approved" if action == "approve" else "rejected"
    row.revision += 1; row.decided_by = actor; row.decided_at = utc_now(); row.decision_note = note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"export_tax.{action}",
        actor=actor, resource_key=row.decision_key,
        detail=f"{fulfillment.fulfillment_no}; {row.tax_treatment}; independent review; no posting"))
    session.commit()
    return row


def approved_export_tax_decision(session: Session, fulfillment: OperationalDeliveryFulfillment,
                                 *, invoice_date: date) -> OperationalExportTaxDecision:
    _check_delivery(session, fulfillment)
    row = session.scalar(select(OperationalExportTaxDecision).where(
        OperationalExportTaxDecision.fulfillment_id == fulfillment.id,
        OperationalExportTaxDecision.status == "approved"))
    if not row or row.valid_until < invoice_date or row.valid_until < date.today():
        raise ValueError("A current, independently approved export tax decision is required")
    if row.delivery_fingerprint != delivery_fingerprint(fulfillment):
        raise ValueError("Approved export tax review no longer matches the delivered order")
    if row.customer_country_code != fulfillment.sales_order.customer_country_code or row.currency_code != fulfillment.sales_order.currency_code:
        raise ValueError("Approved export tax destination or currency no longer matches")
    expected_rate = Decimal("0") if row.tax_treatment == "zero_rated" else Decimal("5")
    if any(Decimal(line.tax_rate) != expected_rate for line in fulfillment.sales_order.lines):
        raise ValueError("Approved invoice tax treatment differs from the quotation/order rate")
    if row.tax_treatment == "zero_rated" and not _evidence_combination({doc.kind for doc in row.documents}):
        raise ValueError("Approved zero-rate evidence is incomplete")
    if any(hashlib.sha256(doc.content).hexdigest() != doc.content_sha256 for doc in row.documents):
        raise ValueError("Stored evidence integrity check failed")
    return row
