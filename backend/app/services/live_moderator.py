import asyncio
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.config import REPLY_TIMEOUT_SEC
from app.database import SessionLocal
from app.models.settings import NickLiveSetting
from app.services.http_client import get_client
from app.services.rate_limiter import shopee_limiter

logger = logging.getLogger(__name__)

# The only host we will send requests to.
_REQUIRED_HOST = "live.shopee.vn"

# Headers managed by httpx — must not be forwarded from cURL.
_SKIP_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})

# Allow-list of response headers safe to log (never log cookies or auth tokens).
_SAFE_LOG_HEADERS = frozenset({"content-type", "content-length", "x-request-id", "date"})

_HOST_HEADERS: dict[str, str] = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5",
    "content-type": "application/json",
    "origin": "https://live.shopee.vn",
    "priority": "u=1, i",
    "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    "x-sz-sdk-version": "1.12.27",
}


def _safe_headers(headers: Any) -> dict[str, str]:
    """Return only allow-listed headers for safe logging."""
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {k: v for k, v in items if k.lower() in _SAFE_LOG_HEADERS}


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
        self._host_configs: dict[int, dict[str, Any]] = {}

    def load_all_from_db(self) -> None:
        """Load all saved moderator and host configs from database into memory cache."""
        db = SessionLocal()
        try:
            rows = db.query(NickLiveSetting).filter(
                (NickLiveSetting.moderator_config.isnot(None))
                | (NickLiveSetting.host_config.isnot(None))
            ).all()
            for row in rows:
                if row.moderator_config:
                    try:
                        config = json.loads(row.moderator_config)
                        self._configs[row.nick_live_id] = config
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid moderator config for nick={row.nick_live_id}")
                if row.host_config:
                    try:
                        config = json.loads(row.host_config)
                        self._host_configs[row.nick_live_id] = config
                        logger.info(f"Loaded host config for nick={row.nick_live_id}")
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid host config for nick={row.nick_live_id}")
            logger.info(
                f"Loaded {len(self._configs)} moderator + "
                f"{len(self._host_configs)} host config(s)"
            )
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

    def save_host_config(self, nick_live_id: int, usersig: str, uuid: str) -> None:
        config = {"usersig": usersig, "uuid": uuid}
        self._host_configs[nick_live_id] = config
        self._persist_host_to_db(nick_live_id, config)

    def get_host_config(self, nick_live_id: int) -> dict[str, Any] | None:
        return self._host_configs.get(nick_live_id)

    def has_host_config(self, nick_live_id: int) -> bool:
        return nick_live_id in self._host_configs

    def _persist_host_to_db(self, nick_live_id: int, config: dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            row = db.query(NickLiveSetting).filter(
                NickLiveSetting.nick_live_id == nick_live_id
            ).first()
            if not row:
                row = NickLiveSetting(nick_live_id=nick_live_id)
                db.add(row)
            row.host_config = json.dumps(config, ensure_ascii=False)
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
        safe_headers_out = {
            k: v for k, v in headers.items() if k.lower() not in _SKIP_HEADERS
        }

        try:
            body_data = json.loads(body)
        except json.JSONDecodeError:
            body_data = {}

        # usersig is required for authenticated replies; a stub/empty value
        # means the cURL template is unusable.
        if len(body_data.get("usersig", "")) < 32:
            return {"error": "Invalid or missing usersig in cURL"}

        config = {
            "headers": safe_headers_out,
            "host_id": safe_headers_out.get("X-Livestreaming-Moderator"),
            "usersig": body_data.get("usersig", ""),
            "uuid": body_data.get("uuid", ""),
        }

        # Save to memory cache and database
        self._configs[nick_live_id] = config
        self._persist_to_db(nick_live_id, config)

        return {
            "nick_live_id": nick_live_id,
            "host_id": safe_headers_out.get("X-Livestreaming-Moderator"),
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

    def generate_moderator_reply_body(
        self,
        nick_live_id: int,
        guest_name: str,
        guest_id: int,
        reply_text: str,
    ) -> dict[str, Any] | None:
        """Build the request body for moderator-channel reply (type 102) with @mention."""
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

    def generate_moderator_post_body(
        self, nick_live_id: int, content: str
    ) -> dict[str, Any] | None:
        """Build moderator-channel plain post body (type 102, no placeholders)."""
        config = self._configs.get(nick_live_id)
        if not config:
            return None

        inner_content = {"type": 102, "content": content}
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
        """Send reply. URL is built from live_session_id, headers from saved config.

        Maps upstream status codes:
          - 401/403 -> returns {"success": False, "error": "auth_expired"} (no raise)
          - 429     -> sleeps 2s and retries once before giving up
          - other failures -> {"success": False, ...}
        """
        config = self._configs.get(nick_live_id)
        if not config:
            return {"success": False, "error": "Moderator not configured"}

        body = self.generate_moderator_reply_body(nick_live_id, guest_name, guest_id, reply_text)
        if not body:
            return {"success": False, "error": "Failed to generate reply body"}

        url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"

        logger.debug(f"[reply] URL: {url}")

        attempts = 0
        max_attempts = 2  # initial + one 429 retry
        while attempts < max_attempts:
            attempts += 1
            try:
                await shopee_limiter.acquire()
                client = get_client()
                resp = await client.post(
                    url,
                    headers=config["headers"],
                    json=body,
                    timeout=REPLY_TIMEOUT_SEC,
                )

                status = resp.status_code

                # Auth expired — surface without raising so caller can keep going.
                if status in (401, 403):
                    logger.warning(
                        f"Reply auth rejected for {guest_name} (id={guest_id}): "
                        f"status={status} | "
                        f"response_headers={_safe_headers(resp.headers)}"
                    )
                    return {
                        "success": False,
                        "status_code": status,
                        "error": "auth_expired",
                        "guest": guest_name,
                        "reply": reply_text,
                    }

                # Rate limited — back off briefly and retry once.
                if status == 429 and attempts < max_attempts:
                    logger.warning(
                        f"Reply rate limited for {guest_name}; sleeping 2s before retry"
                    )
                    await asyncio.sleep(2.0)
                    continue

                is_success = False
                if status == 200:
                    try:
                        resp_data = resp.json()
                        is_success = resp_data.get("err_code") == 0
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse reply response for {guest_name}")
                        is_success = False

                if not is_success:
                    logger.warning(
                        f"Reply failed for {guest_name} (id={guest_id}): "
                        f"status={status} | "
                        f"response_headers={_safe_headers(resp.headers)} | "
                        f"response_body={resp.text[:500]}"
                    )
                # Return only success status — never leak raw upstream response.
                return {
                    "success": is_success,
                    "status_code": status,
                    "guest": guest_name,
                    "reply": reply_text,
                }
            except Exception as e:
                logger.error(f"Send reply error: {e}")
                return {"success": False, "error": "Reply request failed"}

        # Exhausted retries (e.g. 429 both times).
        return {
            "success": False,
            "error": "rate_limited",
            "guest": guest_name,
            "reply": reply_text,
        }

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

    def generate_host_post_body(
        self, nick_live_id: int, content: str
    ) -> dict[str, Any] | None:
        """Build type-101 host-channel post body. Uses host_config credentials."""
        config = self._host_configs.get(nick_live_id)
        if not config:
            return None

        inner_content = {"type": 101, "content": content}
        return {
            "content": json.dumps(inner_content, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": config["usersig"],
            "uuid": config["uuid"],
            "pin": False,
        }

    def generate_host_reply_body(
        self, nick_live_id: int, guest_name: str, guest_id: int | str, reply_text: str,
    ) -> dict[str, Any] | None:
        """Build type-101 host reply body. Host channel always uses type 101."""
        config = self._host_configs.get(nick_live_id)
        if not config:
            return None
        inner_content = {"type": 101, "content": f"@{guest_name} {reply_text}"}
        return {
            "content": json.dumps(inner_content, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": config["usersig"],
            "uuid": config["uuid"],
            "pin": False,
        }

    async def send_host_message(
        self, nick_live_id: int, live_session_id: int, body: dict[str, Any], cookies: str,
    ) -> dict[str, Any]:
        headers = {**_HOST_HEADERS}
        headers["referer"] = f"https://live.shopee.vn/pc/live?session={live_session_id}"
        headers["cookie"] = cookies
        url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"

        print(f"[HOST-DEBUG] url={url}")
        print(f"[HOST-DEBUG] body={json.dumps(body, ensure_ascii=False)[:2000]}")
        attempts = 0
        max_attempts = 2
        while attempts < max_attempts:
            attempts += 1
            try:
                await shopee_limiter.acquire()
                client = get_client()
                resp = await client.post(url, headers=headers, json=body, timeout=REPLY_TIMEOUT_SEC)
                status = resp.status_code
                if status in (401, 403):
                    return {"success": False, "status_code": status, "error": "auth_expired"}
                if status == 429 and attempts < max_attempts:
                    await asyncio.sleep(2.0)
                    continue
                is_success = False
                if status == 200:
                    try:
                        is_success = resp.json().get("err_code") == 0
                    except json.JSONDecodeError:
                        pass
                if not is_success:
                    logger.warning(f"Host message failed: status={status} | body={resp.text[:500]}")
                return {"success": is_success, "status_code": status}
            except Exception as e:
                logger.error(f"Host message error: {e}")
                return {"success": False, "error": "request_failed"}
        return {"success": False, "error": "rate_limited"}

    async def send_moderator_message(
        self, nick_live_id: int, live_session_id: int, body: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a pre-built body via moderator credentials."""
        config = self._configs.get(nick_live_id)
        if not config:
            return {"success": False, "error": "Moderator not configured"}
        url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"
        attempts = 0
        max_attempts = 2
        while attempts < max_attempts:
            attempts += 1
            try:
                await shopee_limiter.acquire()
                client = get_client()
                resp = await client.post(url, headers=config["headers"], json=body, timeout=REPLY_TIMEOUT_SEC)
                status = resp.status_code
                if status in (401, 403):
                    return {"success": False, "status_code": status, "error": "auth_expired"}
                if status == 429 and attempts < max_attempts:
                    await asyncio.sleep(2.0)
                    continue
                is_success = False
                if status == 200:
                    try:
                        is_success = resp.json().get("err_code") == 0
                    except json.JSONDecodeError:
                        pass
                return {"success": is_success, "status_code": status}
            except Exception as e:
                logger.error(f"send_moderator_message error: {e}")
                return {"success": False, "error": "request_failed"}
        return {"success": False, "error": "rate_limited"}


# Singleton instance
moderator = ShopeeLiveModerator()
