# backend/tests/test_ai_reply_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_reply_calls_openai():
    from app.services.ai_reply_service import generate_reply

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Cảm ơn bạn đã hỏi!"))]

    with patch("app.services.ai_reply_service.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await generate_reply(
            api_key="sk-test",
            model="gpt-4o",
            system_prompt="Bạn là nhân viên CSKH Shopee Live.",
            comment_text="Giá bao nhiêu vậy?",
            guest_name="user123",
        )

    assert result == "Cảm ơn bạn đã hỏi!"


@pytest.mark.asyncio
async def test_generate_reply_returns_fallback_on_error():
    from app.services.ai_reply_service import generate_reply

    with patch("app.services.ai_reply_service.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

        result = await generate_reply(
            api_key="sk-test",
            model="gpt-4o",
            system_prompt="...",
            comment_text="Hỏi gì đó",
            guest_name="user",
        )

    assert result is None
