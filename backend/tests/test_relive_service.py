import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.relive_service import pin_livestream_item


@pytest.mark.asyncio
async def test_pin_livestream_item_payload_shape():
    fake_resp = type("R", (), {"status_code": 200, "text": '{"ok":1}',
                               "json": lambda self: {"ok": 1}})()
    mock_client = type("C", (), {})()
    mock_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.relive_service.get_client", return_value=mock_client):
        result = await pin_livestream_item(
            api_key="K", cookies="C", session_id=111,
            item_id=222, shop_id=333, proxy=None,
        )

    assert result == {"ok": 1}
    mock_client.post.assert_awaited_once()
    url, = mock_client.post.await_args.args
    kwargs = mock_client.post.await_args.kwargs
    assert url == "https://api.relive.vn/livestream/show"
    payload = kwargs["json"]
    assert payload["apikey"] == "K"
    assert payload["cookie"] == "C"
    assert payload["session_id"] == 111
    assert json.loads(payload["item"]) == {"item_id": 222, "shop_id": 333}
    assert payload["country"] == "vn"
    assert payload["proxy"] == ""


@pytest.mark.asyncio
async def test_pin_livestream_item_http_error():
    fake_resp = type("R", (), {"status_code": 500, "text": "boom"})()
    mock_client = type("C", (), {})()
    mock_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.relive_service.get_client", return_value=mock_client):
        with pytest.raises(ValueError, match="status 500"):
            await pin_livestream_item(
                api_key="K", cookies="C", session_id=1,
                item_id=2, shop_id=3,
            )
