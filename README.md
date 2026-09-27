# Прогноз пассажиропотока трамвайных маршрутов Москвы

Решение трека «ИИ-прогноз загрузки трамвайных маршрутов»,
хакатон МТТЕХ, сентябрь 2026.

Прогнозирует число посадок по маршрутам и часам на два месяца вперёд
и отдаёт результат через веб-сервис с картой, агрегацией и выгрузкой.

**Лучший результат и текущий ML-релиз: 0.90268** (оценка, сообщённая командой),
при базлайне организаторов 0.48. Релиз `hackathon-v8` объединяет статистическую
декомпозицию и Chronos-2, учитывает восстановление движения 7/50 с 15 ноября
и cold start маршрута 5 с 16 декабря 18:00. Текущий CSV совпадает с оценённым
по MD5 `a2a872c04316e64e41ad2ac7940cd45c`.

Релиз явно ретроспективный (`leaderboard`): использует официальные объявления,
опубликованные после 31 октября, и прежнюю калибровку ×1.012. В режиме
`production` события ограничены датой публикации и калибровки по лидерборду нет.
Скрытые целевые валидации ноября–декабря не используются. Старый релиз 0.88987
сохранён в `release/archive/hackathon-v7/`.

---

## Ответы на форму сдачи: где что смотреть

Репозиторий: https://github.com/dimagb/harkachi_mt. Ниже по каждому полю формы
«Загрузка решения» — ссылка для вставки, короткий текст ответа и где
проверить. Все ссылки ведут в ветку `main`.

### 1. Артефакты ML-модели, код обучения и инференса, README

**Ссылка:** https://github.com/dimagb/harkachi_mt/blob/main/README_ML.md

Модель — ансамбль статистической декомпозиции (уровень × почасовой профиль ×
производственный календарь × события сети) и замороженного Chronos-2,
релиз `hackathon-v8`, WAPE-score 0.90268. Сборка прогноза — одна команда
(раздел «Быстрый старт» ниже), результат проверяется по MD5.

| Что | Где |
|---|---|
| Инструкция запуска ML | [README_ML.md](README_ML.md), раздел «Быстрый старт» этого файла |
| Код пайплайна | [src/](src/): `pipeline.py`, `models/decomp.py`, `models/chronos_ensemble.py`, `models/cold_start.py`, `calendar_ru.py`, `events.py`, `validation.py`, `rolling.py` |
| Сборка и проверка релиза | [ml/build_release.py](ml/build_release.py), [ml/verify_release.py](ml/verify_release.py), [ml/refresh_chronos.py](ml/refresh_chronos.py) |
| Параметры модели и релиза | [configs/final_model.json](configs/final_model.json), [configs/release.json](configs/release.json) |
| Артефакты | [release/](release/): `forecast_release.duckdb`, `submission.csv`, `factor_options.json`; компоненты Chronos — [artifacts/chronos/](artifacts/chronos/) |
| Данные для обучения | [service/data/labels/](service/data/labels/), срез до 2025-10-31 |
| Валидация и эксперименты | [docs/defense_ml.md](docs/defense_ml.md), [docs/model.md](docs/model.md), [artifacts/](artifacts/), [scripts/](scripts/) |
| Тесты | [tests/](tests/) |
| Предыдущий релиз v7 (0.88987) | [release/archive/hackathon-v7/](release/archive/hackathon-v7/) |

### 2. Внешние данные

**Ссылка:** https://github.com/dimagb/harkachi_mt/blob/main/docs/external-sources.md

Каждый источник — с первоисточником, локальной копией и измеренным эффектом
(ablation на 4 временных fold). Сервис в сеть не ходит, всё лежит в репозитории.

| Источник | Файл в репозитории | Эффект |
|---|---|---|
| Производственный календарь 2025–2026 | [data/external/production_calendar.csv](data/external/production_calendar.csv) | бэктест 0.8782 → 0.8868 |
| Световой день (астрономический расчёт) | [data/external/daylight_moscow_2025.csv](data/external/daylight_moscow_2025.csv) | 0.8885 → 0.8896 |
| Публикации о ремонтах, закрытиях и восстановлении движения (7/50, запуск маршрута 5) | [data/external/network_events.csv](data/external/network_events.csv) | в прогнозе; запуск маршрута 5 +0.0046 на лидерборде |
| Архив погоды Open-Meteo | [data/external/weather_moscow_2025_hourly.csv](data/external/weather_moscow_2025_hourly.csv) | what-if коэффициенты тёплого сезона |
| Школьные каникулы Москвы | [data/external/school_holidays_moscow.csv](data/external/school_holidays_moscow.csv) | измерен, не применён |
| Предобученная модель Chronos-2 (Apache-2.0) | https://huggingface.co/amazon/chronos-2, ревизия в [configs/final_model.json](configs/final_model.json) | 25% дневного объёма и профиля |

Машиночитаемо — `GET /api/factors`; расчёты — [artifacts/external_sources.md](artifacts/external_sources.md),
[artifacts/ablation_external.csv](artifacts/ablation_external.csv).

### 3. Запускаемый веб-сервис

**Ссылка:** https://github.com/dimagb/harkachi_mt/blob/main/service/README.md

```bash
cd service
docker compose up --build
```

Данные уже в образе, ничего подкладывать не нужно. Интерфейс —
http://localhost:8000 (вход без пароля, кнопка «Войти»; форма изменений сети —
в роли «Администратор»), документация API — http://localhost:8000/api/docs,
проверка — `GET /api/health`.

| Что | Где |
|---|---|
| Запуск, точки входа API, примеры запросов | [service/README.md](service/README.md), разделы «Запуск» и «Точки входа API» |
| Инструкция для жюри: что открыть и нажать | [docs/demo.md](docs/demo.md) |
| Backend | [service/backend/app/](service/backend/app/) |
| Frontend: исходники / собранный | [frontend/](frontend/) / [service/static/](service/static/) |
| Docker | [service/Dockerfile](service/Dockerfile), [service/docker-compose.yml](service/docker-compose.yml) |

### 4. Схема архитектуры, область определения и адаптация модели

**Ссылка:** https://github.com/dimagb/harkachi_mt/blob/main/docs/architecture.md

| Что | Где |
|---|---|
| Схема | [docs/architecture.svg](docs/architecture.svg) |
| Модули: приём → геопривязка → агрегация → коэффициенты → события сети → API → фронт | [docs/architecture.md](docs/architecture.md), «Цепочка модулей» |
| Область определения модели | там же, «Область определения модели»; машиночитаемо — `GET /api/scope` |
| Адаптация и перенос модели | там же, «Ограничения и перенос модели» |
| Зависимости от внешних данных и что будет без них | там же, «Зависимости от внешних данных» |
| Контракт ML → backend | [release/CONTRACT.md](release/CONTRACT.md), [docs/ml_release.md](docs/ml_release.md) |

### 5. Производительность и дополнительные возможности

**Ссылка:** https://github.com/dimagb/harkachi_mt/blob/main/service/README.md#производительность

Контейнер 2 CPU / 2 GiB, swap запрещён, uvicorn, два воркера; `loadtest.py`,
30 с, 32 потока, 0 ошибок:

| | RPS | p50 | p95 | p99 | RAM |
|---|---|---|---|---|---|
| Прогретый кеш | 2 614 | 7.5 мс | 37.6 мс | 55.6 мс | < 200 МиБ |
| Холодный кеш, каждый запрос уникален | 497 | 61.8 мс | 102.4 мс | 130.2 мс | < 200 МиБ |

Требование ТЗ — сотни RPS при p95 < 200–300 мс — выполнено в обоих режимах.
Согласованность двух воркеров — `service/loadtest/consistency.py`, 7 из 7.

Дополнительные возможности — таблица в [service/README.md](service/README.md#дополнительные-возможности):
три горизонта, разбивка по остановкам, корректирующие коэффициенты
и what-if сценарии, события сети (закрытие, укорочение, множитель) и измеренное
перетекание 17 → 11, сравнение с фактом, выгрузка CSV/XLSX и в формате сдачи,
приём потока валидаций, перезагрузка прогноза без перезапуска, кеш, алиасы `/api/v1`.

### 6. Ограничения и план развития

**Ссылка:** https://github.com/dimagb/harkachi_mt/blob/main/service/README.md#ограничения

Ограничения — [service/README.md](service/README.md#ограничения) и
[docs/architecture.md](docs/architecture.md), «Ограничения и перенос модели»;
план — [service/README.md](service/README.md#что-дальше), [docs/roadmap.md](docs/roadmap.md).

Коротко:
- прогнозируются оплаты «маршрут × час»; разбивка по остановкам оценочная, телематики нет;
- история — 10 месяцев одного года, годовой сезонности модель не видит,
  декабрьский праздничный режим взят по январскому аналогу;
- маршрут 5 без истории: прогноз с 16.12 по аналогу (0.7 × маршрут 25);
- сданный прогноз ретроспективный (объявления после 31.10 учтены явно),
  в режиме `production` — только известное на дату среза;
- изменения сети задаются вручную, вторичный эффект измерен один (17 → 11, выходные);
- цикл «приём потока → пересборка» пока не замкнут.

План: телематика и наполняемость, геопривязка валидаций к остановкам,
несколько лет истории, регулярное переобучение, рекомендации по выпуску
подвижного состава, замыкание цикла приёма данных.

---

## Обучение, инференс и артефакт модели

Статистическая часть (`src/models/decomp.py`) оценивает уровень и почасовой
профиль по labels января–октября. Замороженный pretrained Chronos-2 прогнозирует
дневной объём и 24 часовых канала по календарю, световому дню и событиям сети;
доля Chronos в дневном объёме и почасовом профиле — по 25%. Частного дообучения
в сданной модели нет. Маршрут 5 сохраняет ранее проверенный prior 0.7 × маршрут 25.

Основной код — `src/pipeline.py`, `src/models/chronos_ensemble.py`; точная ревизия
весов и настройки — `configs/final_model.json`. Проверенные компоненты инференса
и контрольные суммы истории/источников — `artifacts/chronos/`.
`release/forecast_release.duckdb`, `release/submission.csv` и
`service/data/submission.csv` содержат один и тот же прогноз. Веб-запросы читают
готовые значения: PyTorch и скачивание весов сервису не нужны.

## Быстрый старт

### Воспроизвести сданный прогноз

Нужен Python 3.12. Labels лежат в `service/data/labels/`; сырые файлы и ночная
папка для сборки не нужны. Использование проверенных компонентов не требует сети.

```bash
python -m venv .venv-ml
# Windows: .venv-ml/Scripts/python; Linux/macOS: .venv-ml/bin/python
.venv-ml/bin/python -m pip install -r requirements-ml.txt
.venv-ml/bin/python -m ml.build_release --data service/data \
    --output release/forecast_release.duckdb --submission release/submission.csv
.venv-ml/bin/python -m ml.verify_release
```

Ожидаемый MD5: `a2a872c04316e64e41ad2ac7940cd45c`, score **0.90268**.
`ml.verify_release` проверяет также совпадение CSV сервиса и таблицы DuckDB.
После пересборки скопируйте `release/submission.csv` в `service/data/submission.csv`
для публикации обновлённого прогноза в сервисе; в поставляемом релизе они уже равны.

Повторный инференс из pinned pretrained весов (нужна сеть при первом скачивании):

```bash
.venv-ml/bin/python -m pip install -r requirements-foundation.txt
.venv-ml/bin/python -m ml.refresh_chronos --data service/data --mode leaderboard
.venv-ml/bin/python -m ml.build_release --data service/data --submission release/submission.csv
```

Кэши модели находятся в `.ml-cache/` внутри проекта. При изменении истории,
источников или горизонта старые компоненты не используются: требуется новый
инференс. Score присваивается только при точном совпадении MD5. `--require-clean`
включают после локального коммита; текущая интеграция не закоммичена, поэтому
чистый SHA сборки не заявляется.

Тесты: `TRAM_DATASET=service/data python -m pytest tests -q`.
Подробности, результаты и ограничения — `README_ML.md`, `docs/defense_ml.md`.

### История: ранний базлайн

`ml/baseline.py` — статистический базлайн ранней стадии. Дал 0.86923 на
лидерборде, **в сдачу не идёт**, оставлен как история работы: журнал его
экспериментов — `docs/model.md`. `ml/profile_data.py` — разведка датасета;
оба скрипта требуют сырые данные хакатона (`initial_data/`, в git нет).

```bash
python ml/profile_data.py initial_data > report.txt   # разведка сырых данных
python ml/baseline.py initial_data                    # ранний базлайн, 0.86923
```

### Сервис

```bash
cd service
docker compose up --build   # данные уже в service/data/, подкладывать ничего не нужно
# http://localhost:8000/api/docs
```

Интерфейс — http://localhost:8000: вход, диспетчерская, аналитика.
Собранный фронтенд уже лежит в `service/static/` и попадает в образ,
npm и сеть при сборке не нужны. Вход без пароля: достаточно нажать
«Войти»; форма изменений сети — в роли «Администратор».

Пересобрать фронтенд из исходников (`frontend/`, нужен Node.js):

```bash
cd frontend && npm ci && npm test && npm run build:service
# dist/ автоматически скопирован в service/static/, .gitkeep сохранён
```

После изменения фронтенда снова выполните `npm run build:service`, затем
пересоберите сервис: `cd ../service && docker compose up --build`.
Dockerfile и Compose используют готовую статику; отдельный Vite или nginx
для этого запуска не требуется. Текущий состав экранов и ограничения UI
описаны в `docs/frontend-tasks.md` и `frontend/README.md`.

### Нагрузочный тест

```bash
python service/loadtest/loadtest.py --url http://localhost:8000 --duration 30 --threads 32
python service/loadtest/loadtest.py --url http://localhost:8000 --duration 30 --threads 32 --cold
```

Итог в контейнере 2 CPU / 2 GiB, два воркера: прогретый кеш 2 614 RPS при
p95 38 мс, холодный 497 RPS при p95 102 мс — требование ТЗ выполняется
в обоих режимах. Полная таблица — `service/README.md`.

---

## Структура

```
CLAUDE.md               контекст проекта: факты, правила, эксперименты
docs/
  rubric.md             рубрика оценки с чек-листами
  data.md               что реально в датасете
  model.md              модель, валидация, журнал экспериментов
  architecture.md       архитектура и область применимости (поле 4), схема .svg
  external-sources.md   внешние источники с измеренными эффектами (поле 2)
  defense_ml.md         ML-часть для защиты (ML-команда)
  ml_release.md         релиз, model_prediction, коэффициенты
  decisions.md          решения и аргументы для защиты
  submission.md         чек-лист сдачи
  roadmap.md            что осталось, по приоритету баллов
  stas-mvp-architecture.md  действующий контракт и план MVP
  ML_BACKEND_CONTRACT.md  отменён, оставлен как история
  frontend-tasks.md     задание фронтенду: экраны, API, сборка
README_ML.md            ML-часть: сборка релиза, тесты
src/                    модель релиза: уровень × профиль × календарь, cold start
ml/
  build_release.py      сборка релиза hackathon-v8 → submission.csv
  transfer_experiment.py  перетекание спроса при закрытиях
  baseline.py           ранний базлайн (0.86923), в сдачу не идёт, история
  profile_data.py       разведка сырого датасета
configs/, release/      параметры модели и релиза, контракт ML → backend
data/external/          внешние источники с URL
artifacts/, scripts/    ablation, бэктест, эксперименты
tests/                  тесты пайплайна и релиза
frontend/               интерфейс: React + Vite, сборка — в service/static/
frontend-fallback/      запасной дашборд одним файлом (резерв, в образ не входит)
service/
  Dockerfile            один контейнер, два воркера: API и статика
  docker-compose.yml
  README.md             запуск, эндпойнты, ошибки, производительность
  backend/app/
    pipeline/           чтение данных → геопривязка → агрегация →
                        коэффициенты → события сети; приём потока
    api/                REST-слой
  static/               собранный интерфейс (сборка frontend/), хранится в git, входит в образ
  data/                 прогноз, labels, справочники — всё для сервиса и пересборки
  loadtest/             нагрузочный тест и проверка согласованности воркеров
initial_data/           сырые данные хакатона (~10 ГБ), в git нет; нужны только
                        baseline.py и profile_data.py
```

---

## Как устроено решение

Прогноз считается **пакетно** и сохраняется файлом в формате сдачи.
Веб-сервис читает готовые значения из памяти и агрегирует под запрос —
модель в момент обращения не работает.

Один расчёт даёт два результата: файл для лидерборда и данные для
дашборда. Расхождений между ними быть не может.

Модель прогноза (релиз `hackathon-v8`, `decomposition-chronos2-v1`) — ансамбль Chronos-2 и прозрачной
декомпозиции:

```
прогноз = уровень(маршрут, день недели) × доля часа(маршрут, тип дня, час) × календарь × события
```

Бустинг проверен (LightGBM в трёх ролях) и в основу не вошёл: устойчивого
прироста на временной валидации не дал. Подробности: `docs/defense_ml.md`;
ранняя модель и журнал экспериментов — `docs/model.md`.

---

## Ключевые факты о задаче

- Целевая величина: число валидаций с `validation_result = 1`,
  гранулярность «маршрут × час»
- Метрика: `WAPE-score = max(0, 1 − Σ|y−ŷ|/Σy)`, баллы начисляются
  ступенями; верхняя ступень 0.88 пройдена
- Горизонт 61 день: будущие фактические лаги недоступны; история до среза используется как контекст Chronos
- В истории девять маршрутов; прогнозируется десять — маршрут 5 запущен
  16 декабря 2025 и в истории отсутствует. В v8 он нулевой до
  16 декабря 18:00, затем prior 0.7 × статистический маршрут 25
- Телематики в датасете нет
- Сдача: ровно 14 640 строк, разделитель `;`

Полный список: `CLAUDE.md`.

---

## Ограничения и план развития

`service/README.md`, разделы «Ограничения» и «Что дальше»; ограничения
и условия переноса модели — `docs/architecture.md`.
