import pytest
from sqlalchemy import func, select

from klen_clone.auth import hash_password
from test_erp_preview import preview_client, seed_operational_controls


def test_dummy_posted_sources_enable_price_credit_and_refund_routes(tmp_path, monkeypatch):
    """Exercise the real HTTP workflow against disposable, never-imported source records."""
    import json
    from datetime import date, timedelta
    from decimal import Decimal

    from klen_clone.cash_management import (create_cash_account, decide_cash_account,
        create_statement_batch, match_recovery_statement_line,
        match_refund_statement_line, transition_statement_batch,
        OperationalCashAccount)
    from klen_clone.close_reporting import build_close_report
    from klen_clone.customer_invoices import create_customer_invoice, transition_customer_invoice
    from klen_clone.delivery_fulfillment import transition_delivery
    from klen_clone.financial_reports import build_customer_statement
    from klen_clone.operational import OperationalFiscalPeriod, OperationalStockPosition
    from klen_clone.payments import create_payment, rehearse_payment_posting, transition_payment
    from klen_clone.period_close import create_period_close, period_close_payload, transition_period_close
    from klen_clone.posting_integration import (OperationalIntegratedJournalLine,
        OperationalIntegratedPostingBatch, OperationalIntegratedSubledgerEntry,
        execute_integrated_posting, posting_preview)
    from klen_clone.sales_returns import sales_return_control_counts
    from test_customer_invoices import delivered_order

    password = "disposable route-test password"
    users_file = tmp_path / "dummy-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "dummy-maker", "password_hash": hash_password(password),
         "roles": ["operations_administrator"],
         "permissions": ["clone.read", "sales_return.create", "bank.statement.import",
                         "bank.reconcile.prepare"],
         "allowed_locations": ["MAIN"]},
        {"id": 2, "username": "dummy-checker", "password_hash": hash_password(password),
         "roles": ["independent_approver"],
         "permissions": ["clone.read", "sales_return.approve",
                         "bank.reconcile.approve", "bank.reconcile.rehearse"],
         "allowed_locations": ["MAIN"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.delenv("ASAS_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ASAS_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'dummy-operational.db'}")
    client = preview_client(tmp_path)
    assert client.get("/api/v1/health").json()["posting_enabled"] is False

    # The isolated database is the only place where synthetic source posting occurs.
    with client.app.state.operational_sessions() as session:
        session.add(OperationalFiscalPeriod(
            period_key="DUMMY-2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31),
            status="open", rehearsal_enabled=True, revision=1,
            approval_reference="isolated-route-test", configured_by="dummy-controller"))
        session.add(OperationalStockPosition(
            location_code="MAIN", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("10"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("4"), revision=1, source_batch_key="dummy-test",
            source_status="operational", availability_enabled=True))
        session.commit()
        _, delivery = delivered_order(session)
        delivery = transition_delivery(session, delivery, expected_revision=3,
            action="deliver", actor="dummy-pod-checker", note="Synthetic POD",
            received_by="Dummy Receiver", pod_reference="DUMMY-POD-1")
        transaction_date = delivery.delivered_at.date()
        invoice = create_customer_invoice(session, delivery, actor="dummy-sales-maker",
            invoice_date=transaction_date, due_date=transaction_date + timedelta(days=30))
        invoice = transition_customer_invoice(session, invoice, expected_revision=1,
            action="submit", actor="dummy-sales-maker")
        invoice = transition_customer_invoice(session, invoice, expected_revision=2,
            action="approve", actor="dummy-sales-checker", note="Dummy invoice review")
        invoice_plan = posting_preview(session, resource_type="customer_invoice",
            resource_key=invoice.invoice_key, actor="dummy-poster")
        execute_integrated_posting(session, resource_type="customer_invoice",
            resource_key=invoice.invoice_key,
            idempotency_key=invoice_plan["idempotency_key"], actor="dummy-poster")
        account = create_cash_account(session, account_code="DUMMY-BANK",
            account_name="Dummy AED bank", account_type="bank", bank_name="Dummy bank",
            identifier="test-only", gl_account_code="1110", location_code="MAIN",
            reason="Isolated refund route test", actor="dummy-treasury-maker")
        decide_cash_account(session, account, action="approve", expected_revision=1,
            actor="dummy-treasury-checker", note="Synthetic approved account")
        receipt = create_payment(session, actor="dummy-ar-maker",
            payment_type="customer_receipt", party_code=invoice.customer_code,
            party_name_snapshot=invoice.customer_name_snapshot,
            location_code=invoice.location_code, payment_date=transaction_date,
            payment_method="bank_transfer", cash_bank_account_code="DUMMY-BANK",
            reference_no="DUMMY-INVOICE-RECEIPT", amount=invoice.total_amount,
            notes="Synthetic settled invoice", lines=[{
                "source_type": "invoice", "source_reference_key": invoice.invoice_no,
                "source_document_date": invoice.invoice_date,
                "source_outstanding_snapshot": invoice.total_amount,
                "allocation_amount": invoice.total_amount}])
        receipt = transition_payment(session, receipt, expected_revision=1,
            action="submit", actor="dummy-ar-maker")
        receipt = transition_payment(session, receipt, expected_revision=2,
            action="approve", actor="dummy-finance-checker")
        receipt_plan = rehearse_payment_posting(session, receipt, actor="dummy-finance-checker")
        execute_integrated_posting(session, resource_type="payment",
            resource_key=receipt.payment_key,
            idempotency_key=receipt_plan["idempotency_key"], actor="dummy-finance-checker")
        invoice_key, invoice_line = invoice.invoice_key, invoice.lines[0]
        original_effective = ((Decimal(invoice_line.net_amount) -
            Decimal(invoice_line.discount_amount)) / Decimal(invoice_line.quantity))
        # Leave another posted invoice untouched for a real browser form submission.
        _, browser_delivery = delivered_order(session)
        browser_delivery = transition_delivery(session, browser_delivery,
            expected_revision=3, action="deliver", actor="dummy-pod-checker",
            note="Second synthetic POD", received_by="Dummy Receiver",
            pod_reference="DUMMY-POD-BROWSER")
        browser_invoice = create_customer_invoice(session, browser_delivery,
            actor="dummy-sales-maker", invoice_date=transaction_date,
            due_date=transaction_date + timedelta(days=30))
        browser_invoice = transition_customer_invoice(session, browser_invoice,
            expected_revision=1, action="submit", actor="dummy-sales-maker")
        browser_invoice = transition_customer_invoice(session, browser_invoice,
            expected_revision=2, action="approve", actor="dummy-sales-checker",
            note="Second synthetic invoice checked")
        browser_invoice_plan = posting_preview(session, resource_type="customer_invoice",
            resource_key=browser_invoice.invoice_key, actor="dummy-poster")
        execute_integrated_posting(session, resource_type="customer_invoice",
            resource_key=browser_invoice.invoice_key,
            idempotency_key=browser_invoice_plan["idempotency_key"], actor="dummy-poster")
        browser_invoice_key = browser_invoice.invoice_key

    def sign_in(username):
        login = client.post("/api/v1/auth/login", json={
            "username": username, "password": password})
        assert login.status_code == 200, login.text
        return {"X-CSRF-Token": login.json()["csrf_token"]}

    maker = sign_in("dummy-maker")
    sources = client.get("/api/v1/customer-price-credits").json()["invoices"]
    assert {row["invoice_key"] for row in sources} == {invoice_key, browser_invoice_key}
    created = client.post("/api/v1/customer-price-credits", headers=maker, json={
        "invoice_key": invoice_key, "line_no": invoice_line.line_no,
        "credit_date": transaction_date.isoformat(),
        "quantity": str(invoice_line.quantity),
        "corrected_unit_net": str((original_effective / 2).quantize(Decimal("0.0001"))),
        "reason": "Synthetic invoice price correction for isolated route test"})
    assert created.status_code == 201, created.text
    credit_key = created.json()["credit_key"]
    submitted = client.post(f"/api/v1/customer-price-credits/{credit_key}/submit",
        headers=maker, json={"expected_revision": 1})
    assert submitted.status_code == 200, submitted.text
    assert client.post(f"/api/v1/customer-price-credits/{credit_key}/approve",
        headers=maker, json={"expected_revision": 2, "note": "Self approval"}).status_code == 403
    checker = sign_in("dummy-checker")
    approved = client.post(f"/api/v1/customer-price-credits/{credit_key}/approve",
        headers=checker, json={"expected_revision": 2, "note": "Synthetic price checked"})
    assert approved.status_code == 200, approved.text
    plan_response = client.post(f"/api/v1/customer-price-credit-posting-plans/{credit_key}",
        headers=checker)
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["movements"] == []
    assert Decimal(str(plan["refund_payable"])) == Decimal(str(approved.json()["total_amount"]))
    assert client.post(f"/api/v1/posting/customer_price_credit/{credit_key}",
        headers=checker, json={"idempotency_key": plan["idempotency_key"]}).status_code == 503

    # This direct domain post creates only a disposable refund source; the HTTP
    # posting gate above remains closed for every browser user.
    with client.app.state.operational_sessions() as session:
        execute_integrated_posting(session, resource_type="customer_price_credit",
            resource_key=credit_key, idempotency_key=plan["idempotency_key"],
            actor="dummy-fixture-poster")
    maker = sign_in("dummy-maker")
    eligible = client.get("/api/v1/customer-refunds").json()
    assert len(eligible["eligible"]) == 1
    assert eligible["eligible"][0]["price_credit_key"] == credit_key
    assert any(row["account_code"] == "DUMMY-BANK" for row in eligible["bank_accounts"])
    refund_amount = Decimal("1.00")
    assert Decimal(str(eligible["eligible"][0]["available"])) > refund_amount
    refund = client.post("/api/v1/customer-refunds", headers=maker, json={
        "price_credit_key": credit_key, "cash_account_code": "DUMMY-BANK",
        "refund_date": transaction_date.isoformat(), "amount": str(refund_amount),
        "notes": "Synthetic refund request; no real bank debit"})
    assert refund.status_code == 201, refund.text
    refund_key = refund.json()["refund_key"]
    submitted_refund = client.post(f"/api/v1/customer-refunds/{refund_key}/submit",
        headers=maker, json={"expected_revision": 1})
    assert submitted_refund.status_code == 200, submitted_refund.text
    remaining = client.get("/api/v1/customer-refunds").json()["eligible"]
    assert Decimal(str(remaining[0]["available"])) > 0
    assert client.post(f"/api/v1/customer-refunds/{refund_key}/approve",
        headers=maker, json={"expected_revision": 2, "note": "Self approval"}).status_code == 403
    checker = sign_in("dummy-checker")
    approved_refund = client.post(f"/api/v1/customer-refunds/{refund_key}/approve",
        headers=checker, json={"expected_revision": 2, "note": "Synthetic liability checked"})
    assert approved_refund.status_code == 200, approved_refund.text
    assert client.post(f"/api/v1/customer-refund-posting-plans/{refund_key}",
        headers=checker).status_code == 409  # Independent bank evidence is still required.
    assert client.post(f"/api/v1/posting/customer_refund/{refund_key}",
        headers=checker, json={"idempotency_key": "never-release-staging"}).status_code == 503

    with client.app.state.operational_sessions() as session:
        from klen_clone.customer_refunds import OperationalCustomerRefund
        from sqlalchemy import select
        row = session.scalar(select(OperationalCustomerRefund).where(
            OperationalCustomerRefund.refund_key == refund_key))
        account = session.scalar(select(OperationalCashAccount).where(
            OperationalCashAccount.account_code == row.cash_account_code))
        statement = create_statement_batch(session, account=account,
            statement_reference="DUMMY-BANK-DEBIT", statement_start=transaction_date,
            statement_end=transaction_date, opening_balance=Decimal("100"),
            closing_balance=Decimal("100") - Decimal(str(refund_amount)),
            source_file_name="synthetic-test-only.csv", actor="dummy-treasury-maker",
            lines=[{"external_id": "DUMMY-DEBIT-1", "transaction_date": transaction_date,
                "reference": row.refund_no, "description": "Synthetic refund debit",
                "debit_amount": Decimal(str(refund_amount)),
                "credit_amount": Decimal("0")}])
        match_refund_statement_line(session, statement, statement.lines[0], row,
            actor="dummy-bank-preparer")
        statement = transition_statement_batch(session, statement, action="submit",
            expected_revision=1, actor="dummy-treasury-maker")
        transition_statement_batch(session, statement, action="approve",
            expected_revision=2, actor="dummy-bank-checker", note="Synthetic debit checked")
    final_plan = client.post(f"/api/v1/customer-refund-posting-plans/{refund_key}",
        headers=checker)
    assert final_plan.status_code == 200, final_plan.text
    assert Decimal(str(final_plan.json()["debit"])) == Decimal(str(refund_amount))
    # Only the disposable domain fixture may post this refund to provide a
    # genuine target-ERP source for the opposite-direction recovery workflow.
    with client.app.state.operational_sessions() as session:
        execute_integrated_posting(session, resource_type="customer_refund",
            resource_key=refund_key, idempotency_key=final_plan.json()["idempotency_key"],
            actor="dummy-fixture-poster")
    maker = sign_in("dummy-maker")
    recovery = client.post("/api/v1/customer-refund-recoveries", headers=maker, json={
        "refund_key": refund_key, "recovery_date": transaction_date.isoformat(),
        "amount": str(refund_amount), "reason": "Synthetic customer repayment"})
    assert recovery.status_code == 201, recovery.text
    recovery_key = recovery.json()["recovery_key"]
    assert client.post(f"/api/v1/customer-refund-recoveries/{recovery_key}/submit",
        headers=maker, json={"expected_revision": 1}).status_code == 200
    assert client.post(f"/api/v1/customer-refund-recoveries/{recovery_key}/approve",
        headers=maker, json={"expected_revision": 2,
            "note": "Self approval must fail"}).status_code == 403
    checker = sign_in("dummy-checker")
    checked = client.post(f"/api/v1/customer-refund-recoveries/{recovery_key}/approve",
        headers=checker, json={"expected_revision": 2,
            "note": "Independent synthetic repayment review"})
    assert checked.status_code == 200, checked.text
    assert client.post(f"/api/v1/customer-refund-recovery-posting-plans/{recovery_key}",
        headers=checker).status_code == 409  # Bank credit approval is still missing.
    with client.app.state.operational_sessions() as session:
        from klen_clone.customer_refunds import OperationalCustomerRefundRecovery
        recovery_row = session.scalar(select(OperationalCustomerRefundRecovery).where(
            OperationalCustomerRefundRecovery.recovery_key == recovery_key))
        account = session.scalar(select(OperationalCashAccount).where(
            OperationalCashAccount.account_code == recovery_row.cash_account_code))
        credit_statement = create_statement_batch(session, account=account,
            statement_reference="DUMMY-BANK-RECOVERY", statement_start=transaction_date,
            statement_end=transaction_date, opening_balance=Decimal("99"),
            closing_balance=Decimal("99") + refund_amount,
            source_file_name="synthetic-recovery-test-only.csv",
            actor="dummy-treasury-maker", lines=[{
                "external_id": "DUMMY-CREDIT-1", "transaction_date": transaction_date,
                "reference": recovery_row.recovery_no,
                "description": "Synthetic repayment credit", "debit_amount": Decimal("0"),
                "credit_amount": refund_amount}])
        match_recovery_statement_line(session, credit_statement,
            credit_statement.lines[0], recovery_row, actor="dummy-bank-preparer")
        credit_statement = transition_statement_batch(session, credit_statement,
            action="submit", expected_revision=1, actor="dummy-treasury-maker")
        transition_statement_batch(session, credit_statement, action="approve",
            expected_revision=2, actor="dummy-bank-checker",
            note="Independent synthetic credit review")
    recovery_plan = client.post(
        f"/api/v1/customer-refund-recovery-posting-plans/{recovery_key}", headers=checker)
    assert recovery_plan.status_code == 200, recovery_plan.text
    assert recovery_plan.json()["movements"] == []
    assert [(line["account"], Decimal(str(line["debit"])),
             Decimal(str(line["credit"]))) for line in recovery_plan.json()["journal"]] == [
        ("1110", refund_amount, Decimal("0")),
        ("2130", Decimal("0"), refund_amount)]
    assert client.post(f"/api/v1/posting/customer_refund_recovery/{recovery_key}",
        headers=checker, json={"idempotency_key": recovery_plan.json()["idempotency_key"]}
        ).status_code == 503
    # Rehearsal is not sufficient: prove the isolated accounting/subledger
    # mutation, idempotent replay and report/close visibility after posting.
    with client.app.state.operational_sessions() as session:
        def account_balance(code):
            lines = session.execute(select(
                OperationalIntegratedJournalLine.debit,
                OperationalIntegratedJournalLine.credit).where(
                OperationalIntegratedJournalLine.account_code == code)).all()
            return sum((Decimal(debit) - Decimal(credit) for debit, credit in lines), Decimal("0"))

        bank_before, payable_before = account_balance("1110"), account_balance("2130")
        batches_before = session.scalar(select(func.count(OperationalIntegratedPostingBatch.id)))
        posted = execute_integrated_posting(session,
            resource_type="customer_refund_recovery", resource_key=recovery_key,
            idempotency_key=recovery_plan.json()["idempotency_key"],
            actor="dummy-fixture-poster")
        assert posted["idempotent_replay"] is False
        assert account_balance("1110") == bank_before + refund_amount
        assert account_balance("2130") == payable_before - refund_amount
        assert sales_return_control_counts(session)["refund_payable"] == -account_balance("2130")
        subledger = session.scalar(select(OperationalIntegratedSubledgerEntry).join(
            OperationalIntegratedPostingBatch,
            OperationalIntegratedSubledgerEntry.batch_id == OperationalIntegratedPostingBatch.id).where(
            OperationalIntegratedPostingBatch.resource_type == "customer_refund_recovery",
            OperationalIntegratedPostingBatch.resource_key == recovery_key))
        assert subledger.entry_type == "customer_refund_recovered"
        assert subledger.party_code == invoice.customer_code
        assert Decimal(subledger.amount) == refund_amount
        statement = build_customer_statement(session, party_code=invoice.customer_code,
            party_name=invoice.customer_name_snapshot, as_of=transaction_date)
        assert statement["recovery_total"] == refund_amount
        assert any(entry["entry_type"] == "customer_refund_recovery" and
                   entry["source_reference"] == refund.json()["refund_no"] and
                   entry["credit"] == refund_amount for entry in statement["entries"])
        replay = execute_integrated_posting(session,
            resource_type="customer_refund_recovery", resource_key=recovery_key,
            idempotency_key=recovery_plan.json()["idempotency_key"],
            actor="dummy-fixture-poster")
        assert replay["idempotent_replay"] is True
        assert session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) == batches_before + 1
        with pytest.raises(ValueError, match="approved customer refund recovery"):
            execute_integrated_posting(session, resource_type="customer_refund_recovery",
                resource_key=recovery_key, idempotency_key="different-recovery-posting",
                actor="dummy-fixture-poster")
        close = create_period_close(session, fiscal_period_key="DUMMY-2026",
            actor="dummy-close-maker")
        close_snapshot = period_close_payload(session, close)
        assert close_snapshot["snapshot"]["permanent_journal_batches"] == batches_before + 1
        assert next(item for item in close_snapshot["checklist"]
                    if item["control"] == "permanent_journal_balance")["status"] == "pass"
        transition_period_close(session, close, action="submit", expected_revision=1,
            actor="dummy-close-maker", note="Synthetic VAT exception documented")
        transition_period_close(session, close, action="approve", expected_revision=2,
            actor="dummy-close-checker", note="Synthetic close accepted for report test")
        report = build_close_report(session, close)
        assert report["ledger_controls"]["integrated_batches"] == batches_before + 1
        assert {item["posted_account"] for item in report["ledger_controls"]["legacy_account_aliases"]} == {
            "DUMMY-BANK", "Accounts Receivable"}
        assert report["trial_balance"]["difference"] == Decimal("0.00")
        assert report["balance_sheet"]["difference"] == Decimal("0.00")
        payable_row = next(row for row in report["trial_balance"]["rows"]
                           if row["account_code"] == "2130")
        assert payable_row["credit"] - payable_row["debit"] == -account_balance("2130")
    maker = sign_in("dummy-maker")
    over_repayment = client.post("/api/v1/customer-refund-recoveries", headers=maker, json={
        "refund_key": refund_key, "recovery_date": transaction_date.isoformat(),
        "amount": "0.01", "reason": "Attempt above recovered payout"})
    assert over_repayment.status_code == 422
    assert client.get("/api/v1/health").json()["posting_enabled"] is False


def test_price_credit_refund_and_recovery_routes_are_scoped_and_live(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'credit-operational.db'}")
    client = preview_client(tmp_path)
    seed_operational_controls(client)
    assert client.get("/api/v1/customer-price-credits").status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password"})
    assert login.status_code == 200
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    for path in ("/customer-price-credits", "/customer-refunds",
                 "/customer-refund-recoveries"):
        response = client.get(f"/api/v1{path}")
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
    invalid_credit = client.post("/api/v1/customer-price-credits", headers=csrf, json={
        "invoice_key": "missing", "line_no": 1, "credit_date": "2026-09-29",
        "quantity": "1", "corrected_unit_net": "1", "reason": "Price error"})
    assert invalid_credit.status_code == 404
    invalid_refund = client.post("/api/v1/customer-refunds", headers=csrf, json={
        "return_key": "missing", "cash_account_code": "BANK", "refund_date": "2026-09-29",
        "amount": "1"})
    assert invalid_refund.status_code == 404
    invalid_recovery = client.post("/api/v1/customer-refund-recoveries", headers=csrf, json={
        "refund_key": "missing", "recovery_date": "2026-09-29", "amount": "1",
        "reason": "Customer returned funds"})
    assert invalid_recovery.status_code == 404
    for resource_type in ("customer_price_credit", "customer_refund"):
        disabled = client.post(f"/api/v1/posting/{resource_type}/missing", headers=csrf,
            json={"idempotency_key": "staging-posting-must-remain-disabled"})
        assert disabled.status_code == 503
        assert "disabled" in disabled.json()["detail"].lower()
