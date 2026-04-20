import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["iso_alice", "iso_bob"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.user_id.in_(
            db.query(User.id).filter(User.username.in_(USERNAMES)).subquery()
        )).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="iso_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.add(User(username="iso_bob", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
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


def test_alice_cannot_see_bobs_nicks():
    atok = _login("iso_alice")
    btok = _login("iso_bob")
    client.post("/api/nick-lives", headers={"Authorization": f"Bearer {btok}"},
                json={"name": "iso_bob_nick", "shopee_user_id": 1, "cookies": "c"})
    r = client.get("/api/nick-lives", headers={"Authorization": f"Bearer {atok}"})
    assert r.status_code == 200
    assert all(n["name"] != "iso_bob_nick" for n in r.json())
