"""Tests for self_post_filter.is_self_post — the self-reply loop guard."""

from __future__ import annotations

import json

import pytest

from app.services.nick_cache import NickSettingsSnapshot
from app.services.self_post_filter import is_self_post


def _settings(
    *,
    shopee_user_id: int | None = 10001,
    moderator_host_id: str | None = "20002",
    host_uuid: str | None = None,
) -> NickSettingsSnapshot:
    moderator_config = (
        {"host_id": moderator_host_id} if moderator_host_id is not None else None
    )
    host_config = {"uuid": host_uuid} if host_uuid is not None else None
    return NickSettingsSnapshot(
        reply_mode="ai",
        reply_to_host=True,
        reply_to_moderator=True,
        auto_post_enabled=False,
        auto_post_to_host=False,
        auto_post_to_moderator=False,
        host_config=host_config,
        moderator_config=moderator_config,
        openai_api_key="sk-test",
        openai_model="gpt-4o",
        system_prompt="",
        knowledge_model=None,
        knowledge_system_prompt="",
        banned_words=(),
        shopee_user_id=shopee_user_id,
    )


# --- guest comments must pass through ------------------------------------


def test_guest_comment_is_not_self() -> None:
    settings = _settings()
    comment = {
        "userId": 99999,
        "username": "guest",
        "content": "Giá sản phẩm 1 bao nhiêu?",
    }
    assert is_self_post(comment, settings) is False


def test_guest_comment_without_user_id_is_not_self() -> None:
    settings = _settings()
    comment = {"username": "guest", "content": "hello"}
    assert is_self_post(comment, settings) is False


# --- host self-reply -----------------------------------------------------


def test_host_own_reply_by_user_id_field() -> None:
    settings = _settings(shopee_user_id=10001)
    comment = {"userId": 10001, "content": "@guest cảm ơn"}
    assert is_self_post(comment, settings) is True


@pytest.mark.parametrize(
    "field",
    ["userId", "user_id", "uid", "streamerId", "fromUserId", "authorId", "senderId"],
)
def test_host_own_reply_any_user_id_field(field: str) -> None:
    settings = _settings(shopee_user_id=10001)
    comment = {field: 10001, "content": "x"}
    assert is_self_post(comment, settings) is True


def test_host_reply_stringified_user_id() -> None:
    settings = _settings(shopee_user_id=10001)
    comment = {"userId": "10001", "content": "x"}
    assert is_self_post(comment, settings) is True


# --- moderator self-reply ------------------------------------------------


def test_moderator_own_reply_by_host_id() -> None:
    settings = _settings(shopee_user_id=10001, moderator_host_id="20002")
    comment = {"userId": 20002, "content": "@guest reply"}
    assert is_self_post(comment, settings) is True


def test_moderator_host_id_as_string() -> None:
    settings = _settings(moderator_host_id="20002")
    comment = {"user_id": "20002", "content": "x"}
    assert is_self_post(comment, settings) is True


# --- content-type detection ---------------------------------------------


def test_top_level_type_101_is_self_even_with_unknown_uid() -> None:
    settings = _settings(shopee_user_id=10001)
    comment = {"userId": 77777, "type": 101, "content": "host message"}
    assert is_self_post(comment, settings) is True


def test_top_level_type_102_is_self() -> None:
    settings = _settings()
    comment = {"type": 102, "content": "mod message"}
    assert is_self_post(comment, settings) is True


def test_inner_json_type_101_detected() -> None:
    settings = _settings()
    inner = json.dumps({"type": 101, "content": "host reply"})
    comment = {"userId": 55555, "content": inner}
    assert is_self_post(comment, settings) is True


def test_inner_json_type_102_detected() -> None:
    settings = _settings()
    inner = json.dumps({"type": 102, "content": "mod reply"})
    comment = {"content": inner}
    assert is_self_post(comment, settings) is True


def test_inner_json_guest_type_not_self() -> None:
    settings = _settings()
    inner = json.dumps({"type": 1, "content": "guest message"})
    comment = {"userId": 99999, "content": inner}
    assert is_self_post(comment, settings) is False


# --- robustness ----------------------------------------------------------


def test_missing_shopee_user_id_and_no_mod_config() -> None:
    settings = _settings(shopee_user_id=None, moderator_host_id=None)
    comment = {"userId": 99999, "content": "guest"}
    # No signals to match against — must not block guest comments.
    assert is_self_post(comment, settings) is False


def test_malformed_user_id_does_not_crash() -> None:
    settings = _settings(shopee_user_id=10001)
    comment = {"userId": "not-a-number", "content": "x"}
    assert is_self_post(comment, settings) is False


def test_non_json_content_does_not_crash() -> None:
    settings = _settings(shopee_user_id=10001)
    comment = {"userId": 99999, "content": "{not really json"}
    assert is_self_post(comment, settings) is False


def test_zero_user_id_is_ignored() -> None:
    settings = _settings(shopee_user_id=10001)
    # userId=0 is the Shopee "unknown" marker; must not coincidentally match
    # a nick whose shopee_user_id has somehow been stored as 0.
    comment = {"userId": 0, "content": "guest"}
    assert is_self_post(comment, settings) is False


def test_host_uuid_numeric_match() -> None:
    settings = _settings(shopee_user_id=None, host_uuid="12345")
    comment = {"userId": 12345, "content": "x"}
    assert is_self_post(comment, settings) is True


def test_host_uuid_non_numeric_does_not_crash() -> None:
    # Real uuid strings (e.g. "abcd-efgh") must not blow up.
    settings = _settings(shopee_user_id=None, host_uuid="abcd-efgh-0001")
    comment = {"userId": 99999, "content": "guest"}
    assert is_self_post(comment, settings) is False
