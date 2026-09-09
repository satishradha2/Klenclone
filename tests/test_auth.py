import pytest

from klen_clone.auth import UatSessionStore, hash_password, issue_token, verify_password, verify_token


def test_password_hash_and_signed_token_round_trip():
    encoded = hash_password("correct horse battery staple", salt=b"0123456789abcdef")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)
    token = issue_token(7, "x" * 32, 300, now=1000)
    assert verify_token(token, "x" * 32, now=1100)["sub"] == 7
    with pytest.raises(ValueError):
        verify_token(token, "y" * 32, now=1100)
    with pytest.raises(ValueError):
        verify_token(token, "x" * 32, now=1300)


def test_uat_session_expiry_revocation_and_rate_limit():
    store = UatSessionStore()
    token, session = store.create(7, 300, now=1000)
    assert store.get(token, now=1299) == session
    assert store.get(token, now=1300) is None

    token, _ = store.create(7, 300, now=2000)
    store.revoke(token)
    assert store.get(token, now=2001) is None
    assert all(store.allow_attempt("login", now=3000 + offset) for offset in range(5))
    assert store.allow_attempt("login", now=3005) is False
    assert store.allow_attempt("login", now=3301) is True
