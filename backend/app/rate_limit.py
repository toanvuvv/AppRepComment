"""Shared slowapi limiter. Kept in its own module so both main.py and
routers can import without circular dependency."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
