from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.credit_management import (
    OperationalCollectionAction, OperationalCreditLimitRequest,
    OperationalCreditOverrideRequest, OperationalCustomerCreditProfile,
    OperationalDunningRequest, assert_customer_credit_allows_order,
    collection_action_payload, consume_credit_override, create_collection_action,
    create_credit_limit_request, create_credit_override_request, create_dunning_request,
    credit_profile_payload, set_credit_hold, transition_collection_action,
    transition_credit_limit_request, transition_credit_override_request,
    transition_dunning_request,
)
from klen_clone.operational import (
    OperationalAuditEvent, OperationalOpeningBalanceBatch,
    OperationalOpeningPartyBalance, initialize_operational_database,
    make_operational_engine,
)
from klen_clone.sales_orders import OperationalSalesQuotation


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        batch = OperationalOpeningBalanceBatch(
            batch_key="c" * 64, source_capture="test", source_manifest_sha256="d" * 64,
            source_atomic=False, approval_reference="credit-test", imported_by="finance",
            receivable_rows=1, receivable_amount=Decimal("100"), customer_advance_rows=0,
            customer_advance_amount=0, payable_rows=0, payable_amount=0,
            supplier_advance_rows=0, supplier_advance_amount=0,
            status="approved_non_atomic_nonposting")
        value.add(batch); value.flush()
        value.add(OperationalOpeningPartyBalance(
            batch_id=batch.id, party_type="customer", party_code="C-1",
            party_name_snapshot="Customer One", balance_type="receivable",
            amount=Decimal("100"), currency_code="AED", control_account_code="AR",
            offset_account_code="Opening", posting_enabled=False, source_status="approved"))
        value.commit()
        yield value
    engine.dispose()


def approved_profile(session: Session, limit="500"):
    request = create_credit_limit_request(session, party_code="C-1", party_name="Customer One",
        proposed_limit=Decimal(limit), proposed_terms_days=30,
        reason="Controlled test limit", actor="credit-maker")
    return transition_credit_limit_request(session, request, expected_revision=1,
        action="approve", actor="credit-approver", note="Exposure and terms verified")


def accepted_quotation(session: Session, amount="450"):
    row = OperationalSalesQuotation(
        quotation_key="q" * 36, quotation_no="SQ-CREDIT-1",
        customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", quotation_date=date(2026, 9, 19),
        valid_until=date(2026, 10, 19), currency_code="AED",
        subtotal=Decimal(amount), discount_amount=0, tax_amount=0,
        total_amount=Decimal(amount), status="accepted", posting_enabled=False,
        created_by="sales-maker", approved_by="sales-approver",
        acceptance_reference="customer-acceptance", accepted_by="sales-maker",
        revision=4, state_changed_by="sales-maker")
    session.add(row); session.commit(); return row


def test_credit_limit_requires_independent_approval_and_controls_exposure(session):
    request = create_credit_limit_request(session, party_code="C-1", party_name="Customer One",
        proposed_limit=Decimal("500"), proposed_terms_days=30,
        reason="Controlled test limit", actor="credit-maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_credit_limit_request(session, request, expected_revision=1,
            action="approve", actor="credit-maker", note="Self approval blocked")
    session.rollback()
    request = transition_credit_limit_request(session, request, expected_revision=1,
        action="approve", actor="credit-approver", note="Exposure and terms verified")
    assert request.status == "approved"
    profile = session.scalar(select(OperationalCustomerCreditProfile))
    assert profile.credit_limit == Decimal("500.00") and profile.payment_terms_days == 30
    payload = credit_profile_payload(session, "C-1", "Customer One", as_of=date(2026, 9, 19))
    assert payload["receivable_exposure"] == Decimal("100.00")
    assert payload["available_credit"] == Decimal("400.00")
    assert payload["credit_status"] == "within_limit"
    assert_customer_credit_allows_order(session, party_code="C-1",
                                        order_amount=Decimal("400"), as_of=date(2026, 9, 19))
    with pytest.raises(ValueError, match="credit limit exceeded"):
        assert_customer_credit_allows_order(session, party_code="C-1",
                                            order_amount=Decimal("400.01"), as_of=date(2026, 9, 19))


def test_credit_hold_blocks_orders_until_controlled_release(session):
    approved_profile(session)
    profile = session.scalar(select(OperationalCustomerCreditProfile))
    profile = set_credit_hold(session, profile, expected_revision=1, action="hold",
                              reason="Overdue review required", actor="credit-approver")
    with pytest.raises(ValueError, match="credit hold"):
        assert_customer_credit_allows_order(session, party_code="C-1",
                                            order_amount=Decimal("1"), as_of=date(2026, 9, 19))
    profile = set_credit_hold(session, profile, expected_revision=2, action="release",
                              reason="Controller approved release", actor="credit-approver")
    assert profile.status == "active" and profile.hold_reason is None
    assert_customer_credit_allows_order(session, party_code="C-1",
                                        order_amount=Decimal("1"), as_of=date(2026, 9, 19))


def test_collection_promise_and_followup_lifecycle_are_audited(session):
    with pytest.raises(ValueError, match="Promise amount"):
        create_collection_action(session, party_code="C-1", party_name="Customer One",
            invoice_no=None, action_date=date(2026, 9, 19), action_type="promise_to_pay",
            outcome="Customer promised payment", next_followup_date=date(2026, 9, 22),
            promise_amount=None, promise_date=None, actor="collector")
    session.rollback()
    action = create_collection_action(session, party_code="C-1", party_name="Customer One",
        invoice_no="SI-1", action_date=date(2026, 9, 19), action_type="promise_to_pay",
        outcome="Customer promised full payment", next_followup_date=date(2026, 9, 22),
        promise_amount=Decimal("100"), promise_date=date(2026, 9, 21), actor="collector")
    assert collection_action_payload(action)["promise_amount"] == Decimal("100.00")
    action = transition_collection_action(session, action, expected_revision=1,
                                          action="break", actor="collector")
    assert action.status == "broken" and action.revision == 2
    assert session.scalar(select(func.count(OperationalCollectionAction.id))) == 1
    assert session.scalar(select(func.count(OperationalCreditLimitRequest.id))) == 0
    assert session.scalar(select(func.count(OperationalAuditEvent.id))) == 2


def test_blocked_order_override_is_independent_expiring_and_single_use(session):
    approved_profile(session)
    quotation = accepted_quotation(session)
    with pytest.raises(ValueError, match="approved quotation-specific override"):
        assert_customer_credit_allows_order(session, party_code="C-1",
            order_amount=quotation.total_amount, as_of=date(2026, 9, 19),
            quotation_key=quotation.quotation_key)
    request = create_credit_override_request(session, quotation,
        valid_until=date(2026, 9, 25), reason="Urgent customer order under review",
        actor="credit-maker", as_of=date(2026, 9, 19))
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_credit_override_request(session, request, expected_revision=1,
            action="approve", actor="credit-maker", note="Self approval blocked")
    session.rollback()
    request = transition_credit_override_request(session, request, expected_revision=1,
        action="approve", actor="credit-approver", note="Commercial risk accepted for one order")
    allowed = assert_customer_credit_allows_order(session, party_code="C-1",
        order_amount=quotation.total_amount, as_of=date(2026, 9, 19),
        quotation_key=quotation.quotation_key)
    assert allowed.id == request.id
    consume_credit_override(session, allowed, actor="sales-maker", sales_order_key="order-1")
    session.commit()
    assert request.status == "consumed" and request.sales_order_key == "order-1"
    with pytest.raises(ValueError, match="approved quotation-specific override"):
        assert_customer_credit_allows_order(session, party_code="C-1",
            order_amount=quotation.total_amount, as_of=date(2026, 9, 19),
            quotation_key=quotation.quotation_key)


def test_dunning_requires_eligibility_sequence_and_independent_approval(session):
    action = create_collection_action(session, party_code="C-1", party_name="Customer One",
        invoice_no=None, action_date=date(2026, 9, 19), action_type="promise_to_pay",
        outcome="Customer promised opening balance", next_followup_date=date(2026, 9, 20),
        promise_amount=Decimal("100"), promise_date=date(2026, 9, 20), actor="collector")
    transition_collection_action(session, action, expected_revision=1,
                                 action="break", actor="collector")
    with pytest.raises(ValueError, match="Complete reminder 1"):
        create_dunning_request(session, party_code="C-1", party_name="Customer One",
            stage="reminder_2", reason="Escalate broken promise", actor="collector",
            as_of=date(2026, 9, 21))
    session.rollback()
    reminder = create_dunning_request(session, party_code="C-1", party_name="Customer One",
        stage="reminder_1", reason="Broken promise requires first reminder", actor="collector",
        as_of=date(2026, 9, 21))
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_dunning_request(session, reminder, expected_revision=1,
            action="approve", actor="collector", note="Self approval blocked")
    session.rollback()
    reminder = transition_dunning_request(session, reminder, expected_revision=1,
        action="approve", actor="credit-approver", note="Reminder evidence verified")
    reminder = transition_dunning_request(session, reminder, expected_revision=2,
        action="complete", actor="collector", note="Reminder issued to customer")
    assert reminder.status == "completed"
    second = create_dunning_request(session, party_code="C-1", party_name="Customer One",
        stage="reminder_2", reason="First reminder completed without payment", actor="collector",
        as_of=date(2026, 9, 22))
    assert second.status == "pending"
    assert session.scalar(select(func.count(OperationalDunningRequest.id))) == 2
    assert session.scalar(select(func.count(OperationalCreditOverrideRequest.id))) == 0
