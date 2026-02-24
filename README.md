# Telegram Gifts Market Intelligence

Веб-приложение и Telegram-бот (встроенный в web-сервис) для анализа рынка Telegram-подарков.

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
- `bot.py` - legacy standalone-бот (опционально, не нужен для прод-схемы с webhook).
- `static/index.html` - дашборд.
- `static/styles.css` - современный интерфейс.
- `static/app.js` - клиентская логика (график, скринер, сигналы).

## Запуск веб-приложения

```bash
cd /Users/nexapai/Downloads/подарки
python3 server.py
```

### AI рекомендации (OpenAI)

Для стабильной работы AI-пайплайна в карточке подарка, скринерах, каталоге и Telegram-боте:

1. Создайте файл `/Users/nexapai/Downloads/подарки/.env.local`
2. Добавьте переменные:

```bash
OPENAI_API_KEY=ваш_ключ
OPENAI_MODEL=gpt-4o-mini
AI_RECO_ENABLED=true
AI_PIPELINE_ENABLED=true
```

3. Запускайте через watchdog:

```bash
cd /Users/nexapai/Downloads/подарки
./scripts/server_start.sh
```

Проверка статуса:

```bash
curl -sS "http://127.0.0.1:8080/api/ai/status?probe=1"
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
- `POST /api/telegram/webhook` - webhook для Telegram-бота (без worker).
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

## Telegram-бот без worker (webhook)

1. Создайте бота через [@BotFather](https://t.me/BotFather).
2. Получите `chat_id` (например, через `getUpdates`).
3. Запустите web-сервис с переменными:

```bash
cd /Users/nexapai/Downloads/подарки
export TG_BOT_TOKEN="ваш_токен"
export TG_CHAT_ID="ваш_chat_id"
export TG_WEBHOOK_SECRET="случайный_секрет"
export BOT_SIGNAL_INTERVAL_SEC=300
export BOT_MIN_INTENSITY=10
python3 server.py
```

4. Установите webhook:

```bash
curl -sS "https://api.telegram.org/bot<TG_BOT_TOKEN>/setWebhook" \
  -d "url=https://<your-domain>/api/telegram/webhook" \
  -d "secret_token=<TG_WEBHOOK_SECRET>"
```

## Важно

Текущая версия использует внутренний генератор рыночных данных. Для продакшена замените источник на реальный фид Telegram-гifts маркетплейса/биржи и включите хранение исторических сделок.

## Verified-Only режим (критичный)

Сервер теперь поддерживает fail-closed режим верифицированных данных:

- `VERIFIED_ONLY=true` (по умолчанию) — использовать только верифицированный источник.
- Источник выбирается через `VERIFIED_SOURCE`:
  - `hybrid` — дефолтный production-режим: сначала `telegram_api`, затем `fragment`, затем fallback на `file`;
  - `file` — локальный файл `data/verified_gifts.json` (или `VERIFIED_DATA_FILE`);
  - `api` — внешний верифицированный API (`VERIFIED_API_URL`);
  - `telegram_api` — API-bridge над Telegram Gifts/MTProto (`TELEGRAM_GIFTS_API_URL`);
  - `fragment` — официальный маркет Fragment (`https://fragment.com/gifts`).
- Если файл отсутствует/невалиден, сервер завершится с ошибкой (чтобы не показывать synthetic данные).

Период обновления verified-файла:

- `VERIFIED_REFRESH_SEC=600` (по умолчанию, 10 минут).

### Подключение внешнего verified API

```bash
export VERIFIED_ONLY=true
export VERIFIED_SOURCE=api
export VERIFIED_API_URL="https://your-verified-source/api/gifts"
export VERIFIED_API_TOKEN="your_token"
export VERIFIED_API_TOKEN_HEADER="Authorization"
export VERIFIED_API_TOKEN_PREFIX="Bearer "
python3 server.py
```

### Подключение Telegram Gifts API bridge (рекомендуемый production-путь)

```bash
export VERIFIED_ONLY=true
export VERIFIED_SOURCE=telegram_api
export TELEGRAM_GIFTS_API_URL="https://your-bridge/api/gifts/verified"
export TELEGRAM_GIFTS_API_TOKEN="your_token"
export TELEGRAM_GIFTS_API_TOKEN_HEADER="Authorization"
export TELEGRAM_GIFTS_API_TOKEN_PREFIX="Bearer "
export TELEGRAM_GIFTS_API_TIMEOUT_SEC=25
python3 server.py
```

Примечания:
- bridge может отдавать как готовый `verified_gifts` (`gifts` + `series` + `profile`), так и сырой `items`-формат;
- сервер нормализует payload в production-формат автоматически и кеширует последний валидный snapshot;
- при ошибке bridge используется fallback на локальный `VERIFIED_DATA_FILE` без обнуления аналитики.

### Hybrid режим (рекомендуется для максимальной устойчивости)

```bash
export VERIFIED_ONLY=true
export VERIFIED_SOURCE=hybrid
export TELEGRAM_GIFTS_API_URL="https://your-bridge/api/gifts/verified"
export TELEGRAM_GIFTS_API_TOKEN="your_token"
python3 server.py
```

Guard от деградации snapshot (чтобы не принять урезанный каталог как валидный):

```bash
export VERIFIED_MIN_GIFTS_ABS=200
export VERIFIED_MIN_GIFTS_RATIO=0.60
export VERIFIED_MIN_COLLECTIONS_RATIO=0.50
export VERIFIED_MIN_MODELS_RATIO=0.40
```

Рекомендуемые пороги fallback канала Fragment:

```bash
export FRAGMENT_MAX_FAILED_COLLECTIONS=12
export FRAGMENT_MIN_COLLECTION_SUCCESS_RATIO=0.88
```

### Подключение официального verified источника Fragment

```bash
export VERIFIED_ONLY=true
export VERIFIED_SOURCE=fragment
export FRAGMENT_GIFTS_URL="https://fragment.com/gifts"
export FRAGMENT_MAX_COLLECTIONS=0              # 0 = все коллекции
export FRAGMENT_MAX_PAGES_PER_COLLECTION=500   # глубина пагинации по каждой коллекции
export FRAGMENT_BOOTSTRAP_CACHE=true           # быстрый старт из локального verified-кэша
# export FRAGMENT_SSL_NO_VERIFY=true            # только для локальной диагностики SSL-цепочки
python3 server.py
```

Примечания:

- Цены из Fragment считаются нативно в `TON` (без конверсии из USD).
- Ссылка "Купить подарок" в модальном окне ведет на `fragment.com` (лот/коллекция).
- Аналитическая история дополнительно хранится локально в `data/fragment_analytics_store.json`.

API фильтров (максимально приближены к Fragment):

- `GET /api/market/filters` — коллекции, модели, фоны, узоры, market statuses.
- `GET /api/market/screener` поддерживает параметры:
  - `market` = `sold|sale|auction`
  - `collection`
  - `model`
  - `backdrop`
  - `symbol`
  - а также `signal`, `group`, `sort_by`, `order`, `min_ratio`.

Поддерживается формат ответа:

- объект датасета напрямую `{ \"gifts\": [...] }`
- или объект с оберткой `{ \"data\": { \"gifts\": [...] } }`

### Ручная синхронизация verified-данных в файл

```bash
export VERIFIED_SOURCE=fragment
export FRAGMENT_GIFTS_URL="https://fragment.com/gifts"
export FRAGMENT_MAX_COLLECTIONS=0
export FRAGMENT_MAX_PAGES_PER_COLLECTION=500
python3 sync_verified.py
```

Минимальная структура подарка в verified-источнике:

```json
{
  "gift_id": "input_key_magic_8_ball_60441",
  "name": "Input Key (magic 8 ball) #60441",
  "group": "Portals Collection",
  "series": [{"dt":"2026-02-17","price":43.3,"demand":1.2,"supply":0.9,"volume":500}],
  "profile": {
    "model": "Magic 8 Ball",
    "pattern": "Magic Hat",
    "background": "Cyberpunk",
    "issued": 128809,
    "total_supply": 159750,
    "value_rub_estimate": 976.0,
    "value_score": 94,
    "source_note": "Verified source"
  }
}
```

## Деплой в интернет

### Вариант 1: Render (рекомендуется)

В проект уже добавлен файл `/Users/nexapai/Downloads/подарки/render.yaml`.

1. Загрузите проект в GitHub.
2. В Render создайте `Blueprint` из репозитория.
3. Render поднимет:
   - `telegram-gifts-market` (web).
4. Для бота задайте переменные:
   - `TG_BOT_TOKEN`
   - `TG_CHAT_ID`
   - `TG_WEBHOOK_SECRET`
   - `BOT_SIGNAL_INTERVAL_SEC`
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
