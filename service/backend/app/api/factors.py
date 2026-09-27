"""Внешние источники данных и область применимости модели.

Отдельный эндпойнт, потому что это отдельный критерий оценки: источники
должны быть перечислены со ссылками, а границы применимости модели — описаны
явно. Интерфейс показывает это пользователю, а жюри видит в API.

Содержание совпадает с docs/external-sources.md — это одна и та же страница
для поля 2 формы, здесь в машиночитаемом виде. Первоисточник чисел —
artifacts/ (ablation, эксперимент с перетеканием) из ML-релиза hackathon-v7.

Статусы:
    confirmed            эффект измерен и указан цифрой
    measured_not_applied эффект измерен, но в сданной версии прогноза
                         не используется
    checked_no_effect    проверка сделана, эффект не найден
    stub                 заготовка: эффект не измерен, источник не заявляется

applied — где источник работает: forecast (внутри model_prediction),
what_if (обоснованные значения ползунков), none.
"""

from __future__ import annotations

import json

from fastapi import APIRouter

from app import config
from app.pipeline.network_events import SECONDARY_RULES

router = APIRouter(tags=["данные и применимость"])

ABLATION_METHOD = (
    "Ablation на 4 временных fold (история до начала fold → прогноз), "
    "взвешенный WAPE-score; scripts/ablation_external.py"
)

EXTERNAL_SOURCES = [
    {
        "id": "calendar",
        "status": "confirmed",
        "applied": "forecast",
        "title": "Производственный календарь РФ 2025–2026",
        "category": "сезонность и календарь",
        "url": "https://www.consultant.ru/law/ref/calendar/proizvodstvennye/2025/",
        "urls": [
            "https://www.consultant.ru/law/ref/calendar/proizvodstvennye/2025/",
            "https://www.consultant.ru/document/cons_doc_LAW_515170/",
        ],
        "used_for": (
            "Нерабочие дни с переносами (постановления № 1335 и № 1466): "
            "праздник в будний день получает уровень и профиль воскресенья, "
            "рабочая суббота 1.11 — пятницы, отдельные множители новогодних дней."
        ),
        "effect": (
            "Бэктест 0.8782 → 0.8868 (+0.0086); на fold с майскими праздниками "
            "0.7915 → 0.8525. По данным: 1–8 января 103 тыс. посадок в день "
            "против 209 тыс. в обычные — коэффициент 0.49."
        ),
        "method": ABLATION_METHOD,
        "integration": "data/external/production_calendar.csv, у строк номер постановления",
    },
    {
        "id": "daylight",
        "status": "confirmed",
        "applied": "forecast",
        "title": "Световой день (рассвет и закат по Москве)",
        "category": "сезонность",
        "url": "https://gml.noaa.gov/grad/solcalc/solareqns.PDF",
        "urls": [
            "https://gml.noaa.gov/grad/solcalc/solareqns.PDF",
            "https://open-meteo.com/en/docs/historical-weather-api",
        ],
        "used_for": (
            "Сдвиг часового профиля под длину дня: зимой вечерние часы "
            "загружены меньше. Сила поправки 0.5."
        ),
        "effect": (
            "Бэктест 0.8885 → 0.8896 (+0.0011), рост на всех 4 fold. Без "
            "поправки вечер 20–22 ч переоценивался на 3–16% при "
            "укорачивающемся дне."
        ),
        "method": ABLATION_METHOD + "; расчёт сверен с Open-Meteo, расхождение ≤ 6 мин",
        "integration": "Считается кодом (src/astro.py), копия на 2025 — data/external/daylight_moscow_2025.csv",
    },
    {
        "id": "roadworks",
        "status": "confirmed",
        "applied": "forecast",
        "title": "Публикации о ремонтах и закрытиях участков",
        "category": "изменения сети",
        "url": "https://newsvostok.ru/dlya-tramvaev-7-i-50-izmeneniya-po-vyhodnym-budut-dejstvovat-do-kontsa-oseni/",
        "urls": [
            "https://newsvostok.ru/dlya-tramvaev-7-i-50-izmeneniya-po-vyhodnym-budut-dejstvovat-do-kontsa-oseni/",
            "https://rimc-rambam.ru/news/14880/",
            "https://uv-kurier.ru/2025/07/08/u-tramvaya-37-konechnaya-budet-v-lefortove-a-marshruty-50-i-13-obedinyat/",
            "https://i.transport.mos.ru/perekrytiya",
        ],
        "used_for": (
            "Протопоповский переулок: маршрут 50 по выходным не ходит, 7 "
            "укорочен, с 6.09.2025 «до конца осени» — в прогнозе режим "
            "выходных 7 и 50 в ноябре, возврат в декабре. Участок "
            "Красносельская — Белорусский вокзал с 10.07.2025. Дни ремонтов "
            "вычищаются из истории."
        ),
        "effect": (
            "Посадки в дни события против медианы тех же дней недели до "
            "события: маршрут 50 в выходные с 6.09 — 0.02 нормы; маршрут 7 "
            "с 10.07 — 0.43 нормы в будни и 0.53 в выходные. Вклад в метрику "
            "на прогнозе не измерить: продолжение режима — горизонт прогноза."
        ),
        "method": "Фактические посадки из labels, медиана дней события к медиане тех же дней недели до события",
        "integration": "data/external/network_events.csv с URL и published_at; в сервисе — события сети с source_url",
    },
    {
        "id": "weather",
        "status": "confirmed",
        "applied": "what_if",
        "title": "Архив погоды Open-Meteo (ERA5)",
        "category": "погодные условия",
        "url": "https://open-meteo.com/en/docs/historical-weather-api",
        "urls": ["https://open-meteo.com/en/docs/historical-weather-api"],
        "used_for": (
            "Осадки, снег, температура почасово за 2025 год. Обоснованные "
            "значения ползунка погоды; в прогноз не входит: в холодный сезон "
            "эффекта почти нет, единая поправка ухудшала бэктест "
            "(0.8868 → 0.8862)."
        ),
        "effect": (
            "Тёплый сезон (апрель–сентябрь), значимы: лёгкий дождь 0.973, "
            "дождь 0.946, сильный дождь 0.897, снег 0.958, жара 0.964. "
            "Холодный сезон: лёгкий дождь 0.997 и снег 0.991 — не значимы."
        ),
        "what_if_options": {
            "warm": {"RAIN_LIGHT": 0.973, "RAIN": 0.946, "RAIN_HEAVY": 0.897,
                     "SNOW": 0.958, "HEAT": 0.964},
            "cold": {},
        },
        "method": (
            "Посадки в дни с условием к ожидаемым (медиана маршрута и дня "
            "недели ±21 день), нормировано на сухие дни того же сезона; "
            "90%-интервал — бутстреп по датам. Подтверждены только значимые."
        ),
        "integration": "data/external/weather_moscow_2025_hourly.csv, выгрузка scripts/fetch_weather.py",
    },
    {
        "id": "route_5_launch",
        "status": "measured_not_applied",
        "applied": "none",
        "title": "Новость о запуске маршрута 5",
        "category": "изменения сети",
        "url": "https://www.m24.ru/videos/transport/16122025/856629",
        "urls": [
            "https://www.m24.ru/videos/transport/16122025/856629",
            "https://msk1.ru/text/transport/2025/12/16/76173070/",
            "https://www.gazetametro.ru/articles/s-20-dekabrja-skorrektirujut-marshruty-nazemnogo-transporta-v-raznyh-chastjah-goroda-18-12-2025",
        ],
        "used_for": (
            "Дата запуска 16.12.2025 и конечные Белорусский вокзал — Метро "
            "«Рижская»; сходятся со справочником (route_date_start = "
            "2025-12-16). В сервисе — только дата запуска (starts_at)."
        ),
        "effect": (
            "Измерен на лидерборде: cold start от аналога с даты запуска дал "
            "0.89447 (лучший результат команды), тот же прогноз с нулями по "
            "маршруту 5 — 0.88987; эффект +0.0046. В сданной версии не "
            "применён: в релизе маршрут 5 нулевой на весь период."
        ),
        "method": "Две отправки на лидерборд, отличающиеся только маршрутом 5",
        "integration": "Запись new_route в data/external/network_events.csv; дата в конфигурации сервиса",
    },
    {
        "id": "school_holidays",
        "status": "measured_not_applied",
        "applied": "none",
        "title": "Школьные каникулы Москвы",
        "category": "сезонность и календарь",
        "url": "https://otvet.userecho.ru/knowledge-bases/2/articles/36-raspisanie-kanikul-2025-2026-v-moskovskih-shkolah-tochnyie-datyi-i-grafiki",
        "urls": ["https://otvet.userecho.ru/knowledge-bases/2/articles/36-raspisanie-kanikul-2025-2026-v-moskovskih-shkolah-tochnyie-datyi-i-grafiki"],
        "used_for": "Проверка в ablation",
        "effect": "На трамвай ≈ −2%; бэктест 0.8868 → 0.8867 — нейтрально, в прогноз не взят",
        "method": ABLATION_METHOD,
        "integration": "data/external/school_holidays_moscow.csv",
    },
    {
        "id": "metro_closures",
        "status": "checked_no_effect",
        "applied": "none",
        "title": "Закрытия станций метро, трамвайный диаметр Т1",
        "category": "изменения сети",
        "url": "https://transport.mos.ru/metro/repairs_closures_metro",
        "urls": [
            "https://transport.mos.ru/metro/repairs_closures_metro",
            "https://rg.ru/2025/11/12/reg-cfo/bystree-metro.html",
        ],
        "used_for": "Проверка близости закрытых станций к нашим остановкам",
        "effect": (
            "Эффекта нет: ни одна остановка не ближе 1 км к закрытой станции; "
            "диаметр Т1 объединил маршруты 13 и 39 — не наши"
        ),
        "method": "Расстояние по координатам остановок из справочника организаторов",
        "integration": None,
    },
    {
        "id": "traffic",
        "status": "stub",
        "applied": "none",
        "title": "Загруженность улиц (TomTom Traffic Index)",
        "category": "дорожный трафик",
        "url": "https://www.tomtom.com/traffic-index/",
        "urls": [
            "https://www.tomtom.com/traffic-index/",
            "https://www.kommersant.ru/doc/8364073",
        ],
        "used_for": "ЗАГОТОВКА",
        "effect": (
            "Не измерен — источник не заявляется: открытого дневного архива "
            "за 2025 нет, годовой профиль по часам ничего не добавляет"
        ),
        "method": None,
        "integration": None,
    },
    {
        "id": "kicksharing_season",
        "status": "stub",
        "applied": "none",
        "title": "Конец сезона кикшеринга 14.11.2025",
        "category": "сезонность",
        "url": "https://www.vedomosti.ru/business/news/2025/11/14/1154982-sezon-elektrosamokatov",
        "urls": [
            "https://www.vedomosti.ru/business/news/2025/11/14/1154982-sezon-elektrosamokatov",
            "https://rg.ru/2025/11/16/reg-cfo/vse-po-pravilam.html",
        ],
        "used_for": "ЗАГОТОВКА. Возможное объяснение осеннего роста спроса",
        "effect": "Не измерен — одного года истории недостаточно; источник не заявляется",
        "method": None,
        "integration": None,
    },
]

# Вторичные эффекты изменений сети: ml/transfer_experiment.py,
# artifacts/transfer_experiment.md. Из 23 проверенных пар опубликовано одно.
# Источник правды — SECONDARY_RULES, которые сервис и применяет.
NETWORK_IMPACT_RULES = [
    {
        "event_type": rule.event_type,
        "source_route": rule.source_route,
        "target_route": rule.target_route,
        "factor": rule.factor,
        "evidence": rule.evidence,
        "caveat": rule.caveat,
        "applied_in_service": True,
        "applied_when": (
            f"активно FULL_CLOSURE маршрута {rule.source_route}; только в его дни "
            "и часы и только в субботу и воскресенье; после прямых эффектов событий "
            f"на маршруте {rule.target_route}, до max(прогноз, 0); в ответе — "
            "отдельной записью secondary_effects"
        ),
        "weekdays": sorted(rule.weekdays),
    }
    for rule in SECONDARY_RULES
]

MODEL_SCOPE = {
    "target": {
        "definition": "Число успешных валидаций (validation_result = 1)",
        "granularity": "маршрут × календарный час",
        "note": (
            "Прогнозируются оплаты проезда, а не фактическая наполняемость "
            "салона: телематики и данных о выходе пассажиров в датасете нет."
        ),
    },
    "valid_for": {
        "routes": [1, 7, 11, 12, 17, 25, 26, 28, 50],
        "horizon_days": 61,
        "period": ["2025-11-01", "2025-12-31"],
        "training_period": ["2025-01-01", "2025-10-31"],
    },
    "limitations": [
        "Маршрут 5 запущен 16.12.2025 и в истории отсутствует. Он есть "
        "в сетке прогноза, но в сданном релизе нулевой на весь период. "
        "Cold start от маршрута-аналога измерен (+0.0046 на лидерборде), "
        "но в сданную версию не взят.",
        "Остановочная детализация оценочная: привязки валидаций к остановкам "
        "в данных нет, place_id — это код депо.",
        "Координаты остановок есть только для маршрутов 1, 5, 7, 11, 12.",
        "История покрывает 10 месяцев одного года, поэтому годовая "
        "сезонность и межгодовое сравнение недоступны.",
        "Декабрьский праздничный режим смоделирован по январскому аналогу — "
        "это допущение, а не наблюдение.",
        "Изменения сети (новые участки, закрытия) моделью не "
        "предсказываются: закрытия и укорочения задаются вручную событиями "
        "сети, прямой эффект применяется поверх прогноза.",
        "Перетекание спроса при закрытиях: из 23 проверенных пар устойчиво "
        "одно правило — закрытие маршрута 17 даёт маршруту 11 × 1.108, "
        "измерено на 4 выходных днях апреля. Для остальных пар перетекание "
        "в данных не наблюдается. Данные видят только трамвай: ушедших "
        "в метро и на автобусы не видно. Правило 17 → 11 применяется "
        "в сервисе при активном закрытии маршрута 17 и только в выходные: "
        "измерено на выходных, перенос на будни требует отдельного измерения.",
        "Погода в прогноз не входит: в холодный сезон её эффект не значим; "
        "измеренные коэффициенты тёплого сезона доступны как what-if.",
    ],
    "adaptation": [
        "Перенос на новые маршруты: нужна история не менее 8 недель для "
        "оценки сезонного профиля. До этого — cold start от маршрута-аналога "
        "с даты запуска; на маршруте 5 он измерен, но в релиз не взят.",
        "Перенос на новый период: релиз пересобирается с новой датой среза "
        "(ml.build_release --cutoff), структура модели не меняется; "
        "календарь 2026 уже в данных.",
        "Зависимость от внешних данных мягкая: без них модель работает, "
        "но без производственного календаря бэктест падает 0.8868 → 0.8782.",
    ],
}


@router.get("/factors", summary="Внешние источники данных")
def factors() -> dict:
    by_status: dict = {}
    for source in EXTERNAL_SOURCES:
        by_status[source["status"]] = by_status.get(source["status"], 0) + 1
    try:
        catalog = json.loads(config.FACTOR_OPTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        catalog = {"seasons": {}, "options": []}
    return {
        "sources": EXTERNAL_SOURCES,
        "seasons": catalog.get("seasons", {}),
        "options": [
            {
                **option,
                "status": (
                    "confirmed" if option.get("confirmed") else
                    "manual_scenario" if option.get("source") == "manual_scenario" else
                    "measured_not_confirmed" if option.get("is_measured") else
                    "neutral"
                ),
            }
            for option in catalog.get("options", [])
        ],
        "count": len(EXTERNAL_SOURCES),
        "by_status": by_status,
        "network_impact_rules": NETWORK_IMPACT_RULES,
        "note": (
            "confirmed — эффект измерен; measured_not_applied — эффект "
            "измерен, но в сданной версии прогноза не применён; "
            "checked_no_effect — проверено, эффекта нет; stub — заготовка, "
            "эффект не измерен, источник не заявляется. Данные кешируются "
            "локально: сервис не ходит в сеть во время работы."
        ),
    }


@router.get("/scope", summary="Область определения и адаптации модели")
def scope() -> dict:
    return MODEL_SCOPE
