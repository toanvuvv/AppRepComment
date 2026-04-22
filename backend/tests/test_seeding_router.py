"""Integration tests for /api/seeding router — clone CRUD endpoints."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, SessionLocal, engine
from app.dependencies import get_current_user
from app.models.user import User
from app.models.seeding import SeedingClone, SeedingCommentTemplate


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
