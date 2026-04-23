# backend/tests/test_settings_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import user  # noqa: F401 - register users table before FK resolution
from app.models import nick_live  # noqa: F401
from app.models.settings import AppSetting, ReplyTemplate, AutoPostTemplate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Import all models
    from app.models import user  # noqa
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
    assert settings.reply_mode == "none"
    assert settings.reply_to_host is False
    assert settings.reply_to_moderator is False
    assert settings.auto_post_enabled is False


def test_nick_live_settings_update(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", "sk-test")
    svc.get_or_create_nick_settings(nick_live_id=1)
    updated = svc.update_nick_settings(nick_live_id=1, reply_mode="ai")
    assert updated.reply_mode == "ai"
    assert updated.auto_post_enabled is False  # unchanged


def test_resolve_openai_config_system_reads_system_rows(db):
    from app.services.settings_service import SettingsService
    SettingsService(db).set_system_openai_api_key("sys-key")
    SettingsService(db).set_system_openai_model("gpt-4o")
    SettingsService(db, user_id=1).set_setting("openai_api_key", "own-key")
    SettingsService(db, user_id=1).set_setting("openai_model", "gpt-own")
    api_key, model = SettingsService(db, user_id=1).resolve_openai_config("system")
    assert api_key == "sys-key"
    assert model == "gpt-4o"


def test_resolve_openai_config_own_reads_per_user_and_does_not_fallback(db):
    from app.services.settings_service import SettingsService
    SettingsService(db).set_system_openai_api_key("sys-key")
    SettingsService(db).set_system_openai_model("gpt-sys")
    svc1 = SettingsService(db, user_id=1)
    assert svc1.resolve_openai_config("own") == (None, None)
    svc1.set_setting("openai_api_key", "own-1")
    svc1.set_setting("openai_model", "gpt-1")
    assert svc1.resolve_openai_config("own") == ("own-1", "gpt-1")


def test_get_system_relive_api_key_is_scope_free(db):
    from app.services.settings_service import SettingsService
    SettingsService(db).set_setting("relive_api_key", "sys-relive")
    assert SettingsService(db, user_id=99).get_system_relive_api_key() == "sys-relive"


def test_resolve_openai_config_rejects_unknown_mode(db):
    import pytest
    from app.services.settings_service import SettingsService
    with pytest.raises(ValueError):
        SettingsService(db, user_id=1).resolve_openai_config("bogus")
