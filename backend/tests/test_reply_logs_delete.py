"""Tests for DELETE /api/reply-logs."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password

USERNAMES = ["rld_owner", "rld_other"]
client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="rld_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.add(User(username="rld_other", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _user_id(u):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=u).first().id


def _make_nick(user_id: int) -> int:
    with SessionLocal() as db:
        n = NickLive(user_id=user_id, name="n", shopee_user_id=1, cookies="c")
        db.add(n)
        db.commit()
        db.refresh(n)
        return n.id


def _insert_log(nick_id: int, session_id: int) -> None:
    with SessionLocal() as db:
        db.add(ReplyLog(
            nick_live_id=nick_id,
            session_id=session_id,
            outcome="success",
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()


def _count_logs(nick_id: int, session_id: int) -> int:
    with SessionLocal() as db:
        return (
            db.query(ReplyLog)
            .filter(ReplyLog.nick_live_id == nick_id, ReplyLog.session_id == session_id)
            .count()
        )


def test_delete_removes_only_target_session():
    tok = _login("rld_owner")
    nick = _make_nick(_user_id("rld_owner"))
    _insert_log(nick, 100)
    _insert_log(nick, 100)
    _insert_log(nick, 200)

    r = client.delete(
        f"/api/reply-logs?nick_live_id={nick}&session_id=100",
        headers=_hdr(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 2}
    assert _count_logs(nick, 100) == 0
    assert _count_logs(nick, 200) == 1


def test_delete_404_when_nick_not_owned():
    tok_other = _login("rld_other")
    nick = _make_nick(_user_id("rld_owner"))
    _insert_log(nick, 100)

    r = client.delete(
        f"/api/reply-logs?nick_live_id={nick}&session_id=100",
        headers=_hdr(tok_other),
    )
    assert r.status_code == 404
    assert _count_logs(nick, 100) == 1
