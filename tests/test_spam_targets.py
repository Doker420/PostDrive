"""Рассылка: пример рандомизации в подсказке и рассылка по контактам."""
import ast
import os
import random
import re

root = os.path.join(os.path.dirname(__file__), '..')
H = open(os.path.join(root, 'handlers.py')).read()
U = open(os.path.join(root, 'user.py')).read()
results = []

# 1. Подсказка содержит синтаксис и живой пример
seg = H[H.index('✏️ <b>Свой текст рассылки</b>'):]
seg = seg[:seg.index('reply_markup=cancel_inline_keyboard())')]
assert '{вариант1|вариант2|вариант3}' in seg, "нет описания спинтакса"
assert '{rand}' in seg, "нет описания {rand}"
assert '{Привет|Здравствуйте|Добрый день}' in seg, "нет примера текста"
results.append("подсказка с синтаксисом и примером: OK")

# 2. Спинтакс реально применяется к своему тексту рассылки
seg2 = U[U.index('async def spam_to_users'):]
assert "re.sub(\n                        r'\\{([^{}]*\\|[^{}]*)\\}'," in seg2 or \
       "r'\\{([^{}]*\\|[^{}]*)\\}'" in seg2, "спинтакс не применяется при отправке"
assert 'entities_to_send' in seg2, "форматирование не защищено от сдвига offsets"
results.append("спинтакс применяется к каждому получателю: OK")

# 3. Регулярка спинтакса работает как обещано в подсказке
rx = re.compile(r'\{([^{}]*\|[^{}]*)\}')
text = "{Привет|Здравствуйте}! {помогаю|занимаюсь} продвижением. #{rand}"
random.seed(0)
out = rx.sub(lambda m: random.choice(m.group(1).split('|')), text)
assert '|' not in out and '{' in out, f"спин отработал неверно: {out}"   # {rand} не тронут
assert out.split('!')[0] in ('Привет', 'Здравствуйте')
results.append("подстановка вариантов не задевает {rand}: OK")

# 4. Контакты: метод в user.py
assert 'async def get_account_contacts' in U, "нет получения контактов"
seg3 = U[U.index('async def get_account_contacts'):U.index('async def spam_to_users')]
assert 'client.get_contacts()' in seg3, "не используется get_contacts"
assert "is_bot" in seg3 and "is_deleted" in seg3, "боты/удалённые не отфильтрованы"
results.append("get_account_contacts с фильтрацией: OK")

# 5. Кнопка и обработчик рассылки по контактам
assert 'callback_data="spam_targets_contacts"' in H, "нет кнопки «По контактам»"
assert '@dp.callback_query(F.data == "spam_targets_contacts", MassActionStates.WAITING_TARGETS)' in H, \
    "нет обработчика рассылки по контактам"
results.append("кнопка и обработчик «По контактам аккаунтов»: OK")

# 6. Запуск рассылки общий для обоих путей (нет дублирования логики)
assert H.count('async def _start_spam_distribution') == 1, "нет общего запуска рассылки"
assert H.count('_start_spam_distribution(') == 3, "общий запуск используется не везде"
assert H.count('account_manager.spam_to_users(') == 1, "логика запуска продублирована"
results.append("общий запуск рассылки для списка и контактов: OK")

# 7. Отправка идёт через tg_call (FloodWait/спам-блок/пропуск цели)
seg4 = U[U.index('async def spam_to_users'):]
assert 'await self.tg_call(' in seg4, "рассылка всё ещё шлёт мимо tg_call"
assert 'client.send_message(' in seg4 and 'await client.send_message(' not in seg4, \
    "остался прямой await client.send_message"
assert 'await client.send_photo(' not in seg4, "остался прямой await client.send_photo"
assert 'except AccountBlockedError' in seg4 and 'except TargetSkipError' in seg4, \
    "не обработаны блокировка аккаунта и пропуск цели"
results.append("рассылка через tg_call с обработкой блокировок: OK")

# 8. Выбор скорости с лимитами
assert 'SPAM_SPEEDS = {' in U, "нет пресетов скорости в user.py"
assert 'delay_min: int = 30' in U and 'random.randint(lo, hi)' in U, \
    "задержка не настраивается"
assert 'SPAM_SPEED_LABELS' in H, "нет описания скоростей в UI"
assert 'сообщений/час' in H, "в подсказке нет актуальных лимитов Telegram"
assert 'F.data.startswith("spam_speed_")' in H, "нет обработчика выбора скорости"
assert 'delay_min=delay_min, delay_max=delay_max' in H, "скорость не доходит до рассылки"
results.append("выбор скорости рассылки с лимитами Telegram: OK")

ast.parse(H)
ast.parse(U)
results.append("handlers.py и user.py компилируются: OK")

print("\n".join("  " + r for r in results))
print("\nALL SPAM TARGET TESTS PASSED")
