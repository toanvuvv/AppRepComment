import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["q_admin", "q_alice"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.user_id.in_(
            db.query(User.id).filter(User.username.in_(USERNAMES)).subquery()
        )).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="q_admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="q_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=2))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.user_id.in_(
            db.query(User.id).filter(User.username.in_(USERNAMES)).subquery()
        )).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


client = TestClient(app)


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _post_nick(tok, name):
    return client.post(
        "/api/nick-lives",
        headers={"Authorization": f"Bearer {tok}"},
        json={"name": name, "shopee_user_id": 1, "cookies": "c"},
    )


def test_quota_allows_up_to_max():
    tok = _login("q_alice")
    assert _post_nick(tok, "qn1").status_code in (200, 201)
    assert _post_nick(tok, "qn2").status_code in (200, 201)
    r = _post_nick(tok, "qn3")
    assert r.status_code == 403
    detail = r.json().get("detail", "").lower()
    assert "quota" in detail or "limit" in detail


def test_admin_unlimited():
    tok = _login("q_admin")
    for i in range(5):
        r = _post_nick(tok, f"qa_{i}")
        assert r.status_code in (200, 201), r.text
