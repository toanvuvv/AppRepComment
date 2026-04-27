"""Unit tests for seeding_proxy_service (parse, import, assign, format_url)."""
import pytest

from app.services.seeding_proxy_service import (
    ParsedProxy,
    ParseError,
    parse_bulk,
)


def test_parse_bulk_valid_lines():
    raw = (
        "proxyx3.ddns.net:4001:proxy:proxy3\n"
        "1.2.3.4:8080:user1:pass1\n"
    )
    parsed, errors = parse_bulk(raw, "socks5")
    assert errors == []
    assert parsed == [
        ParsedProxy(scheme="socks5", host="proxyx3.ddns.net", port=4001,
                    username="proxy", password="proxy3"),
        ParsedProxy(scheme="socks5", host="1.2.3.4", port=8080,
                    username="user1", password="pass1"),
    ]


def test_parse_bulk_skips_blank_and_comment_lines():
    raw = "\n  \n# a comment\nproxyx3.ddns.net:4001:proxy:proxy3\n"
    parsed, errors = parse_bulk(raw, "http")
    assert errors == []
    assert len(parsed) == 1
    assert parsed[0].scheme == "http"


def test_parse_bulk_invalid_format_reports_error_keeps_others():
    raw = (
        "good.host:1234:u:p\n"
        "bad-line-no-colons\n"
        "another.host:80:u:p\n"
    )
    parsed, errors = parse_bulk(raw, "http")
    assert len(parsed) == 2
    assert len(errors) == 1
    assert errors[0].line == 2
    assert errors[0].raw == "bad-line-no-colons"
    assert errors[0].reason == "invalid_format"


def test_parse_bulk_invalid_port_reports_error():
    raw = "host.com:99999:u:p\n"
    parsed, errors = parse_bulk(raw, "http")
    assert parsed == []
    assert len(errors) == 1
    assert errors[0].reason == "invalid_port"


def test_parse_bulk_strips_whitespace():
    raw = "  host.com:80:u:p  \n"
    parsed, _ = parse_bulk(raw, "http")
    assert parsed[0].host == "host.com"


from app.services.seeding_proxy_service import format_url


class _FakeProxy:
    def __init__(self, scheme, host, port, username=None, password=None):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.username = username
        self.password = password


def test_format_url_with_auth():
    p = _FakeProxy("socks5", "proxyx3.ddns.net", 4001, "proxy", "proxy3")
    assert format_url(p) == "socks5://proxy:proxy3@proxyx3.ddns.net:4001"


def test_format_url_no_auth():
    p = _FakeProxy("http", "1.2.3.4", 8080)
    assert format_url(p) == "http://1.2.3.4:8080"


def test_format_url_url_encodes_password_with_special_chars():
    p = _FakeProxy("https", "h", 80, "user@x", "p@ss/word")
    assert format_url(p) == "https://user%40x:p%40ss%2Fword@h:80"


from app.database import SessionLocal, init_db
from app.models.seeding import SeedingProxy
from app.models.user import User
from app.services.seeding_proxy_service import import_bulk


@pytest.fixture
def db_user():
    init_db()
    with SessionLocal() as db:
        db.query(SeedingProxy).delete()
        db.query(User).filter(User.username == "proxytest").delete()
        u = User(username="proxytest", password_hash="x", role="user")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    yield uid
    with SessionLocal() as db:
        db.query(SeedingProxy).filter(SeedingProxy.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_import_bulk_creates_rows(db_user):
    raw = "h1.com:80:u:p\nh2.com:81:u:p\n"
    result = import_bulk(db_user, "http", raw)
    assert result.created == 2
    assert result.skipped_duplicates == 0
    assert result.errors == []
    with SessionLocal() as db:
        rows = db.query(SeedingProxy).filter(
            SeedingProxy.user_id == db_user
        ).all()
        assert len(rows) == 2


def test_import_bulk_dedupes_existing(db_user):
    raw1 = "h1.com:80:u:p\n"
    import_bulk(db_user, "http", raw1)
    raw2 = "h1.com:80:u:p\nh3.com:82:u:p\n"
    result = import_bulk(db_user, "http", raw2)
    assert result.created == 1
    assert result.skipped_duplicates == 1
    assert result.errors == []


def test_import_bulk_reports_parse_errors(db_user):
    raw = "h1.com:80:u:p\nbad-line\n"
    result = import_bulk(db_user, "http", raw)
    assert result.created == 1
    assert len(result.errors) == 1
    assert result.errors[0].reason == "invalid_format"
