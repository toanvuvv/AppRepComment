import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.dependencies import get_current_user
from app.models.user import User
from app.services.auth import create_access_token, hash_password


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username.like("dep_%")).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).filter(User.username.like("dep_%")).delete()
        db.commit()


def _seed_user(username="dep_alice", is_locked=False, role="user"):
    with SessionLocal() as db:
        u = User(
            username=username,
            password_hash=hash_password("pw12345678"),
            role=role,
            max_nicks=5,
            is_locked=is_locked,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u.id


def _app():
    app = FastAPI()

    @app.get("/me")
    def me(user: User = Depends(get_current_user)):
        return {"id": user.id, "username": user.username}

    return app


def test_missing_token_401():
    r = TestClient(_app()).get("/me")
    assert r.status_code == 401


def test_invalid_token_401():
    r = TestClient(_app()).get("/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_valid_token_returns_user():
    uid = _seed_user("dep_alice")
    token = create_access_token(user_id=uid, username="dep_alice", role="user")
    r = TestClient(_app()).get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "dep_alice"


def test_locked_user_403():
    uid = _seed_user("dep_locked", is_locked=True)
    token = create_access_token(user_id=uid, username="dep_locked", role="user")
    r = TestClient(_app()).get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_query_token_works_for_sse():
    uid = _seed_user("dep_sse")
    token = create_access_token(user_id=uid, username="dep_sse", role="user")
    r = TestClient(_app()).get(f"/me?token={token}")
    assert r.status_code == 200
