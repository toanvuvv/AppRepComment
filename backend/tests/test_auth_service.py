from app.services.auth import hash_password, verify_password


def test_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_unique_per_call():
    assert hash_password("abc") != hash_password("abc")


from app.services.auth import create_access_token, decode_access_token


def test_jwt_roundtrip():
    token = create_access_token(user_id=42, username="alice", role="user")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["username"] == "alice"
    assert payload["role"] == "user"


def test_jwt_tampered_returns_none():
    token = create_access_token(user_id=1, username="a", role="user")
    assert decode_access_token(token + "x") is None


def test_jwt_invalid_returns_none():
    assert decode_access_token("garbage") is None
