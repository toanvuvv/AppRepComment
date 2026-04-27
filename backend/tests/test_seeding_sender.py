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
                      new=AsyncMock(return_value={"uuid": "UUID1", "usersig": "SIG1"})), \
         patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, cookies="SPC_EC=c", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=SeedingLog(id=99))), \
         patch.object(sender, "_touch_clone_last_sent",
                      new=AsyncMock(return_value=None)), \
         patch("app.services.seeding_sender.get_client_for_proxy") as get_client, \
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

    with patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, cookies="c", last_sent_at=last, proxy=None))):
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

    with patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, cookies="c", last_sent_at=last, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=written_log)) as wl:
        log = await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=1,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )
    assert log.status == "rate_limited"
    wl.assert_called_once()


@pytest.mark.asyncio
async def test_send_host_config_missing_raises_manual():
    sender = SeedingSender()

    with patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, cookies="c", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_resolve_host_credentials",
                      new=AsyncMock(side_effect=HostConfigMissingError())):
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
                      new=AsyncMock(return_value={"uuid": "U", "usersig": "S"})), \
         patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, cookies="c", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=written)), \
         patch.object(sender, "_touch_clone_last_sent",
                      new=AsyncMock(return_value=None)), \
         patch.object(sender, "_record_failure",
                      new=AsyncMock(return_value=None)), \
         patch("app.services.seeding_sender.get_client_for_proxy") as get_client, \
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


@pytest.mark.asyncio
async def test_post_retries_on_network_exception():
    """First-attempt network exception must retry before failing."""
    import httpx
    sender = SeedingSender()
    calls = {"n": 0}

    async def flaky_post(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return _FakeResp(200)

    with patch.object(sender, "_resolve_host_credentials",
                      new=AsyncMock(return_value={"uuid": "U", "usersig": "S"})), \
         patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(id=7, user_id=1, cookies="c", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=SeedingLog(id=1, status="success"))), \
         patch.object(sender, "_touch_clone_last_sent", new=AsyncMock(return_value=None)), \
         patch("app.services.seeding_sender.get_client_for_proxy") as get_client, \
         patch("app.services.seeding_sender.shopee_limiter") as limiter:
        limiter.acquire = AsyncMock(return_value=None)
        client = MagicMock()
        client.post = AsyncMock(side_effect=flaky_post)
        get_client.return_value = client

        log = await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=1,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )
    assert calls["n"] == 2  # retried
    assert log.status == "success"


@pytest.mark.asyncio
async def test_post_exception_message_does_not_leak_cookie():
    """Ensure we don't log/return the raw exception message which may contain cookies."""
    import httpx
    sender = SeedingSender()

    async def always_raise(*a, **kw):
        raise httpx.ConnectError("Connection failed to host. Headers: cookie=SPC_EC=SECRET")

    with patch.object(sender, "_resolve_host_credentials",
                      new=AsyncMock(return_value={"uuid": "U", "usersig": "S"})), \
         patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(id=7, user_id=1, cookies="SPC_EC=SECRET", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=SeedingLog(id=1, status="failed", error="x"))) as wl, \
         patch.object(sender, "_touch_clone_last_sent", new=AsyncMock(return_value=None)), \
         patch.object(sender, "_record_failure", new=AsyncMock(return_value=None)), \
         patch("app.services.seeding_sender.get_client_for_proxy") as get_client, \
         patch("app.services.seeding_sender.shopee_limiter") as limiter:
        limiter.acquire = AsyncMock(return_value=None)
        client = MagicMock()
        client.post = AsyncMock(side_effect=always_raise)
        get_client.return_value = client

        await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=1,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )
    # The error written to the log should not include "SECRET" from the cookie.
    written_error = wl.call_args.kwargs.get("error", "")
    assert "SECRET" not in written_error


@pytest.mark.asyncio
async def test_send_failure_calls_record_failure_with_error_code():
    """Each auto-mode send failure must be recorded against the clone's health."""
    sender = SeedingSender()

    async def fake_post(*a, **kw):
        return _FakeResp(401)

    with patch.object(sender, "_resolve_host_credentials",
                      new=AsyncMock(return_value={"uuid": "U", "usersig": "S"})), \
         patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, name="c7", cookies="c", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=SeedingLog(id=1, status="failed"))), \
         patch.object(sender, "_touch_clone_last_sent",
                      new=AsyncMock(return_value=None)), \
         patch.object(sender, "_record_failure",
                      new=AsyncMock(return_value=None)) as rf, \
         patch("app.services.seeding_sender.get_client_for_proxy") as get_client, \
         patch("app.services.seeding_sender.shopee_limiter") as limiter:
        limiter.acquire = AsyncMock(return_value=None)
        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        get_client.return_value = client

        await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=1,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )

    rf.assert_awaited_once()
    args = rf.call_args.args
    assert args[0] == 7
    assert "auth_expired" in args[1]


@pytest.mark.asyncio
async def test_send_success_not_counted_as_failure():
    sender = SeedingSender()

    async def fake_post(*a, **kw):
        return _FakeResp(200)

    with patch.object(sender, "_resolve_host_credentials",
                      new=AsyncMock(return_value={"uuid": "U", "usersig": "S"})), \
         patch.object(sender, "_load_clone",
                      new=AsyncMock(return_value=MagicMock(
                          id=7, user_id=1, name="c7", cookies="c", last_sent_at=None, proxy=None))), \
         patch.object(sender, "_write_log",
                      new=AsyncMock(return_value=SeedingLog(id=1, status="success"))), \
         patch.object(sender, "_touch_clone_last_sent",
                      new=AsyncMock(return_value=None)), \
         patch.object(sender, "_record_failure",
                      new=AsyncMock(return_value=None)) as rf, \
         patch("app.services.seeding_sender.get_client_for_proxy") as get_client, \
         patch("app.services.seeding_sender.shopee_limiter") as limiter:
        limiter.acquire = AsyncMock(return_value=None)
        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        get_client.return_value = client

        await sender.send(
            clone_id=7, nick_live_id=1, shopee_session_id=1,
            content="x", template_id=None, mode="auto", log_session_id=1,
        )

    rf.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_uses_proxied_client_when_clone_has_proxy():
    """Sender must acquire a client via get_client_for_proxy(clone.proxy)."""
    sender = SeedingSender()

    fake_clone = type("C", (), {
        "id": 99, "user_id": 1, "name": "C", "cookies": "x",
        "proxy": "socks5://u:p@h:80", "proxy_id": 5,
        "last_sent_at": None, "consecutive_failures": 0,
    })()

    fake_resp = type("R", (), {
        "status_code": 200, "json": lambda self: {"err_code": 0},
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_resolve_host_credentials",
        new=AsyncMock(return_value={"uuid": "u", "usersig": "s"}),
    ), patch.object(
        sender, "_touch_clone_last_sent", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ), patch(
        "app.services.seeding_sender.get_client_for_proxy",
    ) as mock_factory, patch(
        "app.services.seeding_sender.shopee_limiter.acquire",
        new=AsyncMock(),
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_resp)
        mock_factory.return_value = mock_client

        await sender.send(
            clone_id=99, nick_live_id=1, shopee_session_id=10,
            content="hi", template_id=None, mode="manual",
            log_session_id=42,
        )

        mock_factory.assert_called_with("socks5://u:p@h:80")
        mock_client.post.assert_awaited()


@pytest.mark.asyncio
async def test_require_proxy_skips_clone_without_proxy_auto_mode():
    sender = SeedingSender()
    fake_clone = type("C", (), {
        "id": 1, "user_id": 7, "name": "C", "cookies": "x",
        "proxy": None, "proxy_id": None,
        "last_sent_at": None, "consecutive_failures": 0,
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_get_require_proxy", new=AsyncMock(return_value=True),
    ), patch.object(
        sender, "_record_failure", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ) as mock_log, patch(
        "app.services.seeding_sender.get_client_for_proxy",
    ) as mock_factory:
        await sender.send(
            clone_id=1, nick_live_id=1, shopee_session_id=10,
            content="hi", template_id=None, mode="auto",
            log_session_id=42,
        )
        mock_factory.assert_not_called()
        mock_log.assert_awaited()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["error"] == "no_proxy"


@pytest.mark.asyncio
async def test_require_proxy_raises_for_manual_mode():
    sender = SeedingSender()
    fake_clone = type("C", (), {
        "id": 1, "user_id": 7, "name": "C", "cookies": "x",
        "proxy": None, "proxy_id": None,
        "last_sent_at": None, "consecutive_failures": 0,
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_get_require_proxy", new=AsyncMock(return_value=True),
    ), patch.object(
        sender, "_record_failure", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ):
        with pytest.raises(RuntimeError, match="no_proxy"):
            await sender.send(
                clone_id=1, nick_live_id=1, shopee_session_id=10,
                content="hi", template_id=None, mode="manual",
                log_session_id=42,
            )


@pytest.mark.asyncio
async def test_require_proxy_off_allows_direct_send():
    """When require_proxy=False, missing clone.proxy still sends direct."""
    sender = SeedingSender()
    fake_clone = type("C", (), {
        "id": 1, "user_id": 7, "name": "C", "cookies": "x",
        "proxy": None, "proxy_id": None,
        "last_sent_at": None, "consecutive_failures": 0,
    })()
    fake_resp = type("R", (), {
        "status_code": 200, "json": lambda self: {"err_code": 0},
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_get_require_proxy", new=AsyncMock(return_value=False),
    ), patch.object(
        sender, "_resolve_host_credentials",
        new=AsyncMock(return_value={"uuid": "u", "usersig": "s"}),
    ), patch.object(
        sender, "_touch_clone_last_sent", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ), patch(
        "app.services.seeding_sender.get_client_for_proxy",
    ) as mock_factory, patch(
        "app.services.seeding_sender.shopee_limiter.acquire",
        new=AsyncMock(),
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_resp)
        mock_factory.return_value = mock_client

        await sender.send(
            clone_id=1, nick_live_id=1, shopee_session_id=10,
            content="hi", template_id=None, mode="manual",
            log_session_id=42,
        )
        mock_factory.assert_called_with(None)
