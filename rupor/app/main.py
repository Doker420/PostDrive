"""«Рупор» — биржа рекламы для Telegram и VK. Точка входа FastAPI."""
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db
from .web import account, admin, payhooks, public

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title=f"{config.APP_NAME} — {config.APP_TAGLINE}",
                  docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
    app.include_router(public.router)
    app.include_router(account.router)
    app.include_router(admin.router)
    app.include_router(payhooks.router)

    @app.get("/health")
    def health():
        return {"ok": True, "app": config.APP_NAME}

    return app


app = create_app()
