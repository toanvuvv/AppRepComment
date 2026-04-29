#!/usr/bin/env bash
#
# Restore the SQLite database from a backup file.
#
# Usage:
#   ./scripts/restore.sh <path-to-backup.db>
#
# Behavior:
#   - Stops the arc-backend container.
#   - Backs up the current data/database.db to data/database.db.pre-restore-<ts>.
#   - Copies the supplied backup file into data/database.db.
#   - Restarts the backend and runs a sanity SELECT.

set -euo pipefail

CONTAINER="arc-backend"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

log() {
    printf '[%s] %s\n' "$(date +'%Y-%m-%dT%H:%M:%S%z')" "$*" >&2
}

if [ "$#" -ne 1 ]; then
    log "ERROR: usage: $0 <path-to-backup.db>"
    exit 2
fi

SOURCE="$1"
if [ ! -f "${SOURCE}" ]; then
    log "ERROR: backup file not found: ${SOURCE}"
    exit 2
fi

if [ ! -d "${DATA_DIR}" ]; then
    log "ERROR: data directory not found: ${DATA_DIR}"
    exit 2
fi

log "Stopping container ${CONTAINER}"
docker stop "${CONTAINER}" >/dev/null

CURRENT_DB="${DATA_DIR}/database.db"
SAFETY_COPY="${DATA_DIR}/database.db.pre-restore-${TIMESTAMP}"

if [ -f "${CURRENT_DB}" ]; then
    log "Saving current DB to ${SAFETY_COPY}"
    cp -p "${CURRENT_DB}" "${SAFETY_COPY}"
fi

log "Restoring from ${SOURCE} -> ${CURRENT_DB}"
cp -p "${SOURCE}" "${CURRENT_DB}"

# Wipe stale WAL/SHM so SQLite re-initializes against the restored file.
rm -f "${DATA_DIR}/database.db-wal" "${DATA_DIR}/database.db-shm"

log "Starting container ${CONTAINER}"
docker start "${CONTAINER}" >/dev/null

# Give the app a moment to open the DB before we probe it.
sleep 3

log "Verifying restored database"
docker exec "${CONTAINER}" python -c "import sqlite3; print(sqlite3.connect('/app/data/database.db').execute('SELECT count(*) FROM users').fetchone())"

log "Restore OK"
exit 0
