import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.database import SessionLocal
from app.models.settings import NickLiveSetting

logger = logging.getLogger(__name__)

# The only host we will send requests to.
_REQUIRED_HOST = "live.shopee.vn"

# Headers managed by httpx — must not be forwarded from cURL.
_SKIP_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})


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
        r"""--data-raw\s+'(.*?)'""",
        r"""--data-raw\s+"(.*?)" """,
        r"""--data\s+'(.*?)'""",
        r"""--data\s+"(.*?)" """,
        r"""-d\s+'(.*?)'""",
        r"""-d\s+"(.*?)" """,
    ]:
        body_match = re.search(pattern, curl_text, re.DOTALL)
        if body_match:
            body = body_match.group(1)
            break

    return session_id, headers, body


class ShopeeLiveModerator:
    """Manages moderator configs per nick_live and sends replies to live comments.

    Configs are persisted to database (NickLiveSetting.moderator_config)
    and cached in-memory for fast access at runtime.
    """

    def __init__(self) -> None:
        self._configs: dict[int, dict[str, Any]] = {}

    def load_all_from_db(self) -> None:
        """Load all saved moderator configs from database into memory cache."""
        db = SessionLocal()
        try:
            rows = db.query(NickLiveSetting).filter(
                NickLiveSetting.moderator_config.isnot(None)
            ).all()
            for row in rows:
                if not row.moderator_config:
                    continue
                try:
                    config = json.loads(row.moderator_config)
                    self._configs[row.nick_live_id] = config
                    logger.info(f"Loaded moderator config for nick_live_id={row.nick_live_id}")
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Invalid moderator config for nick_live_id={row.nick_live_id}")
            logger.info(f"Loaded {len(self._configs)} moderator config(s) from database")
        finally:
            db.close()

    def _persist_to_db(self, nick_live_id: int, config: dict[str, Any] | None) -> None:
        """Save or clear moderator config in database."""
        db = SessionLocal()
        try:
            row = db.query(NickLiveSetting).filter(
                NickLiveSetting.nick_live_id == nick_live_id
            ).first()
            if not row:
                row = NickLiveSetting(nick_live_id=nick_live_id)
                db.add(row)
            row.moderator_config = json.dumps(config, ensure_ascii=False) if config else None
            db.commit()
        finally:
            db.close()

    def save_curl(self, nick_live_id: int, curl_text: str) -> dict[str, Any]:
        """Parse cURL and save as template for this nick_live.

        The session_id in the cURL URL is ignored - the actual live
        session_id is provided at send time.
        """
        _session_id, headers, body = parse_curl_command(curl_text)

        # Validate that the cURL targets the expected host.
        url_match = re.search(r"['\"]?(https?://[^\s'\"]+)['\"]?", curl_text)
        if url_match:
            parsed = urlparse(url_match.group(1))
            if parsed.hostname != _REQUIRED_HOST:
                return {"error": f"cURL URL must target {_REQUIRED_HOST}"}

        # Forward all headers except ones httpx manages internally.
        safe_headers = {
            k: v for k, v in headers.items() if k.lower() not in _SKIP_HEADERS
        }

        try:
            body_data = json.loads(body)
        except json.JSONDecodeError:
            body_data = {}

        config = {
            "headers": safe_headers,
            "host_id": safe_headers.get("X-Livestreaming-Moderator"),
            "usersig": body_data.get("usersig", ""),
            "uuid": body_data.get("uuid", ""),
        }

        # Save to memory cache and database
        self._configs[nick_live_id] = config
        self._persist_to_db(nick_live_id, config)

        return {
            "nick_live_id": nick_live_id,
            "host_id": safe_headers.get("X-Livestreaming-Moderator"),
            "status": "saved",
        }

    def get_config(self, nick_live_id: int) -> dict[str, Any] | None:
        return self._configs.get(nick_live_id)

    def has_config(self, nick_live_id: int) -> bool:
        return nick_live_id in self._configs

    def remove_config(self, nick_live_id: int) -> bool:
        removed = self._configs.pop(nick_live_id, None) is not None
        if removed:
            self._persist_to_db(nick_live_id, None)
        return removed

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

        inner_content = {
            "content": f"@{guest_name} {reply_text}",
            "content_v2": f"#{placeholder}# {reply_text}",
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

        url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"

        logger.debug(f"[reply] URL: {url}")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers=config["headers"],
                    json=body,
                    timeout=10.0,
                )
                is_success = False
                resp_data: dict = {}
                if resp.status_code == 200:
                    try:
                        resp_data = resp.json()
                        is_success = resp_data.get("err_code") == 0
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse reply response for {guest_name}")
                        is_success = False
                if not is_success:
                    logger.warning(
                        f"Reply failed for {guest_name} (id={guest_id}): "
                        f"status={resp.status_code} | "
                        f"response_headers={dict(resp.headers)} | "
                        f"response_body={resp.text[:500]}"
                    )
                # Return only success status — never leak raw upstream response.
                return {
                    "success": is_success,
                    "status_code": resp.status_code,
                    "guest": guest_name,
                    "reply": reply_text,
                }
        except Exception as e:
            logger.error(f"Send reply error: {e}")
            return {"success": False, "error": "Reply request failed"}

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
