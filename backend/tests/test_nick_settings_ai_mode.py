import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.models import user  # noqa
    from app.models import nick_live  # noqa
    from app.models import settings  # noqa
    from app.models import knowledge_product  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_update_nick_settings_ai_mode_own_missing_key_raises(db):
    from app.services.settings_service import SettingsService
    from app.models.nick_live import NickLive
    from app.models.user import User

    db.add(User(id=1, username="u", password_hash="h", role="user", ai_key_mode="own"))
    db.add(NickLive(id=10, user_id=1, name="n", cookies="c", shopee_user_id=1))
    db.commit()

    svc = SettingsService(db, user_id=1)
    svc.get_or_create_nick_settings(10)

    with pytest.raises(ValueError, match="own"):
        svc.update_nick_settings(10, reply_mode="ai")


def test_update_nick_settings_ai_mode_system_missing_key_raises(db):
    from app.services.settings_service import SettingsService
    from app.models.nick_live import NickLive
    from app.models.user import User

    db.add(User(id=2, username="u2", password_hash="h", role="user", ai_key_mode="system"))
    db.add(NickLive(id=20, user_id=2, name="n", cookies="c", shopee_user_id=2))
    db.commit()

    svc = SettingsService(db, user_id=2)
    svc.get_or_create_nick_settings(20)

    with pytest.raises(ValueError, match="Admin chưa"):
        svc.update_nick_settings(20, reply_mode="ai")


def test_update_nick_settings_ai_mode_system_succeeds_when_admin_key_set(db):
    from app.services.settings_service import SettingsService
    from app.models.nick_live import NickLive
    from app.models.user import User

    db.add(User(id=3, username="u3", password_hash="h", role="user", ai_key_mode="system"))
    db.add(NickLive(id=30, user_id=3, name="n", cookies="c", shopee_user_id=3))
    db.commit()

    SettingsService(db).set_system_openai_api_key("sys")
    SettingsService(db).set_system_openai_model("gpt-4o")

    svc = SettingsService(db, user_id=3)
    svc.get_or_create_nick_settings(30)
    row = svc.update_nick_settings(30, reply_mode="ai")
    assert row.reply_mode == "ai"
