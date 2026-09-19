# Security policy

## Secrets

Never commit `.env`, API keys, Telegram bot tokens, wallet private keys or real payment details. Rotate a key immediately if it appears in logs or chat.

## Reporting

Report vulnerabilities privately to the project maintainers. Do not use production credentials or real payment channels while testing.

## Production checklist

- set a strong `TOKEN_SECRET`, `ADMIN_BOOTSTRAP_TOKEN` and encryption secret;
- use PostgreSQL and Redis;
- run Alembic migrations;
- put API behind TLS and a reverse proxy;
- restrict admin access and enable 2FA;
- disable the bootstrap endpoint after first admin creation;
- configure backups and restore drills;
- move rate limits to Redis;
- run a security review before real funds.
