from decimal import Decimal

from klen_clone.ledger import journal_migration_status, subledger_status


def test_journal_status_never_enables_posting():
    assert journal_migration_status("balanced_nonposting") == "migration_locked_balanced"
    assert journal_migration_status("review_required") == "review_required_source_logic"
    assert journal_migration_status("unexpected") == "blocked_unknown_status"


def test_nonzero_subledger_evidence_requires_reconciliation():
    assert subledger_status(Decimal("0"), Decimal("0")) == "no_balance_evidence"
    assert subledger_status(Decimal("10"), Decimal("2")) == "review_required_reconciliation"
