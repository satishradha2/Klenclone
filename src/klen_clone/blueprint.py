from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .inventory import canonical_uom
from .derived import clear_blueprint_outputs
from .models import (
    ReconciliationException,
    SourceSnapshot,
    StgCashFlowEntry,
    StgCoaAccount,
    StgEntityLink,
    StgFinancialAllocation,
    StgInventoryMovement,
    StgInventoryOpeningControl,
    StgJournalBlueprint,
    StgJournalBlueprintLine,
    StgPaymentAccount,
    StgProduct,
    StgPurchase,
    StgReturn,
    StgSale,
    StgStockBalance,
    StgTaxEvidence,
)

ZERO = Decimal("0")
TOLERANCE = Decimal("0.01")

STATIC_ACCOUNTS = (
    ("1200", "Accounts Receivable", "asset", "current_asset"),
    ("1300", "Inventory and Purchase Clearing", "asset", "inventory"),
    ("1400", "Input VAT Recoverable", "asset", "tax"),
    ("2000", "Accounts Payable", "liability", "current_liability"),
    ("2100", "Output VAT Payable", "liability", "tax"),
    ("3000", "Opening Balance Control", "equity", "migration_control"),
    ("4000", "Sales Revenue", "income", "operating_income"),
    ("4100", "Sales Returns", "income", "contra_income"),
    ("5000", "Cost of Goods Sold", "expense", "cost_of_sales"),
    ("6000", "Operating Expenses", "expense", "operating_expense"),
)


def location_key(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def build_blueprints(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")

    clear_blueprint_outputs(session, snapshot.id)
    session.execute(delete(ReconciliationException).where(
        ReconciliationException.snapshot_id == snapshot.id,
        ReconciliationException.code.in_(("JOURNAL_BLUEPRINT_REVIEW", "JOURNAL_BLUEPRINT_UNBALANCED", "OPENING_STOCK_BLOCKED")),
    ))

    for code, name, account_type, sub_type in STATIC_ACCOUNTS:
        session.add(StgCoaAccount(
            snapshot_id=snapshot.id, account_code=code, account_name=name,
            account_type=account_type, account_sub_type=sub_type,
            mapping_status="provisional", posting_enabled=False,
            details={"requires_business_approval": True},
        ))

    payment_accounts = session.scalars(select(StgPaymentAccount).where(StgPaymentAccount.snapshot_id == snapshot.id)).all()
    cash_entries = session.scalars(select(StgCashFlowEntry).where(StgCashFlowEntry.snapshot_id == snapshot.id)).all()
    cash_names = sorted({row.name for row in payment_accounts} | {row.account_name for row in cash_entries if row.account_name}, key=str.casefold)
    cash_codes = {}
    source_account_names = {row.name.casefold(): row for row in payment_accounts}
    for index, name in enumerate(cash_names, 1):
        code = f"1100-{index:03d}"
        cash_codes[name.casefold()] = code
        source = source_account_names.get(name.casefold())
        session.add(StgCoaAccount(
            snapshot_id=snapshot.id, account_code=code, account_name=name,
            account_type="asset", account_sub_type="cash_or_bank", source_name=name,
            mapping_status="source_account" if source else "cash_flow_only",
            posting_enabled=False,
            details={"source_balance": str(source.balance) if source else None, "requires_business_approval": True},
        ))
    session.flush()

    journal_status: Counter[str] = Counter()
    journal_kind: Counter[str] = Counter()

    def add_journal(source_kind: str, source_key: str, document_no: str | None, transaction_at,
                    description: str, lines: list[tuple[str, Decimal, Decimal, str, dict]],
                    review_reason: str | None = None) -> None:
        debit = sum((line[1] for line in lines), ZERO)
        credit = sum((line[2] for line in lines), ZERO)
        if review_reason:
            status = "review_required"
        elif not lines or (debit == ZERO and credit == ZERO):
            status = "zero_value"
        elif abs(debit - credit) <= TOLERANCE:
            status = "balanced_nonposting"
        else:
            status = "unbalanced_blocked"
        journal = StgJournalBlueprint(
            snapshot_id=snapshot.id, source_kind=source_kind, source_key=source_key,
            document_no=document_no, transaction_at=transaction_at, description=description,
            debit_total=debit, credit_total=credit, status=status, posting_enabled=False,
            details={"review_reason": review_reason, "requires_business_approval": True},
        )
        session.add(journal)
        session.flush()
        for line_no, (account_code, line_debit, line_credit, memo, evidence) in enumerate(lines, 1):
            session.add(StgJournalBlueprintLine(
                journal_id=journal.id, line_no=line_no, account_code=account_code,
                debit=line_debit, credit=line_credit, memo=memo, evidence=evidence,
            ))
        journal_status[status] += 1
        journal_kind[source_kind] += 1
        if status == "review_required":
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="JOURNAL_BLUEPRINT_REVIEW", severity="high",
                entity_type=source_kind, source_key=source_key,
                details={"document_no": document_no, "reason": review_reason},
            ))
        elif status == "unbalanced_blocked":
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="JOURNAL_BLUEPRINT_UNBALANCED", severity="critical",
                entity_type=source_kind, source_key=source_key,
                details={"debit": str(debit), "credit": str(credit)},
            ))

    sales = {row.id: row for row in session.scalars(select(StgSale).where(StgSale.snapshot_id == snapshot.id))}
    purchases = {row.id: row for row in session.scalars(select(StgPurchase).where(StgPurchase.snapshot_id == snapshot.id))}
    tax_evidence_by_id = {row.id: row for row in session.scalars(select(StgTaxEvidence).where(StgTaxEvidence.snapshot_id == snapshot.id))}
    allocations = session.scalars(select(StgFinancialAllocation).where(StgFinancialAllocation.snapshot_id == snapshot.id)).all()
    for allocation in allocations:
        header = sales.get(allocation.header_id) if allocation.document_kind == "sale" else purchases.get(allocation.header_id)
        tax_evidence = tax_evidence_by_id.get((allocation.details or {}).get("tax_evidence_id"))
        total = tax_evidence.amount_with_tax if allocation.document_kind == "sale" and tax_evidence and tax_evidence.amount_with_tax is not None else allocation.header_total
        vat = allocation.vat_amount or ZERO
        review = None
        if allocation.tax_link_status != "resolved":
            review = "tax evidence is not deterministically linked"
            lines = []
        elif total < ZERO or vat < ZERO or vat > total:
            review = "invalid invoice total or VAT sign"
            lines = []
        elif allocation.document_kind == "sale":
            net = total - vat
            lines = [
                ("1200", total, ZERO, "Customer receivable", {"allocation_id": allocation.id, "current_list_total": str(allocation.header_total)}),
                ("4000", ZERO, net, "Net sales revenue", {"tax_evidence": allocation.details.get("tax_evidence_id")}),
                ("2100", ZERO, vat, "Output VAT", {"tax_evidence": allocation.details.get("tax_evidence_id")}),
            ]
        else:
            net = total - vat
            lines = [
                ("1300", net, ZERO, "Inventory and purchase clearing", {"allocation_id": allocation.id}),
                ("1400", vat, ZERO, "Input VAT", {"tax_evidence": allocation.details.get("tax_evidence_id")}),
                ("2000", ZERO, total, "Supplier payable", {"allocation_id": allocation.id}),
            ]
        add_journal(
            f"{allocation.document_kind}_invoice", str(allocation.header_id), allocation.document_no,
            header.transaction_at if header else None, f"Provisional {allocation.document_kind} invoice journal",
            lines, review,
        )

    tax_by_return = defaultdict(list)
    for tax in session.scalars(select(StgTaxEvidence).where(
        StgTaxEvidence.snapshot_id == snapshot.id,
        StgTaxEvidence.link_status == "resolved",
        StgTaxEvidence.link_kind.in_(("sale_return", "purchase_return")),
    )):
        tax_by_return[(tax.link_kind, tax.link_id)].append(tax)
    returns = session.scalars(select(StgReturn).where(StgReturn.snapshot_id == snapshot.id)).all()
    for returned in returns:
        kind = f"{returned.direction}_return"
        taxes = tax_by_return.get((kind, returned.id), [])
        tax = taxes[0] if len(taxes) == 1 else None
        total = returned.total_amount or ZERO
        vat = abs(tax.vat_amount or ZERO) if tax else ZERO
        if not tax:
            lines = []
            review = "return tax evidence is not deterministically linked"
        elif returned.direction == "sale":
            lines = [
                ("4100", total - vat, ZERO, "Sales return", {"return_id": returned.id}),
                ("2100", vat, ZERO, "Output VAT reversal", {"tax_evidence_id": tax.id}),
                ("1200", ZERO, total, "Customer receivable credit", {"return_id": returned.id}),
            ]
            review = None
        else:
            lines = [
                ("2000", total, ZERO, "Supplier payable debit", {"return_id": returned.id}),
                ("1300", ZERO, total - vat, "Purchase return", {"return_id": returned.id}),
                ("1400", ZERO, vat, "Input VAT reversal", {"tax_evidence_id": tax.id}),
            ]
            review = None
        add_journal(kind, str(returned.id), returned.document_no, returned.transaction_at,
                    f"Provisional {kind.replace('_', ' ')} journal", lines, review)

    transfer_groups = defaultdict(list)
    for entry in cash_entries:
        if entry.entry_kind == "internal_transfer" and entry.transfer_group:
            transfer_groups[entry.transfer_group].append(entry)
            continue
        amount = entry.credit or entry.debit
        cash_code = cash_codes.get((entry.account_name or "").casefold())
        lines = []
        review = None
        if not cash_code:
            review = "cash account has no provisional mapping"
        elif amount == ZERO:
            pass
        elif entry.entry_kind == "sale_receipt":
            lines = [(cash_code, amount, ZERO, "Cash receipt", {"cash_flow_id": entry.id}), ("1200", ZERO, amount, "Settle customer receivable", {"payment_id": entry.linked_payment_id})]
        elif entry.entry_kind == "purchase_payment":
            lines = [("2000", amount, ZERO, "Settle supplier payable", {"payment_id": entry.linked_payment_id}), (cash_code, ZERO, amount, "Cash payment", {"cash_flow_id": entry.id})]
        elif entry.entry_kind == "sale_return_payment":
            lines = [("1200", amount, ZERO, "Settle customer return credit", {"payment_reference": entry.payment_reference}), (cash_code, ZERO, amount, "Customer refund", {"cash_flow_id": entry.id})]
        elif entry.entry_kind == "purchase_return_receipt":
            lines = [(cash_code, amount, ZERO, "Supplier refund received", {"cash_flow_id": entry.id}), ("2000", ZERO, amount, "Settle supplier return debit", {"payment_reference": entry.payment_reference})]
        else:
            review = f"unsupported cash-flow kind {entry.entry_kind}"
        add_journal("cash_flow", str(entry.id), entry.document_no, entry.transaction_at,
                    entry.description or "Cash flow", lines, review)

    for group, entries in transfer_groups.items():
        debit_entry = next((row for row in entries if row.debit > ZERO), None)
        credit_entry = next((row for row in entries if row.credit > ZERO), None)
        review = None
        lines = []
        if len(entries) != 2 or not debit_entry or not credit_entry or debit_entry.debit != credit_entry.credit:
            review = "internal transfer pair is incomplete"
        else:
            source_code = cash_codes.get((debit_entry.account_name or "").casefold())
            destination_code = cash_codes.get((credit_entry.account_name or "").casefold())
            if not source_code or not destination_code:
                review = "internal transfer account mapping is missing"
            else:
                amount = debit_entry.debit
                lines = [
                    (destination_code, amount, ZERO, "Internal transfer received", {"cash_flow_id": credit_entry.id}),
                    (source_code, ZERO, amount, "Internal transfer sent", {"cash_flow_id": debit_entry.id}),
                ]
        add_journal("internal_transfer", group, None, entries[0].transaction_at if entries else None,
                    "Paired internal fund transfer", lines, review)

    products = {row.id: row for row in session.scalars(select(StgProduct).where(StgProduct.snapshot_id == snapshot.id))}
    stock_product_links = dict(session.execute(select(StgEntityLink.source_id, StgEntityLink.target_id).where(
        StgEntityLink.snapshot_id == snapshot.id, StgEntityLink.source_kind == "stock_balance",
        StgEntityLink.target_kind == "product", StgEntityLink.status == "resolved",
    )).all())
    movements = session.scalars(select(StgInventoryMovement).where(
        StgInventoryMovement.snapshot_id == snapshot.id,
        StgInventoryMovement.posting_status == "posted",
    )).all()
    movement_groups = defaultdict(list)
    for movement in movements:
        movement_groups[(movement.product_id, location_key(movement.location))].append(movement)
    balances = session.scalars(select(StgStockBalance).where(StgStockBalance.snapshot_id == snapshot.id)).all()
    balance_groups = defaultdict(list)
    for balance in balances:
        balance_groups[(stock_product_links.get(balance.id), location_key(balance.location))].append(balance)

    opening_status: Counter[str] = Counter()
    covered_movement_keys = set()
    for balance in balances:
        product_id = stock_product_links.get(balance.id)
        key = (product_id, location_key(balance.location))
        product = products.get(product_id)
        grouped_movements = movement_groups.get(key, [])
        covered_movement_keys.add(key)
        unresolved = sum(row.quantity_base is None for row in grouped_movements)
        net_movement = sum((row.quantity_base or ZERO for row in grouped_movements), ZERO)
        closing = balance.available_quantity
        status = "implied_opening_requires_approval"
        implied = closing - net_movement if closing is not None else None
        if not product:
            status, implied = "blocked_product_unresolved", None
        elif not balance.location:
            status, implied = "blocked_location_missing", None
        elif len(balance_groups[key]) > 1:
            status, implied = "blocked_sub_location_allocation", None
        elif canonical_uom(balance.unit) != canonical_uom(product.stock_unit):
            status, implied = "blocked_closing_uom_mismatch", None
        elif unresolved:
            status, implied = "blocked_unresolved_movements", None
        elif closing is not None and closing < ZERO:
            status, implied = "blocked_negative_closing", None
        control_key = f"balance:{balance.id}"
        session.add(StgInventoryOpeningControl(
            snapshot_id=snapshot.id, control_key=control_key, stock_balance_id=balance.id,
            product_id=product_id, sku=balance.sku, location=balance.location,
            sub_location=balance.sub_location, canonical_uom=canonical_uom(product.stock_unit) if product else canonical_uom(balance.unit),
            closing_quantity=closing, net_supported_movement=net_movement if product else None,
            implied_opening_quantity=implied, unresolved_movement_count=unresolved,
            status=status, posting_enabled=False,
            details={"movement_count": len(grouped_movements), "requires_business_approval": True},
        ))
        opening_status[status] += 1

    for key, grouped_movements in movement_groups.items():
        if key in covered_movement_keys:
            continue
        product_id, normalized_location = key
        product = products.get(product_id)
        unresolved = sum(row.quantity_base is None for row in grouped_movements)
        session.add(StgInventoryOpeningControl(
            snapshot_id=snapshot.id, control_key=f"movement:{product_id}:{normalized_location}",
            stock_balance_id=None, product_id=product_id, sku=product.sku if product else grouped_movements[0].sku,
            location=grouped_movements[0].location, sub_location=None,
            canonical_uom=canonical_uom(product.stock_unit) if product else None,
            closing_quantity=None, net_supported_movement=sum((row.quantity_base or ZERO for row in grouped_movements), ZERO),
            implied_opening_quantity=None, unresolved_movement_count=unresolved,
            status="blocked_missing_closing_balance", posting_enabled=False,
            details={"movement_count": len(grouped_movements)},
        ))
        opening_status["blocked_missing_closing_balance"] += 1

    blocked_total = sum(count for status, count in opening_status.items() if status.startswith("blocked_"))
    for status, count in opening_status.items():
        if status.startswith("blocked_"):
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="OPENING_STOCK_BLOCKED", severity="critical",
                entity_type="inventory_opening", source_key=status,
                details={"control_count": count},
            ))

    session.commit()
    return {
        "coa_accounts": len(STATIC_ACCOUNTS) + len(cash_names),
        "journals": sum(journal_status.values()),
        "journal_status": dict(journal_status),
        "journal_kinds": dict(journal_kind),
        "journal_lines": session.scalar(select(func.count(StgJournalBlueprintLine.id)).join(StgJournalBlueprint).where(StgJournalBlueprint.snapshot_id == snapshot.id)) or 0,
        "opening_controls": sum(opening_status.values()),
        "opening_status": dict(opening_status),
        "blocked_opening_controls": blocked_total,
    }
