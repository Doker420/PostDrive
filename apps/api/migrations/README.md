# Database migrations

Generate and apply migrations from the repository root:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Production must use migrations instead of `Base.metadata.create_all`.
