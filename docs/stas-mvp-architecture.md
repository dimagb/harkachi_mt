> **Статус: действующий source of truth.** Финальная редакция документа
> Стаса (README_MVP_FINAL, вторая версия). Отменяет `ML_BACKEND_CONTRACT.md`,
> предыдущие MVP-редакции и все варианты с обязательным PostgreSQL.
>
> **Маршрут 5 и два числа скора.** Сданный релиз — вариант раздела 25
> и DoD п.1: **маршрут 5 = 0 на весь период, score релиза 0.88987.** Это
> осознанный консервативный выбор, а не ошибка.
>
> Находка при этом фактическая и остаётся в силе: маршрут 5 **запущен
> 16 декабря 2025**, восстановлен спустя 30 лет, Белорусский вокзал —
> Метро «Рижская»; в справочнике `route_date_start = 2025-12-16` —
> единственная такая дата. Эталон по нему ненулевой, это проверено
> лидербордом: вариант с cold start (`new_route ≈ analogue × coefficient`
> с даты запуска, коэффициент калиброван по лидерборду) дал **0.89447** —
> лучший результат команды, он забанкован и идёт в зачёт. Обнуление
> стоит 0.0046. Механизм описан как способ работы с новыми маршрутами,
> но в сданный релиз не взят.
>
> Как читать числа ниже: в разделах 10, 49 и 56 `score` релиза —
> **0.88987**; 0.89447 — лучший результат команды на лидерборде. Оба
> выше 0.88, балл по критерию 1 одинаковый.
>
> Источники: https://www.m24.ru/videos/transport/16122025/856629 и
> https://msk1.ru/text/transport/2025/12/16/76173070/
>
> **Закрыто автором в этой версии:** пути API
> (раздел 36), `code_git_sha` (разделы 8 и 49), правило «один release —
> один показываемый прогноз» (раздел 10), список блокирующих ML-артефактов
> (раздел 50), отмена приоритета улучшения скора (раздел 56).
>
> **Что остаётся на стороне бекенда — Стасу не нужно:**
>
> 1. **Раздел 37 не отменяет существующие эндпойнты.** Список P0 API — это
>    то, что надо *добавить*. Уже работающие `GET /api/export`,
>    `/api/export/submission`, `/api/factors`, `/api/scope`, `/api/geometry`,
>    `/api/stops`, `/api/routes`, `/api/forecast/routes`,
>    `/api/forecast/stops`, `/api/forecast/compare`, `/api/health`,
>    `/api/reload` **остаются**. Через них закрываются выгрузка и
>    остановочная агрегация (критерий 4), внешние источники и область
>    применимости (критерий 2). Реализовать раздел 37 буквально как полный
>    список — значит потерять уже заработанные баллы.
>
> 2. **Раздел 38: имена параметров и полей.** В документе `route`, `from`,
>    `to`; в работающем беке и в задании фронтенду — `routes` (через
>    запятую), `date_from`, `date_to`. Принцип «ничего не ломаем» из
>    раздела 36 распространяется и на параметры: существующие остаются,
>    новые добавляются алиасами. То же в ответе: `points[].value` остаётся
>    числом, которое рисует график, а `model_prediction` и
>    `operational_prediction` добавляются рядом, а не вместо.
>
> 3. **Раздел 45, тест B.** Синхронная запись в DuckDB внутри `async def`
>    заблокирует event loop и просадит p95 на всех запросах, а не только
>    на пяти процентах ingest. Обработчик объявлять обычным `def` —
>    FastAPI сам уведёт его в пул потоков. Просадка p95 в тесте B
>    относительно теста A ожидаема, так и надо написать.
>
> 4. **Разделы 41 и 52 про фронтенд устарели.** Команда договорилась на три
>    экрана: вход, главный, аналитика. Конфликта нет — главный экран несёт
>    всё оцениваемое, — но состав экранов и предупреждение про авторизацию
>    смотреть в `frontend-tasks.md`, а не здесь.
>
> **Также действует:** два воркера uvicorn с общим состоянием через файлы
> тома `runtime` (см. комментарий в `service/Dockerfile`) и подстановка
> `index.html` для клиентской маршрутизации SPA.
>
> **Сверка с разделами 37–39 — что в сервисе есть и чего нет.**
>
> Сделано:
> - все пути раздела 37 доступны и как `/api/...`, и как `/api/v1/...`
>   (те же обработчики, раздел 36);
> - `POST /api/admin/reload-forecast` — алиас `POST /api/reload`;
>   `GET /health` — алиас `/api/health`;
> - `POST /api/forecast/preview` (раздел 39): опции погоды и событий из
>   `release/factor_options.json` по сезону дат, `season_adjustment_pct`,
>   `manual_adjustment_pct`; база, сценарий, разница и разложение по шагам
>   (раздел 42). Опции, которой для сезона нет, нет и в сценарии — 400;
> - параметры раздела 38 `route`, `from`, `to` — алиасы `routes`,
>   `date_from`, `date_to` в `GET /api/forecast`;
> - `/api/meta` (раздел 49): `release_id`, `model_version`, `score` (только
>   при совпадении md5 прогноза), `cutoff_date`, `forecast_from`,
>   `forecast_to`, `last_ingest_at`, `active_network_events`;
> - ошибки раздела 40 — единый формат `{code, message}`;
> - `network_impact_rules`: правило 17 → 11 × 1.1079 применяется.
>
> Не сделано — расхождения с текстом ниже:
> - ответ `GET /api/forecast` не содержит полей `model_prediction` и
>   `operational_prediction` (раздел 38): `points[].value` — уже
>   операционный прогноз (база → поправки → события). Базу без поправок
>   дают `POST /api/forecast/preview` (`base`) и `/api/export/submission`;
> - `code_git_sha` в `/api/meta` — `null`: он записан в `release_metadata`
>   внутри `.duckdb`, а сервис DuckDB не читает;
> - сервис читает прогноз из `submission.csv`, а не из
>   `forecast_release.duckdb` (значения те же, их пишет `build_release`);
> - пересборка по принятому потоку не замкнута: сервис пишет агрегаты
>   в JSON, `--runtime` ждёт `runtime.duckdb`, конвертера нет.

---

# MVP-архитектура хакатона — FINAL

> Цель: за 44 часа собрать законченный MVP, который закрывает критерии жюри и не тратит время на production-инфраструктуру.
>
> Этот документ — рабочий source of truth команды. Если что-то не указано как P0 — это не блокирует релиз.

---

## 1. Что строим

Один Docker-контейнер:

```text
┌─────────────────────────────────────────────┐
│          TRAM FORECAST SERVICE              │
│                                             │
│  Backend API                                │
│  ├── forecast в RAM                         │
│  ├── what-if engine                         │
│  ├── network events                         │
│  ├── ingest API                             │
│  └── embedded DuckDB                        │
│                                             │
│  Frontend static build                      │
│  Готовый ML forecast release                │
└─────────────────────────────────────────────┘
```

Hot path:

```text
Frontend
   ↓
Backend API
   ↓
Forecast in RAM
   +
Network events
   +
What-if coefficients
```

Тяжёлый ML не запускается на пользовательский запрос.

---

## 2. Главный принцип MVP

Мы НЕ строим online ML platform.

Мы строим:

```text
сильный готовый прогноз
+
быстрый API
+
what-if корректировки
+
операционные изменения сети
+
приём новых данных
+
воспроизводимый rebuild pipeline
+
реальный performance benchmark
```

---

## 3. Что НЕ делаем до готового P0

Не делаем:

```text
PostgreSQL
Redis
Kafka
Airflow
Prefect
Kubernetes
отдельный ML HTTP сервис
real-time training
сложную очередь ML jobs
distributed state
универсальный cold-start engine
графовую transport assignment model
автоматический парсер всех новостей
полноценный digital twin
```

---

## 4. Ограничения из условия

Serving:

```text
1 container
2–4 vCPU
2–4 GB RAM
hundreds RPS
p95 < 200–300 ms
CPU 60–80% с запасом
RAM stable
no swap
```

Поэтому request path:

```text
RAM lookup
+
несколько арифметических операций
+
JSON serialization
```

---

## 5. Верхний уровень

```text
                    BUILD / REBUILD

historical validations
telemetry
calendar
external data
runtime aggregates
        │
        ▼
    ML pipeline
        │
        ▼
forecast_release.duckdb
        │
        ▼

              ONE CONTAINER

┌─────────────────────────────────────┐
│ Backend + Frontend                  │
│                                     │
│ forecast release → RAM              │
│ runtime.duckdb                      │
│                                     │
│ GET forecast                        │
│ POST what-if                        │
│ network events                      │
│ ingest batches                      │
└─────────────────────────────────────┘
```

---

## 6. ML и backend логически независимы

ML отвечает за:

```text
данные → модель → forecast release
```

Backend отвечает за:

```text
forecast release + runtime state + scenarios + API
```

Контракт между ними — schema `forecast_release`.

---

## 7. Хранилище MVP

Два DuckDB-файла.

### `forecast_release.duckdb`

Read-only результат ML:

```text
release_metadata
forecast_points
factor_options
network_impact_rules   optional
```

### `runtime.duckdb`

Mutable runtime:

```text
network_events
ingest_batches
hourly_aggregates
```

---

## 8. `release_metadata`

```text
release_id
created_at
cutoff_date
forecast_from
forecast_to
model_version
score
code_git_sha
schema_version
```

Пример:

```text
release_id = hackathon-v7
cutoff_date = 2025-10-31
forecast_from = 2025-11-01
forecast_to = 2025-12-31
model_version = statistical-v6
score = 0.89447
code_git_sha = <commit that reproduces this exact release>
```

---

## 9. Главный контракт прогноза

Backend не пытается воспроизвести внутреннюю формулу ML.

ML отдаёт:

```text
model_prediction
```

Это готовый базовый прогноз модели.

Минимальная таблица:

```text
route
date
hour
model_prediction
```

---

## 10. Что уже находится внутри `model_prediction`

Это обязательная часть контракта.

| Компонент | Уже внутри `model_prediction`? | Применяется backend ещё раз? |
|---|---|---|
| historical route/day baseline | ДА | НЕТ |
| hourly profile | ДА | НЕТ |
| production calendar / day type | ДА | НЕТ |
| сезонность модели | ДА | НЕТ |
| daylight correction | ДА, если включена в release | НЕТ |
| route-specific known logic текущей модели | ДА | НЕТ |
| финальная calibration, если она использована в единственном release | ДА | НЕТ |
| user weather what-if | НЕТ | ДА |
| user demand-event what-if | НЕТ | ДА |
| user manual/season adjustment | НЕТ | ДА |
| runtime network event | НЕТ | ДА |

Правило:

> Никакой фактор, уже учтённый в `model_prediction`, backend повторно не применяет.

### Один release — один показываемый прогноз

В MVP существует **ровно один активный forecast release**.

Его:

- `model_prediction` отдаёт backend;
- числа видит frontend;
- `score` показывается в `/api/meta`;
- `model_version` и `code_git_sha` описывают код, который воспроизводит именно этот release.

Не существует отдельного «leaderboard release» и отдельного «service release».

Следовательно:

```text
release_metadata.score
```

обязан относиться к **тем же forecast values**, которые реально отдаёт `/api/forecast`.

Для текущего релиза:

```text
score = 0.89447
```

можно указывать только если `forecast_release.duckdb` построен из того же прогноза, который получил этот score.

Если в release есть UI metadata:

```text
default_weather_factor
default_event_factor
default_season_factor
```

для MVP они равны:

```text
1.0
1.0
1.0
```

и нужны только интерфейсу.

Следовательно:

```text
final_default_prediction == model_prediction
```

---

## 11. Никакого `new_factor / applied_factor`

Не используем:

```text
prediction × new_factor / old_factor
```

Scenario всегда считается заново от:

```text
model_prediction
```

---

## 12. What-if формула

```text
scenario_prediction =
    model_prediction
    × weather_factor
    × demand_event_factor
    × season_manual_factor
    × manual_factor
```

Затем:

```text
operational_prediction =
    apply_network_events(scenario_prediction)
```

---

## 13. Что меняет пользователь

P0:

```text
Погода
Событие
Сезонная ручная поправка
Общая ручная поправка
```

UI:

```text
КОРРЕКТИРУЮЩИЕ ФАКТОРЫ

Погода
[ Обычная ▼ ]

Событие
[ Нет ▼ ]

Сезонная поправка
[ 0% ]

Ручная поправка
[ 0% ]

───────────────

Базовый прогноз
18 420

Сценарный прогноз
17 860

Изменение
-3.0%
```

---

## 14. Погода: только подтверждённый эффект

Не используем «демонстрационные» погодные коэффициенты как будто они измерены.

Правило:

```text
если коэффициент измерен на истории
→ можно показывать как data-driven

если не измерен
→ не заявляем его как подтверждённый эффект
```

Эффект осадков зависит от сезона, поэтому нельзя иметь один глобальный:

```text
RAIN = 0.95
```

на весь год.

Если используем погоду, `factor_options` содержит:

```text
factor_type
option_code
season
value
label
source
```

---

## 15. Demand-event what-if

Можно поддержать:

```text
NONE
MEDIUM
MAJOR
```

Но коэффициенты должны быть:

```text
измерены
или
явно помечены как manual scenario
```

---

## 16. Manual season adjustment

Slider:

```text
-20% ... 0% ... +20%
```

Это НЕ внутренняя сезонность модели.

Формула:

```text
season_manual_factor = 1 + pct / 100
```

---

## 17. Глобальные изменения сети

Они описывают реальную работу транспорта и не являются обычным what-if.

P0:

```text
FULL_CLOSURE
SHORTENING
MANUAL_MULTIPLIER
```

---

## 18. `network_events`

```text
id
route
type
valid_from
valid_to
hour_from
hour_to
factor
title
source_url
active
created_at
```

---

## 19. FULL_CLOSURE

```text
route = 17
type = FULL_CLOSURE
```

Backend:

```text
prediction = 0
```

Это deterministic физический эффект.

---

## 20. SHORTENING

```text
route = 50
type = SHORTENING
hour_from = 22
hour_to = 23
factor = measured_or_manual_value
```

Для затронутых часов:

```text
prediction *= factor
```

---

## 21. MANUAL_MULTIPLIER

Для известной поправки:

```text
route = 7
factor = 0.80
```

Используем только если:
- коэффициент измерен;
- или оператор явно задаёт его как ручную гипотезу.

---

## 22. Прямой effect vs secondary effect

Правильная формулировка:

> Прямой физический эффект network event не требует ML.  
> Вторичные эффекты на другие маршруты должны быть оценены по данным.

Пример:

```text
FULL_CLOSURE route 17
```

Гарантированно:

```text
17 → 0
```

Но:

```text
11 → ?
25 → ?
```

Backend сам это не придумывает.

---

## 23. Secondary impact rules

Если ML/анализ реально измерил перетекание:

```text
event_type
source_route
target_route
factor
source
```

Пример структуры:

```text
FULL_CLOSURE | 17 | 11 | <measured> | historical_estimate
```

Только тогда backend применяет secondary effect.

До измерения:

```text
secondary impacts = disabled
```

---

## 24. Эксперимент: перетекание спроса для 7 и 50

Это самый ценный дополнительный ML-анализ после готового baseline.

Проверяем подтверждённые периоды:

### A. С 6 сентября

По выходным:
- ремонт в Протопоповском переулке;
- маршрут 50 в затронутые дни не ходил.

### B. С 10 июля

Изменение участка:

```text
Красносельская — Белорусский вокзал
```

Особенно интересны июльские воскресенья маршрута 7.

Для каждого affected day:

1. считаем фактический daily volume по всем маршрутам;
2. строим expected baseline для соседних маршрутов;
3. сравниваем:

```text
actual / expected
```

4. используем контроль:
   - тот же weekday;
   - соседние недели;
   - тот же сезон;
   - без праздников/аномалий.

Простой estimator:

```text
effect_j =
median(
    actual_j_on_disruption_days
    /
    expected_j_on_disruption_days
)
```

Коэффициент публикуем только если:
- affected days несколько;
- знак эффекта устойчив;
- эффект заметно выше обычного недельного noise.

Если сигнал есть — добавляем `network_impact_rules`.

Если устойчивого сигнала нет — прямо пишем:

> В доступных исторических данных статистически устойчивое перетекание на наблюдаемые трамвайные маршруты не обнаружено, поэтому искусственные secondary coefficients не применяются.

---

## 25. Маршрут 5 — ВАЖНО

В текущем рабочем решении:

```text
ZERO_ROUTES = {5}
```

Для маршрута 5 прогноз должен быть:

```text
0
```

на соответствующем test/release периоде.

Причина:
- в предоставленных сырых данных по нему только нули;
- организаторы подтвердили нулевой эталон;
- ненулевой forecast даёт чистый штраф в числитель WAPE.

НЕ использовать:

```text
forecast(5) = forecast(25) × 0.7
```

в текущем release.

Механизм:

```text
new_route ≈ analogue_route × coefficient
```

остаётся допустимой будущей cold-start идеей, но маршрут 5 — неправильный пример для текущего соревнования.

---

## 26. Приоритет network events

Простой порядок:

```text
1. FULL_CLOSURE
2. остальные MULTIPLY impacts
```

Если active closure:

```text
prediction = 0
```

Иначе:

```text
prediction *= product(active_factors)
```

После:

```text
prediction = max(prediction, 0)
```

---

## 27. Реальный network event и what-if — разные вещи

Network event:

```text
маршрут реально закрыт
```

What-if:

```text
что если будет дождь?
```

What-if не меняет runtime network state.

---

## 28. Приём потоковых данных

Основной путь:

```text
POST /api/ingest/validations
```

Алиас:

```text
POST /api/v1/ingest/validations
```

Используем micro-batches.

---

## 29. Семантика validation batch

Целевая величина — успешные валидации.

Есть два допустимых режима.

### Рекомендуемый MVP

Endpoint принимает **только успешные валидации**.

Тогда:

```json
{
  "batch_id": "2025-10-31-001",
  "records": [
    {
      "timestamp": "2025-10-31T08:12:10+03:00",
      "route": 17
    }
  ]
}
```

Каждая запись уже означает `SUCCESS`.

### Расширенный режим

Если источник присылает все попытки:

```json
{
  "timestamp": "...",
  "route": 17,
  "result": "SUCCESS"
}
```

Backend считает только:

```text
result == SUCCESS
```

В контракте команды нужно выбрать один режим и зафиксировать его.

Для P0 рекомендуется successful-only input.

---

## 30. Ingest обработка

```text
1. проверить batch_id
2. проверить schema
3. проверить route/timestamp
4. group by route/date/hour
5. UPSERT hourly_aggregates
6. записать batch_id
7. вернуть success
```

---

## 31. Idempotency

```text
batch_id UNIQUE
```

Повторный batch не удваивает counts.

Response:

```json
{
  "status": "ok",
  "already_processed": true
}
```

---

## 32. `hourly_aggregates`

```text
route
date
hour
boardings
updated_at
```

Unique:

```text
(route, date, hour)
```

---

## 33. Reproducible pipeline

На защите:

```text
validation batch
↓
schema validation
↓
successful validations
↓
hourly aggregation
↓
DuckDB
↓
ML rebuild
↓
forecast release
```

---

## 34. Rebuild forecast

P0:

```bash
python -m ml.build_release \
  --data /data \
  --output /data/forecast_release.duckdb
```

Он:
1. читает данные;
2. запускает текущую модель;
3. собирает forecast;
4. применяет `ZERO_ROUTES`;
5. проверяет completeness;
6. создаёт release.

---

## 35. Reload forecast

Основной endpoint:

```text
POST /api/admin/reload-forecast
```

Алиас:

```text
POST /api/v1/admin/reload-forecast
```

Логика:

```text
load new release
↓
validate
↓
build new RAM index
↓
replace current pointer
```

Если ошибка — текущий forecast остаётся.

---

## 36. API paths — основной контракт

Работающий backend уже использует:

```text
/api/...
```

Это основной contract.

Ничего не ломаем.

Дополнительно добавляем versioned aliases:

```text
/api/v1/...
```

к тем же handlers.

Пример:

```text
/api/forecast
/api/v1/forecast
```

делают одно и то же.

---

## 37. P0 API

```text
GET  /api/forecast
POST /api/forecast/preview

GET  /api/network-events
POST /api/network-events
DELETE /api/network-events/{id}

POST /api/ingest/validations

POST /api/admin/reload-forecast

GET /api/meta
GET /health
```

И те же пути через:

```text
/api/v1/...
```

---

## 38. `/api/forecast`

Параметры:

```text
route
from
to
```

Возвращает:
- `model_prediction`;
- `operational_prediction`;
- active network events;
- release metadata.

---

## 39. `/api/forecast/preview`

Пример:

```json
{
  "route": 17,
  "from": "2025-11-15",
  "to": "2025-11-16",
  "weather": "RAIN",
  "event": "NONE",
  "season_adjustment_pct": -5,
  "manual_adjustment_pct": 0
}
```

Scenario считается от immutable `model_prediction`.

---

## 40. Ошибки API

Минимум:

```text
400 INVALID_ROUTE
400 INVALID_SCENARIO
409 DUPLICATE_EVENT
422 INVALID_BATCH
503 FORECAST_NOT_LOADED
```

Формат:

```json
{
  "code": "INVALID_ROUTE",
  "message": "Маршрут 999 не поддерживается"
}
```

---

## 41. Frontend P0

Один сильный dashboard.

На одном экране:

```text
route selector
date
hourly forecast graph

base/model forecast
scenario forecast
operational forecast

what-if controls
network warning
difference %
```

---

## 42. Explainability

Не нужен SHAP.

Показываем:

```text
ML forecast             18 420
Weather what-if         ×0.99
Demand event what-if    ×1.05
Manual season           ×0.95
Scenario demand         18 171
Network                 ×0.80
────────────────────────────
Operational scenario    14 537
```

---

## 43. External data

Используем только то, что реально подтверждено:
- производственный календарь;
- реальные изменения маршрутов;
- daylight, если реально в модели;
- погодный эффект, только если измерен;
- source URL.

Не пишем «демонстрационный weather coefficient» как доказанный эффект.

---

## 44. Performance hot path

```text
request
↓
RAM lookup
↓
scenario multiplication
↓
network lookup
↓
JSON
```

Никаких:
- pandas;
- обучения;
- большого DuckDB query;
- `model.predict` на каждый request.

---

## 45. Performance tests

Обязательно:

### Test A

```text
100% GET /api/forecast
```

### Test B

```text
80% forecast
15% preview
5% ingest batches
```

Измеряем:

```text
RPS
p50
p95
p99
error rate
CPU avg/peak
RAM avg/peak
swap
```

Минимум тест:

```text
2 vCPU / 2 GB
```

Желательно ещё:

```text
4 vCPU / 4 GB
```

Не придумывать результаты.

---

## 46. DuckDB runtime

Стартовые лимиты:

```text
threads = 1
memory_limit = 256–512 MB
```

Финальные — после benchmark.

---

## 47. Горизонтальное масштабирование

MVP:

```text
single instance
embedded DuckDB
```

Read path масштабируется:

```text
Load Balancer
├── replica A
├── replica B
└── replica C
```

Все читают immutable forecast release.

Mutable runtime в production выносится во внешний shared store.

API при этом не меняется.

---

## 48. Надёжность P0

Только дешёвые и полезные вещи:

```text
release validation
fallback при reload error
idempotent ingest
API validation
понятные errors
health/meta
```

---

## 49. `/api/meta`

```json
{
  "release_id": "hackathon-v7",
  "model_version": "statistical-v6",
  "code_git_sha": "<commit sha>",
  "score": 0.89447,
  "cutoff_date": "2025-10-31",
  "forecast_from": "2025-11-01",
  "forecast_to": "2025-12-31",
  "last_ingest_at": "...",
  "active_network_events": 2
}
```

---

## 50. Ответственность ML

P0:

```text
1. зафиксировать текущую лучшую модель
2. сохранить ZERO_ROUTES={5}
3. собрать forecast_release
4. документировать что уже внутри model_prediction
5. экспортировать только измеренные factors
6. проверить completeness
7. сделать rebuild command
8. по возможности проверить transfer effects 7/50
```

### ML deliverables, блокирующие интеграцию

Backend/frontend должны получить два конкретных артефакта:

```text
1. forecast_release.duckdb
   ИЛИ, как промежуточный вариант, submission.csv,
   содержащий ровно тот прогноз, который получил score 0.89447.

2. Значения подтверждённых корректирующих факторов
   для factors.py / factor_options.
```

Для каждого factor value должны быть известны:

```text
factor_code
option_code
value
scope/season
source
как значение было измерено
```

Если фактор не измерен, он не попадает в production factor catalog как подтверждённый внешний эффект.

`release_metadata.code_git_sha` должен указывать на commit, которым можно воспроизвести `forecast_release` / `submission.csv`.

---

## 51. Ответственность Backend

P0:

```text
1. release loader
2. RAM index
3. forecast endpoint
4. preview
5. network event CRUD
6. network overlay
7. ingest
8. reload
9. meta/health
10. errors
11. /api + /api/v1 aliases
```

---

## 52. Ответственность Frontend

P0:

```text
1. dashboard
2. route/date selector
3. hourly graph
4. base/scenario/operational values
5. what-if controls
6. network warning
7. network event form
8. errors/loading
```

---

## 53. Порядок реализации

Строго:

```text
1. current forecast → backend → frontend graph
2. what-if
3. network events
4. ingest
5. load test
6. polish
7. только потом дополнительные фичи
```

---

## 54. Demo flow

За 2–3 минуты:

```text
1. docker run
2. открыть dashboard
3. выбрать route/date
4. увидеть forecast
5. изменить scenario → graph изменился
6. добавить FULL_CLOSURE → route стал 0
7. если transfer effect измерен → соседний route изменился
8. отправить validation batch
9. повторить batch → counts не задублировались
10. показать /api/meta
11. показать понятную API error
12. показать performance section README
```

---

## 55. Definition of Done P0

Всего 7 блоков:

```text
[ ] 1. ML release с корректным route 5 = 0
[ ] 2. Forecast API + RAM
[ ] 3. What-if без double-apply
[ ] 4. Network events
[ ] 5. Successful-validation ingest + aggregation
[ ] 6. Frontend demo
[ ] 7. Load test + README
```

---

## 56. Если осталось время

Критерий качества прогноза уже закрыт на максимальный балл:

```text
score = 0.89447 > 0.88
```

Шкала критерия ступенчатая, поэтому дальнейшее улучшение leaderboard score **не даёт дополнительных баллов** и не является приоритетом хакатона.

Приоритет после готового P0:

```text
1. закончить transfer experiment 7/50
   → получить измеренные secondary network impacts
   → усилить network logic и demo

2. polished UI/demo

3. закрыть/документировать внешние источники и factor values

4. live weather adapter, только если effect измерен

5. auto daily rebuild/reload

6. general new-route cold start

7. uncertainty
```

ML-score улучшаем только если изменение почти бесплатное и не отнимает время у критериев, за которые ещё можно получить баллы.

---

## 57. Что НЕ должно съесть время

Не тратим последние часы на:

```text
scheduler
distributed storage
сложные abstractions
multi-container infra
Kafka
online training
универсальную network simulation
```

если ещё не готовы:
- dashboard;
- score;
- benchmark.

---

## 58. Формулировка для жюри про network changes

> Физическое изменение движения применяется сервисом сразу: если маршрут закрыт, его operational forecast мгновенно становится нулевым. Вторичные эффекты на соседние маршруты система применяет только если они подтверждены историческими данными. Поэтому мы не выдумываем перераспределение спроса.

---

## 59. Формулировка для жюри про what-if

> Базовый ML-прогноз immutable. Пользовательские коэффициенты считаются поверх него как отдельный сценарий, поэтому один и тот же эффект не может случайно примениться дважды и сценарий не портит основной прогноз.

---

## 60. Формулировка для жюри про обновление данных

> Сервис принимает успешные валидации micro-batches и агрегирует их по route/date/hour. Rebuild pipeline воспроизводим отдельной командой; в production эту же команду можно запускать по расписанию без изменения архитектуры.

---

## 61. Формулировка про масштабирование

> Основной forecast read path работает из RAM и не зависит от процесса обучения, поэтому read-реплики горизонтально масштабируются обычным load balancer. Embedded DuckDB используется как MVP runtime store; в multi-node deployment repository заменяется внешним shared store.

---

## 62. Поле формы: компромиссы и развитие

> В рамках хакатона мы сознательно разделили обязательный MVP и production-развитие. Serving работает одним контейнером и хранит готовый прогноз в памяти, что минимизирует задержку и расход ресурсов. Embedded DuckDB используется для агрегатов, network events и ingest-state. Мы не реализовывали Kafka, Airflow, отдельный ML-сервис и distributed storage, поскольку они не улучшают качество прогноза или пользовательский сценарий в рамках 44 часов. Архитектура при этом оставляет точки расширения: runtime repository может быть заменён на PostgreSQL при горизонтальном масштабировании, rebuild pipeline — запускаться scheduler'ом, а network impact rules — расширяться измеренными эффектами перераспределения между маршрутами. Пользовательские корректировки считаются поверх immutable `model_prediction`, что исключает двойное применение коэффициентов. Реальные изменения сети имеют отдельный operational layer: гарантированные физические эффекты применяются мгновенно, вторичные эффекты на соседние маршруты — только при наличии исторически подтверждённой оценки.

---

## 63. Performance section template

Заполнить после теста:

```markdown
## Производительность

### Test environment

- Docker image:
- CPU limit:
- RAM limit:
- Dataset:
- Tool:
- Duration:
- Concurrency:

### Forecast read

| Metric | Result |
|---|---:|
| RPS | TODO |
| p50 | TODO |
| p95 | TODO |
| p99 | TODO |
| Error rate | TODO |
| CPU avg | TODO |
| CPU peak | TODO |
| RAM avg | TODO |
| RAM peak | TODO |
| Swap | TODO |

### Mixed workload

80% forecast / 15% preview / 5% ingest.

| Metric | Result |
|---|---:|
| RPS | TODO |
| p95 | TODO |
| Error rate | TODO |
| CPU | TODO |
| RAM | TODO |
```

---

## 64. Финальная схема

```text
                  BUILD / REBUILD

historical data
runtime aggregates
external known data
        │
        ▼
      ML model
        │
        ▼
forecast_release.duckdb
        │
        ▼

             ONE CONTAINER

┌────────────────────────────────┐
│ Forecast release → RAM         │
│                                │
│ /api/forecast                  │
│ /api/forecast/preview          │
│                                │
│ Network events → overlay       │
│                                │
│ Validation ingest              │
│       ↓                        │
│ hourly aggregates              │
│       ↓                        │
│ runtime.duckdb                 │
│                                │
│ Frontend static build          │
└────────────────────────────────┘

Все /api/* также доступны через /api/v1/*.
```

---

## 65. Итог

MVP должен доказать семь вещей:

```text
1. ML прогноз сильный и воспроизводимый.
2. Прогноз быстро отдаётся из RAM.
3. Пользователь может менять коэффициенты без double-apply.
4. Реальные network events мгновенно влияют на operational forecast.
5. Secondary network effects не выдумываются: только measured historical rules.
6. Новые успешные валидации принимаются и корректно агрегируются.
7. Один контейнер реально проходит performance benchmark.
```

Всё остальное — улучшения после готового релиза.
