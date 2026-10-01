"""Админ-панель: модерация площадок, пользователи, транзакции, споры."""
from fastapi import APIRouter, Request

from .. import db
from ..auth import login_required
from ..formats import ORDER_STATUS, price_map
from .helpers import read_form, redirect, render, validate_csrf_or_flash

router = APIRouter()


def admin_guard(request: Request):
    """Редирект, если пользователь не админ. Вызывается внутри handlers."""
    user = getattr(request.state, "user", None)
    if not user:
        resp = redirect("/login?next=/admin", "Войдите как администратор", "warn")
        return resp
    if not user["is_admin"]:
        return redirect("/", "Раздел только для администраторов", "error")
    return None


@router.get("/admin")
@login_required
def admin_dashboard(request: Request):
    guard = admin_guard(request)
    if guard:
        return guard
    conn = db.get_db()
    try:
        stats = {
            "users": db.scalar(conn, "SELECT COUNT(*) FROM users"),
            "listings_active": db.scalar(conn, "SELECT COUNT(*) FROM listings WHERE status='active'"),
            "listings_pending": db.scalar(conn, "SELECT COUNT(*) FROM listings WHERE status='pending'"),
            "orders": db.scalar(conn, "SELECT COUNT(*) FROM orders"),
            "gmv_kop": db.scalar(conn, "SELECT COALESCE(SUM(price_kop),0) FROM orders WHERE status='completed'"),
            "commission_kop": db.scalar(conn, "SELECT COALESCE(SUM(commission_kop),0) FROM orders WHERE status='completed'"),
            "deposits_kop": db.scalar(conn, "SELECT COALESCE(SUM(amount_kop),0) FROM transactions WHERE kind='deposit' AND status='success'"),
        }
        pending = db.q(conn, """
            SELECT l.*, u.email AS owner_email, c.name AS category_name FROM listings l
            LEFT JOIN users u ON u.id = l.owner_id
            LEFT JOIN categories c ON c.id = l.category_id
            WHERE l.status='pending' ORDER BY l.created_at""")
        disputes = db.q(conn, """
            SELECT o.*, l.title AS listing_title, ub.email AS buyer_email
            FROM orders o
            JOIN listings l ON l.id = o.listing_id
            LEFT JOIN users ub ON ub.id = o.buyer_id
            WHERE o.status='disputed' ORDER BY o.created_at""")
    finally:
        conn.close()
    for l in pending:
        l["formats"] = price_map(l)
    return render(request, "admin/dashboard.html", stats=stats, pending=pending,
                  disputes=disputes, order_status=ORDER_STATUS)


@router.post("/admin/listings/{listing_id}/moderate")
@login_required
async def moderate_listing(request: Request, listing_id: int):
    guard = admin_guard(request)
    if guard:
        return guard
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/admin")
    if fail:
        return fail
    action = form.get("action", "")
    if action not in ("approve", "reject"):
        return redirect("/admin", "Неизвестное действие", "error")
    conn = db.get_db()
    try:
        l = db.q1(conn, "SELECT * FROM listings WHERE id=? AND status='pending'", (listing_id,))
        if not l:
            return redirect("/admin", "Площадка не в очереди модерации", "error")
        if action == "approve":
            db.execute(conn, "UPDATE listings SET status='active', reject_reason='' WHERE id=?",
                       (listing_id,))
            msg = "Площадка одобрена и опубликована"
        else:
            reason = form.get("reason", "").strip()[:300] or "Не соответствует правилам площадки"
            db.execute(conn, "UPDATE listings SET status='rejected', reject_reason=? WHERE id=?",
                       (reason, listing_id))
            msg = f"Площадка отклонена: {reason}"
    finally:
        conn.close()
    return redirect("/admin", msg, "ok")


@router.post("/admin/listings/{listing_id}/verify")
@login_required
async def toggle_verify(request: Request, listing_id: int):
    guard = admin_guard(request)
    if guard:
        return guard
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/admin")
    if fail:
        return fail
    conn = db.get_db()
    try:
        l = db.q1(conn, "SELECT id, verified, status FROM listings WHERE id=?", (listing_id,))
        if not l or l["status"] not in ("active", "paused"):
            return redirect("/admin", "Площадка не найдена", "error")
        db.execute(conn, "UPDATE listings SET verified = 1 - verified WHERE id=?", (listing_id,))
        msg = "Галочка подтверждения переключена"
    finally:
        conn.close()
    return redirect("/admin", msg, "ok")


@router.get("/admin/users")
@login_required
def admin_users(request: Request):
    guard = admin_guard(request)
    if guard:
        return guard
    conn = db.get_db()
    try:
        rows = db.q(conn, """SELECT u.*,
                             (SELECT COUNT(*) FROM listings WHERE owner_id=u.id AND status='active') AS listings_cnt,
                             (SELECT COUNT(*) FROM orders WHERE buyer_id=u.id) AS orders_cnt
                             FROM users u ORDER BY u.created_at DESC""")
    finally:
        conn.close()
    return render(request, "admin/users.html", users=rows)


@router.post("/admin/users/{user_id}/action")
@login_required
async def admin_user_action(request: Request, user_id: int):
    guard = admin_guard(request)
    if guard:
        return guard
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/admin/users")
    if fail:
        return fail
    me = request.state.user
    action = form.get("action", "")
    conn = db.get_db()
    try:
        target = db.q1(conn, "SELECT * FROM users WHERE id=?", (user_id,))
        if not target:
            return redirect("/admin/users", "Пользователь не найден", "error")
        if target["id"] == me["id"] and action in ("ban", "unban"):
            return redirect("/admin/users", "Нельзя заблокировать себя", "error")
        if action == "ban":
            db.execute(conn, "UPDATE users SET banned=1 WHERE id=?", (user_id,))
            db.execute(conn, "DELETE FROM sessions WHERE user_id=?", (user_id,))
            msg = "Пользователь заблокирован"
        elif action == "unban":
            db.execute(conn, "UPDATE users SET banned=0 WHERE id=?", (user_id,))
            msg = "Пользователь разблокирован"
        elif action == "adjust":
            raw = form.get("amount", "").replace(" ", "").replace(",", ".")
            try:
                kop = int(round(float(raw) * 100))
            except ValueError:
                return redirect("/admin/users", "Введите сумму корректировки", "error")
            if kop == 0:
                return redirect("/admin/users", "Сумма не может быть нулевой", "error")
            db.add_balance(conn, user_id, kop)
            db.execute(conn, """INSERT INTO transactions (user_id, kind, amount_kop, status,
                                comment, created_at) VALUES (?, 'admin_adjust', ?, 'success', ?, ?)""",
                       (user_id, kop, f"Корректировка администратором", db.now()))
            msg = f"Баланс изменён на {kop/100:.2f} ₽"
        else:
            return redirect("/admin/users", "Неизвестное действие", "error")
    finally:
        conn.close()
    return redirect("/admin/users", msg, "ok")


@router.get("/admin/transactions")
@login_required
def admin_transactions(request: Request):
    guard = admin_guard(request)
    if guard:
        return guard
    conn = db.get_db()
    try:
        rows = db.q(conn, """SELECT t.*, u.email AS user_email FROM transactions t
                             LEFT JOIN users u ON u.id = t.user_id
                             ORDER BY t.created_at DESC LIMIT 200""")
        pending_deposits = [t for t in rows if t["kind"] == "deposit" and t["status"] == "pending"]
    finally:
        conn.close()
    return render(request, "admin/transactions.html", txs=rows, pending=pending_deposits)


@router.post("/admin/tx/{tx_id}/confirm")
@login_required
async def admin_confirm_deposit(request: Request, tx_id: int):
    guard = admin_guard(request)
    if guard:
        return guard
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/admin/transactions")
    if fail:
        return fail
    from .. import payments
    conn = db.get_db()
    try:
        ok = payments.credit_deposit(conn, tx_id, "manual:admin")
    finally:
        conn.close()
    if ok:
        return redirect("/admin/transactions", "Пополнение зачислено вручную", "ok")
    return redirect("/admin/transactions", "Не удалось зачислить (не pending-депозит)", "error")


@router.post("/admin/orders/{order_id}/resolve")
@login_required
async def resolve_dispute(request: Request, order_id: int):
    guard = admin_guard(request)
    if guard:
        return guard
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, "/admin")
    if fail:
        return fail
    decision = form.get("decision", "")
    if decision not in ("refund", "payout"):
        return redirect("/admin", "Выберите решение: возврат или выплата", "error")
    conn = db.get_db()
    try:
        order = db.q1(conn, """SELECT o.*, l.owner_id AS listing_owner_id
                               FROM orders o JOIN listings l ON l.id = o.listing_id
                               WHERE o.id=? AND o.status='disputed'""", (order_id,))
        if not order:
            return redirect("/admin", "Спор не найден или уже решён", "error")
        if decision == "refund":
            from .account import _refund_order
            _refund_order(conn, order, "refunded")
            msg = "Спор решён: средства возвращены рекламодателю"
        else:
            from .account import _payout_order
            _payout_order(conn, order)
            msg = "Спор решён: средства выплачены владельцу"
    finally:
        conn.close()
    return redirect("/admin", msg, "ok")
