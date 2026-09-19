# Production runbook

```bash
cp .env.example .env
# fill production secrets

docker compose up -d postgres redis
alembic upgrade head
docker compose up -d --build api worker
```

Readiness:

```bash
curl http://localhost:3000/health/ready
```

Before enabling live keys verify: TLS, backups, database restore, webhook retry, payout approval, 2FA, rate limiting, logs without secrets, and monitoring alerts.
