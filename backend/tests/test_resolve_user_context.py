import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.dependencies import resolve_user_context
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["ruc_admin", "ruc_alice", "ruc_bob"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="ruc_admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="ruc_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.add(User(username="ruc_bob", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(ctx: User = Depends(resolve_user_context)):
        return {"id": ctx.id, "username": ctx.username}

    return app


def _login(client: TestClient, u: str) -> str:
    # Use the real login endpoint of the main app for token issuance.
    from app.main import app as main_app
    main_client = TestClient(main_app)
    return main_client.post(
        "/api/auth/login", json={"username": u, "password": "pw12345678"}
    ).json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _uid(username: str) -> int:
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).first().id


def test_no_param_returns_caller():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_alice")
    r = client.get("/probe", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["username"] == "ruc_alice"


def test_self_param_returns_caller():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_alice")
    r = client.get(f"/probe?as_user_id={_uid('ruc_alice')}", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["username"] == "ruc_alice"


def test_non_admin_with_other_id_forbidden():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_alice")
    r = client.get(f"/probe?as_user_id={_uid('ruc_bob')}", headers=_hdr(tok))
    assert r.status_code == 403
    assert r.json()["detail"] == "Admin only"


def test_admin_with_other_id_returns_target():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_admin")
    r = client.get(f"/probe?as_user_id={_uid('ruc_bob')}", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["username"] == "ruc_bob"


def test_admin_with_unknown_id_404():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_admin")
    r = client.get("/probe?as_user_id=999999", headers=_hdr(tok))
    assert r.status_code == 404
    assert r.json()["detail"] == "Target user not found"
