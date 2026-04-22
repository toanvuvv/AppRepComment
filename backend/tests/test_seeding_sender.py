import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.seeding import SeedingClone, SeedingLog, SeedingLogSession
from app.schemas.seeding import CloneRateLimitedError, HostConfigMissingError
from app.services.seeding_sender import CLONE_FLOOR_SEC, SeedingSender


class _FakeResp:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {"err_code": 0}
        self.text = json.dumps(self._body)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


@pytest.mark.asyncio
async def test_send_builds_type100_body_with_host_credentials():
    sender = SeedingSender()

    captured = {}

    async def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return _FakeResp(200)

    with patch.object(sender, "_resolve_host_credentials",
                      return_value={"uuid": "UUID1", "usersig": "SIG1"}), \
         patch.object(sender, "_load_clone", return_value=MagicMock(
             id=7, cookies="SPC_EC=c", last_sent_at=None)), \
         patch.object(sender, "_write_log", return_value=SeedingLog(id=99)), \
         patch.object(sender, "_touch_clone_last_sent", return_value=None), \
         patch("app.services.seeding_sender.get_client") as get_client, \
         patch("app.services.seeding_sender.shopee_limiter") as limiter:
        limiter.acquire = AsyncMock(return_value=None)
        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        get_client.return_value = client

        log = await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=999,
            content="đẹp quá", template_id=None, mode="manual",
            log_session_id=42,
        )

    assert log.id == 99
    inner = json.loads(captured["body"]["content"])
    assert inner == {"type": 100, "content": "đẹp quá"}
    assert captured["body"]["uuid"] == "UUID1"
    assert captured["body"]["usersig"] == "SIG1"
    assert captured["body"]["send_ts"] > 0
    assert "pin" not in captured["body"]
    assert captured["headers"]["cookie"] == "SPC_EC=c"
    assert captured["headers"]["referer"] == "https://live.shopee.vn/pc/live?session=999"
    assert "/api/v1/session/999/message" in captured["url"]


@pytest.mark.asyncio
async def test_send_manual_rate_limited_raises():
    sender = SeedingSender()
    last = datetime.now(timezone.utc) - timedelta(seconds=CLONE_FLOOR_SEC - 3)

    with patch.object(sender, "_load_clone", return_value=MagicMock(
            id=7, cookies="c", last_sent_at=last)):
        with pytest.raises(CloneRateLimitedError) as ei:
            await sender.send(
                clone_id=7, nick_live_id=1, shopee_session_id=1,
                content="x", template_id=None, mode="manual", log_session_id=1,
            )
    assert ei.value.retry_after_sec >= 1


@pytest.mark.asyncio
async def test_send_auto_rate_limited_writes_log_returns():
    sender = SeedingSender()
    last = datetime.now(timezone.utc)
    written_log = SeedingLog(id=123, status="rate_limited")

    with patch.object(sender, "_load_clone", return_value=MagicMock(
            id=7, cookies="c", last_sent_at=last)), \
         patch.object(sender, "_write_log", return_value=written_log) as wl:
        log = await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=1,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )
    assert log.status == "rate_limited"
    wl.assert_called_once()


@pytest.mark.asyncio
async def test_send_host_config_missing_raises_manual():
    sender = SeedingSender()

    with patch.object(sender, "_load_clone", return_value=MagicMock(
            id=7, cookies="c", last_sent_at=None)), \
         patch.object(sender, "_resolve_host_credentials",
                      side_effect=HostConfigMissingError()):
        with pytest.raises(HostConfigMissingError):
            await sender.send(
                clone_id=7, nick_live_id=1, shopee_session_id=1,
                content="x", template_id=None, mode="manual", log_session_id=1,
            )


@pytest.mark.asyncio
async def test_send_shopee_failure_writes_failed_log_auto():
    sender = SeedingSender()
    written = SeedingLog(id=55, status="failed", error="upstream_500")

    async def fake_post(*a, **kw):
        return _FakeResp(500, {"err_code": 99})

    with patch.object(sender, "_resolve_host_credentials",
                      return_value={"uuid": "U", "usersig": "S"}), \
         patch.object(sender, "_load_clone", return_value=MagicMock(
             id=7, cookies="c", last_sent_at=None)), \
         patch.object(sender, "_write_log", return_value=written), \
         patch.object(sender, "_touch_clone_last_sent", return_value=None), \
         patch("app.services.seeding_sender.get_client") as get_client, \
         patch("app.services.seeding_sender.shopee_limiter") as limiter:
        limiter.acquire = AsyncMock(return_value=None)
        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        get_client.return_value = client

        log = await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=2,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )
    assert log.status == "failed"
