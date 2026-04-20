import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from app.services import login_attempts
from app.services.auth import hash_password

client = TestClient(app)

USERNAMES = ["rl_gooduser"]


@pytest.fixture(autouse=True)
def _reset():
    login_attempts.reset()
    yield
    login_attempts.reset()


@pytest.fixture(autouse=True)
def _seed_user():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(
            username="rl_gooduser",
            password_hash=hash_password("correct_password"),
            role="user",
            max_nicks=5,
            is_locked=False,
        ))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def test_failed_logins_rate_limited_after_5():
    """Five bad attempts should result in 429 on the sixth."""
    for _ in range(5):
        r = client.post("/api/auth/login",
                        json={"username": "rl_nobody", "password": "x"})
        assert r.status_code == 401

    r = client.post("/api/auth/login",
                    json={"username": "rl_nobody", "password": "x"})
    assert r.status_code == 429
    assert "too many" in r.json()["detail"].lower()


def test_successful_logins_do_not_count():
    """Repeated successful logins must never trigger 429."""
    for _ in range(10):
        r = client.post("/api/auth/login",
                        json={"username": "rl_gooduser", "password": "correct_password"})
        assert r.status_code == 200


def test_success_resets_failure_counter():
    """Four failures followed by a success should clear the counter."""
    for _ in range(4):
        client.post("/api/auth/login",
                    json={"username": "rl_nobody", "password": "x"})
    # Successful login resets the counter
    r = client.post("/api/auth/login",
                    json={"username": "rl_gooduser", "password": "correct_password"})
    assert r.status_code == 200
    # Next failure should NOT immediately 429 (counter was reset)
    r = client.post("/api/auth/login",
                    json={"username": "rl_nobody", "password": "x"})
    assert r.status_code == 401
