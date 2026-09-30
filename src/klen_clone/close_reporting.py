from __future__ import annotations

import hashlib
import io
import json
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .cash_management import OperationalCashAccount
from .finance_foundation import OperationalChartAccount
from .finance_ledger import OperationalGeneralJournal
from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalJournalBatch, utc_now
from .period_close import OperationalPeriodClose, posted_journal_evidence
from .posting_integration import OperationalIntegratedPostingBatch

ZERO = Decimal("0.00")
POSTED_ACCOUNT_ALIASES = {"Accounts Receivable": "1200", "Accounts Payable": "2100"}


class OperationalFinancialReportPackage(OperationalBase):
    __tablename__ = "operational_financial_report_packages"
    __table_args__ = (
        UniqueConstraint("period_close_id", "close_revision", name="uq_financial_report_close_revision"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_financial_report_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    package_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    period_close_id: Mapped[int] = mapped_column(ForeignKey("operational_period_closes.id"), nullable=False, index=True)
    close_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_by: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_close: Mapped[OperationalPeriodClose] = relationship()


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY)


def assert_report_source_current(session: Session, close: OperationalPeriodClose) -> dict:
    if close.status != "approved" or not close.source_fingerprint:
        raise ValueError("Financial statements require an approved frozen close package")
    frozen = json.loads(close.snapshot_json or "{}")
    evidence = posted_journal_evidence(session, close.fiscal_period)
    if not frozen.get("permanent_journal_fingerprint"):
        raise ValueError("This close predates posted-ledger fingerprint controls; revalidate the close before reporting")
    if frozen["permanent_journal_fingerprint"] != evidence["fingerprint"]:
        raise ValueError("Posted ledger changed after close submission; financial statements cannot use the stale close")
    if evidence["imbalance"]:
        raise ValueError("Posted ledger is not balanced for this fiscal period")
    return evidence


def assert_report_package_current(session: Session, row: OperationalFinancialReportPackage) -> dict:
    evidence = assert_report_source_current(session, row.period_close)
    report = json.loads(row.report_json)
    if (report.get("close_fingerprint") != row.period_close.source_fingerprint
            or report.get("ledger_controls", {}).get("posted_ledger_fingerprint") != evidence["fingerprint"]):
        raise ValueError("Financial-report package predates the posted-ledger basis or has stale source evidence")
    return evidence


def build_close_report(session: Session, close: OperationalPeriodClose) -> dict:
    evidence = assert_report_source_current(session, close)
    accounts = {row.account_code: row for row in session.scalars(select(OperationalChartAccount).where(
        OperationalChartAccount.company_code == "ASAS"))}
    movements: list[dict] = []
    alias_mappings = []
    for line in evidence["lines"]:
        source_code = line["account_code"]
        account_code = POSTED_ACCOUNT_ALIASES.get(source_code, source_code)
        if account_code not in accounts:
            cash_account = session.scalar(select(OperationalCashAccount).where(
                OperationalCashAccount.account_code == source_code,
                OperationalCashAccount.status == "active"))
            if cash_account:
                account_code = cash_account.gl_account_code
        account = accounts.get(account_code)
        if not account:
            raise ValueError(f"Posted account {source_code} has no approved ASAS chart mapping")
        if source_code != account_code:
            alias_mappings.append({"posted_account": source_code,
                "chart_account": account_code, "batch_key": line["batch_key"]})
        movements.append({"account_code": account_code,
            "account_name": account.name, "account_class": account.account_class,
            "statement_section": account.statement_section,
            "debit": line["debit"], "credit": line["credit"],
            "source": line["batch_key"]})
    approved_plans = list(session.scalars(select(OperationalGeneralJournal).where(
        OperationalGeneralJournal.status == "approved",
        OperationalGeneralJournal.journal_date.between(close.fiscal_period.starts_on,
            close.fiscal_period.ends_on))))
    approved_adjustments = [item for item in close.adjustments if item.status == "approved"]
    grouped = defaultdict(lambda: {"debit": ZERO, "credit": ZERO, "sources": set()})
    metadata = {}
    for line in movements:
        key = line["account_code"]
        grouped[key]["debit"] += line["debit"]; grouped[key]["credit"] += line["credit"]
        grouped[key]["sources"].add(line["source"]); metadata[key] = line
    trial = []
    for key in sorted(grouped):
        net = _money(grouped[key]["debit"] - grouped[key]["credit"])
        item = metadata[key]
        trial.append({"account_code": key, "account_name": item["account_name"],
            "account_class": item["account_class"], "statement_section": item["statement_section"],
            "debit": net if net > 0 else ZERO, "credit": -net if net < 0 else ZERO,
            "sources": sorted(grouped[key]["sources"])})
    debit = _money(sum((row["debit"] for row in trial), ZERO)); credit = _money(sum((row["credit"] for row in trial), ZERO))
    natural = defaultdict(lambda: ZERO)
    sections = defaultdict(lambda: ZERO)
    for row in trial:
        value = row["debit"] - row["credit"] if row["account_class"] in {"asset", "expense"} else row["credit"] - row["debit"]
        natural[row["account_class"]] += value; sections[row["statement_section"]] += value
    profit = _money(natural["income"] - natural["expense"])
    assets, liabilities, equity = _money(natural["asset"]), _money(natural["liability"]), _money(natural["equity"])
    cash_rows = [row for row in trial if row["statement_section"] == "cash_and_cash_equivalents"]
    cash_change = _money(sum((row["debit"] - row["credit"] for row in cash_rows), ZERO))
    prior = session.scalar(select(OperationalFinancialReportPackage).join(
        OperationalPeriodClose, OperationalFinancialReportPackage.period_close_id == OperationalPeriodClose.id).where(
        OperationalFinancialReportPackage.status == "approved",
        OperationalPeriodClose.id != close.id,
        OperationalPeriodClose.created_at < close.created_at).order_by(OperationalPeriodClose.created_at.desc()))
    prior_report = json.loads(prior.report_json) if prior else None
    return {"period": {"period_key": close.fiscal_period.period_key,
                       "starts_on": close.fiscal_period.starts_on, "ends_on": close.fiscal_period.ends_on},
        "basis": "posted target-ERP journal batches only; unposted plans and close adjustments excluded",
        "close_fingerprint": close.source_fingerprint,
        "ledger_controls": {"posted_batches": evidence["batch_count"],
            "integrated_batches": evidence["integrated_batches"],
            "legacy_batches": evidence["legacy_batches"],
            "posted_ledger_fingerprint": evidence["fingerprint"],
            "posted_ledger_difference": evidence["imbalance"],
            "legacy_account_aliases": alias_mappings,
            "period_movement_only": True,
            "opening_balances_certified": False},
        "unposted_work": {"approved_journal_plans": len(approved_plans),
            "approved_close_adjustments": len(approved_adjustments),
            "close_adjustment_total": _money(sum((item.amount for item in approved_adjustments), ZERO))},
        "trial_balance": {"rows": trial, "debit": debit, "credit": credit, "difference": _money(debit-credit)},
        "profit_and_loss": {"revenue": _money(natural["income"]), "expenses": _money(natural["expense"]),
                            "profit": profit, "sections": dict(sections)},
        "balance_sheet": {"assets": assets, "liabilities": liabilities,
                          "equity_before_profit": equity, "current_profit": profit,
                          "liabilities_and_equity": _money(liabilities+equity+profit),
                          "difference": _money(assets-liabilities-equity-profit)},
        "cash_flow": {"operating": None, "investing": None, "financing": None,
                      "net_change": cash_change,
                      "method": "Cash-account net movement only; activity classification not established"},
        "retained_earnings": {"opening": None, "current_profit": profit, "dividends": None,
                              "closing": None, "status": "opening equity and distributions not certified"},
        "comparative": {"available": bool(prior_report), "period_key": prior_report["period"]["period_key"] if prior_report else None,
                        "profit": prior_report["profit_and_loss"]["profit"] if prior_report else None,
                        "assets": prior_report["balance_sheet"]["assets"] if prior_report else None},
        "posting_enabled": False, "source_evidence_mutated": False}


def generate_report_package(session: Session, close: OperationalPeriodClose, *, actor: str) -> OperationalFinancialReportPackage:
    assert_report_source_current(session, close)
    existing = session.scalar(select(OperationalFinancialReportPackage).where(
        OperationalFinancialReportPackage.period_close_id == close.id,
        OperationalFinancialReportPackage.close_revision == close.revision))
    if existing:
        assert_report_package_current(session, existing)
        return existing
    report = build_close_report(session, close)
    document = json.dumps(report, default=str, sort_keys=True)
    fingerprint = hashlib.sha256(document.encode()).hexdigest()
    key = str(uuid.uuid4())
    row = OperationalFinancialReportPackage(package_key=key,
        package_no=f"FS-{close.fiscal_period.period_key}-{key[:6].upper()}",
        period_close_id=close.id, close_revision=close.revision, status="draft",
        report_json=document, report_fingerprint=fingerprint, created_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="financial_report.generated",
        actor=actor, resource_key=row.package_key, detail=f"{row.package_no}; close {close.close_no}; no posting"))
    session.commit(); return row


def transition_report_package(session: Session, row: OperationalFinancialReportPackage, *, action: str,
                              expected_revision: int, note: str, actor: str) -> OperationalFinancialReportPackage:
    if row.revision != expected_revision: raise ValueError("Financial-report revision is stale")
    if action in {"submit", "approve"}:
        assert_report_package_current(session, row)
    if action == "submit" and row.status in {"draft", "rejected"}:
        if actor != row.created_by: raise PermissionError("Only the report maker may submit this package")
        row.status, row.submitted_by = "submitted", actor
    elif action in {"approve", "reject"} and row.status == "submitted":
        if actor == row.created_by: raise PermissionError("Maker cannot approve their own financial statements")
        if len(note.strip()) < 5: raise ValueError("Decision note must contain at least five characters")
        row.status, row.approved_by, row.decision_note = ("approved" if action == "approve" else "rejected"), actor, note.strip()
        row.approved_at = utc_now() if action == "approve" else None
    else: raise ValueError("Invalid financial-report transition")
    row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"financial_report.{action}",
        actor=actor, resource_key=row.package_key, detail=f"{row.package_no}; {row.status}"))
    session.commit(); return row


def report_package_payload(row: OperationalFinancialReportPackage) -> dict:
    return {"package_key": row.package_key, "package_no": row.package_no,
        "close_no": row.period_close.close_no, "status": row.status,
        "report_fingerprint": row.report_fingerprint, "report": json.loads(row.report_json),
        "created_by": row.created_by, "approved_by": row.approved_by,
        "decision_note": row.decision_note, "revision": row.revision,
        "exports_enabled": row.status == "approved"}


def reporting_workspace_payload(session: Session) -> dict:
    closes = list(session.scalars(select(OperationalPeriodClose).where(OperationalPeriodClose.status == "approved").order_by(OperationalPeriodClose.created_at.desc())))
    packages = list(session.scalars(select(OperationalFinancialReportPackage).order_by(OperationalFinancialReportPackage.created_at.desc())))
    package_payloads = []
    for package in packages:
        payload = report_package_payload(package)
        try:
            assert_report_package_current(session, package)
        except ValueError as exc:
            payload["exports_enabled"] = False
            payload["source_warning"] = str(exc)
        package_payloads.append(payload)
    return {"approved_closes": [{"close_key": row.close_key, "close_no": row.close_no,
                                  "period_key": row.fiscal_period.period_key,
                                  "has_package": any(p.period_close_id == row.id for p in packages)} for row in closes],
            "packages": package_payloads,
            "controls": {"packages": len(packages), "awaiting_approval": sum(row.status == "submitted" for row in packages),
                         "approved": sum(row.status == "approved" for row in packages),
                         "exports_enabled": sum(item["exports_enabled"] for item in package_payloads),
                         "permanent_postings": (session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) or 0)
                         + (session.scalar(select(func.count(OperationalJournalBatch.id))) or 0)}}


def workbook_bytes(row: OperationalFinancialReportPackage) -> bytes:
    report = json.loads(row.report_json); workbook = Workbook(); workbook.remove(workbook.active)
    sheets = [("Trial Balance", report["trial_balance"]["rows"]),
              ("Profit and Loss", [{"Metric": k, "AED": v} for k, v in report["profit_and_loss"].items() if k != "sections"]),
              ("Balance Sheet", [{"Metric": k, "AED": v} for k, v in report["balance_sheet"].items()]),
              ("Cash Flow", [{"Metric": k, "Value": v} for k, v in report["cash_flow"].items()]),
              ("Retained Earnings", [{"Metric": k, "AED": v} for k, v in report["retained_earnings"].items()])]
    for title, rows in sheets:
        sheet = workbook.create_sheet(title)
        if rows:
            headers = list(rows[0]); sheet.append(headers)
            for item in rows: sheet.append([json.dumps(item[h]) if isinstance(item[h], (list, dict)) else item[h] for h in headers])
            sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
    output = io.BytesIO(); workbook.save(output); return output.getvalue()


def pdf_bytes(row: OperationalFinancialReportPackage) -> bytes:
    report = json.loads(row.report_json)
    lines = [f"ASAS GENERAL TRADING LLC - {row.package_no}",
             f"Period: {report['period']['period_key']}", f"Fingerprint: {row.report_fingerprint}", "",
             "TRIAL BALANCE"]
    lines += [f"{item['account_name']}: Debit AED {item['debit']} Credit AED {item['credit']}" for item in report["trial_balance"]["rows"]]
    lines += ["", f"Profit/(loss): AED {report['profit_and_loss']['profit']}",
              f"Asset movement: AED {report['balance_sheet']['assets']}",
              f"Liability/equity movement: AED {report['balance_sheet']['liabilities_and_equity']}",
              "Period movements only; opening balances not certified.",
              "Approved posted-ledger report; export performs no posting."]
    def esc(value): return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 10 Tf 40 800 Td " + " ".join(f"({esc(line)}) Tj 0 -16 Td" for line in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    data = b"%PDF-1.4\n"; offsets = [0]
    for index, obj in enumerate(objects, 1): offsets.append(len(data)); data += f"{index} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(data); data += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode(); return data
