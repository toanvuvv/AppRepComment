# backend/app/services/settings_service.py
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.settings import AppSetting, AutoPostTemplate, NickLiveSetting, ReplyTemplate

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # --- App settings (key-value) ---

    def get_setting(self, key: str) -> str | None:
        row = self._db.query(AppSetting).filter(AppSetting.key == key).first()
        return row.value if row else None

    def set_setting(self, key: str, value: str) -> None:
        row = self._db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value)
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
        return self._db.query(ReplyTemplate).order_by(ReplyTemplate.created_at).all()

    def create_reply_template(self, content: str) -> ReplyTemplate:
        tmpl = ReplyTemplate(content=content)
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_reply_template(self, template_id: int) -> bool:
        tmpl = self._db.query(ReplyTemplate).filter(ReplyTemplate.id == template_id).first()
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Auto-post templates ---

    def get_auto_post_templates(self) -> list[AutoPostTemplate]:
        return self._db.query(AutoPostTemplate).order_by(AutoPostTemplate.created_at).all()

    def create_auto_post_template(
        self, content: str, min_interval: int = 60, max_interval: int = 300
    ) -> AutoPostTemplate:
        tmpl = AutoPostTemplate(
            content=content,
            min_interval_seconds=min_interval,
            max_interval_seconds=max_interval,
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
        tmpl = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.id == template_id).first()
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
        tmpl = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.id == template_id).first()
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

    def update_nick_settings(
        self,
        nick_live_id: int,
        ai_reply_enabled: bool | None = None,
        auto_reply_enabled: bool | None = None,
        auto_post_enabled: bool | None = None,
    ) -> NickLiveSetting:
        row = self.get_or_create_nick_settings(nick_live_id)
        if ai_reply_enabled is not None:
            row.ai_reply_enabled = ai_reply_enabled
        if auto_reply_enabled is not None:
            row.auto_reply_enabled = auto_reply_enabled
        if auto_post_enabled is not None:
            row.auto_post_enabled = auto_post_enabled
        self._db.commit()
        self._db.refresh(row)
        return row
