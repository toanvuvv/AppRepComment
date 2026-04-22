"""Test retention cutoff = 72h (3 ngày)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import REPLY_LOG_RETENTION_HOURS
from app.database import Base, SessionLocal, engine
from app.main import _delete_logs_before
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username == "rlr_owner"))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username == "rlr_owner").delete()
        u = User(username="rlr_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10)
        db.add(u)
        db.commit()
        db.refresh(u)
        n = NickLive(user_id=u.id, name="n", shopee_user_id=1, cookies="c")
        db.add(n)
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username == "rlr_owner"))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username == "rlr_owner").delete()
        db.commit()


def test_retention_is_72_hours():
    assert REPLY_LOG_RETENTION_HOURS == 72


def test_delete_logs_before_cutoff_keeps_recent_rows():
    with SessionLocal() as db:
        owner_id = db.query(User.id).filter(User.username == "rlr_owner").scalar()
        nick_id = db.query(NickLive.id).filter(NickLive.user_id == owner_id).scalar()
        now = datetime.now(timezone.utc)
        db.add(ReplyLog(nick_live_id=nick_id, session_id=1, outcome="success", created_at=now - timedelta(hours=71)))
        db.add(ReplyLog(nick_live_id=nick_id, session_id=1, outcome="success", created_at=now - timedelta(hours=73)))
        db.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    deleted = _delete_logs_before(cutoff)
    assert deleted == 1

    with SessionLocal() as db:
        remaining = db.query(ReplyLog).count()
        assert remaining == 1
