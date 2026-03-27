GiftMarketZone — Developer Package (Production)
Версия: 2026-03-03

Файлы:
1) openapi_full_v1.4.yaml
   - Обновлённый OpenAPI с полями market_regime и edgeRank* в Signal (best-effort patch)
   - Добавлен endpoint /v1/market/status (если его не было)
   Путь: /mnt/data/openapi_full_v1.4.yaml

2) edgerank_weights_by_regime.json
   - Динамические веса EdgeRank по режиму рынка + нормализации
   Путь: /mnt/data/edgerank_weights_by_regime.json

3) signal_profiles_by_regime.json
   - Профили порогов BUY/SELL/WATCH/SKIP по режиму рынка + Telegram publish gate
   Путь: /mnt/data/signal_profiles_by_regime.json

4) decision_engine_v2_spec_RU.txt
   - Полное описание Decision Engine v2 (расчёт режима, EdgeRank, action на сайте, фильтры)
   Путь: /mnt/data/decision_engine_v2_spec_RU.txt

5) schema_signal.created.v2.json
   - JSON Schema события signal.created v2 для realtime
   Путь: /mnt/data/schema_signal.created.v2.json

6) schema_market.status.v1.json
   - JSON Schema события market.status для realtime
   Путь: /mnt/data/schema_market.status.v1.json

7) redis_topics_structure_v1.3.txt
   - Структура Redis topics/keys для realtime + TG dedup + caches
   Путь: /mnt/data/redis_topics_structure_v1.3.txt

8) frontend_signals_ui_mapping.json
   - JSON mapping колонок/фильтров страницы "Лента сигналов" (Bento UI friendly)
   Путь: /mnt/data/frontend_signals_ui_mapping.json

9) GiftMarketZone_Telegram_PRO_templates_v3.txt
   - Telegram templates + приложение про динамические веса EdgeRank
   Путь: /mnt/data/GiftMarketZone_Telegram_PRO_templates_v3.txt

Рекомендуемый порядок внедрения:
A) Backend: реализовать decision engine v2, edgeRank dynamic, signal schema v2
B) Frontend: подключить mapping для таблицы сигналов и фильтров, сортировка по EdgeRank
C) Notifier: применить telegram publish gate + дедуп + rate-limit

