# Тесты

Запускать из корня репозитория:

```bash
python tests/test_pool_async.py     # изоляция соединений в asyncio
python tests/test_pool_threads.py   # то же под реальной многопоточностью
python tests/test_pg_adapter.py     # трансляция SQL-диалекта в PostgreSQL
```

`test_pool_threads.py` — регрессионный тест на баг общего курсора: до перехода
на пул этот сценарий ронял процесс с SIGBUS.
