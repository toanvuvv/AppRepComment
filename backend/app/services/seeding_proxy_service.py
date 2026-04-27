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


from app.models.seeding import SeedingClone as _SeedingClone
from app.schemas.seeding_proxy import ProxyAssignResult


def assign_round_robin(user_id: int, only_unassigned: bool) -> ProxyAssignResult:
    """Round-robin assign proxies to clones (sorted by id ASC).

    With N proxies and M clones, ``clones[i].proxy_id = proxies[i mod N].id``.
    If ``only_unassigned`` is True, skip clones that already have a proxy.
    """
    with SessionLocal() as db:
        proxies = (
            db.query(SeedingProxy)
            .filter(SeedingProxy.user_id == user_id)
            .order_by(SeedingProxy.id.asc())
            .all()
        )
        if not proxies:
            return ProxyAssignResult(assigned=0, reason="no_proxies")

        q = (
            db.query(_SeedingClone)
            .filter(_SeedingClone.user_id == user_id)
        )
        if only_unassigned:
            q = q.filter(_SeedingClone.proxy_id.is_(None))
        clones = q.order_by(_SeedingClone.id.asc()).all()

        if not clones:
            total = (
                db.query(_SeedingClone)
                .filter(_SeedingClone.user_id == user_id)
                .count()
            )
            if total == 0:
                return ProxyAssignResult(assigned=0, reason="no_clones")
            return ProxyAssignResult(assigned=0, reason="all_assigned")

        n = len(proxies)
        for i, clone in enumerate(clones):
            target = proxies[i % n]
            clone.proxy_id = target.id
            clone.proxy = format_url(target)
        db.commit()

        return ProxyAssignResult(assigned=len(clones), reason="ok")


def refresh_clone_cache_for_proxy(proxy_id: int) -> None:
    """Refresh ``clone.proxy`` URL cache on every clone using this proxy."""
    with SessionLocal() as db:
        proxy = db.get(SeedingProxy, proxy_id)
        if proxy is None:
            return
        url = format_url(proxy)
        clones = db.query(_SeedingClone).filter(
            _SeedingClone.proxy_id == proxy_id
        ).all()
        for c in clones:
            c.proxy = url
        db.commit()


def clear_clone_cache_for_proxy(proxy_id: int) -> None:
    """Set ``proxy_id`` and ``proxy`` to NULL on clones using this proxy.

    Caller is expected to call this BEFORE deleting the proxy row so the
    explicit clear runs in the same transaction (FK ON DELETE SET NULL
    handles the column too, but we also clear the cached string).
    """
    with SessionLocal() as db:
        clones = db.query(_SeedingClone).filter(
            _SeedingClone.proxy_id == proxy_id
        ).all()
        for c in clones:
            c.proxy_id = None
            c.proxy = None
        db.commit()
