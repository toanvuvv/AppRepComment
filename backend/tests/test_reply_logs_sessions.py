"""Tests for GET /api/reply-logs/sessions and session_id filter."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password

USERNAMES = ["rls_owner", "rls_other"]
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
        db.add(User(username="rls_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.add(User(username="rls_other", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
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


def _insert_log(nick_id: int, session_id: int, created_at: datetime) -> None:
    with SessionLocal() as db:
        db.add(ReplyLog(
            nick_live_id=nick_id,
            session_id=session_id,
            outcome="success",
            created_at=created_at,
        ))
        db.commit()


def test_list_sessions_groups_and_orders_by_last_at_desc():
    tok = _login("rls_owner")
    nick = _make_nick(_user_id("rls_owner"))
    now = datetime.now(timezone.utc)

    # Session 100: 2 logs from 2h ago to 1h ago
    _insert_log(nick, 100, now - timedelta(hours=2))
    _insert_log(nick, 100, now - timedelta(hours=1))
    # Session 200: 1 log from 30m ago (newest)
    _insert_log(nick, 200, now - timedelta(minutes=30))

    r = client.get(f"/api/reply-logs/sessions?nick_live_id={nick}", headers=_hdr(tok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert data[0]["session_id"] == 200
    assert data[0]["count"] == 1
    assert data[1]["session_id"] == 100
    assert data[1]["count"] == 2


def test_list_sessions_ownership_hides_other_users_nicks():
    tok_owner = _login("rls_owner")
    tok_other = _login("rls_other")
    nick = _make_nick(_user_id("rls_owner"))
    _insert_log(nick, 100, datetime.now(timezone.utc))

    r = client.get(f"/api/reply-logs/sessions?nick_live_id={nick}", headers=_hdr(tok_other))
    assert r.status_code == 200
    assert r.json() == []

    r = client.get(f"/api/reply-logs/sessions?nick_live_id={nick}", headers=_hdr(tok_owner))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_list_logs_filters_by_session_id():
    tok = _login("rls_owner")
    nick = _make_nick(_user_id("rls_owner"))
    now = datetime.now(timezone.utc)
    _insert_log(nick, 100, now - timedelta(minutes=5))
    _insert_log(nick, 100, now - timedelta(minutes=4))
    _insert_log(nick, 200, now - timedelta(minutes=3))

    r = client.get(
        f"/api/reply-logs?nick_live_id={nick}&session_id=100",
        headers=_hdr(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert all(row["session_id"] == 100 for row in data)
