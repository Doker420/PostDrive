"""FlowPay background worker.

Runs durable work outside API web processes. The first worker job is webhook
retry delivery. Blockchain payout adapters are intentionally separate and
must be enabled only with a configured provider.
"""
import asyncio
import logging
import os

from sqlalchemy import select

from apps.api.app.db import SessionLocal
from apps.api.app.main import deliver_webhook
from apps.api.app.models import WebhookDelivery

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("flowpay.worker")


async def run_once() -> int:
    db = SessionLocal()
    try:
        deliveries = db.scalars(select(WebhookDelivery).where(
            WebhookDelivery.status == "pending").limit(50)).all()
        ids = [item.id for item in deliveries]
    finally:
        db.close()
    await asyncio.gather(*(deliver_webhook(item_id) for item_id in ids))
    return len(ids)


async def main() -> None:
    interval = int(os.getenv("WORKER_INTERVAL_SECONDS", "10"))
    log.info("FlowPay worker started")
    while True:
        try:
            count = await run_once()
            if count:
                log.info("processed %s webhook deliveries", count)
        except Exception:
            log.exception("worker cycle failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
