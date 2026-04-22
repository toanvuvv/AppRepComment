import pytest
from pydantic import ValidationError

from app.schemas.seeding import (
    SeedingCloneCreate,
    SeedingCloneResponse,
    SeedingTemplateCreate,
    SeedingManualSendRequest,
    SeedingAutoStartRequest,
)


def test_clone_create_nested_form():
    p = SeedingCloneCreate.model_validate({
        "user": {"id": 12345, "name": "Clone 1", "avatar": "https://..."},
        "cookies": "SPC_EC=abc; SPC_F=xyz",
        "proxy": "http:1.2.3.4:8080:u:p",
    })
    assert p.name == "Clone 1"
    assert p.shopee_user_id == 12345
    assert p.avatar == "https://..."
    assert p.cookies.startswith("SPC_EC=")
    assert p.proxy == "http:1.2.3.4:8080:u:p"


def test_clone_create_flat_form():
    p = SeedingCloneCreate.model_validate({
        "name": "Clone flat",
        "shopee_user_id": 999,
        "cookies": "c=1",
    })
    assert p.name == "Clone flat"
    assert p.shopee_user_id == 999
    assert p.proxy is None


def test_clone_create_requires_name():
    with pytest.raises(ValidationError):
        SeedingCloneCreate.model_validate({"cookies": "c=1"})


def test_template_create():
    t = SeedingTemplateCreate.model_validate({"content": "đẹp quá"})
    assert t.content == "đẹp quá"
    assert t.enabled is True


def test_manual_send_required_fields():
    with pytest.raises(ValidationError):
        SeedingManualSendRequest.model_validate({"content": "hi"})


def test_auto_start_interval_floor():
    with pytest.raises(ValidationError):
        SeedingAutoStartRequest.model_validate({
            "nick_live_id": 1,
            "shopee_session_id": 123,
            "clone_ids": [1],
            "min_interval_sec": 5,
            "max_interval_sec": 30,
        })


def test_auto_start_min_le_max():
    with pytest.raises(ValidationError):
        SeedingAutoStartRequest.model_validate({
            "nick_live_id": 1,
            "shopee_session_id": 123,
            "clone_ids": [1],
            "min_interval_sec": 60,
            "max_interval_sec": 30,
        })


def test_auto_start_non_empty_clones():
    with pytest.raises(ValidationError):
        SeedingAutoStartRequest.model_validate({
            "nick_live_id": 1,
            "shopee_session_id": 123,
            "clone_ids": [],
            "min_interval_sec": 30,
            "max_interval_sec": 60,
        })


def test_clone_rate_limited_error_has_message():
    from app.schemas.seeding import CloneRateLimitedError
    err = CloneRateLimitedError(retry_after_sec=30)
    assert err.retry_after_sec == 30
    assert "30" in str(err)


def test_clone_create_rejects_both_forms():
    from app.schemas.seeding import SeedingCloneCreate
    with pytest.raises(ValidationError):
        SeedingCloneCreate.model_validate({
            "name": "flat",
            "shopee_user_id": 1,
            "user": {"id": 2, "name": "nested"},
            "cookies": "c=1",
        })
