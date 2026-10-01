"""Аккаунт: регистрация/вход, личный кабинет, площадки, баланс, заказы."""
from fastapi import APIRouter, Request

from .. import config, db, payments
from ..auth import (create_session, destroy_session, flash, get_user, hash_password,
                    login_required, set_session_cookie, clear_session_cookie,
                    SESSION_COOKIE, verify_password, fmt)
from ..formats import FORMATS, ORDER_STATUS, price_map
from .helpers import read_form, redirect, render, validate_csrf_or_flash

router = APIRouter()

PRICE_FIELDS = ["price_24h", "price_48h", "price_72h", "price_repost", "price_native"]


# ── Регистрация и вход ────────────────────────────────────────────

@router.get("/register")
def register_page(request: Request):
    return render(request, "auth/register.html")


@router.post("/register")
async def register(request: Request):
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/register")
    if fail:
        return fail
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    name = form.get("name", "").strip() or email.split("@")[0]
    if "@" not in email or "." not in email.split("@")[-1]:
        return redirect("/register", "Укажите корректный e-mail", "error")
    if len(password) < 8:
        return redirect("/register", "Пароль должен быть не короче 8 символов", "error")

    conn = db.get_db()
    try:
        if db.q1(conn, "SELECT id FROM users WHERE email = ?", (email,)):
            return redirect("/register", "Такой e-mail уже зарегистрирован", "error")
        first_admin = db.scalar(conn, "SELECT COUNT(*) FROM users") == 0
        is_admin = first_admin or email in config.ADMIN_EMAILS
        uid = db.execute(conn, """INSERT INTO users (email, pass_hash, name, tg_username,
                                 vk_url, is_admin, created_at)
                                 VALUES (?,?,?,?,?,?,?)""",
                         (email, hash_password(password), name,
                          form.get("tg_username", "").strip().lstrip("@"),
                          form.get("vk_url", "").strip(), int(is_admin), db.now()))
        token = create_session(conn, uid)
    finally:
        conn.close()
    resp = redirect("/lk", f"Добро пожаловать в «{config.APP_NAME}»!", "ok")
    set_session_cookie(resp, token)
    return resp


@router.get("/login")
def login_page(request: Request):
    return render(request, "auth/login.html")


@router.post("/login")
async def login(request: Request):
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/login")
    if fail:
        return fail
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    next_url = form.get("next", "/lk") or "/lk"
    if not next_url.startswith("/"):
        next_url = "/lk"

    conn = db.get_db()
    try:
        user = db.q1(conn, "SELECT * FROM users WHERE email = ?", (email,))
        if not user or not verify_password(password, user["pass_hash"]):
            return redirect("/login", "Неверный e-mail или пароль", "error")
        if user["banned"]:
            return redirect("/login", "Аккаунт заблокирован", "error")
        token = create_session(conn, user["id"])
    finally:
        conn.close()
    resp = redirect(next_url, "Вы вошли в аккаунт", "ok")
    set_session_cookie(resp, token)
    return resp


@router.get("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn = db.get_db()
        try:
            destroy_session(conn, token)
        finally:
            conn.close()
    resp = redirect("/", "Вы вышли из аккаунта", "ok")
    clear_session_cookie(resp)
    return resp


# ── Личный кабинет ────────────────────────────────────────────────

@router.get("/lk")
@login_required
def lk_dashboard(request: Request):
    user = request.state.user
    conn = db.get_db()
    try:
        my_listings = db.q(conn, "SELECT * FROM listings WHERE owner_id=? AND status != 'deleted' "
                                 "ORDER BY created_at DESC", (user["id"],))
        sales = db.q(conn, """SELECT o.*, l.title AS listing_title FROM orders o
                              JOIN listings l ON l.id = o.listing_id
                              WHERE l.owner_id = ? ORDER BY o.created_at DESC LIMIT 5""", (user["id"],))
        purchases = db.q(conn, """SELECT o.*, l.title AS listing_title FROM orders o
                                  JOIN listings l ON l.id = o.listing_id
                                  WHERE o.buyer_id = ? ORDER BY o.created_at DESC LIMIT 5""", (user["id"],))
        txs = db.q(conn, "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 6",
                   (user["id"],))
        stats = {
            "active": sum(1 for l in my_listings if l["status"] == "active"),
            "pending": sum(1 for l in my_listings if l["status"] == "pending"),
            "earned": db.scalar(conn, """SELECT COALESCE(SUM(price_kop - commission_kop),0)
                                         FROM orders WHERE listing_id IN
                                         (SELECT id FROM listings WHERE owner_id=?)
                                         AND status='completed'""", (user["id"],)),
            "spent": db.scalar(conn, "SELECT COALESCE(SUM(price_kop),0) FROM orders "
                                     "WHERE buyer_id=? AND status IN ('completed','published')",
                               (user["id"],)),
        }
    finally:
        conn.close()
    return render(request, "lk/dashboard.html", my_listings=my_listings, sales=sales,
                  purchases=purchases, txs=txs, stats=stats, order_status=ORDER_STATUS)


# ── Мои площадки ──────────────────────────────────────────────────

@router.get("/lk/listings")
@login_required
def lk_listings(request: Request):
    user = request.state.user
    conn = db.get_db()
    try:
        rows = db.q(conn, """
            SELECT l.*, c.name AS category_name FROM listings l
            LEFT JOIN categories c ON c.id = l.category_id
            WHERE l.owner_id = ? AND l.status != 'deleted'
            ORDER BY l.created_at DESC""", (user["id"],))
    finally:
        conn.close()
    for r in rows:
        r["formats"] = price_map(r)
    return render(request, "lk/listings.html", listings=rows, order_status=ORDER_STATUS)


@router.get("/lk/listings/new")
@login_required
def lk_listing_new(request: Request):
    return render(request, "lk/listing_form.html", l=None, action="/lk/listings/new",
                  formats=FORMATS, price_fields=PRICE_FIELDS)


def _parse_listing_form(form: dict) -> tuple[dict, str | None]:
    """Валидация формы площадки. Возвращает (данные, ошибка)."""
    data = {
        "platform": form.get("platform", ""),
        "kind": form.get("kind", ""),
        "title": form.get("title", "").strip(),
        "link": form.get("link", "").strip(),
        "category_id": form.get("category_id", ""),
        "description": form.get("description", "").strip()[:3000],
        "subscribers": form.get("subscribers", "0").strip() or "0",
        "err": form.get("err", "0").strip() or "0",
    }
    if data["platform"] not in ("telegram", "vk"):
        return data, "Выберите платформу"
    if data["kind"] not in ("channel", "chat", "bot"):
        return data, "Выберите тип площадки"
    if not (3 <= len(data["title"]) <= 100):
        return data, "Название: от 3 до 100 символов"
    if not (data["link"].startswith("http") or data["link"].startswith("@")):
        return data, "Ссылка должна начинаться с http(s):// или @username"
    if not data["category_id"].isdigit():
        return data, "Выберите категорию"
    data["category_id"] = int(data["category_id"])
    if not data["subscribers"].isdigit():
        return data, "Подписатели: только цифры"
    data["subscribers"] = int(data["subscribers"])
    try:
        data["err"] = round(float(data["err"].replace(",", ".")), 2)
    except ValueError:
        data["err"] = 0.0
    if not (0 <= data["err"] <= 100):
        data["err"] = 0.0

    any_price = False
    for f in PRICE_FIELDS:
        raw = form.get(f, "").strip()
        if raw:
            if not raw.replace(",", "").replace(".", "").isdigit():
                return data, f"Цена {FORMATS[f]['title'].lower()}: только число"
            kop = round(float(raw.replace(",", ".")) * 100)
            if kop < 1000:
                return data, f"Минимальная цена формата — 10 ₽"
            data[f] = kop
            any_price = True
        else:
            data[f] = None
    if not any_price:
        return data, "Укажите цену хотя бы для одного формата рекламы"
    return data, None


@router.post("/lk/listings/new")
@login_required
async def lk_listing_create(request: Request):
    user = request.state.user
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/lk/listings/new")
    if fail:
        return fail
    data, error = _parse_listing_form(form)
    if error:
        return redirect("/lk/listings/new", error, "error")
    conn = db.get_db()
    try:
        db.execute(conn, """INSERT INTO listings (owner_id, platform, kind, title, link,
                category_id, description, subscribers, err, price_24h, price_48h, price_72h,
                price_repost, price_native, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending', ?)""",
                   (user["id"], data["platform"], data["kind"], data["title"], data["link"],
                    data["category_id"], data["description"], data["subscribers"], data["err"],
                    data["price_24h"], data["price_48h"], data["price_72h"],
                    data["price_repost"], data["price_native"], db.now()))
        db.recalc_price_from(conn, db.scalar(conn, "SELECT last_insert_rowid()"))
    finally:
        conn.close()
    return redirect("/lk/listings", "Площадка отправлена на модерацию", "ok")


@router.get("/lk/listings/{listing_id}/edit")
@login_required
def lk_listing_edit(request: Request, listing_id: int):
    user = request.state.user
    conn = db.get_db()
    try:
        l = db.q1(conn, "SELECT * FROM listings WHERE id=? AND owner_id=? AND status != 'deleted'",
                  (listing_id, user["id"]))
    finally:
        conn.close()
    if not l:
        return redirect("/lk/listings", "Площадка не найдена", "error")
    return render(request, "lk/listing_form.html", l=l,
                  action=f"/lk/listings/{listing_id}/edit",
                  formats=FORMATS, price_fields=PRICE_FIELDS)


@router.post("/lk/listings/{listing_id}/edit")
@login_required
async def lk_listing_update(request: Request, listing_id: int):
    user = request.state.user
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, f"/lk/listings/{listing_id}/edit")
    if fail:
        return fail
    data, error = _parse_listing_form(form)
    if error:
        return redirect(f"/lk/listings/{listing_id}/edit", error, "error")
    conn = db.get_db()
    try:
        l = db.q1(conn, "SELECT * FROM listings WHERE id=? AND owner_id=? AND status != 'deleted'",
                  (listing_id, user["id"]))
        if not l:
            return redirect("/lk/listings", "Площадка не найдена", "error")
        # Изменение площадки после правки → снова на модерацию
        new_status = "pending" if l["status"] == "active" else l["status"]
        db.execute(conn, """UPDATE listings SET platform=?, kind=?, title=?, link=?,
                category_id=?, description=?, subscribers=?, err=?, price_24h=?, price_48h=?,
                price_72h=?, price_repost=?, price_native=?, status=?
                WHERE id=?""",
                   (data["platform"], data["kind"], data["title"], data["link"],
                    data["category_id"], data["description"], data["subscribers"], data["err"],
                    data["price_24h"], data["price_48h"], data["price_72h"],
                    data["price_repost"], data["price_native"], new_status, listing_id))
        db.recalc_price_from(conn, listing_id)
    finally:
        conn.close()
    return redirect("/lk/listings", "Изменения сохранены. Площадка снова на модерации", "ok")


@router.post("/lk/listings/{listing_id}/status")
@login_required
async def lk_listing_status(request: Request, listing_id: int):
    user = request.state.user
    form = await read_form(request)
    action = form.get("action", "")
    conn = db.get_db()
    try:
        fail = validate_csrf_or_flash(request, form, "/lk/listings")
        if fail:
            return fail
        l = db.q1(conn, "SELECT * FROM listings WHERE id=? AND owner_id=? AND status != 'deleted'",
                  (listing_id, user["id"]))
        if not l:
            return redirect("/lk/listings", "Площадка не найдена", "error")
        if action == "pause" and l["status"] == "active":
            db.execute(conn, "UPDATE listings SET status='paused' WHERE id=?", (listing_id,))
            msg = "Площадка поставлена на паузу"
        elif action == "resume" and l["status"] == "paused":
            db.execute(conn, "UPDATE listings SET status='active' WHERE id=?", (listing_id,))
            msg = "Площадка снова активна"
        elif action == "delete":
            db.execute(conn, "UPDATE listings SET status='deleted' WHERE id=?", (listing_id,))
            msg = "Площадка удалена"
        else:
            return redirect("/lk/listings", "Недопустимое действие", "error")
    finally:
        conn.close()
    return redirect("/lk/listings", msg, "ok")


# ── Баланс и пополнение ───────────────────────────────────────────

@router.get("/lk/balance")
@login_required
def lk_balance(request: Request):
    user = request.state.user
    conn = db.get_db()
    try:
        txs = db.q(conn, "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                   (user["id"],))
        pending = [t for t in txs if t["status"] == "pending"]
    finally:
        conn.close()
    return render(request, "lk/balance.html", txs=txs, pending=pending,
                  providers=payments.PROVIDERS, min_dep=config.MIN_DEPOSIT_RUB,
                  max_dep=config.MAX_DEPOSIT_RUB,
                  provider_available=config.provider_available,
                  usdt_rate=config.USDT_RUB_RATE,
                  crypto_providers=payments.CRYPTO_PROVIDERS)


@router.post("/lk/deposit")
@login_required
async def deposit(request: Request):
    user = request.state.user
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/lk/balance")
    if fail:
        return fail
    provider = form.get("provider", "")
    if provider not in payments.PROVIDERS:
        return redirect("/lk/balance", "Выберите способ пополнения", "error")
    raw = form.get("amount", "").replace(" ", "").replace(",", ".")
    try:
        rub = round(float(raw), 2)
    except ValueError:
        return redirect("/lk/balance", "Введите сумму пополнения", "error")
    if not (config.MIN_DEPOSIT_RUB <= rub <= config.MAX_DEPOSIT_RUB):
        return redirect("/lk/balance",
                        f"Сумма: от {config.MIN_DEPOSIT_RUB} до {config.MAX_DEPOSIT_RUB} ₽", "error")
    kop = int(rub * 100)

    conn = db.get_db()
    try:
        tx_id = db.execute(conn, """INSERT INTO transactions
                (user_id, kind, amount_kop, status, provider, comment, created_at)
                VALUES (?, 'deposit', ?, 'pending', ?, ?, ?)""",
                (user["id"], kop, provider,
                 f"Пополнение через {payments.PROVIDERS[provider]['title']}", db.now()))
        tx = db.q1(conn, "SELECT * FROM transactions WHERE id=?", (tx_id,))
    finally:
        conn.close()

    # Демо-режим: если у провайдера не настроены ключи
    if payments.is_demo(provider):
        return redirect(f"/pay/demo/{tx_id}")

    result = await payments.create_payment(tx, provider, form.get("pay_type", "AC"))
    if "error" in result:
        conn = db.get_db()
        try:
            db.execute(conn, "UPDATE transactions SET status='failed' WHERE id=?", (tx_id,))
        finally:
            conn.close()
        return redirect("/lk/balance", result["error"], "error")

    conn = db.get_db()
    try:
        db.execute(conn, "UPDATE transactions SET external_id=? WHERE id=?",
                   (str(result.get("external_id", "")), tx_id))
    finally:
        conn.close()
    return redirect(result["url"], "Инвойс создан, завершите оплату", "ok")


@router.post("/lk/deposit/{tx_id}/check")
@login_required
async def deposit_check(request: Request, tx_id: int):
    user = request.state.user
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/lk/balance")
    if fail:
        return fail
    conn = db.get_db()
    try:
        tx = db.q1(conn, "SELECT * FROM transactions WHERE id=? AND user_id=? AND kind='deposit'",
                   (tx_id, user["id"]))
    finally:
        conn.close()
    if not tx:
        return redirect("/lk/balance", "Пополнение не найдено", "error")
    if tx["status"] == "success":
        return redirect("/lk/balance", "Пополнение уже зачислено", "ok")
    if tx["status"] != "pending":
        return redirect("/lk/balance", "Пополнение не в статусе ожидания", "error")
    if payments.is_demo(tx["provider"]):
        return redirect(f"/pay/demo/{tx_id}")
    result = await payments.check_pending_deposit(db.get_db(), tx)
    if result == "paid":
        return redirect("/lk/balance", "Оплата подтверждена, баланс пополнен!", "ok")
    if result == "error":
        return redirect("/lk/balance", "Не удалось связаться с провайдером, попробуйте позже", "error")
    return redirect("/lk/balance", "Оплата пока не поступила. Если вы оплатили — подождите пару минут",
                    "warn")


# ── Покупки и продажи ─────────────────────────────────────────────

@router.post("/order")
@login_required
async def create_order(request: Request):
    user = request.state.user
    form = await read_form(request)
    listing_id = form.get("listing_id", "")
    back = f"/listing/{listing_id}" if listing_id.isdigit() else "/catalog"
    fail = validate_csrf_or_flash(request, form, back)
    if fail:
        return fail

    conn = db.get_db()
    try:
        l = db.q1(conn, "SELECT * FROM listings WHERE id=? AND status='active'",
                  (int(listing_id) if listing_id.isdigit() else 0,))
        if not l:
            return redirect("/catalog", "Площадка не найдена или неактивна", "error")
        if l["owner_id"] == user["id"]:
            return redirect(f"/listing/{l['id']}", "Нельзя заказать рекламу на своей площадке", "error")
        fmt_code = form.get("fmt", "")
        meta = FORMATS.get(fmt_code)
        if not meta:
            return redirect(back, "Выберите формат рекламы", "error")
        price = l[meta["field"]]
        if price is None:
            return redirect(back, "Такой формат недоступен на этой площадке", "error")
        comment = form.get("comment", "").strip()[:2000]
        if len(comment) < 10:
            return redirect(back, "Опишите рекламные материалы (мин. 10 символов)", "error")
        contact = form.get("contact", "").strip()[:200]
        if not contact:
            return redirect(back, "Укажите контакт для связи", "error")

        commission = round(price * config.COMMISSION_PCT / 100)
        buyer = db.q1(conn, "SELECT * FROM users WHERE id=?", (user["id"],))
        if buyer["balance_kop"] < price:
            return redirect("/lk/balance",
                            f"Недостаточно средств: нужно {fmt(price)}. Пополните баланс", "error")

        # Списание в эскроу + транзакция
        db.execute(conn, "UPDATE users SET balance_kop = balance_kop - ? WHERE id=?",
                   (price, user["id"]))
        db.execute(conn, """INSERT INTO transactions (user_id, kind, amount_kop, status, comment, created_at)
                            VALUES (?, 'order_hold', ?, 'success', ?, ?)""",
                   (user["id"], -price, f"Бронь за рекламу: {l['title']}", db.now()))
        order_id = db.execute(conn, """INSERT INTO orders
                (listing_id, buyer_id, fmt, price_kop, commission_kop, comment, contact,
                 status, created_at) VALUES (?,?,?,?,?,?,?, 'new', ?)""",
                (l["id"], user["id"], fmt_code, price, commission, comment, contact, db.now()))
    finally:
        conn.close()
    return redirect("/lk/orders", f"Заказ #{order_id} создан. Средства забронированы в эскроу", "ok")


def _order_guard(conn, request: Request, order_id: int):
    """Загружает заказ с проверкой прав. Возвращает (order, listing, error_response)."""
    user = request.state.user
    order = db.q1(conn, "SELECT * FROM orders WHERE id=?", (order_id,))
    if not order:
        return None, None, redirect("/lk", "Заказ не найден", "error")
    listing = db.q1(conn, "SELECT * FROM listings WHERE id=?", (order["listing_id"],))
    is_buyer = order["buyer_id"] == user["id"]
    is_owner = listing["owner_id"] == user["id"]
    return order, listing, (is_buyer, is_owner)


def _refund_order(conn, order: dict, new_status: str) -> None:
    db.add_balance(conn, order["buyer_id"], order["price_kop"])
    db.execute(conn, """INSERT INTO transactions (user_id, kind, amount_kop, status, comment, created_at)
                        VALUES (?, 'order_refund', ?, 'success', ?, ?)""",
               (order["buyer_id"], order["price_kop"],
                f"Возврат по заказу #{order['id']}", db.now()))
    db.execute(conn, "UPDATE orders SET status=?, closed_at=? WHERE id=?",
               (new_status, db.now(), order["id"]))


def _payout_order(conn, order: dict) -> None:
    payout = order["price_kop"] - order["commission_kop"]
    db.add_balance(conn, order["listing_owner_id"], payout)
    db.execute(conn, """INSERT INTO transactions (user_id, kind, amount_kop, status, comment, created_at)
                        VALUES (?, 'order_payout', ?, 'success', ?, ?)""",
               (order["listing_owner_id"], payout,
                f"Выплата за заказ #{order['id']} (комиссия {fmt(order['commission_kop'])})", db.now()))
    db.execute(conn, "UPDATE orders SET status='completed', closed_at=? WHERE id=?",
               (db.now(), order["id"]))


@router.get("/lk/orders")
@login_required
def lk_orders(request: Request):
    user = request.state.user
    conn = db.get_db()
    try:
        rows = db.q(conn, """
            SELECT o.*, l.title AS listing_title, l.platform, l.kind, l.link,
                   u.name AS owner_name
            FROM orders o
            JOIN listings l ON l.id = o.listing_id
            LEFT JOIN users u ON u.id = l.owner_id
            WHERE o.buyer_id = ? ORDER BY o.created_at DESC""", (user["id"],))
    finally:
        conn.close()
    for o in rows:
        o["fmt_title"] = FORMATS.get(o["fmt"], {}).get("title", o["fmt"])
    return render(request, "lk/orders.html", orders=rows, order_status=ORDER_STATUS, role="buyer")


@router.get("/lk/sales")
@login_required
def lk_sales(request: Request):
    user = request.state.user
    conn = db.get_db()
    try:
        rows = db.q(conn, """
            SELECT o.*, l.title AS listing_title, l.platform, l.kind, l.link,
                   l.owner_id AS listing_owner_id, u.name AS buyer_name, u.email AS buyer_email,
                   u.tg_username AS buyer_tg
            FROM orders o
            JOIN listings l ON l.id = o.listing_id
            LEFT JOIN users u ON u.id = o.buyer_id
            WHERE l.owner_id = ? ORDER BY o.created_at DESC""", (user["id"],))
    finally:
        conn.close()
    for o in rows:
        o["fmt_title"] = FORMATS.get(o["fmt"], {}).get("title", o["fmt"])
    return render(request, "lk/sales.html", orders=rows, order_status=ORDER_STATUS, role="seller")


@router.post("/orders/{order_id}/action")
@login_required
async def order_action(request: Request, order_id: int):
    user = request.state.user
    form = await read_form(request)
    action = form.get("action", "")
    conn = db.get_db()
    try:
        fail = validate_csrf_or_flash(request, form, "/lk")
        if fail:
            return fail
        order = db.q1(conn, """
            SELECT o.*, l.owner_id AS listing_owner_id, l.title AS listing_title
            FROM orders o JOIN listings l ON l.id = o.listing_id WHERE o.id=?""", (order_id,))
        if not order:
            return redirect("/lk", "Заказ не найден", "error")
        is_buyer = order["buyer_id"] == user["id"]
        is_owner = order["listing_owner_id"] == user["id"]

        # ── Владелец: принять / отклонить / разместить
        if action == "accept" and is_owner and order["status"] == "new":
            db.execute(conn, "UPDATE orders SET status='accepted' WHERE id=?", (order_id,))
            return redirect("/lk/sales", "Заказ принят в работу", "ok")
        if action == "decline" and is_owner and order["status"] == "new":
            _refund_order(conn, order, "declined")
            return redirect("/lk/sales", "Заказ отклонён, средства возвращены рекламодателю", "ok")
        if action == "publish" and is_owner and order["status"] == "accepted":
            db.execute(conn, "UPDATE orders SET status='published', published_at=? WHERE id=?",
                       (db.now(), order_id))
            return redirect("/lk/sales", "Заказ отмечен как размещённый", "ok")

        # ── Покупатель: отменить / принять работу / спор
        if action == "cancel" and is_buyer and order["status"] == "new":
            _refund_order(conn, order, "cancelled")
            return redirect("/lk/orders", "Заказ отменён, средства возвращены на баланс", "ok")
        if action == "complete" and is_buyer and order["status"] == "published":
            _payout_order(conn, order)
            return redirect("/lk/orders", "Работа принята! Оставьте отзыв на странице площадки", "ok")
        if action == "dispute" and is_buyer and order["status"] == "published":
            reason = form.get("reason", "").strip()[:500] or "Причина не указана"
            db.execute(conn, "UPDATE orders SET status='disputed', dispute_reason=? WHERE id=?",
                       (reason, order_id))
            return redirect("/lk/orders", "Спор открыт. Администратор рассмотрит его", "warn")

        return redirect("/lk", "Действие недоступно для этого статуса заказа", "error")
    finally:
        conn.close()


@router.post("/listing/{listing_id}/review")
@login_required
async def leave_review(request: Request, listing_id: int):
    user = request.state.user
    form = await read_form(request)
    back = f"/listing/{listing_id}"
    fail = validate_csrf_or_flash(request, form, back)
    if fail:
        return fail
    try:
        rating = int(form.get("rating", "0"))
    except ValueError:
        rating = 0
    text = form.get("text", "").strip()[:1000]
    if not (1 <= rating <= 5):
        return redirect(back, "Поставьте оценку от 1 до 5", "error")
    if len(text) < 5:
        return redirect(back, "Напишите пару слов о сотрудничестве", "error")
    conn = db.get_db()
    try:
        order = db.q1(conn, """SELECT id FROM orders WHERE listing_id=? AND buyer_id=?
                               AND status='completed' LIMIT 1""", (listing_id, user["id"]))
        if not order:
            return redirect(back, "Отзыв можно оставить после завершённого заказа", "error")
        if db.q1(conn, "SELECT id FROM reviews WHERE order_id=?", (order["id"],)):
            return redirect(back, "Вы уже оставляли отзыв по этой площадке", "error")
        db.execute(conn, """INSERT INTO reviews (listing_id, order_id, author_id, rating, text, created_at)
                            VALUES (?,?,?,?,?,?)""",
                   (listing_id, order["id"], user["id"], rating, text, db.now()))
    finally:
        conn.close()
    return redirect(back, "Спасибо за отзыв!", "ok")
