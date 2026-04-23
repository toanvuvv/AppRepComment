import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_non_admin_cannot_get_system_keys(client, seed_user_and_admin):
    token = _login(client, "usr1", "password1")
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    assert r.status_code == 403


def test_admin_get_system_keys_reports_unset(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "relive_api_key_set": False,
        "openai_api_key_set": False,
        "openai_model": None,
    }


def test_admin_put_system_relive(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.put(
        "/api/admin/system-keys/relive",
        json={"api_key": "sys-relive"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    assert r.json()["relive_api_key_set"] is True


def test_admin_put_system_openai_persists_and_masks(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.put(
        "/api/admin/system-keys/openai",
        json={"api_key": "sk-system", "model": "gpt-4o"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    body = r.json()
    assert body["openai_api_key_set"] is True
    assert body["openai_model"] == "gpt-4o"
    assert "sk-system" not in r.text


def test_auth_me_returns_ai_key_mode(client, seed_user_and_admin):
    token = _login(client, "usr1", "password1")
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["ai_key_mode"] == "own"


def test_settings_openai_response_exposes_mode_flag(client, seed_user_and_admin):
    token = _login(client, "usr1", "password1")
    r = client.get("/api/settings/openai", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["ai_key_mode"] == "own"
    assert body["is_managed_by_admin"] is False


def test_settings_openai_response_flips_when_admin_sets_system(client, seed_user_and_admin):
    admin_token = _login(client, "admin1", "password1")
    # Get usr1 id then flip to system
    r = client.get("/api/admin/users", headers=_auth(admin_token))
    u1 = next(u for u in r.json() if u["username"] == "usr1")
    client.patch(
        f"/api/admin/users/{u1['id']}",
        json={"ai_key_mode": "system"},
        headers=_auth(admin_token),
    )

    token = _login(client, "usr1", "password1")
    r = client.get("/api/settings/openai", headers=_auth(token))
    body = r.json()
    assert body["ai_key_mode"] == "system"
    assert body["is_managed_by_admin"] is True


def test_admin_create_user_defaults_to_system_mode(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.post(
        "/api/admin/users",
        json={"username": "usr2", "password": "password1"},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["ai_key_mode"] == "system"


def test_admin_create_user_with_own_mode(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.post(
        "/api/admin/users",
        json={"username": "usr3", "password": "password1", "ai_key_mode": "own"},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["ai_key_mode"] == "own"


def test_admin_patch_user_ai_key_mode_invalidates_cache(client, seed_user_and_admin, monkeypatch):
    from app.services.nick_cache import nick_cache

    calls = []
    monkeypatch.setattr(nick_cache, "invalidate_settings", lambda nid: calls.append(nid))

    token = _login(client, "admin1", "password1")
    # Get u1's id
    r = client.get("/api/admin/users", headers=_auth(token))
    u1 = next(u for u in r.json() if u["username"] == "u1")

    r = client.patch(
        f"/api/admin/users/{u1['id']}",
        json={"ai_key_mode": "system"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["ai_key_mode"] == "system"


def test_admin_list_users_includes_openai_own_key_set(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    # Seed a per-user openai key for u1 directly.
    from app.database import SessionLocal
    from app.services.settings_service import SettingsService
    from app.models.user import User as _U
    with SessionLocal() as db:
        u = db.query(_U).filter(_U.username == "u1").first()
        SettingsService(db, user_id=u.id).set_setting("openai_api_key", "sk-u1")

    r = client.get("/api/admin/users", headers=_auth(token))
    assert r.status_code == 200
    rows = {row["username"]: row for row in r.json()}
    assert rows["u1"]["openai_own_key_set"] is True
    assert rows["admin1"]["openai_own_key_set"] is False
