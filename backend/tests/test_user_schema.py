def test_user_create_defaults_ai_key_mode_to_system():
    from app.schemas.user import UserCreate
    u = UserCreate(username="abc", password="password1")
    assert u.ai_key_mode == "system"


def test_user_create_rejects_invalid_ai_key_mode():
    import pytest
    from pydantic import ValidationError
    from app.schemas.user import UserCreate
    with pytest.raises(ValidationError):
        UserCreate(username="abc", password="password1", ai_key_mode="bogus")


def test_user_update_accepts_none_ai_key_mode():
    from app.schemas.user import UserUpdate
    u = UserUpdate()
    assert u.ai_key_mode is None
