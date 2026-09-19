# FlowPay worker

Запускается отдельным процессом и повторно доставляет сохранённые webhook-задачи.

```bash
python -m apps.worker.main
```

Переменные:

```env
WORKER_INTERVAL_SECONDS=10
LOG_LEVEL=INFO
```

В production worker запускается отдельным контейнером/процессом. Платёжные и blockchain-адаптеры не должны блокировать HTTP API.
