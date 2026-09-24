"""Регрессии входа по QR-коду.

Симптом: пользователь отсканировал код → в Telegram появилась «незавершённая
попытка входа», бот молчит.

Причины:
  1. Опрос Telegram запускался ТОЛЬКО по кнопке «✅ Я отсканировал». Пока её не
     нажали, ImportLoginToken/ExportLoginToken не вызывались, вход не
     завершался и висел как неподтверждённая сессия.
  2. Кнопка была привязана к состоянию WAITING_QR_SCAN: после перезапуска бота
     (потеря FSM) нажатие проваливалось в пустоту — «тишина».
  3. ImportLoginToken вызывался ДО сканирования, портя свежий токен.
  4. SessionPasswordNeeded из ExportLoginToken тонул в общем except: аккаунт с
     2FA ждал таймаута вместо запроса пароля.
"""
import ast
import os
import sys

root = os.path.join(os.path.dirname(__file__), '..')
H = open(os.path.join(root, 'handlers.py')).read()
U = open(os.path.join(root, 'user.py')).read()
results = []

# 1. Опрос стартует автоматически после показа QR
assert 'qr_pollers' in H and 'async def _qr_poll(' in H, "нет фонового опроса QR"
seg = H[H.index('async def auth_qr_callback'):H.index('async def qr_scanned_callback')]
assert 'asyncio.create_task(' in seg and '_qr_poll(' in seg, \
    "опрос QR не запускается сразу после отправки кода"
results.append("опрос запускается автоматически после показа QR: OK")

# 2. Кнопка проверки работает без состояния FSM
assert '@dp.callback_query(F.data == "qr_scanned")' in H, \
    "qr_scanned всё ещё привязан к состоянию (при потере FSM — тишина)"
results.append("кнопка проверки не зависит от FSM: OK")

# 3. Повторное нажатие не плодит вторые опросы
seg2 = H[H.index('async def qr_scanned_callback'):]
seg2 = seg2[:seg2.index('@dp.message(AddAccountStates.WAITING_QR_2FA)')]
assert 'if task and not task.done()' in seg2, "повторное нажатие запускает второй опрос"
assert 'temp_auth_clients' in seg2, "нет сообщения об истёкшей QR-сессии"
results.append("защита от двойного опроса и истёкшей сессии: OK")

# 4. Отмена гасит фоновый опрос
seg3 = H[H.index('async def cancel_action_handler'):][:400]
assert '_stop_qr_poller' in seg3, "отмена не останавливает опрос QR"
results.append("отмена останавливает опрос: OK")

# 5. Преждевременный ImportLoginToken убран
seg4 = U[U.index('async def finish_qr_login_stream'):]
seg4 = seg4[:seg4.index('def cancel_phone_auth')]
assert 'import_attempted' not in seg4, "остался преждевременный ImportLoginToken"
assert 'deadline = time.time() + 600' in seg4, "слишком короткое окно ожидания"
results.append("нет преждевременного ImportLoginToken, окно 10 минут: OK")

# 6. 2FA обрабатывается до общего except
exp = seg4[seg4.index('functions.auth.ExportLoginToken('):]
head = exp[:exp.index('except Exception as e:')]
assert 'except SessionPasswordNeeded:' in head, "SessionPasswordNeeded тонет в общем except"
results.append("2FA при QR-входе запрашивает пароль сразу: OK")

# 7. Файлы компилируются
ast.parse(H)
ast.parse(U)
results.append("handlers.py и user.py компилируются: OK")

print("\n".join("  " + r for r in results))
print("\nALL QR LOGIN TESTS PASSED")
