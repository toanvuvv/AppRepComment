"""Integration tests for /api/seeding router — clone CRUD endpoints."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, SessionLocal, engine
from app.dependencies import get_current_user
from app.models.nick_live import NickLive
from app.models.seeding import SeedingClone, SeedingCommentTemplate, SeedingLog, SeedingLogSession
from app.models.settings import NickLiveSetting
from app.models.user import User


def _override_user(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


@pytest.fixture
def user():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username == "seeduser").delete()
        u = User(username="seeduser", password_hash="x", role="user", max_clones=None)
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    # Re-fetch outside session so the object is detached but usable
    with SessionLocal() as db:
        u = db.get(User, uid)
        db.expunge(u)
    _override_user(u)
    yield u
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        # Collect nick ids for this user before deleting dependents
        nick_ids = [n.id for n in db.query(NickLive).filter(NickLive.user_id == uid).all()]
        # Delete in FK-safe order: logs → sessions → settings → nicks → clones/templates → user
        if nick_ids:
            session_ids = [
                s.id for s in db.query(SeedingLogSession)
                .filter(SeedingLogSession.nick_live_id.in_(nick_ids)).all()
            ]
            if session_ids:
                db.query(SeedingLog).filter(
                    SeedingLog.seeding_log_session_id.in_(session_ids)
                ).delete(synchronize_session=False)
            db.query(SeedingLogSession).filter(
                SeedingLogSession.nick_live_id.in_(nick_ids)
            ).delete(synchronize_session=False)
            db.query(NickLiveSetting).filter(
                NickLiveSetting.nick_live_id.in_(nick_ids)
            ).delete(synchronize_session=False)
            db.query(NickLive).filter(NickLive.user_id == uid).delete(synchronize_session=False)
        db.query(SeedingCommentTemplate).filter(SeedingCommentTemplate.user_id == uid).delete()
        db.query(SeedingClone).filter(SeedingClone.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_create_clone_nested(user):
    c = TestClient(app)
    r = c.post("/api/seeding/clones", json={
        "user": {"id": 12345, "name": "Clone A"},
        "cookies": "SPC_EC=abc",
        "proxy": "http:1.2.3.4:8080",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Clone A"
    assert data["shopee_user_id"] == 12345


def test_list_clones_isolated_by_user(user):
    c = TestClient(app)
    c.post("/api/seeding/clones", json={
        "user": {"id": 1, "name": "A"}, "cookies": "c",
    })
    r = c.get("/api/seeding/clones")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_clone(user):
    c = TestClient(app)
    r = c.post("/api/seeding/clones", json={
        "user": {"id": 1, "name": "A"}, "cookies": "c",
    })
    cid = r.json()["id"]
    r = c.delete(f"/api/seeding/clones/{cid}")
    assert r.status_code == 204


def test_quota_enforced():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username == "seedquota").delete()
        u = User(username="seedquota", password_hash="x", role="user", max_clones=1)
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    with SessionLocal() as db:
        u = db.get(User, uid)
        db.expunge(u)
    _override_user(u)
    try:
        c = TestClient(app)
        r1 = c.post("/api/seeding/clones", json={
            "user": {"id": 1, "name": "A"}, "cookies": "c",
        })
        assert r1.status_code == 200, r1.text
        r2 = c.post("/api/seeding/clones", json={
            "user": {"id": 2, "name": "B"}, "cookies": "c",
        })
        assert r2.status_code == 403
    finally:
        app.dependency_overrides.clear()
        with SessionLocal() as db:
            db.query(SeedingCommentTemplate).filter(SeedingCommentTemplate.user_id == uid).delete()
            db.query(SeedingClone).filter(SeedingClone.user_id == uid).delete()
            db.query(User).filter(User.id == uid).delete()
            db.commit()


def test_template_create(user):
    c = TestClient(app)
    r = c.post("/api/seeding/templates", json={"content": "đẹp quá"})
    assert r.status_code == 200
    assert r.json()["content"] == "đẹp quá"


def test_template_bulk(user):
    c = TestClient(app)
    r = c.post("/api/seeding/templates/bulk",
               json={"lines": ["a", "b", " ", "c"]})
    assert r.status_code == 200
    # empty/whitespace lines are skipped
    assert len(r.json()) == 3


def test_template_toggle_disable(user):
    c = TestClient(app)
    r = c.post("/api/seeding/templates", json={"content": "x"})
    tid = r.json()["id"]
    r2 = c.patch(f"/api/seeding/templates/{tid}", json={"enabled": False})
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False


# ---------- Manual send tests ----------

def _make_nick_with_host_config(user_id: int) -> int:
    from sqlalchemy import text
    with SessionLocal() as db:
        nick = NickLive(
            user_id=user_id, name="host", shopee_user_id=100,
            shop_id=None, avatar=None, cookies="c=1",
        )
        db.add(nick)
        db.commit()
        db.refresh(nick)
        # NickLiveSetting ORM model is out of sync with the DB: extra NOT NULL
        # columns (ai_reply_enabled, auto_reply_enabled, auto_post_enabled, …)
        # live in the DB but are absent from the mapped class. Use raw INSERT
        # so we can supply defaults for every NOT NULL column at once.
        db.execute(
            text(
                "INSERT INTO nick_live_settings "
                "(nick_live_id, host_config, "
                " ai_reply_enabled, auto_reply_enabled, auto_post_enabled, "
                " reply_to_host, reply_to_moderator, "
                " auto_post_to_host, auto_post_to_moderator, "
                " auto_pin_enabled) "
                "VALUES (:nid, :hc, 0, 0, 0, 0, 0, 0, 0, 0)"
            ),
            {"nid": nick.id, "hc": '{"uuid":"U","usersig":"S"}'},
        )
        db.commit()
        return nick.id


def test_manual_send_success(user, monkeypatch):
    nick_id = _make_nick_with_host_config(user.id)
    c = TestClient(app)
    r = c.post("/api/seeding/clones",
               json={"user": {"id": 1, "name": "A"}, "cookies": "c"})
    clone_id = r.json()["id"]

    async def fake_send(**kw):
        return SeedingLog(
            id=1, status="success", content=kw["content"],
            seeding_log_session_id=kw["log_session_id"],
            clone_id=kw["clone_id"], template_id=None,
            error=None, sent_at=datetime.now(timezone.utc),
        )

    with patch("app.routers.seeding.seeding_sender.send",
               new=AsyncMock(side_effect=fake_send)):
        r = c.post("/api/seeding/manual/send", json={
            "clone_id": clone_id,
            "nick_live_id": nick_id,
            "shopee_session_id": 12345,
            "content": "đẹp",
        })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"


def test_manual_send_rate_limited_returns_429(user):
    from app.schemas.seeding import CloneRateLimitedError

    nick_id = _make_nick_with_host_config(user.id)
    c = TestClient(app)
    r = c.post("/api/seeding/clones",
               json={"user": {"id": 1, "name": "A"}, "cookies": "c"})
    clone_id = r.json()["id"]

    async def raise_rl(**kw):
        raise CloneRateLimitedError(7)

    with patch("app.routers.seeding.seeding_sender.send",
               new=AsyncMock(side_effect=raise_rl)):
        r = c.post("/api/seeding/manual/send", json={
            "clone_id": clone_id,
            "nick_live_id": nick_id,
            "shopee_session_id": 12345,
            "content": "x",
        })
    assert r.status_code == 429
    assert r.json()["detail"]["retry_after_sec"] == 7


def test_manual_send_host_config_missing(user):
    from app.schemas.seeding import HostConfigMissingError

    with SessionLocal() as db:
        nick = NickLive(
            user_id=user.id, name="h", shopee_user_id=1,
            shop_id=None, avatar=None, cookies="c",
        )
        db.add(nick)
        db.commit()
        db.refresh(nick)
        nick_id = nick.id

    c = TestClient(app)
    r = c.post("/api/seeding/clones",
               json={"user": {"id": 1, "name": "A"}, "cookies": "c"})
    clone_id = r.json()["id"]

    async def raise_hm(**kw):
        raise HostConfigMissingError()

    with patch("app.routers.seeding.seeding_sender.send",
               new=AsyncMock(side_effect=raise_hm)):
        r = c.post("/api/seeding/manual/send", json={
            "clone_id": clone_id,
            "nick_live_id": nick_id,
            "shopee_session_id": 12345,
            "content": "x",
        })
    assert r.status_code == 400
    assert "host" in r.json()["detail"].lower()
