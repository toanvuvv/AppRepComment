import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["adm_admin", "adm_alice", "adm_bob"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="adm_admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="adm_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


client = TestClient(app)


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _id(username):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).first().id


def test_non_admin_forbidden():
    tok = _login("adm_alice")
    r = client.get("/api/admin/users", headers=_hdr(tok))
    assert r.status_code == 403


def test_list_users_includes_nick_count():
    tok = _login("adm_admin")
    r = client.get("/api/admin/users", headers=_hdr(tok))
    assert r.status_code == 200
    rows = r.json()
    alice = [u for u in rows if u["username"] == "adm_alice"][0]
    assert alice["nick_count"] == 0


def test_create_user():
    tok = _login("adm_admin")
    r = client.post("/api/admin/users", headers=_hdr(tok),
                    json={"username": "adm_bob", "password": "pw12345678", "max_nicks": 5})
    assert r.status_code == 201
    assert r.json()["username"] == "adm_bob"
    r2 = client.post("/api/auth/login",
                     json={"username": "adm_bob", "password": "pw12345678"})
    assert r2.status_code == 200


def test_create_duplicate_rejected():
    tok = _login("adm_admin")
    r = client.post("/api/admin/users", headers=_hdr(tok),
                    json={"username": "adm_alice", "password": "pw12345678", "max_nicks": 5})
    assert r.status_code == 409


def test_update_max_nicks():
    tok = _login("adm_admin")
    r = client.patch(f"/api/admin/users/{_id('adm_alice')}",
                     headers=_hdr(tok), json={"max_nicks": 10})
    assert r.status_code == 200
    assert r.json()["max_nicks"] == 10


def test_lock_and_unlock_flow():
    tok = _login("adm_admin")
    aid = _id("adm_alice")
    client.patch(f"/api/admin/users/{aid}", headers=_hdr(tok), json={"is_locked": True})
    r = client.post("/api/auth/login",
                    json={"username": "adm_alice", "password": "pw12345678"})
    assert r.status_code == 403
    client.patch(f"/api/admin/users/{aid}", headers=_hdr(tok), json={"is_locked": False})
    r2 = client.post("/api/auth/login",
                     json={"username": "adm_alice", "password": "pw12345678"})
    assert r2.status_code == 200


def test_reset_password():
    tok = _login("adm_admin")
    r = client.patch(f"/api/admin/users/{_id('adm_alice')}",
                     headers=_hdr(tok), json={"new_password": "brandnew99"})
    assert r.status_code == 200
    r2 = client.post("/api/auth/login",
                     json={"username": "adm_alice", "password": "brandnew99"})
    assert r2.status_code == 200


def test_delete_user():
    tok = _login("adm_admin")
    aid = _id("adm_alice")
    r = client.delete(f"/api/admin/users/{aid}", headers=_hdr(tok))
    assert r.status_code == 204
    r2 = client.post("/api/auth/login",
                     json={"username": "adm_alice", "password": "pw12345678"})
    assert r2.status_code == 401


def test_cannot_delete_self():
    tok = _login("adm_admin")
    r = client.delete(f"/api/admin/users/{_id('adm_admin')}", headers=_hdr(tok))
    assert r.status_code == 400


def test_cannot_lock_self():
    tok = _login("adm_admin")
    r = client.patch(f"/api/admin/users/{_id('adm_admin')}",
                     headers=_hdr(tok), json={"is_locked": True})
    assert r.status_code == 400
