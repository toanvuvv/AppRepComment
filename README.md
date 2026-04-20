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
