# backend/app/services/settings_service.py
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.settings import AppSetting, AutoPostTemplate, NickLiveSetting, ReplyTemplate

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, db: Session, user_id: int | None = None) -> None:
        self._db = db
        self._user_id = user_id

    # --- App settings (key-value) ---

    def get_setting(self, key: str) -> str | None:
        q = self._db.query(AppSetting).filter(AppSetting.key == key)
        if self._user_id is not None:
            q = q.filter(AppSetting.user_id == self._user_id)
        row = q.first()
        return row.value if row else None

    def set_setting(self, key: str, value: str) -> None:
        q = self._db.query(AppSetting).filter(AppSetting.key == key)
        if self._user_id is not None:
            q = q.filter(AppSetting.user_id == self._user_id)
        row = q.first()
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value, user_id=self._user_id)
            self._db.add(row)
        self._db.commit()

    def get_openai_config(self) -> dict[str, Any]:
        api_key = self.get_setting("openai_api_key")
        model = self.get_setting("openai_model")
        return {
            "api_key_set": bool(api_key),
            "model": model,
        }

    def get_openai_api_key(self) -> str | None:
        return self.get_setting("openai_api_key")

    def get_system_prompt(self) -> str:
        return self.get_setting("ai_system_prompt") or ""

    # --- Reply templates ---

    def get_reply_templates(self) -> list[ReplyTemplate]:
        q = self._db.query(ReplyTemplate).filter(ReplyTemplate.nick_live_id.is_(None))
        if self._user_id is not None:
            q = q.filter(ReplyTemplate.user_id == self._user_id)
        return q.order_by(ReplyTemplate.created_at).all()

    def create_reply_template(self, content: str) -> ReplyTemplate:
        tmpl = ReplyTemplate(content=content, user_id=self._user_id)
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_reply_template(self, template_id: int) -> bool:
        q = self._db.query(ReplyTemplate).filter(ReplyTemplate.id == template_id)
        if self._user_id is not None:
            q = q.filter(ReplyTemplate.user_id == self._user_id)
        tmpl = q.first()
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Auto-post templates ---

    def get_auto_post_templates(self) -> list[AutoPostTemplate]:
        q = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.nick_live_id.is_(None))
        if self._user_id is not None:
            q = q.filter(AutoPostTemplate.user_id == self._user_id)
        return q.order_by(AutoPostTemplate.created_at).all()

    def create_auto_post_template(
        self, content: str, min_interval: int = 60, max_interval: int = 300
    ) -> AutoPostTemplate:
        tmpl = AutoPostTemplate(
            content=content,
            min_interval_seconds=min_interval,
            max_interval_seconds=max_interval,
            user_id=self._user_id,
        )
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def update_auto_post_template(
        self,
        template_id: int,
        content: str | None = None,
        min_interval: int | None = None,
        max_interval: int | None = None,
    ) -> AutoPostTemplate | None:
        q = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.id == template_id)
        if self._user_id is not None:
            q = q.filter(AutoPostTemplate.user_id == self._user_id)
        tmpl = q.first()
        if not tmpl:
            return None
        if content is not None:
            tmpl.content = content
        if min_interval is not None:
            tmpl.min_interval_seconds = min_interval
        if max_interval is not None:
            tmpl.max_interval_seconds = max_interval
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_auto_post_template(self, template_id: int) -> bool:
        q = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.id == template_id)
        if self._user_id is not None:
            q = q.filter(AutoPostTemplate.user_id == self._user_id)
        tmpl = q.first()
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Nick live settings ---

    def get_or_create_nick_settings(self, nick_live_id: int) -> NickLiveSetting:
        row = self._db.query(NickLiveSetting).filter(
            NickLiveSetting.nick_live_id == nick_live_id
        ).first()
        if not row:
            row = NickLiveSetting(nick_live_id=nick_live_id)
            self._db.add(row)
            self._db.commit()
            self._db.refresh(row)
        return row

    # --- Per-nick reply templates ---

    def get_reply_templates_for_nick(self, nick_live_id: int) -> list[ReplyTemplate]:
        return (
            self._db.query(ReplyTemplate)
            .filter(ReplyTemplate.nick_live_id == nick_live_id)
            .order_by(ReplyTemplate.created_at)
            .all()
        )

    def create_reply_template_for_nick(self, nick_live_id: int, content: str) -> ReplyTemplate:
        tmpl = ReplyTemplate(content=content, nick_live_id=nick_live_id)
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_reply_template_for_nick(self, nick_live_id: int, template_id: int) -> bool:
        tmpl = (
            self._db.query(ReplyTemplate)
            .filter(ReplyTemplate.id == template_id, ReplyTemplate.nick_live_id == nick_live_id)
            .first()
        )
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Per-nick auto-post templates ---

    def get_auto_post_templates_for_nick(self, nick_live_id: int) -> list[AutoPostTemplate]:
        return (
            self._db.query(AutoPostTemplate)
            .filter(AutoPostTemplate.nick_live_id == nick_live_id)
            .order_by(AutoPostTemplate.created_at)
            .all()
        )

    def create_auto_post_template_for_nick(
        self,
        nick_live_id: int,
        content: str,
        min_interval: int = 60,
        max_interval: int = 300,
    ) -> AutoPostTemplate:
        tmpl = AutoPostTemplate(
            content=content,
            min_interval_seconds=min_interval,
            max_interval_seconds=max_interval,
            nick_live_id=nick_live_id,
        )
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_auto_post_template_for_nick(self, nick_live_id: int, template_id: int) -> bool:
        tmpl = (
            self._db.query(AutoPostTemplate)
            .filter(AutoPostTemplate.id == template_id, AutoPostTemplate.nick_live_id == nick_live_id)
            .first()
        )
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    def update_nick_settings(
        self,
        nick_live_id: int,
        *,
        reply_mode: str | None = None,
        reply_to_host: bool | None = None,
        reply_to_moderator: bool | None = None,
        auto_post_enabled: bool | None = None,
        auto_post_to_host: bool | None = None,
        auto_post_to_moderator: bool | None = None,
        host_proxy: str | None = None,
        auto_pin_enabled: bool | None = None,
        pin_min_interval_minutes: int | None = None,
        pin_max_interval_minutes: int | None = None,
    ) -> NickLiveSetting:
        # Local imports to avoid cycles.
        from app.models.knowledge_product import KnowledgeProduct

        row = self.get_or_create_nick_settings(nick_live_id)

        # --- Validate reply_mode ---
        if reply_mode is not None:
            if reply_mode not in ("none", "knowledge", "ai", "template"):
                raise ValueError(f"invalid reply_mode: {reply_mode}")
            if reply_mode == "knowledge":
                n = (
                    self._db.query(KnowledgeProduct)
                    .filter(KnowledgeProduct.nick_live_id == nick_live_id)
                    .count()
                )
                if n == 0:
                    raise ValueError("Cần import sản phẩm trước khi bật Knowledge AI")
            elif reply_mode == "template":
                n = (
                    self._db.query(ReplyTemplate)
                    .filter(ReplyTemplate.nick_live_id == nick_live_id)
                    .count()
                )
                if n == 0:
                    raise ValueError("Cần tạo template reply trước khi bật chế độ Template")
            elif reply_mode == "ai":
                if not self.get_openai_api_key():
                    raise ValueError("Cần cấu hình OpenAI API key trước")
            row.reply_mode = reply_mode

        # --- Validate channel toggles (only when turning ON) ---
        if reply_to_host is True and not row.host_config:
            raise ValueError("Cần Get Credentials cho host trước khi bật Reply Host")
        if reply_to_moderator is True and not row.moderator_config:
            raise ValueError("Cần cấu hình cURL moderator trước khi bật Reply Moderator")
        if auto_post_to_host is True and not row.host_config:
            raise ValueError("Cần Get Credentials cho host trước khi bật Auto Post Host")
        if auto_post_to_moderator is True and not row.moderator_config:
            raise ValueError("Cần cấu hình cURL moderator trước khi bật Auto Post Moderator")

        # --- Validate auto_post_enabled ---
        if auto_post_enabled is True:
            n = (
                self._db.query(AutoPostTemplate)
                .filter(AutoPostTemplate.nick_live_id == nick_live_id)
                .count()
            )
            if n == 0:
                raise ValueError("Cần tạo template auto-post trước khi bật")

        # --- Apply updates ---
        if reply_to_host is not None:
            row.reply_to_host = reply_to_host
        if reply_to_moderator is not None:
            row.reply_to_moderator = reply_to_moderator
        if auto_post_enabled is not None:
            row.auto_post_enabled = auto_post_enabled
        if auto_post_to_host is not None:
            row.auto_post_to_host = auto_post_to_host
        if auto_post_to_moderator is not None:
            row.auto_post_to_moderator = auto_post_to_moderator
        if host_proxy is not None:
            row.host_proxy = host_proxy

        if auto_pin_enabled is not None:
            row.auto_pin_enabled = auto_pin_enabled
        if pin_min_interval_minutes is not None:
            row.pin_min_interval_minutes = pin_min_interval_minutes
        if pin_max_interval_minutes is not None:
            row.pin_max_interval_minutes = pin_max_interval_minutes

        # Cross-field invariant guard.
        if row.pin_min_interval_minutes > row.pin_max_interval_minutes:
            raise ValueError("pin_min_interval_minutes phải <= pin_max_interval_minutes")

        self._db.commit()
        self._db.refresh(row)
        return row

    # --- Knowledge AI config ---

    def get_knowledge_system_prompt(self) -> str:
        return self.get_setting("knowledge_system_prompt") or ""

    def get_knowledge_model(self) -> str | None:
        return self.get_setting("knowledge_model")

    # --- Banned words ---

    def get_banned_words(self) -> list[str]:
        raw = self.get_setting("banned_words")
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_banned_words(self, words: list[str]) -> None:
        self.set_setting("banned_words", json.dumps(words, ensure_ascii=False))

    # --- Host config helpers ---

    def save_host_config(self, nick_live_id: int, usersig: str, uuid: str) -> NickLiveSetting:
        row = self.get_or_create_nick_settings(nick_live_id)
        row.host_config = json.dumps({"usersig": usersig, "uuid": uuid})
        self._db.commit()
        self._db.refresh(row)
        return row

    def get_host_config(self, nick_live_id: int) -> dict | None:
        row = self.get_or_create_nick_settings(nick_live_id)
        if not row.host_config:
            return None
        try:
            return json.loads(row.host_config)
        except (json.JSONDecodeError, TypeError):
            return None
