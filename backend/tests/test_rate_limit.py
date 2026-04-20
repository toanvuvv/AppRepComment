import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    """slowapi stores state in-memory between tests; reset it."""
    limiter.reset()
    yield
    limiter.reset()


client = TestClient(app)


def test_login_rate_limited_after_5_attempts():
    for _ in range(5):
        r = client.post("/api/auth/login",
                        json={"username": "rl_nobody", "password": "x"})
        assert r.status_code in (401, 429)  # all invalid creds return 401 until limit
    r = client.post("/api/auth/login",
                    json={"username": "rl_nobody", "password": "x"})
    assert r.status_code == 429
    assert "too many" in r.json()["detail"].lower()
