"""Деньги, пароли, сессии, CSRF, флеш-сообщения."""
import functools
import hashlib
import hmac
import inspect
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import RedirectResponse

from . import config, db

# ── Деньги ────────────────────────────────────────────────────────

def fmt(kop: int | float | None, sign: bool = False) -> str:
    """123450 → «1 234,50 ₽» (None → «—»)."""
    if kop is None:
        return "—"
    kop = int(kop)
    sign_str = "-" if kop < 0 else ("+" if sign else "")
    kop = abs(kop)
    rub, kop_part = divmod(kop, 100)
    rub_str = f"{rub:,}".replace(",", "\u202f")
    if kop_part:
        return f"{sign_str}{rub_str},{kop_part:02d}\u00a0₽"
    return f"{sign_str}{rub_str}\u00a0₽"


def rub_to_kop(value: str | float) -> int:
    return round(float(str(value).replace(",", ".").replace(" ", "")) * 100)


def fmt_subs(n: int) -> str:
    return f"{n:,}".replace(",", "\u00a0")


# ── Пароли ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ── Сессии ────────────────────────────────────────────────────────

SESSION_COOKIE = "rupor_session"
SESSION_DAYS = 30


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(conn, "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
               (token, user_id, db.now(), expires))
    return token


def destroy_session(conn, token: str) -> None:
    db.execute(conn, "DELETE FROM sessions WHERE token = ?", (token,))


def get_user(conn, request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = db.q1(conn, """
        SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ? AND u.banned = 0
    """, (token, db.now()))
    return row


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400,
                        httponly=True, samesite="lax")


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE)


# ── CSRF ──────────────────────────────────────────────────────────
# Токен привязан к сессионному токену; до логина — к anon-cookie.
# Базовое значение кэшируется в request.state, чтобы cookie и токен
# в форме совпадали даже при первом заходе.

CSRF_COOKIE = "rupor_csrf"


def _csrf_base(request: Request) -> str:
    base = request.cookies.get(SESSION_COOKIE) or request.cookies.get(CSRF_COOKIE)
    if base:
        return base
    if not hasattr(request.state, "_new_csrf_base"):
        request.state._new_csrf_base = secrets.token_urlsafe(16)
    return request.state._new_csrf_base


def csrf_token(request: Request) -> str:
    return hmac.new(config.SECRET_KEY.encode(), f"csrf:{_csrf_base(request)}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def set_csrf_cookie_if_needed(request: Request, response) -> None:
    """Вызывается после формирования ответа: проставляет anon-cookie,
    если она только что создана."""
    base = getattr(request.state, "_new_csrf_base", None)
    if base and CSRF_COOKIE not in request.cookies:
        response.set_cookie(CSRF_COOKIE, base, max_age=86400 * 365,
                            httponly=True, samesite="lax")


def check_csrf(request: Request, form) -> bool:
    supplied = form.get("csrf", "")
    return hmac.compare_digest(supplied, csrf_token(request))


# ── Флеш-сообщения ────────────────────────────────────────────────

FLASH_COOKIE = "rupor_flash"


def flash(response, message: str, kind: str = "ok") -> None:
    encoded = quote(f"{kind}|{message}", safe="")
    response.set_cookie(FLASH_COOKIE, encoded, max_age=30,
                        httponly=False, samesite="lax")


def pop_flash(request: Request) -> dict | None:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    raw = unquote(raw)
    if "|" not in raw:
        return None
    kind, _, message = raw.partition("|")
    return {"kind": kind, "message": message}


# ── Декоратор: требует авторизации ────────────────────────────────

def login_required(func):
    """Подходит и для sync-, и для async-обработчиков."""
    @functools.wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        conn = db.get_db()
        try:
            user = get_user(conn, request)
        finally:
            conn.close()
        if not user:
            resp = RedirectResponse(f"/login?next={request.url.path}", status_code=303)
            flash(resp, "Войдите в аккаунт, чтобы продолжить", "warn")
            return resp
        request.state.user = user
        result = func(request, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    return wrapper
