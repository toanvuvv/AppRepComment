# App Rep Comment

Automated Shopee comment reply system with per-user isolation and an admin control plane.

## Authentication

This app uses JWT-based auth with admin-managed user accounts.

**First run:** Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in your `.env`. A bcrypt-hashed
admin user is seeded on first boot and existing data is attached to that admin.

**JWT_SECRET** must be a long random string in production (enforced).

**User lifecycle:** Admin creates users via `/admin/users` (and the Admin UI). Each user
manages their own nicks, Relive/AI settings, knowledge base and reply logs. Users can
change their own password. Admin can lock, unlock, reset password, or delete users.

**Quota:** Admin can set `max_nicks` per user (`null` = unlimited).

## Quick Start

```bash
cp .env.example .env          # fill in secrets
docker compose up --build
```

See `backend/.env.example` for all available configuration variables.

## Development

```bash
cd backend
pip install -r requirements.txt
python -m pytest
```

## Backup & Restore

The backend stores SQLite data in `./data/` (bind-mounted to `/app/data` inside
the container). Make sure this directory exists on the host **before** running
`docker compose up` — Compose will not create it for you on first run.

```bash
# Manual online backup (writers stay unblocked). Output: ./backups/database-YYYYMMDD-HHMMSS.db
./scripts/backup.sh

# Install a cron job that runs the above every 6 hours. Idempotent.
./scripts/install-backup-cron.sh

# Restore from a backup (stops the backend, swaps the file, restarts, verifies).
./scripts/restore.sh backups/database-20260429-120000.db
```

The most recent 14 backups are kept; older files are pruned automatically.
Pre-bind-mount `.bak` files have been moved to `backups/legacy/`.
