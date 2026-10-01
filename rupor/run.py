"""Запуск «Рупор»: python run.py (или uvicorn app.main:app)."""
import uvicorn

from app import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.PORT, reload=False)
