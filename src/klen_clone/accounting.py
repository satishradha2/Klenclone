from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import (
    RawFileManifest,
    RawRecord,
    ReconciliationException,
    SourceSnapshot,
    StgAccountingControl,
    StgCashFlowEntry,
    StgContact,
    StgPayment,
    StgPaymentAccount,
    StgTaxEvidence,
    StgTrialBalanceEntry,
)
from .transform import clean, datetime_value, decimal_value
from .derived import clear_blueprint_outputs

ZERO = Decimal("0")
TOLERANCE = Decimal("0.01")
UI_TRIAL_BALANCE_CONTROLS = {
    "bizmodo-2026-09-08-browser": (Decimal("861430.28"), Decimal("820387.73")),
}
PAYMENT_REFERENCE = re.compile(r"Pay reference no\.:\s*(.*?)Added By:", re.IGNORECASE)
SALE_DOCUMENT = re.compile(r"Invoice No\.:\s*(.*?)Pay reference no\.", re.IGNORECASE)
PURCHASE_DOCUMENT = re.compile(r"Reference No:\s*(.*?)Pay reference no\.", re.IGNORECASE)
TRANSFER_COUNTERPARTY = re.compile(r"Fund Transfer\s*\(\s*(?:To|From):\s*([^\)]+)\)", re.IGNORECASE)


def classify_cash_flow(description: str | None) -> str:
    value = (description or "").casefold()
    if value.startswith("purchase return"):
        return "purchase_return_receipt"
    if value.startswith("sales"):
        return "sale_receipt"
    if value.startswith("purchase"):
        return "purchase_payment"
    if value.startswith("fund transfer"):
        return "internal_transfer"
    if value.startswith("sell return"):
        return "sale_return_payment"
    if value.startswith("expense"):
        return "expense_payment"
    if value.startswith("deposit"):
        return "deposit"
    return "other"


def extract_payment_reference(description: str | None) -> str | None:
    match = PAYMENT_REFERENCE.search(description or "")
    return clean(match.group(1)) if match else None


def extract_document_no(description: str | None, kind: str) -> str | None:
    pattern = PURCHASE_DOCUMENT if kind in ("purchase_payment", "purchase_return_receipt") else SALE_DOCUMENT
    match = pattern.search(description or "")
    return clean(match.group(1)) if match else None


def build_accounting_snapshot(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")

    clear_blueprint_outputs(session, snapshot.id)
    session.execute(delete(StgAccountingControl).where(StgAccountingControl.snapshot_id == snapshot.id))
    session.execute(delete(StgCashFlowEntry).where(StgCashFlowEntry.snapshot_id == snapshot.id))
    session.execute(delete(StgTrialBalanceEntry).where(StgTrialBalanceEntry.snapshot_id == snapshot.id))
    session.execute(delete(StgPaymentAccount).where(StgPaymentAccount.snapshot_id == snapshot.id))
    accounting_codes = (
        "ACCOUNTING_CONTROL_VARIANCE", "CASH_FLOW_PAYMENT_UNMATCHED",
        "PAYMENT_WITHOUT_CASH_FLOW", "CASH_FLOW_SIGN_ANOMALY", "TRIAL_BALANCE_LABEL_MISSING",
    )
    session.execute(delete(ReconciliationException).where(
        ReconciliationException.snapshot_id == snapshot.id,
        ReconciliationException.code.in_(accounting_codes),
    ))

    account_rows = session.scalars(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id,
        RawFileManifest.entity_type == "payment_account",
        RawRecord.is_presentation_row.is_(False),
    ).order_by(RawRecord.id)).all()
    payment_account_total = ZERO
    for raw in account_rows:
        payload = raw.payload or {}
        name = clean(payload.get("Name")) or f"RAW-{raw.id}"
        balance = decimal_value(payload.get("Balance")) or ZERO
        payment_account_total += balance
        session.add(StgPaymentAccount(
            snapshot_id=snapshot.id, raw_record_id=raw.id, name=name,
            account_type=clean(payload.get("Account Type")), account_sub_type=clean(payload.get("Account Sub Type")),
            account_number=clean(payload.get("Account Number")), note=clean(payload.get("Note")),
            balance=balance, added_by=clean(payload.get("Added By")),
        ))

    payments_by_ref: dict[str, list[StgPayment]] = defaultdict(list)
    for payment in session.scalars(select(StgPayment).where(StgPayment.snapshot_id == snapshot.id)):
        if payment.reference_no:
            payments_by_ref[payment.reference_no].append(payment)

    cash_rows = session.scalars(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id,
        RawFileManifest.entity_type == "cash_flow",
        RawRecord.is_presentation_row.is_(False),
    ).order_by(RawRecord.id)).all()
    entries = []
    entry_kind_counts: Counter[str] = Counter()
    link_status_counts: Counter[str] = Counter()
    transfer_groups: dict[str, list[StgCashFlowEntry]] = defaultdict(list)
    linked_payment_ids = set()
    last_account_balances: dict[str, Decimal] = {}
    cash_debit = ZERO
    cash_credit = ZERO
    for raw in cash_rows:
        payload = raw.payload or {}
        description = clean(payload.get("Description"))
        kind = classify_cash_flow(description)
        payment_ref = extract_payment_reference(description)
        candidates = payments_by_ref.get(payment_ref, []) if payment_ref else []
        link_status = "not_applicable" if not payment_ref else "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "unmatched"
        linked_payment = candidates[0] if link_status == "resolved" else None
        if linked_payment:
            linked_payment_ids.add(linked_payment.id)
        debit = decimal_value(payload.get("Debit")) or ZERO
        credit = decimal_value(payload.get("Credit")) or ZERO
        when = datetime_value(payload.get("Date"))
        amount = debit or credit
        transfer_group = f"{when.replace(tzinfo=None).isoformat()}|{amount}" if kind == "internal_transfer" and when else None
        counterpart_match = TRANSFER_COUNTERPARTY.search(description or "")
        account_name = clean(payload.get("Account"))
        entry = StgCashFlowEntry(
            snapshot_id=snapshot.id, raw_record_id=raw.id, transaction_at=when,
            account_name=account_name, description=description,
            payment_method=clean(payload.get("Payment Method")), payment_details=clean(payload.get("Payment details")),
            debit=debit, credit=credit, account_balance=decimal_value(payload.get("Account Balance")),
            total_balance=decimal_value(payload.get("Total Balance")), entry_kind=kind,
            payment_reference=payment_ref, document_no=extract_document_no(description, kind),
            linked_payment_id=linked_payment.id if linked_payment else None,
            payment_link_status=link_status, transfer_group=transfer_group,
            details={"payment_candidate_count": len(candidates), "transfer_counterparty": clean(counterpart_match.group(1)) if counterpart_match else None},
        )
        entries.append(entry)
        session.add(entry)
        if transfer_group:
            transfer_groups[transfer_group].append(entry)
        entry_kind_counts[kind] += 1
        link_status_counts[link_status] += 1
        cash_debit += debit
        cash_credit += credit
        if account_name and entry.account_balance is not None:
            last_account_balances[account_name] = entry.account_balance
        expected_sign_ok = (
            kind == "sale_receipt" and credit >= 0 and debit == 0
            or kind in ("purchase_payment", "sale_return_payment", "expense_payment") and debit >= 0 and credit == 0
            or kind == "purchase_return_receipt" and credit > 0 and debit == 0
            or kind in ("internal_transfer", "other", "deposit")
        )
        if not expected_sign_ok:
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="CASH_FLOW_SIGN_ANOMALY", severity="high",
                entity_type="cash_flow", source_key=str(raw.id),
                details={"entry_kind": kind, "debit": str(debit), "credit": str(credit)},
            ))
        if payment_ref and link_status != "resolved":
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="CASH_FLOW_PAYMENT_UNMATCHED", severity="high",
                entity_type="cash_flow", source_key=payment_ref,
                details={"raw_record_id": raw.id, "entry_kind": kind, "candidate_count": len(candidates)},
            ))

    paired_transfers = 0
    unpaired_transfers = 0
    for group, group_entries in transfer_groups.items():
        balanced_pair = (
            len(group_entries) == 2
            and sum((row.debit for row in group_entries), ZERO) == sum((row.credit for row in group_entries), ZERO)
            and sum(row.debit > 0 for row in group_entries) == 1
            and sum(row.credit > 0 for row in group_entries) == 1
        )
        for entry in group_entries:
            entry.transfer_pair_status = "paired" if balanced_pair else "unpaired"
        if balanced_pair:
            paired_transfers += 1
        else:
            unpaired_transfers += len(group_entries)

    all_payments = session.scalars(select(StgPayment).where(StgPayment.snapshot_id == snapshot.id)).all()
    payments_without_cash = [row for row in all_payments if row.id not in linked_payment_ids]
    for payment in payments_without_cash:
        session.add(ReconciliationException(
            snapshot_id=snapshot.id, code="PAYMENT_WITHOUT_CASH_FLOW", severity="high",
            entity_type=f"{payment.direction}_payment", source_key=payment.reference_no,
            details={"payment_id": payment.id, "amount": str(payment.amount)},
        ))

    trial_rows = session.scalars(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id,
        RawFileManifest.entity_type == "trial_balance",
        RawRecord.is_presentation_row.is_(False),
    ).order_by(RawRecord.ordinal)).all()
    trial_debit = ZERO
    trial_credit = ZERO
    missing_trial_labels = 0
    trial_named: dict[str, tuple[Decimal, Decimal]] = {}
    for raw in trial_rows:
        payload = raw.payload or {}
        account_name = clean(payload.get("Trial Balance - Asas General Trading LLC"))
        debit = decimal_value(payload.get("column_2")) or ZERO
        credit = decimal_value(payload.get("column_3")) or ZERO
        label_status = "source_label" if account_name else "missing_source_label"
        if not account_name:
            missing_trial_labels += 1
        else:
            trial_named[account_name.casefold()] = (debit, credit)
        trial_debit += debit
        trial_credit += credit
        session.add(StgTrialBalanceEntry(
            snapshot_id=snapshot.id, raw_record_id=raw.id, row_ordinal=raw.ordinal,
            account_name=account_name, debit=debit, credit=credit,
            label_status=label_status, details={"source_account_cell_missing": not bool(account_name)},
        ))
    if missing_trial_labels:
        session.add(ReconciliationException(
            snapshot_id=snapshot.id, code="TRIAL_BALANCE_LABEL_MISSING", severity="critical",
            entity_type="trial_balance", source_key="missing-account-labels",
            details={"row_count": missing_trial_labels},
        ))

    tax_output = session.scalar(select(func.sum(StgTaxEvidence.vat_amount)).where(
        StgTaxEvidence.snapshot_id == snapshot.id, StgTaxEvidence.direction == "output"
    )) or ZERO
    tax_input = session.scalar(select(func.sum(StgTaxEvidence.vat_amount)).where(
        StgTaxEvidence.snapshot_id == snapshot.id, StgTaxEvidence.direction == "input"
    )) or ZERO
    customer_due = session.scalar(select(func.sum(StgContact.amount_due)).where(StgContact.snapshot_id == snapshot.id, StgContact.kind == "customer")) or ZERO
    customer_return_due = session.scalar(select(func.sum(StgContact.return_due)).where(StgContact.snapshot_id == snapshot.id, StgContact.kind == "customer")) or ZERO
    supplier_due = session.scalar(select(func.sum(StgContact.amount_due)).where(StgContact.snapshot_id == snapshot.id, StgContact.kind == "supplier")) or ZERO
    supplier_return_due = session.scalar(select(func.sum(StgContact.return_due)).where(StgContact.snapshot_id == snapshot.id, StgContact.kind == "supplier")) or ZERO
    trial_output_tax = trial_named.get("output tax", (ZERO, ZERO))[1] - trial_named.get("output tax", (ZERO, ZERO))[0]
    trial_ar = trial_named.get("accounts receivable (a/r)", (ZERO, ZERO))[0] - trial_named.get("accounts receivable (a/r)", (ZERO, ZERO))[1]
    trial_ap = trial_named.get("suppliers", (ZERO, ZERO))[1] - trial_named.get("suppliers", (ZERO, ZERO))[0]
    cash_flow_closing = sum(last_account_balances.values(), ZERO)

    sale_payment_total = sum((row.amount or ZERO for row in all_payments if row.direction == "sale"), ZERO)
    purchase_payment_total = sum((row.amount or ZERO for row in all_payments if row.direction == "purchase"), ZERO)
    cash_sale_total = sum((row.credit - row.debit for row in entries if row.entry_kind == "sale_receipt"), ZERO)
    cash_purchase_total = sum((row.debit - row.credit for row in entries if row.entry_kind == "purchase_payment"), ZERO)
    missing_sale_cash_total = sum((row.amount or ZERO for row in payments_without_cash if row.direction == "sale"), ZERO)
    missing_purchase_cash_total = sum((row.amount or ZERO for row in payments_without_cash if row.direction == "purchase"), ZERO)

    controls = [
        ("TRIAL_BALANCE_EXPORTED_ROW_SUM", trial_debit, trial_credit, None, {"debit": str(trial_debit), "credit": str(trial_credit), "scope": "all 532 exported rows; includes parent/detail hierarchy"}),
        ("CASH_FLOW_NET_TO_CLOSING", cash_credit - cash_debit, cash_flow_closing, None, {"cash_debit": str(cash_debit), "cash_credit": str(cash_credit), "accounts": len(last_account_balances)}),
        ("PAYMENT_ACCOUNTS_TO_CASH_FLOW", payment_account_total, cash_flow_closing, None, {"payment_accounts": len(account_rows), "cash_flow_accounts": len(last_account_balances)}),
        ("OUTPUT_VAT_TO_TRIAL_BALANCE", tax_output, trial_output_tax, None, {"input_vat_evidence": str(tax_input), "trial_input_tax_label": "not exposed"}),
        ("CUSTOMER_AR_TO_TRIAL_BALANCE", customer_due - customer_return_due, trial_ar, None, {"customer_due": str(customer_due), "customer_return_due": str(customer_return_due)}),
        ("SUPPLIER_AP_TO_TRIAL_BALANCE", supplier_due - supplier_return_due, trial_ap, None, {"supplier_due": str(supplier_due), "supplier_return_due": str(supplier_return_due)}),
        ("SALE_PAYMENTS_TO_CASH_FLOW", sale_payment_total, cash_sale_total, missing_sale_cash_total, {"payment_rows": sum(row.direction == "sale" for row in all_payments), "cash_rows": entry_kind_counts["sale_receipt"], "payments_without_cash_flow": str(missing_sale_cash_total)}),
        ("PURCHASE_PAYMENTS_TO_CASH_FLOW", purchase_payment_total, cash_purchase_total, missing_purchase_cash_total, {"payment_rows": sum(row.direction == "purchase" for row in all_payments), "cash_rows": entry_kind_counts["purchase_payment"], "payments_without_cash_flow": str(missing_purchase_cash_total)}),
    ]
    ui_trial_control = UI_TRIAL_BALANCE_CONTROLS.get(snapshot.name)
    if ui_trial_control:
        controls.append((
            "TRIAL_BALANCE_UI_TOP_LEVEL", ui_trial_control[0], ui_trial_control[1], None,
            {"visible_accounts": 24, "scope": "browser UI top-level control captured with this snapshot"},
        ))
    control_status_counts: Counter[str] = Counter()
    for code, amount_a, amount_b, explained_variance, details in controls:
        variance = amount_a - amount_b
        status = "balanced" if abs(variance) <= TOLERANCE else "explained_variance" if explained_variance is not None and abs(variance - explained_variance) <= TOLERANCE else "variance"
        session.add(StgAccountingControl(
            snapshot_id=snapshot.id, control_code=code, amount_a=amount_a, amount_b=amount_b,
            variance=variance, status=status, details=details,
        ))
        control_status_counts[status] += 1
        if status == "variance":
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="ACCOUNTING_CONTROL_VARIANCE", severity="critical",
                entity_type="accounting_control", source_key=code,
                details={"amount_a": str(amount_a), "amount_b": str(amount_b), "variance": str(variance), **details},
            ))

    session.commit()
    return {
        "payment_accounts": len(account_rows),
        "cash_flow_entries": len(cash_rows),
        "cash_flow_entry_kinds": dict(entry_kind_counts),
        "payment_link_status": dict(link_status_counts),
        "payments_without_cash_flow": len(payments_without_cash),
        "transfer_pairs": paired_transfers,
        "unpaired_transfer_rows": unpaired_transfers,
        "trial_balance_entries": len(trial_rows),
        "trial_balance_missing_labels": missing_trial_labels,
        "trial_balance_debit": str(trial_debit),
        "trial_balance_credit": str(trial_credit),
        "trial_balance_variance": str(trial_debit - trial_credit),
        "trial_balance_ui_debit": str(ui_trial_control[0]) if ui_trial_control else None,
        "trial_balance_ui_credit": str(ui_trial_control[1]) if ui_trial_control else None,
        "trial_balance_ui_variance": str(ui_trial_control[0] - ui_trial_control[1]) if ui_trial_control else None,
        "accounting_controls": dict(control_status_counts),
    }
