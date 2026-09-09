from __future__ import annotations

from collections import Counter
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .foundation import _add_once
from .transactions import _cache, _ensure
from .models import (
    ErpAuditEvent, ErpCashLedgerEvidence, ErpFinancialActivationGate, ErpGlAccount,
    ErpJournalBlueprint, ErpJournalBlueprintLine, ErpOpeningBalanceQueue, ErpParty,
    ErpSubledgerControl, ErpTaxLedgerEvidence, ErpTransactionDocument,
    ErpTransactionPayment, ErpTrialBalanceEvidence, SourceSnapshot, StgAccountingControl,
    StgCashFlowEntry, StgCoaAccount, StgContact, StgJournalBlueprint,
    StgJournalBlueprintLine, StgTaxEvidence, StgTrialBalanceEntry,
)

ZERO = Decimal("0")


def subledger_status(gross_due: Decimal, return_due: Decimal) -> str:
    return "no_balance_evidence" if gross_due == ZERO and return_due == ZERO else "review_required_reconciliation"


def journal_migration_status(source_status: str) -> str:
    return {
        "balanced_nonposting": "migration_locked_balanced",
        "zero_value": "review_required_zero_value",
        "review_required": "review_required_source_logic",
    }.get(source_status, "blocked_unknown_status")


def build_canonical_ledger(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    parties = {row.source_contact_id: row for row in session.scalars(select(ErpParty).where(ErpParty.snapshot_id == snapshot.id))}
    documents = {(row.source_kind, row.source_id): row for row in session.scalars(
        select(ErpTransactionDocument).where(ErpTransactionDocument.snapshot_id == snapshot.id))}
    payments = {row.source_payment_id: row for row in session.scalars(
        select(ErpTransactionPayment).where(ErpTransactionPayment.snapshot_id == snapshot.id))}
    if not documents or not parties:
        raise RuntimeError("Canonical transactions must be built before accounting promotion")

    created = Counter()
    account_fields = ("snapshot_id", "source_account_id")
    accounts = _cache(session, ErpGlAccount, account_fields, snapshot.id)
    account_by_code = {}
    account_by_source_name = {}
    for source in session.scalars(select(StgCoaAccount).where(StgCoaAccount.snapshot_id == snapshot.id).order_by(StgCoaAccount.id)):
        key = (snapshot.id, source.id)
        account, was_created = _ensure(session, ErpGlAccount, accounts, key, account_fields,
            {"account_code": source.account_code, "account_name": source.account_name,
             "account_type": source.account_type, "account_sub_type": source.account_sub_type,
             "source_name": source.source_name, "migration_status": "migration_locked_provisional",
             "operational_enabled": False, "posting_enabled": False,
             "evidence": {"source_mapping_status": source.mapping_status, "source_details": source.details}})
        created["gl_accounts"] += was_created
        account_by_code[source.account_code] = account
        if source.source_name:
            account_by_source_name[source.source_name.casefold()] = account
    session.flush()

    journal_fields = ("snapshot_id", "source_journal_id")
    journals = _cache(session, ErpJournalBlueprint, journal_fields, snapshot.id)
    journal_map = {}
    journal_statuses = Counter()
    source_kind_map = {"sale_invoice": "sale", "purchase_invoice": "purchase",
                       "sale_return": "sale_return", "purchase_return": "purchase_return"}
    for source in session.scalars(select(StgJournalBlueprint).where(StgJournalBlueprint.snapshot_id == snapshot.id).order_by(StgJournalBlueprint.id)):
        document = None
        target_kind = source_kind_map.get(source.source_kind)
        if target_kind and source.source_key.isdigit():
            document = documents.get((target_kind, int(source.source_key)))
        status = journal_migration_status(source.status)
        key = (snapshot.id, source.id)
        journal, was_created = _ensure(session, ErpJournalBlueprint, journals, key, journal_fields,
            {"document_id": document.id if document else None, "source_kind": source.source_kind,
             "source_key": source.source_key, "document_no": source.document_no,
             "occurred_at": source.transaction_at, "description": source.description,
             "debit_total": source.debit_total, "credit_total": source.credit_total,
             "migration_status": status, "approval_enabled": False, "posting_enabled": False,
             "evidence": {"source_status": source.status, "source_details": source.details}})
        created["journals"] += was_created
        journal_map[source.id] = journal
        journal_statuses[status] += 1
    session.flush()

    existing_lines = {row.source_line_id: row for row in session.scalars(select(ErpJournalBlueprintLine))}
    journal_line_count = 0
    for source in session.scalars(select(StgJournalBlueprintLine).join(StgJournalBlueprint).where(
        StgJournalBlueprint.snapshot_id == snapshot.id).order_by(StgJournalBlueprintLine.id)):
        journal = journal_map[source.journal_id]
        account = account_by_code.get(source.account_code)
        if not account:
            raise RuntimeError(f"Journal line {source.id} has no GL account mapping for {source.account_code}")
        values = {"journal_id": journal.id, "line_no": source.line_no, "gl_account_id": account.id,
                  "debit": source.debit, "credit": source.credit, "memo": source.memo,
                  "evidence": {"source_account_code": source.account_code, "source_evidence": source.evidence}}
        row = existing_lines.get(source.id)
        if row:
            for field, expected in values.items():
                if getattr(row, field) != expected:
                    raise RuntimeError(f"Immutable accounting mismatch: ErpJournalBlueprintLine.{field} source={source.id}")
        else:
            row = ErpJournalBlueprintLine(source_line_id=source.id, **values)
            session.add(row)
            existing_lines[source.id] = row
            created["journal_lines"] += 1
        journal_line_count += 1

    subledger_fields = ("snapshot_id", "source_contact_id")
    subledgers = _cache(session, ErpSubledgerControl, subledger_fields, snapshot.id)
    subledger_statuses = Counter()
    for source in session.scalars(select(StgContact).where(StgContact.snapshot_id == snapshot.id).order_by(StgContact.id)):
        party = parties.get(source.id)
        if not party:
            raise RuntimeError(f"Contact {source.id} has no canonical party")
        gross_due, returned = source.amount_due or ZERO, source.return_due or ZERO
        status = subledger_status(gross_due, returned)
        key = (snapshot.id, source.id)
        _, was_created = _ensure(session, ErpSubledgerControl, subledgers, key, subledger_fields,
            {"party_id": party.id, "ledger_kind": "receivable" if source.kind == "customer" else "payable",
             "gross_due": gross_due, "return_due": returned, "net_due": gross_due - returned,
             "explicit_opening_balance": source.opening_balance or ZERO, "advance_balance": source.advance_balance or ZERO,
             "reconciliation_status": status, "posting_enabled": False,
             "evidence": {"source_contact_code": source.contact_id,
                          "warning": "current due evidence; not an approved opening balance"}})
        created["subledger_controls"] += was_created
        subledger_statuses[status] += 1

    tax_fields = ("snapshot_id", "source_tax_id")
    taxes = _cache(session, ErpTaxLedgerEvidence, tax_fields, snapshot.id)
    tax_statuses = Counter()
    for source in session.scalars(select(StgTaxEvidence).where(StgTaxEvidence.snapshot_id == snapshot.id).order_by(StgTaxEvidence.id)):
        document = documents.get((source.link_kind, source.link_id)) if source.link_kind and source.link_id else None
        status = "migration_locked_linked" if source.link_status == "resolved" and document else "review_required_relationship"
        key = (snapshot.id, source.id)
        _, was_created = _ensure(session, ErpTaxLedgerEvidence, taxes, key, tax_fields,
            {"document_id": document.id if document else None, "direction": source.direction,
             "document_no": source.document_no, "occurred_at": source.transaction_at,
             "amount_ex_tax": source.amount_ex_tax, "amount_with_tax": source.amount_with_tax,
             "discount_amount": source.discount_amount, "vat_amount": source.vat_amount,
             "relation_status": status, "posting_enabled": False,
             "evidence": {"source_link_status": source.link_status, "match_method": source.match_method,
                          "party_name": source.party_name, "tax_number_present": bool(source.tax_number),
                          "source_details": source.details}})
        created["tax_entries"] += was_created
        tax_statuses[status] += 1

    cash_fields = ("snapshot_id", "source_cash_id")
    cash_entries = _cache(session, ErpCashLedgerEvidence, cash_fields, snapshot.id)
    cash_statuses = Counter()
    for source in session.scalars(select(StgCashFlowEntry).where(StgCashFlowEntry.snapshot_id == snapshot.id).order_by(StgCashFlowEntry.id)):
        account = account_by_source_name.get((source.account_name or "").casefold())
        payment = payments.get(source.linked_payment_id) if source.linked_payment_id else None
        link_ok = source.payment_link_status == "not_applicable" or (source.payment_link_status == "resolved" and payment is not None)
        status = "migration_locked_linked" if account and link_ok else "review_required_relationship"
        key = (snapshot.id, source.id)
        _, was_created = _ensure(session, ErpCashLedgerEvidence, cash_entries, key, cash_fields,
            {"gl_account_id": account.id if account else None, "payment_id": payment.id if payment else None,
             "occurred_at": source.transaction_at, "entry_kind": source.entry_kind,
             "description": source.description, "debit": source.debit, "credit": source.credit,
             "relation_status": status, "posting_enabled": False,
             "evidence": {"source_account_name": source.account_name, "payment_reference": source.payment_reference,
                          "document_no": source.document_no, "payment_link_status": source.payment_link_status,
                          "transfer_group": source.transfer_group, "transfer_pair_status": source.transfer_pair_status,
                          "source_account_balance": str(source.account_balance) if source.account_balance is not None else None,
                          "source_total_balance": str(source.total_balance) if source.total_balance is not None else None}})
        created["cash_entries"] += was_created
        cash_statuses[status] += 1

    trial_fields = ("snapshot_id", "source_trial_id")
    trial_rows = _cache(session, ErpTrialBalanceEvidence, trial_fields, snapshot.id)
    trial_statuses = Counter()
    for source in session.scalars(select(StgTrialBalanceEntry).where(StgTrialBalanceEntry.snapshot_id == snapshot.id).order_by(StgTrialBalanceEntry.id)):
        status = "migration_locked_labeled" if source.label_status == "source_label" else "review_required_missing_label"
        key = (snapshot.id, source.id)
        _, was_created = _ensure(session, ErpTrialBalanceEvidence, trial_rows, key, trial_fields,
            {"row_ordinal": source.row_ordinal, "account_name": source.account_name,
             "debit": source.debit, "credit": source.credit, "label_status": source.label_status,
             "reconciliation_status": status, "posting_enabled": False,
             "evidence": {"source_details": source.details}})
        created["trial_balance_rows"] += was_created
        trial_statuses[status] += 1

    accounting_controls = list(session.scalars(select(StgAccountingControl).where(StgAccountingControl.snapshot_id == snapshot.id)))
    nonbalanced_controls = sum(row.status != "balanced" for row in accounting_controls)
    opening_unapproved = session.scalar(select(func.count(ErpOpeningBalanceQueue.id)).where(
        ErpOpeningBalanceQueue.snapshot_id == snapshot.id, ErpOpeningBalanceQueue.posting_enabled.is_(False))) or 0
    gate_specs = {
        "COA_APPROVAL": ("Chart of accounts approval", len(accounts), {"reason": "all mappings are provisional"}),
        "JOURNAL_REVIEW": ("Journal logic review", journal_statuses["review_required_source_logic"], {}),
        "ZERO_VALUE_JOURNALS": ("Zero-value journal review", journal_statuses["review_required_zero_value"], {}),
        "TAX_LINKAGE": ("Tax document linkage", tax_statuses["review_required_relationship"], {}),
        "CASH_LINKAGE": ("Cash/payment linkage", cash_statuses["review_required_relationship"], {}),
        "TRIAL_BALANCE_LABELS": ("Trial-balance source labels", trial_statuses["review_required_missing_label"], {}),
        "ACCOUNTING_CONTROLS": ("Accounting reconciliation controls", nonbalanced_controls, {}),
        "SUBLEDGER_RECONCILIATION": ("AR/AP party reconciliation", subledger_statuses["review_required_reconciliation"], {}),
        "OPENING_BALANCE_APPROVAL": ("Opening balance approval", opening_unapproved, {}),
    }
    gates = {}
    for code, (name, issue_count, evidence) in gate_specs.items():
        gate, was_created = _add_once(session, ErpFinancialActivationGate,
            {"snapshot_id": snapshot.id, "gate_code": code},
            {"gate_name": name, "issue_count": issue_count,
             "gate_status": "blocked" if issue_count else "ready_disabled",
             "activation_enabled": False, "evidence": evidence})
        created["activation_gates"] += was_created
        gates[code] = {"status": gate.gate_status, "issues": gate.issue_count}

    event_key = f"canonical-ledger:{len(accounts)}:{len(journals)}:{journal_line_count}:{len(taxes)}:{len(cash_entries)}:{len(trial_rows)}"
    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": event_key},
        {"event_type": "canonical_accounting_registered", "actor_type": "migration_service",
         "details": {"gl_accounts": len(accounts), "journals": len(journals), "journal_lines": journal_line_count,
                     "subledgers": len(subledgers), "tax_entries": len(taxes), "cash_entries": len(cash_entries),
                     "trial_balance_rows": len(trial_rows), "activation_gates": len(gates),
                     "source_mutated": False, "posting_enabled": False}})
    created["audit_events"] += was_created
    session.commit()

    posting_enabled = sum(session.scalar(select(func.count(model.id)).where(
        model.snapshot_id == snapshot.id, model.posting_enabled.is_(True))) or 0
        for model in (ErpGlAccount, ErpJournalBlueprint, ErpSubledgerControl,
                      ErpTaxLedgerEvidence, ErpCashLedgerEvidence, ErpTrialBalanceEvidence))
    approval_enabled = session.scalar(select(func.count(ErpFinancialActivationGate.id)).where(
        ErpFinancialActivationGate.snapshot_id == snapshot.id,
        ErpFinancialActivationGate.activation_enabled.is_(True))) or 0
    return {"snapshot": snapshot.name, "gl_accounts": len(accounts), "journals": len(journals),
            "journal_status": dict(journal_statuses), "journal_lines": journal_line_count,
            "subledger_controls": len(subledgers), "subledger_status": dict(subledger_statuses),
            "tax_entries": len(taxes), "tax_status": dict(tax_statuses),
            "cash_entries": len(cash_entries), "cash_status": dict(cash_statuses),
            "trial_balance_rows": len(trial_rows), "trial_status": dict(trial_statuses),
            "activation_gates": gates, "posting_enabled_records": posting_enabled,
            "activation_enabled_gates": approval_enabled, "new_records": dict(created)}
