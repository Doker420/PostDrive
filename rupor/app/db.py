"""SQLite-слой «Рупор»: схема, миграции, простые помощники.

Деньги хранятся целыми числами в копейках — никаких float в финансах.
"""
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    pass_hash     TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    tg_username   TEXT NOT NULL DEFAULT '',
    vk_url        TEXT NOT NULL DEFAULT '',
    is_admin      INTEGER NOT NULL DEFAULT 0,
    banned        INTEGER NOT NULL DEFAULT 0,
    balance_kop   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug  TEXT NOT NULL UNIQUE,
    name  TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    sort  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS listings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform       TEXT NOT NULL CHECK (platform IN ('telegram','vk')),
    kind           TEXT NOT NULL CHECK (kind IN ('channel','chat','bot')),
    title          TEXT NOT NULL,
    link           TEXT NOT NULL,
    category_id    INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    description    TEXT NOT NULL DEFAULT '',
    subscribers    INTEGER NOT NULL DEFAULT 0,
    err            REAL NOT NULL DEFAULT 0,          -- вовлечённость, %
    price_24h      INTEGER,                          -- всё в копейках
    price_48h      INTEGER,
    price_72h      INTEGER,
    price_repost   INTEGER,
    price_native   INTEGER,
    price_from     INTEGER,                          -- вычисляется: мин. цена формата
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('draft','pending','active','rejected','paused','deleted')),
    reject_reason  TEXT NOT NULL DEFAULT '',
    verified       INTEGER NOT NULL DEFAULT 0,
    views          INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id     INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    buyer_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fmt            TEXT NOT NULL,
    price_kop      INTEGER NOT NULL,
    commission_kop INTEGER NOT NULL DEFAULT 0,
    comment        TEXT NOT NULL DEFAULT '',   -- рекламные материалы
    contact        TEXT NOT NULL DEFAULT '',   -- связь с владельцем
    status         TEXT NOT NULL DEFAULT 'new'
                   CHECK (status IN ('new','accepted','published','completed',
                                     'declined','cancelled','disputed','refunded')),
    dispute_reason TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    published_at   TEXT,
    closed_at      TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,   -- deposit|order_hold|order_refund|order_payout|admin_adjust
    amount_kop   INTEGER NOT NULL,  -- подпись: + приход, - расход
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|success|failed|canceled
    provider     TEXT NOT NULL DEFAULT '',
    external_id  TEXT NOT NULL DEFAULT '',
    comment      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_platform ON listings(platform);
CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(category_id);
CREATE INDEX IF NOT EXISTS idx_orders_listing ON orders(listing_id);
CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
"""


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_db() -> sqlite3.Connection:
    """Новое соединение на запрос (синхронные обработчики FastAPI)."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ── Помощники запросов ────────────────────────────────────────────

def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    """Все строки результата в виде списка dict."""
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def q1(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[dict]:
    """Первая строка или None."""
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def execute(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    """INSERT/UPDATE/DELETE + commit. Возвращает lastrowid."""
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def add_balance(conn: sqlite3.Connection, user_id: int, delta_kop: int) -> None:
    execute(conn, "UPDATE users SET balance_kop = balance_kop + ? WHERE id = ?",
            (delta_kop, user_id))


def recalc_price_from(conn: sqlite3.Connection, listing_id: int) -> None:
    execute(conn, """
        UPDATE listings SET price_from = (
            SELECT MIN(v) FROM (
                SELECT price_24h AS v UNION ALL SELECT price_48h
                UNION ALL SELECT price_72h UNION ALL SELECT price_repost
                UNION ALL SELECT price_native
            ) WHERE v IS NOT NULL
        ) WHERE id = ?
    """, (listing_id,))


def delete_expired_sessions(conn: sqlite3.Connection) -> None:
    execute(conn, "DELETE FROM sessions WHERE expires_at < ?", (now(),))
