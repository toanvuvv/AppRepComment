"""Business logic for SeedingProxy: parse, import, assign, cache refresh."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote


ProxyScheme = Literal["socks5", "http", "https"]


@dataclass(frozen=True)
class ParsedProxy:
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None
    password: str | None


@dataclass(frozen=True)
class ParseError:
    line: int
    raw: str
    reason: str


def parse_bulk(
    raw_text: str, scheme: ProxyScheme,
) -> tuple[list[ParsedProxy], list[ParseError]]:
    """Parse bulk proxy text. One proxy per line: ``host:port:user:pass``.

    Lines beginning with ``#`` and blank lines are skipped.
    """
    parsed: list[ParsedProxy] = []
    errors: list[ParseError] = []

    for idx, raw in enumerate(raw_text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) != 4:
            errors.append(ParseError(idx, raw, "invalid_format"))
            continue
        host, port_raw, user, pwd = parts
        host = host.strip()
        if not host:
            errors.append(ParseError(idx, raw, "invalid_format"))
            continue
        try:
            port = int(port_raw)
        except ValueError:
            errors.append(ParseError(idx, raw, "invalid_port"))
            continue
        if not (1 <= port <= 65535):
            errors.append(ParseError(idx, raw, "invalid_port"))
            continue
        parsed.append(ParsedProxy(
            scheme=scheme, host=host, port=port,
            username=user or None, password=pwd or None,
        ))
    return parsed, errors


from app.database import SessionLocal
from app.models.seeding import SeedingProxy
from app.schemas.seeding_proxy import ProxyImportError, ProxyImportResult


def import_bulk(
    user_id: int, scheme: ProxyScheme, raw_text: str,
) -> ProxyImportResult:
    """Insert parsed proxies, deduping against existing user rows."""
    parsed, parse_errors = parse_bulk(raw_text, scheme)
    errors = [
        ProxyImportError(line=e.line, raw=e.raw, reason=e.reason)
        for e in parse_errors
    ]

    if not parsed:
        return ProxyImportResult(
            created=0, skipped_duplicates=0, errors=errors,
        )

    created = 0
    skipped = 0
    with SessionLocal() as db:
        existing_rows = db.query(SeedingProxy).filter(
            SeedingProxy.user_id == user_id
        ).all()
        existing_keys = {
            (p.scheme, p.host, p.port, p.username or "")
            for p in existing_rows
        }
        for pp in parsed:
            key = (pp.scheme, pp.host, pp.port, pp.username or "")
            if key in existing_keys:
                skipped += 1
                continue
            db.add(SeedingProxy(
                user_id=user_id,
                scheme=pp.scheme, host=pp.host, port=pp.port,
                username=pp.username, password=pp.password,
            ))
            existing_keys.add(key)
            created += 1
        db.commit()

    return ProxyImportResult(
        created=created, skipped_duplicates=skipped, errors=errors,
    )


def format_url(proxy) -> str:
    """Build the proxy URL string used by httpx.

    ``proxy`` may be a ``SeedingProxy`` ORM row or any object exposing
    ``scheme``, ``host``, ``port``, ``username``, ``password``.
    """
    if proxy.username:
        creds = f"{quote(proxy.username, safe='')}:{quote(proxy.password or '', safe='')}@"
    else:
        creds = ""
    return f"{proxy.scheme}://{creds}{proxy.host}:{proxy.port}"
