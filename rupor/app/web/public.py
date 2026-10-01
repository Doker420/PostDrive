"""Публичные страницы: главная, каталог, карточка площадки, «как это работает»."""
import math

from fastapi import APIRouter, Request

from .. import db
from ..auth import get_user
from ..formats import price_map
from .helpers import render

router = APIRouter()
PER_PAGE = 20

SORTS = {
    "subs_desc": ("Самые крупные", "subscribers DESC"),
    "subs_asc": ("Самые маленькие", "subscribers ASC"),
    "price_asc": ("Сначала дешёвые", "price_from ASC"),
    "price_desc": ("Сначала дорогие", "price_from DESC"),
    "new": ("Новые", "created_at DESC"),
    "er_desc": ("Высокая вовлечённость", "err DESC"),
}


@router.get("/")
def index(request: Request):
    conn = db.get_db()
    try:
        stats = {
            "listings": db.scalar(conn, "SELECT COUNT(*) FROM listings WHERE status='active'"),
            "subscribers": db.scalar(conn, "SELECT COALESCE(SUM(subscribers),0) FROM listings WHERE status='active'"),
            "owners": db.scalar(conn, "SELECT COUNT(DISTINCT owner_id) FROM listings WHERE status='active'"),
            "orders": db.scalar(conn, "SELECT COUNT(*) FROM orders"),
        }
        featured = db.q(conn, """
            SELECT l.*, u.name AS owner_name, c.name AS category_name, c.emoji AS category_emoji
            FROM listings l
            LEFT JOIN users u ON u.id = l.owner_id
            LEFT JOIN categories c ON c.id = l.category_id
            WHERE l.status='active'
            ORDER BY l.verified DESC, l.subscribers DESC LIMIT 8
        """)
        categories = db.q(conn, """
            SELECT c.*, COUNT(l.id) AS cnt FROM categories c
            LEFT JOIN listings l ON l.category_id = c.id AND l.status='active'
            GROUP BY c.id ORDER BY cnt DESC, c.sort
        """)
    finally:
        conn.close()
    for l in featured:
        l["formats"] = price_map(l)
    return render(request, "index.html", stats=stats, featured=featured,
                  categories=categories)


@router.get("/catalog")
def catalog(request: Request):
    p = request.query_params
    platform = p.get("platform", "")
    kind = p.get("kind", "")
    category = p.get("category", "")
    q = p.get("q", "").strip()
    price_min = p.get("price_min", "").strip()
    price_max = p.get("price_max", "").strip()
    subs_min = p.get("subs_min", "").strip()
    subs_max = p.get("subs_max", "").strip()
    sort = p.get("sort", "subs_desc")
    page = max(1, int(p.get("page", "1") or 1))

    where = ["l.status = 'active'"]
    params: list = []
    if platform in ("telegram", "vk"):
        where.append("l.platform = ?")
        params.append(platform)
    if kind in ("channel", "chat", "bot"):
        where.append("l.kind = ?")
        params.append(kind)
    if category.isdigit():
        where.append("l.category_id = ?")
        params.append(int(category))
    if q:
        where.append("(l.title LIKE ? OR l.description LIKE ? OR l.link LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if price_min.isdigit():
        where.append("COALESCE(l.price_from, 0) >= ?")
        params.append(int(price_min) * 100)
    if price_max.isdigit():
        where.append("COALESCE(l.price_from, 99999999999) <= ?")
        params.append(int(price_max) * 100)
    if subs_min.isdigit():
        where.append("l.subscribers >= ?")
        params.append(int(subs_min))
    if subs_max.isdigit():
        where.append("l.subscribers <= ?")
        params.append(int(subs_max))

    order_by = SORTS.get(sort, SORTS["subs_desc"])[1]
    where_sql = " AND ".join(where)

    conn = db.get_db()
    try:
        total = db.scalar(conn, f"SELECT COUNT(*) FROM listings l WHERE {where_sql}", tuple(params))
        pages = max(1, math.ceil(total / PER_PAGE))
        page = min(page, pages)
        rows = db.q(conn, f"""
            SELECT l.*, u.name AS owner_name, c.name AS category_name, c.emoji AS category_emoji
            FROM listings l
            LEFT JOIN users u ON u.id = l.owner_id
            LEFT JOIN categories c ON c.id = l.category_id
            WHERE {where_sql}
            ORDER BY {order_by} LIMIT ? OFFSET ?
        """, tuple(params + [PER_PAGE, (page - 1) * PER_PAGE]))
        categories = db.q(conn, "SELECT * FROM categories ORDER BY sort, name")
    finally:
        conn.close()

    for l in rows:
        l["formats"] = price_map(l)

    filters = {k: v for k, v in {
        "platform": platform, "kind": kind, "category": category, "q": q,
        "price_min": price_min, "price_max": price_max,
        "subs_min": subs_min, "subs_max": subs_max, "sort": sort,
    }.items()}
    return render(request, "catalog.html", listings=rows, total=total, page=page,
                  pages=pages, filters=filters, categories=categories,
                  sorts=SORTS, cur_cat=category)


@router.get("/listing/{listing_id}")
def listing_page(request: Request, listing_id: int):
    conn = db.get_db()
    try:
        user = get_user(conn, request)
        l = db.q1(conn, """
            SELECT l.*, u.name AS owner_name, u.tg_username AS owner_tg, u.id AS owner_id,
                   c.name AS category_name, c.emoji AS category_emoji
            FROM listings l
            LEFT JOIN users u ON u.id = l.owner_id
            LEFT JOIN categories c ON c.id = l.category_id
            WHERE l.id = ?
        """, (listing_id,))
        if not l or l["status"] == "deleted":
            return render(request, "error.html", status_code=404,
                          code=404, message="Площадка не найдена")
        is_owner = bool(user and user["id"] == l["owner_id"])
        is_admin = bool(user and user["is_admin"])
        if l["status"] not in ("active", "paused") and not (is_owner or is_admin):
            return render(request, "error.html", status_code=404,
                          code=404, message="Площадка недоступна")
        if l["status"] == "active":
            db.execute(conn, "UPDATE listings SET views = views + 1 WHERE id = ?", (listing_id,))
        reviews = db.q(conn, """
            SELECT r.*, u.name AS author_name FROM reviews r
            LEFT JOIN users u ON u.id = r.author_id
            WHERE r.listing_id = ? ORDER BY r.created_at DESC LIMIT 30
        """, (listing_id,))
        rating_avg = db.scalar(conn, "SELECT AVG(rating) FROM reviews WHERE listing_id = ?", (listing_id,))
        can_review = False
        if user:
            can_review = bool(db.q1(conn, """
                SELECT id FROM orders WHERE listing_id=? AND buyer_id=? AND status='completed'
            """, (listing_id, user["id"])))
    finally:
        conn.close()

    l["formats"] = price_map(l)
    return render(request, "listing.html", l=l, reviews=reviews,
                  rating_avg=rating_avg, can_review=can_review, is_owner=is_owner)


@router.get("/how")
def how(request: Request):
    return render(request, "how.html")
