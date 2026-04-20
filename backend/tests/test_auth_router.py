import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(["ar_alice", "ar_locked"])).delete()
        db.add(User(username="ar_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3, is_locked=False))
        db.add(User(username="ar_locked", password_hash=hash_password("pw12345678"),
                    role="user", is_locked=True))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(["ar_alice", "ar_locked"])).delete()
        db.commit()


client = TestClient(app)


def test_login_success():
    r = client.post("/api/auth/login",
                    json={"username": "ar_alice", "password": "pw12345678"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    assert data["user"]["username"] == "ar_alice"


def test_login_wrong_password():
    r = client.post("/api/auth/login",
                    json={"username": "ar_alice", "password": "bad"})
    assert r.status_code == 401


def test_login_locked_account():
    r = client.post("/api/auth/login",
                    json={"username": "ar_locked", "password": "pw12345678"})
    assert r.status_code == 403


def test_login_unknown_user():
    r = client.post("/api/auth/login",
                    json={"username": "ar_nobody", "password": "pw12345678"})
    assert r.status_code == 401


def _token(u="ar_alice", p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def test_me():
    tok = _token()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["username"] == "ar_alice"


def test_change_password_success():
    tok = _token()
    r = client.post("/api/auth/change-password",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"old_password": "pw12345678", "new_password": "newpw12345"})
    assert r.status_code == 204

    r2 = client.post("/api/auth/login",
                     json={"username": "ar_alice", "password": "newpw12345"})
    assert r2.status_code == 200
    r3 = client.post("/api/auth/login",
                     json={"username": "ar_alice", "password": "pw12345678"})
    assert r3.status_code == 401


def test_change_password_wrong_old():
    tok = _token()
    r = client.post("/api/auth/change-password",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"old_password": "bad", "new_password": "newpw12345"})
    assert r.status_code == 400


def test_change_password_too_short():
    tok = _token()
    r = client.post("/api/auth/change-password",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"old_password": "pw12345678", "new_password": "short"})
    assert r.status_code == 422
