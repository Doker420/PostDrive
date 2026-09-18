"""Тесты генерации комментариев.

Две регрессии из продакшена:
1. gpt-oss отвечал развёрнутым разбором с таблицами и списками на 3000+
   символов вместо короткой реплики — мгновенный признак бота.
2. PollinationsAI перешёл на платную модель (402 No cake credits), а бот
   продолжал его опрашивать при каждом комментарии.
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)

import user as U
M = U.AccountSessionManager
results = []

# ── 1. Простыня обрезается ────────────────────────────────────────
longform = """Сегодняшний рост активов на 5% выглядит заметным. Вот моменты для оценки:

| Фактор | Коррекция | Новый тренд |
|--------|-----------|-------------|
| Объём | низкий | высокий |

### Что делать
1. Проверить объём.
2. Осмотреть уровни.

### Вывод
- Ждать подтверждения."""
out = M._clean_ai_output(longform)
assert len(out) <= M.MAX_COMMENT_CHARS, f"{len(out)} > {M.MAX_COMMENT_CHARS}"
for junk in ('|', '###', '1.', '- '):
    assert junk not in out, f"остался мусор {junk!r}: {out!r}"
results.append(f"простыня обрезана: {len(longform)} -> {len(out)} символов")

# ── 2. Короткая реплика не портится ───────────────────────────────
short = "Согласен, рост впечатляет. Подробности у меня в профиле."
assert M._clean_ai_output(short) == short, "короткий текст изменён"
results.append("короткий комментарий не тронут: OK")

# ── 3. Markdown и обёртки снимаются ───────────────────────────────
assert '**' not in M._clean_ai_output("**Жирный** текст")
assert M._clean_ai_output('"В кавычках"') == 'В кавычках'
assert M._clean_ai_output('Комментарий: привет') == 'привет'
assert M._clean_ai_output('<think>рассуждения</think>Ответ') == 'Ответ'
results.append("markdown/кавычки/префиксы/reasoning снимаются: OK")

# ── 4. Обрезка идёт по границе предложения ────────────────────────
sentences = ("Первое предложение тут. Второе предложение здесь. " * 12)
cut = M._clean_ai_output(sentences)
assert len(cut) <= M.MAX_COMMENT_CHARS
assert cut.endswith(('.', '…')), repr(cut[-20:])
results.append("обрезка по границе предложения: OK")

# ── 5. Платные провайдеры не опрашиваются ─────────────────────────
for p in ('PollinationsAI', 'OpenAIFM'):
    assert p in M.G4F_PAID_PROVIDERS, f"{p} должен быть в платных"
    assert p not in U.G4F_PROVIDERS, f"{p} не должен быть в списке по умолчанию"
results.append("PollinationsAI/OpenAIFM исключены как платные: OK")

M._g4f_provider_cache = None
provs = M._g4f_providers()
assert provs, "не осталось ни одного бесплатного провайдера"
paid = [n for _, n in provs if n in M.G4F_PAID_PROVIDERS]
assert not paid, f"платные в пуле: {paid}"
results.append(f"пул только из бесплатных: OK ({len(provs)} шт)")

# ── 6. Детектор требования оплаты ─────────────────────────────────
class PaymentRequiredError(Exception): pass
paid_errors = [
    PaymentRequiredError("Error 402: No cake credits. Bake proof-of-work cakes at g4f.dev/chat"),
    Exception("401 Unauthorized"),
    Exception("Please sign up to get an API key"),
    Exception("insufficient quota"),
]
for e in paid_errors:
    assert M._is_paid_error(e), f"не распознано как платное: {e}"
for e in (Exception("connection timeout"), Exception("bad gateway 502")):
    assert not M._is_paid_error(e), f"ложное срабатывание: {e}"
results.append("детектор 402/credits/proof-of-work: OK")

# ── 7. Промт требует короткий ответ без разметки ──────────────────
msgs = M.build_comment_messages("Согласись с автором", "Тестовый пост")
system = msgs[0]['content']
for req in ('2 предложения', '300 символов', 'НИКАКИХ списков'):
    assert req in system, f"в промте нет требования: {req}"
assert any(m['role'] == 'assistant' for m in msgs), "нет few-shot примера"
assert 'Согласись с автором' in system, "инструкция пользователя не попала в промт"
results.append("промт: лимит длины, запрет разметки, few-shot, инструкция юзера: OK")

print("\n".join("  " + r for r in results))
print("\nALL AI-COMMENT TESTS PASSED")
