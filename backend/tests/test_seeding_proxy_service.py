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
