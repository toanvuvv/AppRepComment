import json
import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def parse_curl_command(curl_text: str) -> tuple[str | None, dict[str, str], str]:
    """Parse a cURL command into (session_id, headers, body)."""
    url_match = re.search(r"['\"]?(https?://[^\s'\"]+)['\"]?", curl_text)
    url = url_match.group(1) if url_match else None
    session_id = url.split("/")[-2] if url else None

    headers: dict[str, str] = {}
    for pattern in [
        r"""-H\s+['"](.*?)['"]""",
        r"""--header\s+['"](.*?)['"]""",
    ]:
        for match in re.finditer(pattern, curl_text):
            header_str = match.group(1)
            if ":" in header_str:
                key, value = header_str.split(":", 1)
                headers[key.strip()] = value.strip()

    body = "{}"
    for pattern in [
        r"""--data-raw\s+['"](.*?)['"]""",
        r"""--data\s+['"](.*?)['"]""",
        r"""-d\s+['"](.*?)['"]""",
    ]:
        body_match = re.search(pattern, curl_text, re.DOTALL)
        if body_match:
            body = body_match.group(1)
            break

    return session_id, headers, body


class ShopeeLiveModerator:
    """Manages moderator configs per nick_live and sends replies to live comments.

    The cURL is stored as a template keyed by nick_live_id.
    At send time, the actual live session_id is injected into the URL.
    """

    def __init__(self) -> None:
        self._configs: dict[int, dict[str, Any]] = {}

    def save_curl(self, nick_live_id: int, curl_text: str) -> dict[str, Any]:
        """Parse cURL and save as template for this nick_live.

        The session_id in the cURL URL is ignored - the actual live
        session_id is provided at send time.
        """
        _session_id, headers, body = parse_curl_command(curl_text)

        try:
            body_data = json.loads(body)
        except json.JSONDecodeError:
            body_data = {}

        self._configs[nick_live_id] = {
            "headers": headers,
            "host_id": headers.get("X-Livestreaming-Moderator"),
            "usersig": body_data.get("usersig", ""),
            "uuid": body_data.get("uuid", ""),
        }
        return {
            "nick_live_id": nick_live_id,
            "host_id": headers.get("X-Livestreaming-Moderator"),
            "status": "saved",
        }

    def get_config(self, nick_live_id: int) -> dict[str, Any] | None:
        return self._configs.get(nick_live_id)

    def has_config(self, nick_live_id: int) -> bool:
        return nick_live_id in self._configs

    def remove_config(self, nick_live_id: int) -> bool:
        return self._configs.pop(nick_live_id, None) is not None

    def generate_reply_body(
        self,
        nick_live_id: int,
        guest_name: str,
        guest_id: int,
        reply_text: str,
    ) -> dict[str, Any] | None:
        """Build the request body for replying to a guest comment."""
        config = self._configs.get(nick_live_id)
        if not config:
            return None

        placeholder = re.sub(
            r"[^A-Z0-9]",
            "",
            guest_name.upper()[:8] + str(int(time.time())),
        )[-10:]

        mention_text = f"@{guest_name} {reply_text}"

        inner_content = {
            "content": mention_text,
            "content_v2": f"#{placeholder}# {mention_text}",
            "extra_info": {
                "feedback_transparent": "",
                "place_holders": [
                    {
                        "key": f"#{placeholder}#",
                        "type": 1,
                        "user_id": guest_id,
                        "value": guest_name,
                    }
                ],
            },
            "type": 102,
        }

        return {
            "content": json.dumps(inner_content, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": config["usersig"],
            "uuid": config["uuid"],
        }

    async def send_reply(
        self,
        nick_live_id: int,
        live_session_id: int,
        guest_name: str,
        guest_id: int,
        reply_text: str,
    ) -> dict[str, Any]:
        """Send reply. URL is built from live_session_id, headers from saved config."""
        config = self._configs.get(nick_live_id)
        if not config:
            return {"success": False, "error": "Moderator not configured"}

        body = self.generate_reply_body(nick_live_id, guest_name, guest_id, reply_text)
        if not body:
            return {"success": False, "error": "Failed to generate reply body"}

        url = f"https://live.shopee.vn/api/v1/session/{live_session_id}/message"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers=config["headers"],
                    json=body,
                    timeout=10.0,
                )
                is_success = False
                if resp.status_code == 200:
                    try:
                        resp_data = resp.json()
                        is_success = resp_data.get("err_code") == 0
                    except Exception:
                        is_success = False
                if not is_success:
                    logger.warning(
                        f"Reply failed for {guest_name} (id={guest_id}): "
                        f"status={resp.status_code} body={resp.text[:500]}"
                    )
                return {
                    "success": is_success,
                    "status_code": resp.status_code,
                    "response": resp.text,
                    "guest": guest_name,
                    "reply": reply_text,
                }
        except Exception as e:
            logger.error(f"Send reply error: {e}")
            return {"success": False, "error": str(e)}

    async def auto_reply_comments(
        self,
        nick_live_id: int,
        live_session_id: int,
        comments: list[dict[str, Any]],
        reply_text: str,
    ) -> list[dict[str, Any]]:
        """Auto reply to a list of comments."""
        results = []
        for comment in comments:
            username = (
                comment.get("username")
                or comment.get("userName")
                or comment.get("nick_name")
                or comment.get("nickname")
                or "Unknown"
            )
            user_id = comment.get("streamerId") or comment.get("userId") or 0

            result = await self.send_reply(
                nick_live_id, live_session_id, username, user_id, reply_text
            )
            results.append(result)

        return results


# Singleton instance
moderator = ShopeeLiveModerator()
