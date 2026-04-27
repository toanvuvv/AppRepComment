"""Tests for GET /api/nick-lives/{id}/scan-stats."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password
from app.services.comment_scanner import scanner

USERNAMES = ["ss_owner"]
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
        db.add(User(username="ss_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    yield
    scanner._stats_counters.clear() if hasattr(scanner, "_stats_counters") else None
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


def _create_nick(user_id: int) -> int:
    with SessionLocal() as db:
        nl = NickLive(user_id=user_id, name="n", shopee_user_id=1, cookies="ck=1")
        db.add(nl)
        db.commit()
        return nl.id


def _add_reply_log(nick_id: int, outcome: str, seconds_ago: int):
    with SessionLocal() as db:
        rl = ReplyLog(
            nick_live_id=nick_id,
            session_id=1,
            guest_id="g",
            guest_name="g",
            outcome=outcome,
            comment_text="c",
            created_at=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
        )
        db.add(rl)
        db.commit()


def test_scan_stats_zero_for_idle_nick():
    owner = _user_id("ss_owner")
    nid = _create_nick(owner)
    tok = _login("ss_owner")

    r = client.get(f"/api/nick-lives/{nid}/scan-stats?window=300", headers=_hdr(tok))
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "comments_new": 0,
        "replies_ok": 0,
        "replies_fail": 0,
        "replies_dropped": 0,
        "window_seconds": 300,
    }


def test_scan_stats_counts_replies_in_window():
    owner = _user_id("ss_owner")
    nid = _create_nick(owner)
    tok = _login("ss_owner")

    _add_reply_log(nid, "success", seconds_ago=60)
    _add_reply_log(nid, "success", seconds_ago=120)
    _add_reply_log(nid, "failed", seconds_ago=30)
    _add_reply_log(nid, "dropped", seconds_ago=10)
    _add_reply_log(nid, "success", seconds_ago=600)  # outside window

    r = client.get(f"/api/nick-lives/{nid}/scan-stats?window=300", headers=_hdr(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["replies_ok"] == 2
    assert body["replies_fail"] == 1
    assert body["replies_dropped"] == 1


def test_scan_stats_comments_new_from_scanner_counter():
    owner = _user_id("ss_owner")
    nid = _create_nick(owner)
    tok = _login("ss_owner")

    scanner.record_comment(nid)
    scanner.record_comment(nid)
    scanner.record_comment(nid)

    r = client.get(f"/api/nick-lives/{nid}/scan-stats?window=300", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["comments_new"] == 3


def test_scan_stats_404_for_other_user_nick():
    owner = _user_id("ss_owner")
    nid = _create_nick(owner)
    with SessionLocal() as db:
        db.add(User(username="ss_intruder", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    tok = client.post("/api/auth/login", json={"username": "ss_intruder", "password": "pw12345678"}).json()["access_token"]
    r = client.get(f"/api/nick-lives/{nid}/scan-stats", headers=_hdr(tok))
    assert r.status_code == 404
    with SessionLocal() as db:
        db.query(User).filter_by(username="ss_intruder").delete()
        db.commit()
