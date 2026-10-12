# Autoposter — версия 6.0.1

Список исправлений: [FIX_LIST.md](FIX_LIST.md).

Инструкция по установке и запуску Autoposter
Требования
Python 3.8 или выше
Telegram Bot Token (получить у @BotFather)
API_ID и API_HASH (получить на https://my.telegram.org)
Аккаунт Telegram для userbot


Шаг 1: Установка Python
Windows:
Скачайте Python с https://www.python.org/downloads/

При установке поставьте галочку "Add Python to PATH"

Нажмите "Install Now"

Linux:

sudo apt update
sudo apt install python3 python3-pip
Шаг 2: Создание бота в Telegram
Откройте Telegram и найдите бота @BotFather
Отправьте команду /newbot
Введите название бота (например: My Autoposter Bot)
Введите username бота (должен заканчиваться на bot, например: my_autoposter_bot)
Скопируйте полученный TOKEN (будет нужен позже)




Шаг 3: Получение API_ID и API_HASH
Перейдите на https://my.telegram.org
Войдите с помощью вашего номера телефона
Перейдите в "API development tools"
Создайте новое приложение:
App title: Autoposter
Short name: autoposter
Platform: Desktop

Скопируйте API_ID и API_HASH

Откройте config.ini
Заполните 
[BOT]
TOKEN = ВАШ_ТОКЕН_БОТА
ADMIN = ВАШ_TELEGRAM_ID
USERNAME = @username_вашего_бота
DIR = 

[USER]

API_ID = ВАШ_API_ID
API_HASH = ВАШ_API_HASH
API_HASHES_FILE = hashs.txt

Для распределения аккаунтов по разным API создайте рядом с main.py файл hashs.txt.
Каждая строка: api_id:api_hash. Пустые строки и строки с # игнорируются.

Для шифрования session string и API hash в базе задайте переменную окружения
`SESSION_ENCRYPTION_KEY` (Fernet-ключ). Ключ нельзя сохранять в Git или в базе:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

В интерфейсе доступны Центр здоровья аккаунтов, dry-run ZIP-импорт,
blacklist/отписки, черновики кампаний, история операций и безопасный backup
метаданных без секретов.

Как узнать свой TELEGRAM_ID:
Напишите боту @userinfobot


Далее 
в терминале выполните
pip install -r requirements

после

python main.py
