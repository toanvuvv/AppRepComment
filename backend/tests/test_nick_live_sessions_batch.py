"""Tests for GET /api/nick-lives/sessions?ids=..."""
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password

USERNAMES = ["sb_owner", "sb_other"]
client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="sb_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.add(User(username="sb_other", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _create_nick(user_id: int, name: str) -> int:
    with SessionLocal() as db:
        nl = NickLive(user_id=user_id, name=name, shopee_user_id=12345, cookies="ck=1")
        db.add(nl)
        db.commit()
        return nl.id


def _user_id(u):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=u).first().id


def _live_response(session_id: int, status: int = 1):
    return {"data": {"list": [{
        "sessionId": session_id, "title": "live", "coverImage": "",
        "startTime": 0, "duration": 0, "status": status,
        "views": 0, "viewers": 0, "peakViewers": 0, "comments": 0,
    }]}}


def test_batch_sessions_returns_per_nick():
    owner = _user_id("sb_owner")
    nid1 = _create_nick(owner, "n1")
    nid2 = _create_nick(owner, "n2")
    tok = _login("sb_owner")

    async def fake_get_live_sessions(cookies: str):
        return _live_response(99, status=1)

    with patch("app.routers.nick_live.get_live_sessions", new=AsyncMock(side_effect=fake_get_live_sessions)):
        r = client.get(f"/api/nick-lives/sessions?ids={nid1},{nid2}", headers=_hdr(tok))

    assert r.status_code == 200, r.text
    body = r.json()
    assert "sessions" in body
    assert str(nid1) in body["sessions"]
    assert str(nid2) in body["sessions"]
    assert body["sessions"][str(nid1)]["active_session"]["sessionId"] == 99


def test_batch_sessions_skips_other_users_nick():
    owner = _user_id("sb_owner")
    other = _user_id("sb_other")
    nid_owner = _create_nick(owner, "mine")
    nid_other = _create_nick(other, "theirs")
    tok = _login("sb_owner")

    with patch("app.routers.nick_live.get_live_sessions", new=AsyncMock(return_value=_live_response(1))):
        r = client.get(f"/api/nick-lives/sessions?ids={nid_owner},{nid_other}", headers=_hdr(tok))

    assert r.status_code == 200
    body = r.json()
    assert str(nid_owner) in body["sessions"]
    assert str(nid_other) not in body["sessions"]


def test_batch_sessions_per_nick_error_does_not_fail_batch():
    owner = _user_id("sb_owner")
    nid1 = _create_nick(owner, "n1")
    nid2 = _create_nick(owner, "n2")
    tok = _login("sb_owner")

    call_count = {"n": 0}

    async def flaky(cookies: str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("shopee down")
        return _live_response(7)

    with patch("app.routers.nick_live.get_live_sessions", new=AsyncMock(side_effect=flaky)):
        r = client.get(f"/api/nick-lives/sessions?ids={nid1},{nid2}", headers=_hdr(tok))

    assert r.status_code == 200
    body = r.json()
    keys = list(body["sessions"].keys())
    assert len(keys) == 2
    failed_key = next(k for k in keys if body["sessions"][k].get("error"))
    ok_key = next(k for k in keys if not body["sessions"][k].get("error"))
    assert "shopee down" in body["sessions"][failed_key]["error"]
    assert body["sessions"][ok_key]["active_session"]["sessionId"] == 7


def test_batch_sessions_requires_auth():
    r = client.get("/api/nick-lives/sessions?ids=1")
    assert r.status_code in (401, 403)


def test_batch_sessions_empty_ids_returns_empty():
    tok = _login("sb_owner")
    r = client.get("/api/nick-lives/sessions?ids=", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json() == {"sessions": {}}
