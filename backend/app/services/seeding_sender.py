"""Send Shopee type-100 guest comments from a clone into a live session.

The session's host nick supplies uuid/usersig (from NickLiveSetting.host_config);
the clone supplies cookies. Enforces a global per-clone 10s rate floor and
writes one SeedingLog per attempt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.config import REPLY_TIMEOUT_SEC
from app.database import SessionLocal
from app.models.seeding import SeedingClone, SeedingLog
from app.models.settings import NickLiveSetting
from app.schemas.seeding import CloneRateLimitedError, HostConfigMissingError
from app.services.http_client import get_client
from app.services.rate_limiter import shopee_limiter

logger = logging.getLogger(__name__)

_SHOPEE_HOST = "live.shopee.vn"
CLONE_FLOOR_SEC = 10

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


class SeedingSender:
    async def send(
        self,
        *,
        clone_id: int,
        nick_live_id: int,
        shopee_session_id: int,
        content: str,
        template_id: int | None,
        mode: Literal["manual", "auto"],
        log_session_id: int,
    ) -> SeedingLog:
        clone = self._load_clone(clone_id)
        if clone is None:
            raise ValueError(f"clone {clone_id} not found")

        retry_after = self._floor_remaining_sec(clone.last_sent_at)
        if retry_after > 0:
            if mode == "manual":
                raise CloneRateLimitedError(retry_after)
            return self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="rate_limited",
                error=f"floor {retry_after}s",
            )

        try:
            creds = self._resolve_host_credentials(nick_live_id)
        except HostConfigMissingError:
            if mode == "manual":
                raise
            return self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="failed", error="host_config_missing",
            )

        body = self._build_body(content, creds)
        headers = self._build_headers(clone.cookies, shopee_session_id)
        url = f"https://{_SHOPEE_HOST}/api/v1/session/{shopee_session_id}/message"

        status, err = await self._post_with_retry(url, headers, body)

        if status == 200 and err is None:
            self._touch_clone_last_sent(clone_id)
            return self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="success", error=None,
            )

        if mode == "manual":
            self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="failed", error=err or f"http_{status}",
            )
            raise RuntimeError(err or f"http_{status}")

        return self._write_log(
            log_session_id=log_session_id, clone_id=clone_id,
            template_id=template_id, content=content,
            status="failed", error=err or f"http_{status}",
        )

    def _floor_remaining_sec(self, last_sent_at: datetime | None) -> int:
        if last_sent_at is None:
            return 0
        if last_sent_at.tzinfo is None:
            last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_sent_at
        remaining = CLONE_FLOOR_SEC - int(delta.total_seconds())
        return max(0, remaining)

    def _load_clone(self, clone_id: int) -> SeedingClone | None:
        with SessionLocal() as db:
            return db.query(SeedingClone).filter(
                SeedingClone.id == clone_id
            ).first()

    def _resolve_host_credentials(self, nick_live_id: int) -> dict[str, str]:
        with SessionLocal() as db:
            row = db.query(NickLiveSetting).filter(
                NickLiveSetting.nick_live_id == nick_live_id
            ).first()
            if row is None or not row.host_config:
                raise HostConfigMissingError()
            try:
                data = json.loads(row.host_config)
            except (json.JSONDecodeError, TypeError) as e:
                raise HostConfigMissingError() from e
        uuid = data.get("uuid")
        usersig = data.get("usersig")
        if not uuid or not usersig:
            raise HostConfigMissingError()
        return {"uuid": uuid, "usersig": usersig}

    def _build_body(self, content: str, creds: dict[str, str]) -> dict[str, Any]:
        inner = {"type": 100, "content": content}
        return {
            "content": json.dumps(inner, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": creds["usersig"],
            "uuid": creds["uuid"],
        }

    def _build_headers(self, cookies: str, shopee_session_id: int) -> dict[str, str]:
        h = dict(_HOST_HEADERS)
        h["cookie"] = cookies
        h["referer"] = f"https://live.shopee.vn/pc/live?session={shopee_session_id}"
        return h

    async def _post_with_retry(
        self, url: str, headers: dict[str, str], body: dict[str, Any],
    ) -> tuple[int, str | None]:
        attempts = 0
        max_attempts = 2
        last_status = 0
        last_err: str | None = None
        while attempts < max_attempts:
            attempts += 1
            try:
                await shopee_limiter.acquire()
                client = get_client()
                resp = await client.post(
                    url, headers=headers, json=body, timeout=REPLY_TIMEOUT_SEC,
                )
                last_status = resp.status_code
                if last_status in (401, 403):
                    return last_status, "auth_expired"
                if last_status == 429 and attempts < max_attempts:
                    await asyncio.sleep(2.0)
                    continue
                if last_status == 200:
                    try:
                        if resp.json().get("err_code") == 0:
                            return 200, None
                    except json.JSONDecodeError:
                        pass
                return last_status, f"upstream_{last_status}"
            except Exception as e:
                last_err = str(e)[:200]
                logger.exception(f"seeding send error: {e}")
                return 0, "request_failed"
        return last_status, last_err or "rate_limited"

    def _touch_clone_last_sent(self, clone_id: int) -> None:
        with SessionLocal() as db:
            row = db.query(SeedingClone).filter(
                SeedingClone.id == clone_id
            ).first()
            if row is not None:
                row.last_sent_at = datetime.now(timezone.utc)
                db.commit()

    def _write_log(
        self, *, log_session_id: int, clone_id: int, template_id: int | None,
        content: str, status: str, error: str | None,
    ) -> SeedingLog:
        with SessionLocal() as db:
            row = SeedingLog(
                seeding_log_session_id=log_session_id,
                clone_id=clone_id,
                template_id=template_id,
                content=content,
                status=status,
                error=error,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row


seeding_sender = SeedingSender()
