"""Регрессия: CallbackQuery у pydantic v2 заморожен.

Баг: обработчики присваивали callback.data, чтобы переиспользовать другой
хендлер → ValidationError "Instance is frozen", галочка не переключалась.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

H = os.path.join(os.path.dirname(__file__), '..', 'handlers.py')
src = open(H).read()
results = []

# 1. Никаких присваиваний callback.data / event.data
bad = re.findall(r'^\s*(?:callback|call|cb|query|event)\.data\s*=\s*[^=]', src, re.M)
assert not bad, f"мутация frozen-модели: {bad}"
results.append("нет присваиваний callback.data: OK")

# 2. То же для прочих полей замороженных моделей
for field in ('from_user', 'message.text', 'id'):
    bad = re.findall(rf'^\s*callback\.{re.escape(field)}\s*=\s*[^=]', src, re.M)
    assert not bad, f"мутация callback.{field}: {bad}"
results.append("нет мутаций других полей CallbackQuery: OK")

# 3. Рендер принимает параметры явно, а не читает их из callback.data
assert 'async def _render_nc_channels(' in src
m = re.search(r'async def _render_nc_channels\((.*?)\):', src, re.S)
sig = m.group(1)
for p in ('account_id', 'page', 'cached'):
    assert p in sig, f"в сигнатуре _render_nc_channels нет {p}"
results.append("_render_nc_channels принимает account_id/page/cached явно: OK")

# 4. Защита от параллельных сканирований и предупреждение пользователю
assert '_nc_scanning' in src, "нет защиты от двойного сканирования"
assert 'Не нажимайте кнопки' in src, "нет предупреждения о долгой операции"
results.append("защита от двойного запуска + предупреждение: OK")

# 5. Потеря FSM-кэша обрабатывается, а не приводит к пустому списку
assert 'Список устарел' in src, "не обработана потеря кэша при переключении"
results.append("потеря FSM-кэша обработана: OK")

# 6. Поиск каналов распараллелен
U = open(os.path.join(os.path.dirname(__file__), '..', 'user.py')).read()
block = U[U.index('async def list_commentable_channels'):]
block = block[:block.index('# ==================== CHAT LIST')]
# Пакетный GetChannels (1 запрос на 100 каналов) вместо поштучных get_chat,
# которые вызывали FloodWait
assert 'GetChannels' in block, "поиск каналов не пакетный"
assert 'client.get_chat(' not in block, "остались поштучные get_chat"
results.append("поиск каналов пакетный (GetChannels), без get_chat: OK")

# 7. Файл компилируется
import ast
ast.parse(src)
results.append("handlers.py компилируется: OK")

print("\n".join("  " + r for r in results))
print("\nALL NC-CHANNEL TESTS PASSED")
