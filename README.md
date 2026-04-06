# 🐦 Twitter Monitor Bot

Мониторинг Twitter/X через приватный список с AI-обработкой и отправкой в Telegram.

## Как работает

1. Ты создаёшь **приватный список** в Twitter и добавляешь туда аккаунты
2. Бот раз в 30 мин загружает ленту этого списка через куки (GraphQL API)
3. Каждый твит фильтруется по тегам/исключениям для конкретного аккаунта
4. Совпавшие твиты ставятся в очередь → AI-обработка (перевод + анализ) → отправка в Telegram
5. Дубли не отправляются (каждый tweet_id сохраняется в SQLite)

## Быстрый старт

### 1. Подготовка Twitter

- Зайди в Twitter через браузер (Chrome / Firefox)
- Создай **приватный список** → добавь нужных юзеров
- Запомни List ID из URL: `https://x.com/i/lists/123456789` → `123456789`

### 2. Получение куки

**На ПК (Chrome/Firefox):**
- Установи расширение **Cookie-Editor**
- Зайди на x.com → нажми на расширение → **Export** (JSON)
- Скинь боту через `/cookies` (текстом или файлом)

**На Android:**
- Используй **Firefox** (поддерживает расширения) или любое приложение для экспорта куки
- Экспортируй куки x.com → отправь боту через `/cookies`

### 3. Установка

```bash
git clone https://github.com/Aliskasq/ActivityX.git
cd ActivityX

pip install -r requirements.txt

cp .env.example .env
nano .env  # заполни ключи
```

### 4. Запуск

```bash
python3 main.py
```

### 5. Systemd (автозапуск)

```bash
sudo nano /etc/systemd/system/twitter-monitor.service
```

```ini
[Unit]
Description=Twitter Monitor Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ActivityX
ExecStart=/usr/bin/python3 /root/ActivityX/main.py
Restart=always
RestartSec=15
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
# Активировать и запустить
sudo systemctl daemon-reload
sudo systemctl enable twitter-monitor
sudo systemctl start twitter-monitor

# Проверить статус
sudo systemctl status twitter-monitor

# Логи
sudo journalctl -u twitter-monitor -f
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Справка |
| `/add @username` | Добавить аккаунт (фильтр) |
| `/remove @username` | Удалить аккаунт |
| `/list` | Список аккаунтов с тегами |
| `/pages` | Управление тегами (inline кнопки) |
| `/cookies` | Загрузить куки Twitter (текст или файл) |
| `/listid ID` | Установить ID списка |
| `/key ключ` | Сменить OpenRouter API ключ |
| `/models` | Список моделей / сменить |
| `/time 18:05 20:49 03:00` | Расписание скана (МСК) |
| `/time30` | Вернуть режим каждые 30 мин |
| `/status` | Статус |

## Расписание скана

По умолчанию бот сканит каждые 30 минут. Можно задать конкретное время (МСК):

```
/time 18:05 18:38 20:49 03:00
```

Бот будет сканить только в указанное время. Чтобы вернуть интервал:

```
/time30
```

Также можно задать через `.env`:
```
SCHEDULE_TIMES_MSK=18:05,18:38,20:49,03:00
```

## Теги (фильтры)

Каждый аккаунт имеет свои теги и исключения. Управление через `/pages`:

- `giveaway` — содержит слово "giveaway"
- `follow+repost` — содержит И "follow" И "repost" (составной тег)
- Исключения: если твит содержит слово-исключение → отклоняется

## Куки

Куки протухают примерно раз в несколько недель. Когда бот перестанет получать твиты — повтори экспорт и скинь через `/cookies`. Бот принимает любой формат (массив объектов, обёрнутый JSON, простой dict).

## Стек

- Python 3.10+
- python-telegram-bot 21.x
- httpx (прямые запросы к Twitter GraphQL API)
- SQLite (хранение аккаунтов, тегов, seen tweets)
- OpenRouter (AI перевод/анализ, бесплатная модель stepfun)
