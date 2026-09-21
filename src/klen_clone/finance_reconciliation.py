from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import (
    OperationalAuditEvent,
    OperationalBase,
    OperationalFinancialMigrationException,
    OperationalOpeningBalanceBatch,
    utc_now,
)


RESOLUTION_TYPES = {
    "recheck_final_sync",
    "source_correction_required",
    "target_mapping_correction",
    "accepted_test_variance",
}


class OperationalFinanceReconciliationReview(OperationalBase):
    __tablename__ = "operational_finance_reconciliation_reviews"
    __table_args__ = (
        UniqueConstraint("company_code", "control_key", name="uq_operational_finance_reconciliation"),
        CheckConstraint(
            "control_type IN ('trial_balance','opening_balance_exception')",
            name="ck_operational_finance_reconciliation_type",
        ),
        CheckConstraint(
            "status IN ('draft','pending','approved','rejected')",
            name="ck_operational_finance_reconciliation_status",
        ),
        CheckConstraint("posting_enabled = false", name="ck_operational_finance_reconciliation_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    control_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    control_key: Mapped[str] = mapped_column(String(220), nullable=False)
    control_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    authoritative_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    comparison_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    variance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    resolution_type: Mapped[str | None] = mapped_column(String(50))
    proposal_note: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    posting_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def initialize_finance_reconciliation(
    session: Session, *, snapshot_name: str, trial_balance: dict, actor: str = "finance_reconciliation"
) -> int:
    controls: list[dict] = []
    trial_difference = _money(trial_balance.get("difference"))
    if int(trial_balance.get("rows") or 0) and trial_difference:
        controls.append({
            "control_type": "trial_balance",
            "control_key": f"trial_balance:{snapshot_name}",
            "control_name": "Trial balance difference",
            "source_reference": snapshot_name,
            "source_fingerprint": snapshot_name,
            "authoritative_amount": _money(trial_balance.get("debit")),
            "comparison_amount": _money(trial_balance.get("credit")),
            "variance_amount": trial_difference,
        })

    batches = {row.id: row for row in session.scalars(select(OperationalOpeningBalanceBatch))}
    for exception in session.scalars(select(OperationalFinancialMigrationException).order_by(
            OperationalFinancialMigrationException.id)):
        batch = batches.get(exception.batch_id)
        if batch is None:
            continue
        controls.append({
            "control_type": "opening_balance_exception",
            "control_key": f"opening_exception:{batch.batch_key}:{exception.control_name}",
            "control_name": exception.control_name,
            "source_reference": batch.source_capture,
            "source_fingerprint": batch.source_manifest_sha256,
            "authoritative_amount": _money(exception.authoritative_amount),
            "comparison_amount": _money(exception.comparison_amount),
            "variance_amount": _money(exception.variance_amount),
        })

    created = 0
    for control in controls:
        if session.scalar(select(OperationalFinanceReconciliationReview.id).where(
                OperationalFinanceReconciliationReview.company_code == "ASAS",
                OperationalFinanceReconciliationReview.control_key == control["control_key"])):
            continue
        session.add(OperationalFinanceReconciliationReview(
            review_key=str(uuid.uuid4()), company_code="ASAS", status="draft", revision=1,
            posting_enabled=False, **control,
        ))
        created += 1
    if created:
        session.add(OperationalAuditEvent(
            event_key=str(uuid.uuid4()), event_type="finance.reconciliation_seeded", actor=actor,
            resource_key="ASAS", detail=f"created={created}; test evidence only; posting disabled",
        ))
        session.commit()
    return created


def _review(session: Session, review_key: str, *, lock: bool = False) -> OperationalFinanceReconciliationReview:
    query = select(OperationalFinanceReconciliationReview).where(
        OperationalFinanceReconciliationReview.review_key == review_key,
        OperationalFinanceReconciliationReview.company_code == "ASAS",
    )
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ValueError("Finance reconciliation review was not found")
    return row


def request_reconciliation_review(
    session: Session, *, actor: str, review_key: str, resolution_type: str, note: str
) -> OperationalFinanceReconciliationReview:
    if resolution_type not in RESOLUTION_TYPES:
        raise ValueError("Unsupported finance reconciliation resolution")
    row = _review(session, review_key, lock=True)
    if row.status == "pending":
        raise RuntimeError("This reconciliation plan is already awaiting approval")
    if row.status == "approved":
        raise RuntimeError("This reconciliation plan is already approved")
    row.status = "pending"
    row.resolution_type = resolution_type
    row.proposal_note = note.strip()
    row.proposed_by = actor
    row.decision_note = None
    row.decided_by = None
    row.revision += 1
    row.updated_at = utc_now()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="finance.reconciliation_requested", actor=actor,
        resource_key=row.review_key,
        detail=f"control={row.control_key}; resolution={resolution_type}; revision={row.revision}; posting disabled",
    ))
    session.commit()
    return row


def decide_reconciliation_review(
    session: Session, *, actor: str, review_key: str, action: str, expected_revision: int, note: str
) -> OperationalFinanceReconciliationReview:
    if action not in {"approve", "reject"}:
        raise ValueError("Reconciliation decision must be approve or reject")
    row = _review(session, review_key, lock=True)
    if row.status != "pending":
        raise RuntimeError("This reconciliation plan is not awaiting approval")
    if row.revision != expected_revision:
        raise RuntimeError(f"Finance reconciliation revision conflict; current revision is {row.revision}")
    if row.proposed_by and row.proposed_by.casefold() == actor.casefold():
        raise PermissionError("The reconciliation maker cannot decide their own plan")
    row.status = "approved" if action == "approve" else "rejected"
    row.decision_note = note.strip()
    row.decided_by = actor
    row.revision += 1
    row.updated_at = utc_now()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"finance.reconciliation_{action}d", actor=actor,
        resource_key=row.review_key,
        detail=f"control={row.control_key}; revision={row.revision}; posting disabled",
    ))
    session.commit()
    return row


def _cause_analysis(row: OperationalFinanceReconciliationReview) -> dict:
    authoritative = f"AED {row.authoritative_amount:.2f}"
    comparison = f"AED {row.comparison_amount:.2f}"
    if row.control_type == "trial_balance":
        return {
            "classification": "partially_explained_export_structure_defect",
            "confidence": "partially explained",
            "summary": (
                "AED 26,685.11 of the displayed difference is explained by customer and supplier detail rows "
                "repeating their parent controls. The remaining top-level difference of AED 41,042.55 is unresolved; "
                "46 amount-bearing detail rows also have no account label."
            ),
            "calculation": f"All exported rows: {authoritative} debit versus {comparison} credit.",
            "evidence_sources": ["trial_balance_2026.xlsx", "Browser UI top-level trial balance"],
            "supporting_facts": [
                "Accounts Receivable parent and child rows both show AED 2,551.60.",
                "Supplier parent and child net rows both show AED 38,953.43.",
                "Customer parent and child net rows both show AED 63,086.94.",
                "Detail-row net AED 26,685.11 plus top-level difference AED 41,042.55 equals AED 67,727.66.",
            ],
            "recommended_action": (
                "Do not create a balancing journal. Export a clean leaf-account trial balance at the final frozen "
                "cutoff, require every row to have an account code, and reconcile debit to credit before import."
            ),
        }
    details = {
        "customer_header_due": {
            "calculation": f"Customer contact net {authoritative} versus sales header due less sales-return due {comparison}.",
            "evidence_sources": ["customers_current.csv", "sales_2026_current.csv", "sales_returns_2026_current.csv"],
            "supporting_facts": [
                "Contact-master due values are party-level controls.",
                "Sales and return registers are document-level reports captured separately.",
            ],
            "workspace": "receivable ageing",
        },
        "supplier_header_due": {
            "calculation": f"Supplier contact net {authoritative} versus purchase header due less purchase-return due {comparison}.",
            "evidence_sources": ["suppliers_current.csv", "purchases_2026_current.csv", "purchase_returns_2026_current.csv"],
            "supporting_facts": [
                "Contact-master due values are party-level controls.",
                "Purchase and return registers are document-level reports captured separately.",
            ],
            "workspace": "payable ageing",
        },
        "combined_ytd_due": {
            "calculation": f"Customer contact net less supplier contact net {authoritative} versus YTD customer/supplier report due {comparison}.",
            "evidence_sources": ["customers_current.csv", "suppliers_current.csv", "customer_supplier_report_ytd.csv"],
            "supporting_facts": [
                "The YTD report applies its own reporting-period and sign presentation.",
                "Customer and supplier masters were exported separately from the YTD report.",
            ],
            "workspace": "receivable and payable ageing",
        },
    }.get(row.control_name, {})
    return {
        "classification": "unresolved_non_atomic_report_variance",
        "confidence": "requires final-sync investigation",
        "summary": (
            "The current files prove which reports disagree, but they cannot prove the exact transaction that caused "
            "the difference because the exports were sequential and the reports use different balance semantics."
        ),
        "calculation": details.get("calculation", f"{authoritative} versus {comparison}."),
        "evidence_sources": details.get("evidence_sources", []),
        "supporting_facts": details.get("supporting_facts", []),
        "recommended_action": (
            f"Use the {details.get('workspace', 'AR/AP ageing')} workspace to identify party-level differences, then "
            "repeat all reports at one frozen cutoff. Correct BizModo or the ERP mapping only after the mismatching "
            "records are evidenced."
        ),
    }


def finance_reconciliation_payload(session: Session) -> dict:
    batches = session.scalars(select(OperationalOpeningBalanceBatch).order_by(
        OperationalOpeningBalanceBatch.id.desc())).all()
    rows = session.scalars(select(OperationalFinanceReconciliationReview).where(
        OperationalFinanceReconciliationReview.company_code == "ASAS").order_by(
        OperationalFinanceReconciliationReview.control_type,
        OperationalFinanceReconciliationReview.control_name)).all()
    return {
        "reviews": [{
            "review_key": row.review_key,
            "control_type": row.control_type,
            "control_key": row.control_key,
            "control_name": row.control_name,
            "source_reference": row.source_reference,
            "source_fingerprint": row.source_fingerprint,
            "authoritative_amount": row.authoritative_amount,
            "comparison_amount": row.comparison_amount,
            "variance_amount": row.variance_amount,
            "status": row.status,
            "resolution_type": row.resolution_type,
            "proposal_note": row.proposal_note,
            "proposed_by": row.proposed_by,
            "decision_note": row.decision_note,
            "decided_by": row.decided_by,
            "revision": row.revision,
            "posting_enabled": False,
            "cause_analysis": _cause_analysis(row),
        } for row in rows],
        "opening_balance_batches": [{
            "batch_key": row.batch_key,
            "source_capture": row.source_capture,
            "source_manifest_sha256": row.source_manifest_sha256,
            "status": row.status,
            "receivable_rows": row.receivable_rows,
            "receivable_amount": row.receivable_amount,
            "customer_advance_rows": row.customer_advance_rows,
            "customer_advance_amount": row.customer_advance_amount,
            "payable_rows": row.payable_rows,
            "payable_amount": row.payable_amount,
            "supplier_advance_rows": row.supplier_advance_rows,
            "supplier_advance_amount": row.supplier_advance_amount,
            "source_atomic": row.source_atomic,
        } for row in batches],
        "controls": {
            "test_data_only": True,
            "final_sync_required": True,
            "posting_enabled": False,
            "approved_plans": sum(row.status == "approved" for row in rows),
            "pending_plans": sum(row.status == "pending" for row in rows),
            "unresolved_variances": sum(row.variance_amount != 0 for row in rows),
        },
    }
