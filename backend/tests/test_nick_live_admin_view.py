import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["nlav_admin", "nlav_alice", "nlav_bob"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.name.like("nlav_%")).delete()
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="nlav_admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="nlav_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.add(User(username="nlav_bob", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.commit()

        bob_id = db.query(User).filter_by(username="nlav_bob").first().id
        db.add(NickLive(user_id=bob_id, name="nlav_bob_nick", shopee_user_id=111,
                        cookies="cookie-bob"))
        alice_id = db.query(User).filter_by(username="nlav_alice").first().id
        db.add(NickLive(user_id=alice_id, name="nlav_alice_nick", shopee_user_id=222,
                        cookies="cookie-alice"))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.name.like("nlav_%")).delete()
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


client = TestClient(app)


def _login(u: str) -> str:
    return client.post(
        "/api/auth/login", json={"username": u, "password": "pw12345678"}
    ).json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _uid(username: str) -> int:
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).first().id


def _bob_nick_id() -> int:
    with SessionLocal() as db:
        return db.query(NickLive).filter_by(name="nlav_bob_nick").first().id


def test_admin_lists_target_user_nicks():
    tok = _login("nlav_admin")
    r = client.get(
        f"/api/nick-lives?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 200
    names = [n["name"] for n in r.json()]
    assert names == ["nlav_bob_nick"]


def test_non_admin_with_other_as_user_id_forbidden():
    tok = _login("nlav_alice")
    r = client.get(
        f"/api/nick-lives?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 403


def test_admin_target_user_not_found():
    tok = _login("nlav_admin")
    r = client.get("/api/nick-lives?as_user_id=999999", headers=_hdr(tok))
    assert r.status_code == 404


def test_admin_no_param_sees_own_nicks_only():
    tok = _login("nlav_admin")
    r = client.get("/api/nick-lives", headers=_hdr(tok))
    assert r.status_code == 200
    # Admin owns no nicks in this fixture.
    assert r.json() == []


def test_admin_can_read_other_user_nick_cookies():
    tok = _login("nlav_admin")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/cookies?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 200
    assert r.json()["cookies"] == "cookie-bob"


def test_non_admin_cannot_access_other_user_nick():
    tok = _login("nlav_alice")
    nick_id = _bob_nick_id()
    # Without as_user_id: standard ownership check returns 404.
    r = client.get(f"/api/nick-lives/{nick_id}/cookies", headers=_hdr(tok))
    assert r.status_code == 404


def test_admin_get_scan_status_for_other_user():
    tok = _login("nlav_admin")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/scan/status?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 200
    assert "is_scanning" in r.json()


def test_admin_can_list_other_user_knowledge_products():
    tok = _login("nlav_admin")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/knowledge/products?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    # Empty list is fine; the contract is "no 404 because admin context".
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_non_admin_cannot_list_other_user_knowledge_products():
    tok = _login("nlav_alice")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/knowledge/products?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 403


def test_admin_can_list_other_user_reply_logs():
    tok = _login("nlav_admin")
    r = client.get(
        f"/api/reply-logs?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_non_admin_cannot_list_other_user_reply_logs():
    tok = _login("nlav_alice")
    r = client.get(
        f"/api/reply-logs?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 403


def test_admin_can_read_other_user_reply_templates():
    tok = _login("nlav_admin")
    r = client.get(
        f"/api/settings/reply-templates?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_non_admin_cannot_read_other_user_reply_templates():
    tok = _login("nlav_alice")
    r = client.get(
        f"/api/settings/reply-templates?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 403
