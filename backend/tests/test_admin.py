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
