# 🐦 Twitter Monitor Bot

Мониторинг Twitter/X аккаунтов через Nitter с AI-обработкой и отправкой в Telegram.

## Возможности

- Мониторинг 20+ Twitter аккаунтов по очереди (1 аккаунт в минуту)
- Фильтрация по ключевым словам (giveaway, airdrop и т.д.)
- AI-перевод и анализ через OpenRouter (перевод на русский, выделение заданий)
- Кнопка "Открыть в X" на каждом сообщении
- Управление через Telegram команды

## Команды бота

| Команда | Описание |
|---------|----------|
| `/add @username` | Добавить аккаунт в мониторинг |
| `/remove @username` | Удалить аккаунт |
| `/list` | Список всех аккаунтов с тегами |
| `/pages` | Управление тегами по аккаунтам (кнопки) |
| `/addkw слово` | Глобальное ключевое слово |
| `/rmkw слово` | Удалить глобальное слово |
| `/keywords` | Глобальные ключевые слова |
| `/status` | Статус мониторинга |

## Теги (фильтры)

Каждый аккаунт может иметь свои теги. Твит проходит фильтр если совпадает хотя бы один тег.

- `giveaway` — твит содержит слово "giveaway"
- `follow+repost` — твит содержит И "follow" И "repost" (оба обязательны)
- `share+usdt` — И "share" И "usdt"

Управление через `/pages` → выбрать аккаунт → добавить/удалить теги.

Если у аккаунта нет тегов — используются глобальные (`/addkw`). Если и глобальных нет — все твиты проходят.

## Установка

```bash
# 1. Клонируй или скопируй файлы на VPS
# 2. Создай виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# 3. Установи зависимости
pip install -r requirements.txt

# 4. Скопируй и заполни .env
cp .env.example .env
nano .env

# 5. Запусти
python main.py
```

## Запуск как сервис (systemd)

```bash
sudo nano /etc/systemd/system/twitter-monitor.service
```

```ini
[Unit]
Description=Twitter Monitor Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/twitter-monitor-bot
ExecStart=/path/to/twitter-monitor-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable twitter-monitor
sudo systemctl start twitter-monitor
```

## Как получить TG_CHAT_ID

1. Напиши боту `/start`
2. Или перешли сообщение из нужного чата боту @userinfobot
