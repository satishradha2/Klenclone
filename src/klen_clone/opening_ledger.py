"""Non-posting, target-side opening trial-balance reconciliation.

This package proves arithmetic and control-account tie-outs. It does not
certify the truth of a source extract or create a posted opening journal.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .finance_foundation import OperationalChartAccount
from .operational import OperationalAuditEvent, OperationalBase, utc_now

CENT = Decimal("0.01")
CONTROL_CODES = {"receivable": "1200", "payable": "2100", "supplier_advance": "1210",
                 "customer_advance": "2140", "inventory": "1300"}
CONTROL_SIDES = {"receivable": "debit", "payable": "credit", "supplier_advance": "debit",
                 "customer_advance": "credit", "inventory": "debit"}


class OperationalOpeningLedgerPackage(OperationalBase):
    __tablename__ = "operational_opening_ledger_packages"
    __table_args__ = (
        UniqueConstraint("company_code", "cutoff_date", "source_sha256", name="uq_opening_ledger_source"),
        CheckConstraint("status IN ('draft','submitted','approved_rehearsal','rejected')",
                        name="ck_opening_ledger_status"),
        CheckConstraint("posting_enabled = false", name="ck_opening_ledger_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False)
    cutoff_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_atomic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_by: Mapped[str | None] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _amount(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Opening amounts must be finite decimal values") from exc
    if not number.is_finite() or number != number.quantize(CENT):
        raise ValueError("Opening amounts must be finite AED values with at most two decimals")
    return number.quantize(CENT)


def opening_reconciliation(session: Session, *, lines: list[dict], party_balances: list[dict],
                           stock_value, stock_evidence_reference: str) -> dict:
    if not lines or not stock_evidence_reference.strip():
        raise ValueError("Opening GL lines and a stock-valuation evidence reference are required")
    chart = {row.account_code: row for row in session.scalars(select(OperationalChartAccount).where(
        OperationalChartAccount.company_code == "ASAS"))}
    normalized, seen = [], set()
    for line in lines:
        code = str(line.get("account_code") or "").strip()
        if code in seen:
            raise ValueError(f"Duplicate opening account {code}")
        seen.add(code)
        account = chart.get(code)
        if account is None or account.status != "active" or not account.is_postable:
            raise ValueError(f"Opening account {code} is not an active postable ASAS chart account")
        debit, credit = _amount(line.get("debit", 0)), _amount(line.get("credit", 0))
        if debit < 0 or credit < 0 or (debit and credit) or (not debit and not credit):
            raise ValueError(f"Opening account {code} must have exactly one positive debit or credit")
        normalized.append({"account_code": code, "debit": str(debit), "credit": str(credit)})
    debit_total = sum((Decimal(row["debit"]) for row in normalized), Decimal(0))
    credit_total = sum((Decimal(row["credit"]) for row in normalized), Decimal(0))
    if debit_total != credit_total:
        raise ValueError(f"Opening trial balance is not balanced: debit {debit_total}, credit {credit_total}")
    totals = {kind: Decimal(0) for kind in CONTROL_CODES}
    parties = set()
    normalized_parties = []
    for item in party_balances:
        kind = str(item.get("balance_type") or "")
        code = str(item.get("party_code") or "").strip()
        if kind not in totals or kind == "inventory" or not code:
            raise ValueError("Opening party balance requires a known type and party code")
        key = kind, code.casefold()
        if key in parties:
            raise ValueError(f"Duplicate opening party balance {kind}:{code}")
        parties.add(key)
        amount = _amount(item.get("amount"))
        if amount <= 0:
            raise ValueError("Opening party balances must be positive")
        totals[kind] += amount
        normalized_parties.append({"balance_type": kind, "party_code": code, "amount": str(amount)})
    totals["inventory"] = _amount(stock_value)
    if totals["inventory"] < 0:
        raise ValueError("Opening stock valuation cannot be negative")
    by_code = {row["account_code"]: row for row in normalized}
    tie_outs = []
    for kind, code in CONTROL_CODES.items():
        gl = by_code.get(code, {"debit": "0", "credit": "0"})
        side = CONTROL_SIDES[kind]
        opposite = "credit" if side == "debit" else "debit"
        gl_balance = Decimal(gl[side]) - Decimal(gl[opposite])
        delta = gl_balance - totals[kind]
        tie_outs.append({"control": kind, "account_code": code,
                         "gl_balance": str(gl_balance), "supporting_total": str(totals[kind]),
                         "difference": str(delta)})
    if any(Decimal(row["difference"]) for row in tie_outs):
        raise ValueError("Opening control mismatch: " + ", ".join(
            f"{row['control']} {row['difference']}" for row in tie_outs if Decimal(row["difference"])))
    return {"lines": sorted(normalized, key=lambda row: row["account_code"]),
            "party_balances": sorted(normalized_parties, key=lambda row: (row["balance_type"], row["party_code"])),
            "stock_value": str(totals["inventory"]), "stock_evidence_reference": stock_evidence_reference.strip(),
            "debit_total": str(debit_total), "credit_total": str(credit_total), "tie_outs": tie_outs,
            "scope": "Arithmetic and supplied-control tie-out only; no source truth certification or posting"}


def create_opening_package(session: Session, *, actor: str, cutoff_date: date, source_reference: str,
                           source_sha256: str, source_atomic: bool, lines: list[dict],
                           party_balances: list[dict], stock_value, stock_evidence_reference: str
                           ) -> OperationalOpeningLedgerPackage:
    reference, checksum = source_reference.strip(), source_sha256.strip().lower()
    if not reference or len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
        raise ValueError("A named source and its SHA-256 checksum are required")
    existing = session.scalar(select(OperationalOpeningLedgerPackage).where(
        OperationalOpeningLedgerPackage.company_code == "ASAS",
        OperationalOpeningLedgerPackage.cutoff_date == cutoff_date,
        OperationalOpeningLedgerPackage.source_sha256 == checksum))
    if existing:
        raise RuntimeError("This opening source and cutoff already have a package")
    evidence = opening_reconciliation(session, lines=lines, party_balances=party_balances,
        stock_value=stock_value, stock_evidence_reference=stock_evidence_reference)
    evidence["source"] = {"cutoff_date": cutoff_date.isoformat(), "reference": reference,
                          "sha256": checksum, "atomic_claim": source_atomic}
    document = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    row = OperationalOpeningLedgerPackage(package_key=str(uuid.uuid4()), company_code="ASAS",
        cutoff_date=cutoff_date, source_reference=reference, source_sha256=checksum,
        source_atomic=source_atomic, evidence_json=document,
        evidence_fingerprint=hashlib.sha256(document.encode()).hexdigest(),
        status="draft", posting_enabled=False, created_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="opening_ledger.created",
        actor=actor, resource_key=row.package_key, detail=f"cutoff={cutoff_date}; non-posting rehearsal"))
    session.commit()
    return row


def transition_opening_package(session: Session, *, key: str, action: str, actor: str,
                               expected_revision: int, note: str) -> OperationalOpeningLedgerPackage:
    row = session.scalar(select(OperationalOpeningLedgerPackage).where(
        OperationalOpeningLedgerPackage.package_key == key).with_for_update())
    if row is None:
        raise ValueError("Opening package not found")
    if row.revision != expected_revision:
        raise RuntimeError("Opening package revision conflict")
    if action == "submit" and row.status == "draft":
        row.status, row.submitted_by = "submitted", actor
    elif action in {"approve", "reject"} and row.status == "submitted":
        if actor.casefold() in {row.created_by.casefold(), (row.submitted_by or "").casefold()}:
            raise PermissionError("Opening package maker cannot decide their own package")
        if not note.strip():
            raise ValueError("An independent decision note is required")
        evidence = json.loads(row.evidence_json)
        current = opening_reconciliation(session, lines=evidence["lines"],
            party_balances=evidence["party_balances"], stock_value=evidence["stock_value"],
            stock_evidence_reference=evidence["stock_evidence_reference"])
        current["source"] = {"cutoff_date": row.cutoff_date.isoformat(),
                             "reference": row.source_reference, "sha256": row.source_sha256,
                             "atomic_claim": row.source_atomic}
        if hashlib.sha256(json.dumps(current, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != row.evidence_fingerprint:
            raise RuntimeError("Opening evidence changed after submission")
        row.status = "approved_rehearsal" if action == "approve" else "rejected"
        row.decided_by, row.decision_note = actor, note.strip()
    else:
        raise RuntimeError("Invalid opening-package transition")
    row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"opening_ledger.{action}",
        actor=actor, resource_key=row.package_key,
        detail=f"revision={row.revision}; status={row.status}; posting disabled"))
    session.commit()
    return row


def opening_package_payload(row: OperationalOpeningLedgerPackage) -> dict:
    return {"package_key": row.package_key, "cutoff_date": row.cutoff_date,
            "source_reference": row.source_reference, "source_sha256": row.source_sha256,
            "source_atomic": row.source_atomic, "status": row.status, "revision": row.revision,
            "created_by": row.created_by, "submitted_by": row.submitted_by, "decided_by": row.decided_by,
            "decision_note": row.decision_note, "evidence_fingerprint": row.evidence_fingerprint,
            "evidence": json.loads(row.evidence_json), "posting_enabled": False,
            "opening_balances_certified": False}
