"""Форматы рекламы и их человекочитаемые названия."""

FORMATS = {
    "post_24h":  {"title": "Пост 24 часа",   "field": "price_24h",  "hint": "Публикация поста на 24 часа"},
    "post_48h":  {"title": "Пост 48 часов",  "field": "price_48h",  "hint": "Публикация поста на 48 часов"},
    "post_72h":  {"title": "Пост 72 часа",   "field": "price_72h",  "hint": "Публикация поста на 72 часа"},
    "repost":    {"title": "Репост",         "field": "price_repost", "hint": "Репост вашего поста"},
    "native":    {"title": "Нативный пост",  "field": "price_native", "hint": "Нативная интеграция от владельца"},
}

ORDER_STATUS = {
    "new":       ("Новый", "badge-blue"),
    "accepted":  ("Принят", "badge-teal"),
    "published": ("Размещён", "badge-violet"),
    "completed": ("Завершён", "badge-green"),
    "declined":  ("Отклонён", "badge-red"),
    "cancelled": ("Отменён", "badge-gray"),
    "disputed":  ("Спор", "badge-orange"),
    "refunded":  ("Возврат", "badge-gray"),
}

LISTING_STATUS = {
    "pending":  ("На модерации", "badge-orange"),
    "active":   ("Активна", "badge-green"),
    "rejected": ("Отклонена", "badge-red"),
    "paused":   ("На паузе", "badge-gray"),
    "draft":    ("Черновик", "badge-gray"),
}


def price_map(listing: dict) -> list[dict]:
    """Форматы площадки с ценами: [{'code','title','price'}...] для заданных."""
    out = []
    for code, meta in FORMATS.items():
        price = listing.get(meta["field"])
        if price is not None:
            out.append({"code": code, "title": meta["title"],
                        "hint": meta["hint"], "price": price})
    return out
