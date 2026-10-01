"""Общие помощники веб-слоя: шаблоны, контекст, редиректы."""
import os

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import config, db
from ..auth import (check_csrf, clear_session_cookie, csrf_token, flash, fmt,
                    get_user, pop_flash, set_csrf_cookie_if_needed,
                    set_session_cookie, fmt_subs)

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)
templates.env.filters["money"] = fmt
templates.env.filters["subs"] = fmt_subs
templates.env.filters["dt"] = lambda s: (s or "")[:16].replace("T", " ")
templates.env.globals["APP_NAME"] = config.APP_NAME
templates.env.globals["APP_TAGLINE"] = config.APP_TAGLINE
templates.env.globals["COMMISSION_PCT"] = config.COMMISSION_PCT
templates.env.globals["DEMO_PAYMENTS"] = config.DEMO_PAYMENTS

PLATFORM_TITLES = {"telegram": "Telegram", "vk": "VK"}
KIND_TITLES = {
    ("telegram", "channel"): "Канал",
    ("telegram", "chat"): "Чат",
    ("telegram", "bot"): "Бот",
    ("vk", "channel"): "Сообщество",
    ("vk", "chat"): "Беседа",
    ("vk", "bot"): "Приложение / бот",
}
templates.env.globals["PLATFORM_TITLES"] = PLATFORM_TITLES
templates.env.globals["KIND_TITLES"] = KIND_TITLES


def render(request: Request, template: str, status_code: int = 200, **ctx):
    """Рендер шаблона с общим контекстом (юзер, csrf, флеш, категории)."""
    conn = db.get_db()
    try:
        user = get_user(conn, request)
        categories = db.q(conn, "SELECT * FROM categories ORDER BY sort, name")
        context = {
            "request": request,
            "user": user,
            "csrf": csrf_token(request),
            "flash_msg": pop_flash(request),
            "categories": categories,
        }
        context.update(ctx)
    finally:
        conn.close()
    response = templates.TemplateResponse(request, template, context, status_code=status_code)
    set_csrf_cookie_if_needed(request, response)
    return response


def redirect(url: str, message: str | None = None, kind: str = "ok") -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    if message:
        flash(resp, message, kind)
    return resp


async def read_form(request: Request) -> dict:
    """Читает form-urlencoded или multipart в плоский dict[str]."""
    form = await request.form()
    return {k: (v if isinstance(v, str) else v.filename or "") for k, v in form.items()}


def validate_csrf_or_flash(request: Request, form: dict, back_url: str):
    """Возвращает RedirectResponse при неудаче, иначе None."""
    if check_csrf(request, form):
        return None
    return redirect(back_url, "Сессия устарела, попробуйте ещё раз", "error")


__all__ = [
    "templates", "render", "redirect", "read_form", "validate_csrf_or_flash",
    "set_session_cookie", "clear_session_cookie",
]
