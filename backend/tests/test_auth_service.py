from app.services.auth import hash_password, verify_password


def test_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_unique_per_call():
    assert hash_password("abc") != hash_password("abc")
