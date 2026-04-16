"""One-shot migration: encrypt plaintext secrets in nick_lives and nick_live_settings.

Run from the backend/ directory:

    python -m migrations.001_encrypt_secrets

Idempotent: rows whose values already look like Fernet tokens (prefix "gAAAAA")
or are None/empty are skipped. A timestamped backup of database.db is created
before any writes; the migration aborts if the backup cannot be created.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

# Allow running as `python -m migrations.001_encrypt_secrets` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import engine  # noqa: E402
from app.services import crypto  # noqa: E402

_CIPHERTEXT_PREFIX = "gAAAAA"

_TARGETS: list[tuple[str, str, str]] = [
    # (table, id_column, secret_column)
    ("nick_lives", "id", "cookies"),
    ("nick_live_settings", "id", "moderator_config"),
]


def _backup_database() -> Path:
    db_path = _BACKEND_ROOT / "database.db"
    if not db_path.exists():
        raise FileNotFoundError(
            f"Cannot back up database: {db_path} does not exist."
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"database.db.bak-{stamp}")
    shutil.copy2(db_path, backup_path)
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        raise RuntimeError(f"Backup verification failed at {backup_path}.")
    return backup_path


def _should_encrypt(value: str | None) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if value.startswith(_CIPHERTEXT_PREFIX):
        return False
    return True


def _migrate_table(conn, table: str, id_col: str, secret_col: str) -> tuple[int, int]:
    encrypted = 0
    skipped = 0

    rows = conn.execute(
        text(f"SELECT {id_col}, {secret_col} FROM {table}")
    ).fetchall()

    for row in rows:
        row_id, current = row[0], row[1]
        if not _should_encrypt(current):
            skipped += 1
            continue
        new_value = crypto.encrypt(current)
        conn.execute(
            text(f"UPDATE {table} SET {secret_col} = :v WHERE {id_col} = :id"),
            {"v": new_value, "id": row_id},
        )
        encrypted += 1

    return encrypted, skipped


def main() -> int:
    try:
        backup_path = _backup_database()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[migration] ABORT: backup failed: {exc}", file=sys.stderr)
        return 1

    print(f"[migration] backup created at: {backup_path}")

    total_encrypted = 0
    total_skipped = 0

    # Use a raw connection with an explicit transaction so EncryptedString's
    # auto-encrypt on bind does not interfere. We drive plain SQL via text().
    with engine.begin() as conn:
        for table, id_col, secret_col in _TARGETS:
            try:
                enc, skip = _migrate_table(conn, table, id_col, secret_col)
            except Exception as exc:
                print(
                    f"[migration] ERROR while migrating {table}.{secret_col}: {exc}",
                    file=sys.stderr,
                )
                raise
            print(
                f"[migration] {table}.{secret_col}: "
                f"encrypted={enc} skipped={skip}"
            )
            total_encrypted += enc
            total_skipped += skip

    print(
        f"[migration] done: {total_encrypted} rows encrypted, "
        f"{total_skipped} skipped."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
