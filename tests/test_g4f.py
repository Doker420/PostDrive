"""Тесты g4f-фолбэка.

Главное, что проверяем: g4f НЕ требует API-ключа, и несовпадение имён
провайдеров в конфиге с установленной версией g4f не ломает генерацию.
Сеть не нужна — проверяется подбор провайдеров, а не сами ответы.
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)

import user as U

results = []

# 1. Никакого G4F_API_KEY в коде быть не должно
src = open(os.path.join(os.path.dirname(__file__), '..', 'user.py')).read()
assert 'G4F_API_KEY' not in src, "g4f не требует ключа — переменная должна быть удалена"
assert not hasattr(U, 'G4F_API_KEY')
for cfg in ('config.ini', 'config.ini.example'):
    p = os.path.join(os.path.dirname(__file__), '..', cfg)
    if os.path.exists(p):
        for line in open(p):
            ls = line.strip()
            if ls.startswith('G4F_API_KEY'):
                raise AssertionError(f"{cfg}: G4F_API_KEY не должен быть в конфиге")
results.append("G4F_API_KEY отсутствует в коде и конфигах: OK")

# 2. Провайдеры подбираются и все реально существуют
U.AccountSessionManager._g4f_provider_cache = None
provs = U.AccountSessionManager._g4f_providers()
assert provs, "не найдено ни одного провайдера"
assert all(getattr(p, 'working', False) for p, _ in provs), "есть нерабочие провайдеры"
assert all(not getattr(p, 'needs_auth', False) for p, _ in provs), "есть провайдеры с авторизацией"
results.append(f"подбор провайдеров: OK ({len(provs)} шт, все working, без авторизации)")

# 3. Картиночные/аудио провайдеры отфильтрованы
bad = [n for _, n in provs
       if any(k in n.lower() for k in ('image', 'flux', 'audio', 'sd35', 'stability'))]
assert not bad, f"картиночные провайдеры не отфильтрованы: {bad}"
results.append("картиночные/аудио провайдеры отфильтрованы: OK")

# 4. Битые имена в конфиге не ломают фолбэк (регрессия: Blackbox/DDG/ChatGptEs
#    были в конфиге, но в g4f 8.5.1 их нет)
orig = U.G4F_PROVIDERS
try:
    U.G4F_PROVIDERS = ['Blackbox', 'DDG', 'ChatGptEs', 'Free2GPT', 'Liaobots']
    U.AccountSessionManager._g4f_provider_cache = None
    provs2 = U.AccountSessionManager._g4f_providers()
    assert provs2, "битый конфиг не должен оставлять бота без провайдеров"
    results.append(f"битые имена в конфиге -> автопоиск: OK ({len(provs2)} шт)")
finally:
    U.G4F_PROVIDERS = orig
    U.AccountSessionManager._g4f_provider_cache = None

# 5. Имена провайдеров из конфига по умолчанию проверяем на существование
import g4f.Provider as P
missing = [n for n in U.G4F_PROVIDERS if getattr(P, n, None) is None]
if missing:
    results.append(f"ВНИМАНИЕ: в конфиге отсутствующие в g4f провайдеры: {missing}")
else:
    results.append("все провайдеры из config.ini существуют в g4f: OK")

print("\n".join("  " + r for r in results))
print("\nALL G4F TESTS PASSED")
