# backend/app/services/settings_service.py
import json
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
        ai_reply_enabled: bool | None = None,
        auto_reply_enabled: bool | None = None,
        auto_post_enabled: bool | None = None,
        knowledge_reply_enabled: bool | None = None,
        host_reply_enabled: bool | None = None,
        host_auto_post_enabled: bool | None = None,
        host_proxy: str | None = None,
    ) -> NickLiveSetting:
        row = self.get_or_create_nick_settings(nick_live_id)

        # Mutual exclusion: only one of ai_reply / knowledge_reply can be active
        if knowledge_reply_enabled is True:
            row.knowledge_reply_enabled = True
            row.ai_reply_enabled = False
        elif ai_reply_enabled is True:
            row.ai_reply_enabled = True
            row.knowledge_reply_enabled = False
        else:
            if ai_reply_enabled is not None:
                row.ai_reply_enabled = ai_reply_enabled
            if knowledge_reply_enabled is not None:
                row.knowledge_reply_enabled = knowledge_reply_enabled

        if auto_reply_enabled is not None:
            row.auto_reply_enabled = auto_reply_enabled
        if auto_post_enabled is not None:
            row.auto_post_enabled = auto_post_enabled

        if host_reply_enabled is not None:
            row.host_reply_enabled = host_reply_enabled
        if host_auto_post_enabled is not None:
            row.host_auto_post_enabled = host_auto_post_enabled
        if host_proxy is not None:
            row.host_proxy = host_proxy

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
