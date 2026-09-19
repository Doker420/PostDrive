"""FlowPay Telegram operations bot.

This bot is an optional operations interface. It deliberately does not contain
payment credentials; all financial actions must be confirmed in the web panel
with 2FA.
"""
import os

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

API_URL = os.getenv("FLOWPAY_API_URL", "http://localhost:3000/api/v1")
ADMIN_TOKEN = os.getenv("FLOWPAY_ADMIN_TOKEN", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
dp = Dispatcher()


async def get(path: str):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(API_URL + path, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        response.raise_for_status()
        return response.json()


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("FlowPay Operations\n\n/stats — статистика платформы\n/health — состояние API")


@dp.message(Command("stats"))
async def stats(message: Message):
    if not ADMIN_TOKEN:
        await message.answer("Бот ещё не настроен.")
        return
    try:
        data = await get("/admin/statistics?days=1")
        await message.answer(
            f"FlowPay за сегодня\n\nПлатежей: {data['payments']}\n"
            f"Успешных: {data['succeeded']}\nОборот: {data['gross']}\n"
            f"Доход платформы: {data['platform_fees']}"
        )
    except Exception:
        await message.answer("Не удалось получить статистику. Проверьте API.")


@dp.message(Command("health"))
async def health(message: Message):
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(API_URL.replace("/api/v1", "") + "/health")
        await message.answer("API: online" if response.is_success else "API: error")
    except Exception:
        await message.answer("API: offline")


@dp.message(F.text)
async def unknown(message: Message):
    await message.answer("Неизвестная команда. Используйте /start.")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    await dp.start_polling(Bot(BOT_TOKEN))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
