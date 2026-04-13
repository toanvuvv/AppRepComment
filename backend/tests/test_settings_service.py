# backend/tests/test_settings_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.settings import AppSetting, ReplyTemplate, AutoPostTemplate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Import all models
    from app.models import nick_live  # noqa
    from app.models import settings  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_set_and_get_setting(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", "sk-test")
    assert svc.get_setting("openai_api_key") == "sk-test"


def test_get_setting_missing_returns_none(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    assert svc.get_setting("nonexistent") is None


def test_get_openai_config_api_key_set(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", "sk-real")
    svc.set_setting("openai_model", "gpt-4o")
    config = svc.get_openai_config()
    assert config["api_key_set"] is True
    assert config["model"] == "gpt-4o"


def test_reply_template_crud(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    tmpl = svc.create_reply_template("Cảm ơn bạn!")
    assert tmpl.id is not None
    assert tmpl.content == "Cảm ơn bạn!"
    templates = svc.get_reply_templates()
    assert len(templates) == 1
    svc.delete_reply_template(tmpl.id)
    assert len(svc.get_reply_templates()) == 0


def test_auto_post_template_crud(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    tmpl = svc.create_auto_post_template("Mua ngay!", min_interval=30, max_interval=120)
    assert tmpl.min_interval_seconds == 30
    updated = svc.update_auto_post_template(tmpl.id, content="Săn sale!")
    assert updated.content == "Săn sale!"
    svc.delete_auto_post_template(tmpl.id)
    assert len(svc.get_auto_post_templates()) == 0


def test_nick_live_settings_default_all_off(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    settings = svc.get_or_create_nick_settings(nick_live_id=42)
    assert settings.ai_reply_enabled is False
    assert settings.auto_reply_enabled is False
    assert settings.auto_post_enabled is False


def test_nick_live_settings_update(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.get_or_create_nick_settings(nick_live_id=1)
    updated = svc.update_nick_settings(nick_live_id=1, ai_reply_enabled=True)
    assert updated.ai_reply_enabled is True
    assert updated.auto_reply_enabled is False  # unchanged
