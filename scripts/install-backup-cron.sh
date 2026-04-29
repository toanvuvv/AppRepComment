#!/usr/bin/env bash
#
# Install (or refresh) a cron entry that runs ./scripts/backup.sh every 6 hours.
# Idempotent: re-running replaces the previous arc-backup entry.
#
# Usage:
#   ./scripts/install-backup-cron.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="/var/log/arc-backup.log"
TAG="arc-backup"

log() {
    printf '[%s] %s\n' "$(date +'%Y-%m-%dT%H:%M:%S%z')" "$*" >&2
}

CRON_LINE="0 */6 * * * cd ${PROJECT_ROOT} && ./scripts/backup.sh >> ${LOG_FILE} 2>&1 # ${TAG}"

# Ensure the log file exists and is writable by the current user.
if [ ! -e "${LOG_FILE}" ]; then
    if ! touch "${LOG_FILE}" 2>/dev/null; then
        log "WARN: cannot create ${LOG_FILE} (need sudo). Cron will still run if log path becomes writable later."
    fi
fi

# Read existing crontab (if any), drop prior arc-backup entries, append fresh one.
EXISTING="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "${EXISTING}" | grep -v "${TAG}" || true)"

{
    if [ -n "${FILTERED}" ]; then
        printf '%s\n' "${FILTERED}"
    fi
    printf '%s\n' "${CRON_LINE}"
} | crontab -

log "Installed cron entry:"
log "  ${CRON_LINE}"
exit 0
