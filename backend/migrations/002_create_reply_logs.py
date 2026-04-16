"""Migration: create the reply_logs table with its indexes.

Run from the backend/ directory:

    python -m migrations.002_create_reply_logs

Idempotent: uses Base.metadata.create_all with tables=[ReplyLog.__table__],
which CREATEs the table and its indexes only if they do not already exist.
Safe to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect

# Allow running as `python -m migrations.002_create_reply_logs` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import Base, engine  # noqa: E402
from app.models.reply_log import ReplyLog  # noqa: E402,F401


def _table_exists(table_name: str) -> bool:
    inspector = inspect(engine)
    return inspector.has_table(table_name)


def _existing_indexes(table_name: str) -> set[str]:
    inspector = inspect(engine)
    try:
        return {idx["name"] for idx in inspector.get_indexes(table_name) if idx.get("name")}
    except Exception:
        return set()


def main() -> int:
    table_name = ReplyLog.__tablename__
    already_existed = _table_exists(table_name)

    # create_all is idempotent — it only creates tables/indexes that don't exist.
    Base.metadata.create_all(bind=engine, tables=[ReplyLog.__table__])

    if already_existed:
        print(f"Already exists, skipping: {table_name}")
    else:
        print(f"Created reply_logs table: {table_name}")

    # Verify expected indexes are present.
    expected_indexes = {
        "ix_reply_logs_nick_live_id",
        "ix_reply_logs_outcome",
        "ix_reply_logs_created_at",
        "ix_reply_logs_nick_created",
    }
    present = _existing_indexes(table_name)
    missing = expected_indexes - present
    if missing:
        print(
            f"[migration] WARNING: expected indexes missing on {table_name}: "
            f"{sorted(missing)}"
        )
    else:
        print(f"[migration] indexes verified on {table_name}: {sorted(expected_indexes)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
