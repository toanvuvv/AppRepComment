"""Tests for auto-pin router endpoints and settings validation."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password

USERNAMES = ["ap_owner", "ap_other"]

client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).filter(
            NickLive.user_id.in_(
                db.query(User.id).filter(User.username.in_(USERNAMES))
            )
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="ap_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.add(User(username="ap_other", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(NickLive).filter(
            NickLive.user_id.in_(
                db.query(User.id).filter(User.username.in_(USERNAMES))
            )
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _login(username, password="pw12345678"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r.json()["access_token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _get_user_id(username):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).first().id


def _create_nick(user_id) -> int:
    """Create a NickLive for the given user_id and return its id."""
    with SessionLocal() as db:
        nick = NickLive(
            user_id=user_id,
            name="test_nick",
            shopee_user_id=12345,
            shop_id=None,
            avatar=None,
            cookies="test_cookies",
        )
        db.add(nick)
        db.commit()
        db.refresh(nick)
        return nick.id


# ---------------------------------------------------------------------------
# Test 1: PUT settings rejects min > max
# ---------------------------------------------------------------------------

def test_update_settings_rejects_min_gt_max():
    tok = _login("ap_owner")
    owner_id = _get_user_id("ap_owner")
    nick_id = _create_nick(owner_id)

    r = client.put(
        f"/api/nick-lives/{nick_id}/settings",
        headers=_hdr(tok),
        json={"pin_min_interval_minutes": 10, "pin_max_interval_minutes": 3},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Test 2: PUT settings rejects out-of-range values
# ---------------------------------------------------------------------------

def test_update_settings_rejects_out_of_range():
    tok = _login("ap_owner")
    owner_id = _get_user_id("ap_owner")
    nick_id = _create_nick(owner_id)

    # min=0 is below the ge=1 constraint
    r1 = client.put(
        f"/api/nick-lives/{nick_id}/settings",
        headers=_hdr(tok),
        json={"pin_min_interval_minutes": 0},
    )
    assert r1.status_code == 422

    # max=61 is above the le=60 constraint
    r2 = client.put(
        f"/api/nick-lives/{nick_id}/settings",
        headers=_hdr(tok),
        json={"pin_max_interval_minutes": 61},
    )
    assert r2.status_code == 422


# ---------------------------------------------------------------------------
# Test 3: POST auto-pin/start on foreign nick → 404
# ---------------------------------------------------------------------------

def test_auto_pin_start_requires_ownership():
    other_id = _get_user_id("ap_other")
    foreign_nick_id = _create_nick(other_id)

    tok = _login("ap_owner")
    r = client.post(
        f"/api/nick-lives/{foreign_nick_id}/auto-pin/start",
        headers=_hdr(tok),
        json={"session_id": 1},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test 4: POST auto-pin/stop on foreign nick → 404
# ---------------------------------------------------------------------------

def test_auto_pin_stop_requires_ownership():
    other_id = _get_user_id("ap_other")
    foreign_nick_id = _create_nick(other_id)

    tok = _login("ap_owner")
    r = client.post(
        f"/api/nick-lives/{foreign_nick_id}/auto-pin/stop",
        headers=_hdr(tok),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test 5: GET auto-pin/status reports running=True when pinner says so
# ---------------------------------------------------------------------------

def test_auto_pin_status_reports_running():
    owner_id = _get_user_id("ap_owner")
    nick_id = _create_nick(owner_id)

    tok = _login("ap_owner")

    mock_pinner = MagicMock()
    mock_pinner.is_running.return_value = True

    with patch("app.main.auto_pinner", mock_pinner):
        r = client.get(
            f"/api/nick-lives/{nick_id}/auto-pin/status",
            headers=_hdr(tok),
        )

    assert r.status_code == 200
    assert r.json() == {"running": True}
