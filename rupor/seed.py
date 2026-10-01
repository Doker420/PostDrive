"""Демо-данные для «Рупор»: python seed.py [--force].

Создаёт категории, демо-аккаунты и площадки, чтобы каталог не был пустым.
Внимание: для продакшена не запускайте (или запускайте без --force —
категории идемпотентны, демо-данные добавляются только в пустую базу).
"""
import sys

from app import db
from app.auth import hash_password

CATEGORIES = [
    ("news",     "Новости и медиа", "📰", 1),
    ("crypto",   "Криптовалюты и финансы", "🪙", 2),
    ("tech",     "Технологии и IT", "💻", 3),
    ("business", "Бизнес и маркетинг", "📈", 4),
    ("humor",    "Юмор и мемы", "😂", 5),
    ("games",    "Игры и киберспорт", "🎮", 6),
    ("sport",    "Спорт", "⚽", 7),
    ("lifestyle","Лайфстайл и красота", "💅", 8),
    ("education","Образование и языки", "🎓", 9),
    ("auto",     "Авто", "🚗", 10),
    ("cinema",   "Музыка и кино", "🎬", 11),
    ("psych",    "Психология и отношения", "🧠", 12),
    ("chats",    "Общение и чаты", "💬", 13),
    ("bots",     "Боты и сервисы", "🤖", 14),
]

OWNERS = [
    ("owner@rupor.ru", "owner1234", "МедиаГрупп «Северный ветер»", "@severwind_media"),
    ("owner2@rupor.ru", "owner1234", "VK Продакшн", "", "https://vk.com/vkproduction"),
    ("owner3@rupor.ru", "owner1234", "TG Network", "@tgnetwork_admin"),
]

# (owner_idx, platform, kind, title, link, category_slug, subs, er, desc,
#  p24, p48, p72, repost, native, verified)
LISTINGS = [
    (0, "telegram", "channel", "Криптоновости СНГ", "@cryptonews_sng", "crypto", 84500, 11.2,
     "Главные новости крипторы на русском: аналитика, дайджесты, разборы сделок. Аудитория 18–40, 70% РФ.\nНе размещаем: хайпы, скам, казино.", 18000, 26000, 32000, 9000, 42000, 1),
    (0, "telegram", "channel", "Технологии завтра", "@techzavtra", "tech", 152000, 7.8,
     "Наука, гаджеты, ИИ и стартапы — коротко и по делу. Охват поста ~25 000.", 52000, 74000, 92000, 28000, 120000, 1),
    (0, "telegram", "chat", "Криптотрейдеры | Чат", "@cryptotraders_chat", "chats", 12300, 0,
     "Активный чат трейдеров: 400+ сообщений в день. Реклама — закреп + сообщение.", 6000, None, None, 3500, None, 0),
    (1, "vk", "channel", "Мемы про работу | VK", "https://vk.com/workmemes", "humor", 210000, 9.5,
     "Самый тёплый паблик про офисную жизнь. Охваты поста 30–60k, много репостов.", 15000, 22000, 28000, 7000, 35000, 0),
    (1, "vk", "channel", "АвтоВести", "https://vk.com/autovesti", "auto", 96000, 6.2,
     "Новости автоиндустрии, обзоры, тест-драйвы. Мужская аудитория 25–45.", 21000, 30000, 38000, 11000, 48000, 0),
    (1, "vk", "chat", "Беседа предпринимателей", "https://vk.com/im?sel=-bizchat", "business", 4800, 0,
     "Закрытая беседа владельцев малого бизнеса. Обсуждение налогов, поставок, маркетинга.", 4500, None, None, None, 12000, 0),
    (2, "telegram", "channel", "Психология простыми словами", "@psyhologiya", "psych", 68000, 14.1,
     "Отношения, самооценка, тревожность — статьи и практики. Аудитория 75% женщины 20–45.", 14000, 20000, 25000, 8000, 30000, 1),
    (2, "telegram", "bot", "Бот «Найди подписчиков»", "@findsub_bot", "bots", 32000, 0,
     "Сервис-бот по продвижению каналов, 8 000 активных пользователей в сутки.\nРеклама: сообщение всем пользователям бота.", 9000, None, None, None, 25000, 0),
    (2, "telegram", "channel", "Игровая зона", "@gamezone_tg", "games", 45000, 10.3,
     "Игровые новости, розыгрыши ключей, стримы. Аудитория 14–28.", 9000, 13000, 16000, 5000, 21000, 0),
    (0, "telegram", "channel", "Английский каждый день", "@english_daily", "education", 77000, 12.0,
     "Слова, идиомы и мини-уроки. Студенты и саморазвитие.", 11000, 16000, 20000, 6000, 27000, 0),
    (1, "vk", "channel", "Кино и сериалы HD", "https://vk.com/kinohdclub", "cinema", 175000, 8.0,
     "Подборки фильмов, рецензии, новости индустрии. Охват поста 20–45k.", 13000, 19000, 24000, 6000, 30000, 0),
    (2, "telegram", "channel", "Лайфстайл и красота", "@beauty_life", "lifestyle", 39000, 15.7,
     "Уход, макияж, разборы косметики. 80% женщины 18–35.", 8000, 11500, 14500, 4500, 19000, 0),
    (0, "telegram", "chat", "Чат маркетологов", "@marketchat", "business", 8700, 0,
     "Чат профильных маркетологов: таргет, SMM, перформанс. Реклама — сообщение днём.", 5500, None, None, 3000, 9000, 0),
    (2, "telegram", "channel", "Спорт Обзор", "@sportobzor", "sport", 54000, 9.0,
     "Футбол, хоккей, итоги матчей. Ставки не рекламируем.", 10000, 15000, 18000, 5500, 26000, 0),
]

RUB = lambda r: r * 100  # noqa: E731


def main() -> None:
    force = "--force" in sys.argv
    if force:
        # Полный сброс базы (только для разработки!)
        import os
        if os.path.exists(db.config.DB_PATH):
            os.remove(db.config.DB_PATH)
            for suffix in ("-wal", "-shm"):
                p = db.config.DB_PATH + suffix
                if os.path.exists(p):
                    os.remove(p)
        print("⚠️  База сброшена (--force)")
    db.init_db()
    conn = db.get_db()
    try:
        # Категории — идемпотентно
        for slug, name, emoji, sort in CATEGORIES:
            existing = db.q1(conn, "SELECT id FROM categories WHERE slug=?", (slug,))
            if not existing:
                db.execute(conn, "INSERT INTO categories (slug, name, emoji, sort) VALUES (?,?,?,?)",
                           (slug, name, emoji, sort))
        cats = {c["slug"]: c["id"] for c in db.q(conn, "SELECT * FROM categories")}

        has_users = db.scalar(conn, "SELECT COUNT(*) FROM users") > 0
        if has_users and not force:
            print("База не пуста — демо-данные пропущены (используйте --force для добавления).")
            return
        if force or not has_users:
            # Демо-админ + владельцы + рекламодатель
            admin_id = db.execute(conn, """INSERT INTO users
                (email, pass_hash, name, is_admin, created_at) VALUES (?,?,?,?,?)""",
                ("admin@rupor.ru", hash_password("admin1234"), "Администрация", 1, db.now()))
            owner_ids = []
            for email, pwd, name, tg, *vk in OWNERS:
                vk_url = vk[0] if vk else ""
                owner_ids.append(db.execute(conn, """INSERT INTO users
                    (email, pass_hash, name, tg_username, vk_url, balance_kop, created_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (email, hash_password(pwd), name, tg, vk_url, 0, db.now())))
            adv_id = db.execute(conn, """INSERT INTO users
                (email, pass_hash, name, tg_username, balance_kop, created_at) VALUES (?,?,?,?,?,?)""",
                ("advertiser@rupor.ru", hash_password("adv1234"), "Рекламодатель",
                 "@advertiser", RUB(50000), db.now()))

            for (oi, platform, kind, title, link, cat, subs, er, desc,
                 p24, p48, p72, repost, native, verified) in LISTINGS:
                lid = db.execute(conn, """INSERT INTO listings
                    (owner_id, platform, kind, title, link, category_id, description,
                     subscribers, err, price_24h, price_48h, price_72h, price_repost,
                     price_native, status, verified, views, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'active',?,?,?)""",
                    (owner_ids[oi], platform, kind, title, link, cats[cat], desc, subs, er,
                     RUB(p24), RUB(p48) if p48 else None, RUB(p72) if p72 else None,
                     RUB(repost) if repost else None, RUB(native) if native else None,
                     verified, 150 + oi * 40, db.now()))
                db.recalc_price_from(conn, lid)
    finally:
        conn.close()
    print("✅ Демо-данные готовы.")
    print("   Админ:          admin@rupor.ru / admin1234")
    print("   Владельцы:      owner@rupor.ru, owner2@rupor.ru, owner3@rupor.ru / owner1234")
    print("   Рекламодатель:  advertiser@rupor.ru / adv1234 (на балансе 50 000 ₽)")


if __name__ == "__main__":
    main()
