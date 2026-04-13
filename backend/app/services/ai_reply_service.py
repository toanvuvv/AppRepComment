# backend/app/services/ai_reply_service.py
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def generate_reply(
    api_key: str,
    model: str,
    system_prompt: str,
    comment_text: str,
    guest_name: str,
) -> str | None:
    """Call OpenAI to generate reply text for a guest comment.

    Returns the reply text (to be appended after @guest_name), or None on error.
    """
    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Khách hàng {guest_name} bình luận: {comment_text}",
                },
            ],
            max_tokens=200,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI reply generation failed: {e}")
        return None
