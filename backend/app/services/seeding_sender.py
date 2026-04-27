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
from app.services.http_client import get_client_for_proxy
from app.services.rate_limiter import shopee_limiter

logger = logging.getLogger(__name__)

_SHOPEE_HOST = "live.shopee.vn"
CLONE_FLOOR_SEC = 10
REQUIRE_PROXY_SETTING_KEY = "seeding.require_proxy"
# Auto-disable a clone after this many consecutive failed sends (auto mode).
AUTO_DISABLE_THRESHOLD = 5

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
        clone = await self._load_clone(clone_id)
        if clone is None:
            raise ValueError(f"clone {clone_id} not found")

        clone_name = getattr(clone, "name", f"clone#{clone_id}")

        retry_after = self._floor_remaining_sec(clone.last_sent_at)
        if retry_after > 0:
            if mode == "manual":
                raise CloneRateLimitedError(retry_after)
            logger.info(
                "seeding rate_limited clone_id=%s name=%s retry_after=%ss",
                clone_id, clone_name, retry_after,
            )
            return await self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="rate_limited",
                error=f"floor {retry_after}s",
            )

        require_proxy = await self._get_require_proxy(clone.user_id)
        if require_proxy and not clone.proxy:
            logger.warning(
                "seeding skipped clone_id=%s name=%s reason=no_proxy",
                clone_id, clone_name,
            )
            await self._record_failure(clone_id, "no_proxy")
            log_row = await self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="failed", error="no_proxy",
            )
            if mode == "manual":
                raise RuntimeError("no_proxy")
            return log_row

        try:
            creds = await self._resolve_host_credentials(nick_live_id)
        except HostConfigMissingError:
            if mode == "manual":
                raise
            logger.warning(
                "seeding failed clone_id=%s name=%s error=host_config_missing",
                clone_id, clone_name,
            )
            await self._record_failure(clone_id, "host_config_missing")
            return await self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="failed", error="host_config_missing",
            )

        body = self._build_body(content, creds)
        headers = self._build_headers(clone.cookies, shopee_session_id)
        url = f"https://{_SHOPEE_HOST}/api/v1/session/{shopee_session_id}/message"

        status, err = await self._post_with_retry(
            url, headers, body, proxy_url=clone.proxy,
        )

        if status == 200 and err is None:
            await self._touch_clone_last_sent(clone_id)
            logger.info(
                "seeding success clone_id=%s name=%s mode=%s",
                clone_id, clone_name, mode,
            )
            return await self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="success", error=None,
            )

        error_msg = err or f"http_{status}"
        logger.warning(
            "seeding failed clone_id=%s name=%s mode=%s status=%s error=%s",
            clone_id, clone_name, mode, status, error_msg,
        )
        await self._record_failure(clone_id, error_msg)

        if mode == "manual":
            await self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="failed", error=error_msg,
            )
            raise RuntimeError(error_msg)

        return await self._write_log(
            log_session_id=log_session_id, clone_id=clone_id,
            template_id=template_id, content=content,
            status="failed", error=error_msg,
        )

    def _floor_remaining_sec(self, last_sent_at: datetime | None) -> int:
        if last_sent_at is None:
            return 0
        if last_sent_at.tzinfo is None:
            last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_sent_at
        remaining = CLONE_FLOOR_SEC - int(delta.total_seconds())
        return max(0, remaining)

    # --- async wrappers (Fix 1: offload sync DB calls via asyncio.to_thread) ---

    async def _load_clone(self, clone_id: int) -> SeedingClone | None:
        return await asyncio.to_thread(self._load_clone_sync, clone_id)

    async def _get_require_proxy(self, user_id: int) -> bool:
        return await asyncio.to_thread(
            self._get_require_proxy_sync, user_id,
        )

    def _get_require_proxy_sync(self, user_id: int) -> bool:
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            svc = SettingsService(db, user_id=user_id)
            value = svc.get_setting(REQUIRE_PROXY_SETTING_KEY)
            return value == "true"

    async def _resolve_host_credentials(self, nick_live_id: int) -> dict[str, str]:
        return await asyncio.to_thread(self._resolve_host_credentials_sync, nick_live_id)

    async def _touch_clone_last_sent(self, clone_id: int) -> None:
        await asyncio.to_thread(self._touch_clone_last_sent_sync, clone_id)

    async def _record_failure(self, clone_id: int, error: str) -> None:
        await asyncio.to_thread(self._record_failure_sync, clone_id, error)

    async def _write_log(
        self, *, log_session_id: int, clone_id: int, template_id: int | None,
        content: str, status: str, error: str | None,
    ) -> SeedingLog:
        return await asyncio.to_thread(
            self._write_log_sync,
            log_session_id=log_session_id,
            clone_id=clone_id,
            template_id=template_id,
            content=content,
            status=status,
            error=error,
        )

    # --- sync DB helpers (called only via asyncio.to_thread) ---

    def _load_clone_sync(self, clone_id: int) -> SeedingClone | None:
        with SessionLocal() as db:
            return db.query(SeedingClone).filter(
                SeedingClone.id == clone_id
            ).first()

    def _resolve_host_credentials_sync(self, nick_live_id: int) -> dict[str, str]:
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

    def _touch_clone_last_sent_sync(self, clone_id: int) -> None:
        with SessionLocal() as db:
            row = db.query(SeedingClone).filter(
                SeedingClone.id == clone_id
            ).first()
            if row is not None:
                row.last_sent_at = datetime.now(timezone.utc)
                row.consecutive_failures = 0
                row.last_status = "success"
                row.last_error = None
                db.commit()

    def _record_failure_sync(self, clone_id: int, error: str) -> None:
        with SessionLocal() as db:
            row = db.query(SeedingClone).filter(
                SeedingClone.id == clone_id
            ).first()
            if row is None:
                return
            row.consecutive_failures = (row.consecutive_failures or 0) + 1
            row.last_status = "failed"
            row.last_error = error
            if row.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
                if not row.auto_disabled:
                    logger.warning(
                        "seeding auto-disabled clone_id=%s name=%s after "
                        "%s consecutive failures (last_error=%s)",
                        clone_id, row.name, row.consecutive_failures, error,
                    )
                row.auto_disabled = True
            db.commit()

    def _write_log_sync(
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
        proxy_url: str | None,
    ) -> tuple[int, str | None]:
        last_status = 0
        last_err: str | None = None
        for attempt in range(1, 3):  # attempts 1 and 2
            try:
                await shopee_limiter.acquire()
                client = get_client_for_proxy(proxy_url)
                resp = await client.post(
                    url, headers=headers, json=body, timeout=REPLY_TIMEOUT_SEC,
                )
                last_status = resp.status_code
                if last_status in (401, 403):
                    return last_status, "auth_expired"
                if last_status == 429 and attempt < 2:
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
                last_err = type(e).__name__
                logger.error(
                    "seeding send error (attempt %d): %s",
                    attempt, type(e).__name__,
                )
                if attempt < 2:
                    await asyncio.sleep(0.5)
                    continue
                return 0, last_err or "request_failed"
        return last_status, last_err or "rate_limited"


seeding_sender = SeedingSender()
