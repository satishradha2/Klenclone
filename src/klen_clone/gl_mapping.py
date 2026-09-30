"""Fail-closed chart resolution for activated HTTP posting paths.

The operational rehearsals retain their original account labels for audit. An
activated posting must resolve every journal line to an approved chart code.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .cash_management import OperationalCashAccount
from .finance_foundation import OperationalChartAccount


ACCOUNT_ALIASES = {
    "Inventory": "1300",
    "GRNI": "2115",
    "Accounts Receivable": "1200",
    "Accounts Payable": "2100",
    "Customer Advances": "2140",
    "Supplier Advances": "1210",
    "Sales Revenue": "4000",
    "Cost of Goods Sold": "5000",
    "Output VAT": "2120",
    "Input VAT": "1320",
}


def posting_gl_preflight(session: Session, journal: list[dict]) -> dict:
    """Resolve a complete journal without modifying source evidence or the database."""
    accounts = {row.account_code: row for row in session.scalars(select(OperationalChartAccount).where(
        OperationalChartAccount.company_code == "ASAS"))}
    cash_accounts = {row.account_code: row for row in session.scalars(select(OperationalCashAccount).where(
        OperationalCashAccount.status == "active"))}
    resolved, issues, aliases = [], [], []
    for number, line in enumerate(journal, 1):
        source = str(line.get("account") or "").strip()
        debit, credit = Decimal(str(line.get("debit") or 0)), Decimal(str(line.get("credit") or 0))
        if not source or debit < 0 or credit < 0 or (debit > 0 and credit > 0):
            issues.append(f"Line {number}: invalid account or debit/credit sides")
            continue
        if source == "Inventory Adjustment":
            code = "5120" if debit > 0 else "4020"
        elif source in cash_accounts:
            code = cash_accounts[source].gl_account_code
        else:
            code = ACCOUNT_ALIASES.get(source, source)
        account = accounts.get(code)
        if not account or account.status != "active" or not account.is_postable:
            issues.append(f"Line {number}: {source} does not resolve to an active postable ASAS chart account")
            continue
        if source in cash_accounts and (account.account_class != "asset"
                                        or account.statement_section != "cash_and_cash_equivalents"):
            issues.append(f"Line {number}: {source} does not map to a cash-equivalent asset account")
            continue
        if source != code:
            aliases.append({"line_no": number, "source_account": source, "chart_account": code})
        resolved.append({"account": code, "debit": debit, "credit": credit})
    if not issues and sum((row["debit"] - row["credit"] for row in resolved), Decimal("0")) != 0:
        issues.append("The resolved GL journal is not balanced")
    fingerprint = hashlib.sha256(json.dumps(resolved, default=str, sort_keys=True).encode()).hexdigest()
    return {"ready": not issues, "issues": issues, "journal": resolved,
            "aliases": aliases, "fingerprint": fingerprint}


def require_posting_gl(session: Session, journal: list[dict]) -> dict:
    result = posting_gl_preflight(session, journal)
    if not result["ready"]:
        raise ValueError("GL mapping gate: " + "; ".join(result["issues"][:5]))
    return result
