#!/usr/bin/env bash
#
# Online backup of the SQLite database inside the arc-backend container.
# Uses sqlite3.Connection.backup() so writers are not blocked.
#
# Usage:
#   ./scripts/backup.sh
#
# Behavior:
#   - Snapshots /app/data/database.db -> /app/data/_tmp_backup.db inside the container.
#   - Copies the snapshot out to ./backups/database-YYYYMMDD-HHMMSS.db on the host.
#   - Removes the in-container temp file.
#   - Retains the 14 most recent backups; older ones are deleted.

set -euo pipefail

CONTAINER="arc-backend"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${PROJECT_ROOT}/backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="${BACKUP_DIR}/database-${TIMESTAMP}.db"
KEEP=14

log() {
    printf '[%s] %s\n' "$(date +'%Y-%m-%dT%H:%M:%S%z')" "$*" >&2
}

mkdir -p "${BACKUP_DIR}"

if ! docker inspect -f '{{.State.Running}}' "${CONTAINER}" >/dev/null 2>&1; then
    log "ERROR: container '${CONTAINER}' is not running"
    exit 1
fi

log "Snapshotting database inside container ${CONTAINER}"
docker exec "${CONTAINER}" python -c "import sqlite3; src=sqlite3.connect('/app/data/database.db'); dst=sqlite3.connect('/app/data/_tmp_backup.db'); src.backup(dst); dst.close(); src.close()"

log "Copying snapshot to ${TARGET}"
docker cp "${CONTAINER}:/app/data/_tmp_backup.db" "${TARGET}"

log "Removing in-container temp file"
docker exec "${CONTAINER}" rm -f /app/data/_tmp_backup.db

log "Pruning backups, keeping ${KEEP} most recent"
# shellcheck disable=SC2012
ls -1t "${BACKUP_DIR}"/database-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

log "Backup OK: ${TARGET}"
exit 0
