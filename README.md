# Telegram Gifts Market Intelligence

Веб-приложение и Telegram-бот для анализа рынка Telegram-подарков.

## Возможности

- График роста цены по каждому подарку.
- Скринер по сигналам (`BUY`, `SELL`, `ANOMALY`, `HOLD`) и ключевым метрикам.
- Аналитика спроса/предложения, объёмов и волатильности.
- Сводка рынка: средний рост, количество сигналов, общее состояние.
- Обновление данных в реальном времени (фоновые тики + автообновление UI).
- Telegram-бот для алертов:
  - сигнал на покупку/продажу;
  - аномальный рост/падение цены.

## Архитектура

- `server.py` - HTTP-сервер + API + отдача фронтенда.
- `market_data.py` - генерация/хранение исторических данных.
- `analytics.py` - расчет рыночных метрик и сигналов.
- `bot.py` - Telegram-бот, отправляющий сигналы.
- `static/index.html` - дашборд.
- `static/styles.css` - современный интерфейс.
- `static/app.js` - клиентская логика (график, скринер, сигналы).

## Запуск веб-приложения

```bash
cd /Users/nexapai/Downloads/подарки
python3 server.py
```

Откройте:
- `http://127.0.0.1:8091`
- `http://192.168.0.10:8091`

## API

- `GET /api/market/summary` - сводка и таблица подарков.
- `GET /api/market/chart?gift_id=...` - серия для графика.
- `GET /api/market/screener?sort_by=change_7d&order=desc&signal=BUY` - скринер.
- `GET /api/signals/latest` - топ сигналов.
- `GET /api/market/realtime-status` - состояние realtime-движка.
- `POST /api/admin/refresh` - пересоздать датасет.

## Realtime режим

- По умолчанию сервер обновляет рынок каждые `3` секунды.
- Изменить интервал можно через переменную окружения:

```bash
REALTIME_INTERVAL_SEC=2 python3 server.py
```

## Настройки ссылок покупки

- По умолчанию кнопка `Купить подарок` ведет на Portals:
  - `https://portals.market/gifts/{gift_id}`
- Шаблон можно переопределить переменной:

```bash
PORTALS_GIFT_URL_TEMPLATE=\"https://portals.market/gifts/{gift_id}\" python3 server.py
```

## Запуск Telegram-бота

1. Создайте бота через [@BotFather](https://t.me/BotFather).
2. Получите `chat_id` (например, через `getUpdates`).
3. Запустите:

```bash
cd /Users/nexapai/Downloads/подарки
export TG_BOT_TOKEN="ваш_токен"
export TG_CHAT_ID="ваш_chat_id"
export BOT_POLL_INTERVAL=300
export BOT_MIN_INTENSITY=10
python3 bot.py
```

## Важно

Текущая версия использует внутренний генератор рыночных данных. Для продакшена замените источник на реальный фид Telegram-гifts маркетплейса/биржи и включите хранение исторических сделок.

## Деплой в интернет

### Вариант 1: Render (рекомендуется)

В проект уже добавлен файл `/Users/nexapai/Downloads/подарки/render.yaml`.

1. Загрузите проект в GitHub.
2. В Render создайте `Blueprint` из репозитория.
3. Render поднимет:
   - `telegram-gifts-market` (web);
   - `telegram-gifts-bot` (worker, опционально).
4. Для бота задайте переменные:
   - `TG_BOT_TOKEN`
   - `TG_CHAT_ID`
5. Проверьте health:
   - `https://<your-domain>/healthz`

### Вариант 2: Docker (любой VPS/облако)

В проекте есть `/Users/nexapai/Downloads/подарки/Dockerfile`.

```bash
docker build -t telegram-gifts-market .
docker run -d --name gifts-app -p 8080:8080 \
  -e HOST=0.0.0.0 \
  -e PORT=8080 \
  -e REALTIME_INTERVAL_SEC=3 \
  telegram-gifts-market
```

После запуска приложение доступно на `http://<server-ip>:8080`.
