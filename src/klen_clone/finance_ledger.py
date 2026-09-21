from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .finance_foundation import OperationalAccountMapping, OperationalChartAccount
from .operational import (
    OperationalAuditEvent,
    OperationalBase,
    OperationalDraft,
    OperationalFiscalPeriod,
    OperationalJournalBatch,
    utc_now,
)

ZERO = Decimal("0.00")


class OperationalGeneralJournal(OperationalBase):
    __tablename__ = "operational_general_journals"
    __table_args__ = (
        CheckConstraint("status IN ('draft','pending','approved','rejected')", name="ck_general_journal_status"),
        CheckConstraint("posting_enabled = false", name="ck_general_journal_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    journal_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    company_code: Mapped[str] = mapped_column(String(40), default="ASAS", nullable=False, index=True)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    branch_code: Mapped[str] = mapped_column(String(80), default="MAIN", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    test_data_only: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    prepared_by: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    lines: Mapped[list["OperationalGeneralJournalLine"]] = relationship(
        back_populates="journal", cascade="all, delete-orphan", order_by="OperationalGeneralJournalLine.line_no"
    )


class OperationalGeneralJournalLine(OperationalBase):
    __tablename__ = "operational_general_journal_lines"
    __table_args__ = (
        UniqueConstraint("journal_id", "line_no", name="uq_general_journal_line"),
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_general_journal_nonnegative"),
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_general_journal_one_side",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("operational_general_journals.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500))
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    journal: Mapped[OperationalGeneralJournal] = relationship(back_populates="lines")


def _money(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def _validate_lines(session: Session, lines: list[dict]) -> tuple[list[dict], Decimal]:
    if len(lines) < 2:
        raise ValueError("A journal requires at least two lines")
    active = {row.account_code: row for row in session.scalars(select(OperationalChartAccount).where(
        OperationalChartAccount.company_code == "ASAS",
        OperationalChartAccount.status == "active",
        OperationalChartAccount.is_postable.is_(True),
    ))}
    normalized = []
    for number, source in enumerate(lines, 1):
        account_code = str(source.get("account_code") or "").strip()
        debit, credit = _money(source.get("debit")), _money(source.get("credit"))
        if account_code not in active:
            raise ValueError(f"Account {account_code} is not an active postable account")
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise ValueError(f"Journal line {number} must contain a positive debit or a positive credit, but not both")
        normalized.append({
            "line_no": number,
            "account_code": account_code,
            "description": (str(source.get("description") or "").strip() or None),
            "debit": debit,
            "credit": credit,
        })
    debit_total = sum((row["debit"] for row in normalized), ZERO)
    credit_total = sum((row["credit"] for row in normalized), ZERO)
    if debit_total != credit_total:
        raise ValueError(f"Journal is not balanced: debit AED {debit_total:.2f}, credit AED {credit_total:.2f}")
    if debit_total <= 0:
        raise ValueError("Journal total must be greater than zero")
    return normalized, debit_total


def _replace_lines(journal: OperationalGeneralJournal, lines: list[dict]) -> None:
    journal.lines.clear()
    journal.lines.extend(OperationalGeneralJournalLine(**row) for row in lines)


def create_general_journal(session: Session, *, actor: str, journal_date: date, branch_code: str,
                           reference: str | None, description: str, lines: list[dict]) -> OperationalGeneralJournal:
    normalized, total = _validate_lines(session, lines)
    key = str(uuid.uuid4())
    journal = OperationalGeneralJournal(
        journal_key=key,
        journal_no=f"JV-TEST-{journal_date:%Y%m%d}-{key[:8].upper()}",
        journal_date=journal_date,
        branch_code=branch_code.strip().upper(),
        reference=reference.strip() if reference else None,
        description=description.strip(),
        prepared_by=actor,
        status="draft",
        posting_enabled=False,
        test_data_only=True,
    )
    _replace_lines(journal, normalized)
    session.add(journal)
    session.flush()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="finance.general_journal_created", actor=actor,
        resource_key=journal.journal_key,
        detail=f"journal={journal.journal_no}; total={total:.2f}; test only; posting disabled",
    ))
    session.commit()
    return journal


def replace_general_journal(session: Session, journal: OperationalGeneralJournal, *, actor: str,
                            expected_revision: int, journal_date: date, branch_code: str,
                            reference: str | None, description: str,
                            lines: list[dict]) -> OperationalGeneralJournal:
    if journal.status not in {"draft", "rejected"}:
        raise ValueError("Only a draft or rejected journal can be edited")
    if journal.revision != expected_revision:
        raise RuntimeError(f"General-journal revision conflict; current revision is {journal.revision}")
    normalized, total = _validate_lines(session, lines)
    journal.journal_date = journal_date
    journal.branch_code = branch_code.strip().upper()
    journal.reference = reference.strip() if reference else None
    journal.description = description.strip()
    journal.status = "draft"
    journal.requested_by = None
    journal.decided_by = None
    journal.decision_note = None
    journal.revision += 1
    journal.updated_at = utc_now()
    _replace_lines(journal, normalized)
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="finance.general_journal_revised", actor=actor,
        resource_key=journal.journal_key,
        detail=f"revision={journal.revision}; total={total:.2f}; test only; posting disabled",
    ))
    session.commit()
    return journal


def transition_general_journal(session: Session, journal: OperationalGeneralJournal, *, actor: str,
                               action: str, expected_revision: int, note: str) -> OperationalGeneralJournal:
    if journal.revision != expected_revision:
        raise RuntimeError(f"General-journal revision conflict; current revision is {journal.revision}")
    transitions = {
        ("draft", "request"): "pending",
        ("rejected", "request"): "pending",
        ("pending", "approve"): "approved",
        ("pending", "reject"): "rejected",
    }
    target = transitions.get((journal.status, action))
    if target is None:
        raise ValueError(f"Action {action} is not allowed from {journal.status}")
    if action in {"approve", "reject"} and journal.requested_by and journal.requested_by.casefold() == actor.casefold():
        raise PermissionError("The journal maker cannot decide their own journal")
    if action == "request":
        _validate_lines(session, [{
            "account_code": row.account_code,
            "description": row.description,
            "debit": row.debit,
            "credit": row.credit,
        } for row in journal.lines])
        journal.requested_by = actor
        journal.decided_by = None
    else:
        journal.decided_by = actor
    journal.status = target
    journal.decision_note = note.strip()
    journal.revision += 1
    journal.updated_at = utc_now()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"finance.general_journal_{action}d", actor=actor,
        resource_key=journal.journal_key,
        detail=f"status={target}; revision={journal.revision}; test only; posting disabled",
    ))
    session.commit()
    return journal


def _journal_payload(row: OperationalGeneralJournal) -> dict:
    debit = sum((_money(line.debit) for line in row.lines), ZERO)
    credit = sum((_money(line.credit) for line in row.lines), ZERO)
    return {
        "journal_key": row.journal_key,
        "journal_no": row.journal_no,
        "journal_date": row.journal_date,
        "branch_code": row.branch_code,
        "reference": row.reference,
        "description": row.description,
        "status": row.status,
        "posting_enabled": False,
        "test_data_only": row.test_data_only,
        "prepared_by": row.prepared_by,
        "requested_by": row.requested_by,
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
        "revision": row.revision,
        "debit": debit,
        "credit": credit,
        "lines": [{
            "line_no": line.line_no,
            "account_code": line.account_code,
            "description": line.description,
            "debit": line.debit,
            "credit": line.credit,
        } for line in row.lines],
    }


def _automatic_projection(session: Session, draft: OperationalDraft) -> dict:
    net = _money(draft.subtotal) - _money(draft.discount_amount)
    if draft.document_type == "sale":
        cogs = sum((_money(line.cost_amount) for line in draft.lines), ZERO)
        lines = [
            ("1200", draft.total_amount, ZERO), ("4000", ZERO, net),
            ("2120", ZERO, draft.tax_amount), ("5000", cogs, ZERO), ("1300", ZERO, cogs),
        ]
    else:
        lines = [("1300", net, ZERO), ("1320", draft.tax_amount, ZERO), ("2100", ZERO, draft.total_amount)]
    debit = sum((_money(row[1]) for row in lines), ZERO)
    credit = sum((_money(row[2]) for row in lines), ZERO)
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= draft.created_at.date(),
        OperationalFiscalPeriod.ends_on >= draft.created_at.date(),
    ))
    return {
        "draft_key": draft.draft_key,
        "draft_no": draft.draft_no,
        "document_type": draft.document_type,
        "document_date": draft.created_at.date(),
        "debit": debit,
        "credit": credit,
        "balanced": debit == credit,
        "period_key": period.period_key if period else None,
        "rehearsal_ready": bool(period and period.status == "open" and period.rehearsal_enabled and debit == credit),
        "lines": [{"account_code": code, "debit": _money(debit_value), "credit": _money(credit_value)}
                  for code, debit_value, credit_value in lines],
    }


def general_ledger_payload(session: Session, *, account_code: str | None = None) -> dict:
    accounts = list(session.scalars(select(OperationalChartAccount).where(
        OperationalChartAccount.company_code == "ASAS",
    ).order_by(OperationalChartAccount.account_code)))
    journals = list(session.scalars(select(OperationalGeneralJournal).where(
        OperationalGeneralJournal.company_code == "ASAS",
    ).order_by(OperationalGeneralJournal.journal_date.desc(), OperationalGeneralJournal.id.desc())))
    approved = [row for row in journals if row.status == "approved"]
    amounts: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"debit": ZERO, "credit": ZERO})
    ledger_entries = []
    for journal in approved:
        for line in journal.lines:
            amounts[line.account_code]["debit"] += _money(line.debit)
            amounts[line.account_code]["credit"] += _money(line.credit)
            if not account_code or line.account_code == account_code:
                ledger_entries.append({
                    "journal_no": journal.journal_no,
                    "journal_date": journal.journal_date,
                    "reference": journal.reference,
                    "description": line.description or journal.description,
                    "account_code": line.account_code,
                    "debit": line.debit,
                    "credit": line.credit,
                    "status": "approved_test_projection",
                })
    trial_balance = []
    for account in accounts:
        debit, credit = amounts[account.account_code]["debit"], amounts[account.account_code]["credit"]
        net = debit - credit
        trial_balance.append({
            "account_code": account.account_code,
            "account_name": account.name,
            "account_class": account.account_class,
            "statement_section": account.statement_section,
            "debit": net if net > 0 else ZERO,
            "credit": -net if net < 0 else ZERO,
        })
    trial_debit = sum((row["debit"] for row in trial_balance), ZERO)
    trial_credit = sum((row["credit"] for row in trial_balance), ZERO)
    class_balance = defaultdict(lambda: ZERO)
    section_balance = defaultdict(lambda: ZERO)
    for row in trial_balance:
        natural = (row["debit"] - row["credit"] if row["account_class"] in {"asset", "expense"}
                   else row["credit"] - row["debit"])
        class_balance[row["account_class"]] += natural
        section_balance[row["statement_section"]] += natural
    income, expenses = class_balance["income"], class_balance["expense"]
    profit = income - expenses
    assets = class_balance["asset"]
    liabilities = class_balance["liability"]
    equity_before_profit = class_balance["equity"]
    mappings = list(session.scalars(select(OperationalAccountMapping).where(
        OperationalAccountMapping.company_code == "ASAS"
    )))
    drafts = list(session.scalars(select(OperationalDraft).where(
        OperationalDraft.status == "approved"
    ).order_by(OperationalDraft.created_at.desc()).limit(25)))
    periods = list(session.scalars(select(OperationalFiscalPeriod).order_by(OperationalFiscalPeriod.starts_on.desc())))
    return {
        "journals": [_journal_payload(row) for row in journals],
        "accounts": [{"code": row.account_code, "name": row.name, "class": row.account_class,
                      "status": row.status, "postable": row.is_postable} for row in accounts],
        "ledger_entries": ledger_entries,
        "selected_account_code": account_code,
        "trial_balance": {"rows": trial_balance, "debit": trial_debit, "credit": trial_credit,
                          "difference": trial_debit - trial_credit},
        "profit_or_loss": {"income": income, "expenses": expenses, "profit": profit,
                           "sections": dict(section_balance)},
        "statement_of_financial_position": {
            "assets": assets,
            "liabilities": liabilities,
            "equity_before_current_profit": equity_before_profit,
            "current_profit": profit,
            "liabilities_and_equity": liabilities + equity_before_profit + profit,
            "difference": assets - liabilities - equity_before_profit - profit,
        },
        "automatic_journal_previews": [_automatic_projection(session, row) for row in drafts],
        "periods": [{"period_key": row.period_key, "starts_on": row.starts_on, "ends_on": row.ends_on,
                     "status": row.status, "rehearsal_enabled": row.rehearsal_enabled,
                     "revision": row.revision, "approval_reference": row.approval_reference}
                    for row in periods],
        "controls": {
            "test_data_only": True,
            "posting_enabled": False,
            "permanent_journal_batches": session.scalar(select(func.count(OperationalJournalBatch.id))) or 0,
            "approved_journal_plans": len(approved),
            "pending_journal_plans": sum(row.status == "pending" for row in journals),
            "active_accounts": sum(row.status == "active" for row in accounts),
            "approved_mappings": sum(row.mapping_status == "approved" for row in mappings),
        },
    }
