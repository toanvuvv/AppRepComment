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
