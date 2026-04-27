"""Integration tests for /api/seeding/proxies router."""
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, init_db
from app.dependencies import get_current_user
from app.main import app
from app.models.seeding import SeedingClone, SeedingProxy
from app.models.settings import AppSetting
from app.models.user import User


def _override_user(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


@pytest.fixture
def user():
    init_db()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(SeedingProxy).delete()
        stale = db.query(User).filter(User.username == "proxyrouter").first()
        if stale is not None:
            db.query(AppSetting).filter(AppSetting.user_id == stale.id).delete()
        db.query(User).filter(User.username == "proxyrouter").delete()
        u = User(username="proxyrouter", password_hash="x", role="user")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    with SessionLocal() as db:
        u = db.get(User, uid)
        db.expunge(u)
    _override_user(u)
    yield u
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(SeedingClone).filter(SeedingClone.user_id == uid).delete()
        db.query(SeedingProxy).filter(SeedingProxy.user_id == uid).delete()
        db.query(AppSetting).filter(AppSetting.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_create_proxy(user):
    c = TestClient(app)
    r = c.post("/api/seeding/proxies", json={
        "scheme": "socks5", "host": "h.com", "port": 80,
        "username": "u", "password": "p",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["scheme"] == "socks5"
    assert data["host"] == "h.com"
    assert "password" not in data


def test_list_proxies(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h1", "port": 80,
    })
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h2", "port": 80,
    })
    r = c.get("/api/seeding/proxies")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_update_proxy_refreshes_clone_cache(user):
    c = TestClient(app)
    pr = c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "old", "port": 80,
        "username": "u", "password": "p",
    }).json()

    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})

    r = c.patch(f"/api/seeding/proxies/{pr['id']}", json={"host": "new"})
    assert r.status_code == 200
    assert r.json()["host"] == "new"

    clones = c.get("/api/seeding/clones").json()
    assert clones[0]["proxy"] == "http://u:p@new:80"


def test_delete_proxy_clears_clone_cache(user):
    c = TestClient(app)
    pr = c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h", "port": 80,
    }).json()
    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})

    r = c.delete(f"/api/seeding/proxies/{pr['id']}")
    assert r.status_code == 204

    clones = c.get("/api/seeding/clones").json()
    assert clones[0]["proxy"] is None
    assert clones[0].get("proxy_meta") is None


def test_user_isolation(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h", "port": 80,
    })
    with SessionLocal() as db:
        other = User(username="otherproxy", password_hash="x", role="user")
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
    try:
        with SessionLocal() as db:
            other = db.get(User, other_id)
            db.expunge(other)
        _override_user(other)
        r = c.get("/api/seeding/proxies")
        assert r.json() == []
    finally:
        with SessionLocal() as db:
            db.query(SeedingProxy).filter(
                SeedingProxy.user_id == other_id
            ).delete()
            db.query(User).filter(User.id == other_id).delete()
            db.commit()


def test_import_endpoint(user):
    c = TestClient(app)
    r = c.post("/api/seeding/proxies/import", json={
        "scheme": "socks5",
        "raw_text": "h1:80:u:p\nh2:81:u:p\nbad-line\n",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 2
    assert data["skipped_duplicates"] == 0
    assert len(data["errors"]) == 1
    assert data["errors"][0]["reason"] == "invalid_format"


def test_assign_endpoint(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies/import", json={
        "scheme": "http", "raw_text": "h1:80:u:p\nh2:81:u:p\n",
    })
    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/clones", json={
        "name": "C2", "shopee_user_id": 2, "cookies": "x",
    })
    c.post("/api/seeding/clones", json={
        "name": "C3", "shopee_user_id": 3, "cookies": "x",
    })

    r = c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})
    assert r.status_code == 200
    assert r.json() == {"assigned": 3, "reason": "ok"}


def test_setting_round_trip(user):
    c = TestClient(app)
    r = c.get("/api/seeding/proxies/setting")
    assert r.status_code == 200
    assert r.json() == {"require_proxy": False}

    r = c.put("/api/seeding/proxies/setting", json={"require_proxy": True})
    assert r.status_code == 200
    assert r.json() == {"require_proxy": True}

    r = c.get("/api/seeding/proxies/setting")
    assert r.json() == {"require_proxy": True}
