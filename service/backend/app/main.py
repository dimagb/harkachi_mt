"""Точка входа сервиса.

Цепочка модулей повторяет архитектуру решения:

    pipeline/ingest.py    приём и нормализация данных
    pipeline/geo.py       геопривязка
    pipeline/aggregate.py агрегация прогноза по маршрутам, остановкам, времени
    pipeline/adjust.py    корректирующие коэффициенты
    api/                  REST-слой
    static/               собранный фронтенд (если есть)

Прогноз рассчитывается заранее пакетным пайплайном и лежит файлом. Сервис
только читает готовые значения из памяти, поэтому отклик стабильно в единицах
миллисекунд даже под нагрузкой.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import config
from app.api import export, factors, forecast, health, network, reference
from app.api import validations as validations_api
from app.api.deps import ApiError
from app.pipeline import geo as geo_module
from app.pipeline import network_events
from app.pipeline import validations
from app.pipeline.shared_state import signature
from app.pipeline.cache import cache as response_cache
from app.pipeline.ingest import get_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

app = FastAPI(
    title=config.APP_TITLE,
    version=config.APP_VERSION,
    description=(
        "Сервис прогнозирования пассажиропотока на трамвайных маршрутах "
        "Москвы. Прогноз считается пакетно, API отдаёт готовые агрегаты "
        "с фильтрацией по маршруту, остановке, интервалу и горизонту."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# PID воркера в заголовке X-Worker: видно, какой процесс ответил. Нужно,
# чтобы проверять согласованность состояния между воркерами.
WORKER_ID = str(os.getpid())

CACHEABLE_PREFIXES = (
    "/api/forecast",
    "/api/routes",
    "/api/stops",
    "/api/geometry",
    "/api/factors",
    "/api/scope",
)


@app.middleware("http")
async def timing_and_cache(request: Request, call_next):
    """Замер времени и кеш ответов.

    Прогноз пересчитывается пакетно, поэтому в пределах жизни процесса ответ
    на один и тот же запрос неизменен и кешируется целиком.
    """
    started = time.perf_counter()
    path = request.url.path

    # Слишком большой батч отклоняется по заголовку, до чтения и разбора
    # тела — иначе сервис сначала честно загрузил бы в память всё присланное.
    if request.method == "POST" and path in validations_api.INGEST_PATHS:
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > validations.MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "code": "BATCH_TOO_LARGE",
                    "message": (
                        f"Тело батча {int(length)} байт, максимум "
                        f"{validations.MAX_BODY_BYTES}. Разбейте поток на батчи поменьше"
                    ),
                },
            )

    cacheable = request.method == "GET" and path.startswith(CACHEABLE_PREFIXES)

    if cacheable:
        # В ключе — подписи файла событий сети и метки перезагрузки. Добавили
        # закрытие через любой воркер или перезагрузили данные — ключи во всех
        # процессах сразу другие, и устаревший ответ не отдаётся нигде:
        # межпроцессная инвалидация без общего кеша. Два stat на запрос.
        state = (
            signature(config.NETWORK_EVENTS_PATH),
            signature(config.RELOAD_MARKER_PATH),
        )
        key = f"{path}?{request.url.query}#{state}"
        cached = response_cache.get(key)
        if cached is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return Response(
                content=cached["body"],
                status_code=cached["status"],
                media_type=cached["media_type"],
                headers={
                    "X-Process-Time-ms": f"{elapsed_ms:.2f}",
                    "X-Cache": "HIT",
                    "X-Worker": WORKER_ID,
                },
            )

    generation = response_cache.generation
    response = await call_next(request)

    if cacheable and response.status_code == 200:
        chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(chunks)
        response_cache.set(
            key,
            {
                "body": body,
                "status": response.status_code,
                "media_type": response.media_type,
            },
            generation=generation,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        return Response(
            content=body,
            status_code=response.status_code,
            media_type=response.media_type,
            headers={
                "X-Process-Time-ms": f"{elapsed_ms:.2f}",
                "X-Cache": "MISS",
                "X-Worker": WORKER_ID,
            },
        )

    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.2f}"
    response.headers["X-Worker"] = WORKER_ID
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return error_response(exc.status, exc.code, exc.message)


# Единый формат ошибок всего API (раздел 40 контракта): {"code", "message"}.
# Поле detail дублирует message — старый фронт читал текст оттуда.
def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "detail": message},
    )


def _explain(err: dict) -> str:
    """Ошибка валидации FastAPI человеческими словами."""
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    if kind == "missing":
        return "обязательный параметр не передан"
    if kind in ("float_parsing", "float_type"):
        return f"должно быть числом, получено {err.get('input')!r}"
    if kind in ("int_parsing", "int_type"):
        return f"должно быть целым числом, получено {err.get('input')!r}"
    if kind == "greater_than_equal":
        return f"должно быть не меньше {ctx.get('ge')}, получено {err.get('input')}"
    if kind == "less_than_equal":
        return f"должно быть не больше {ctx.get('le')}, получено {err.get('input')}"
    if kind == "bool_parsing":
        return f"должно быть true или false, получено {err.get('input')!r}"
    return err.get("msg", "неверное значение")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Ошибки разбора параметров и тела — в формате контракта, с кодом
    по смыслу: коэффициенты — INVALID_SCENARIO, маршрут — INVALID_ROUTE."""
    path = request.url.path
    errors = exc.errors()
    first = errors[0] if errors else {}
    if path in validations_api.INGEST_PATHS:
        reason = first.get("msg", "тело запроса не разобрано")
        return error_response(
            422, "INVALID_BATCH",
            f"Тело запроса должно быть JSON-объектом с batch_id и records: {reason}",
        )
    loc = first.get("loc", ())
    where = loc[0] if loc else ""
    name = str(loc[-1]) if len(loc) > 1 else ""
    text = f"{name}: {_explain(first)}" if name else _explain(first)
    if where == "query" and name.startswith("k_"):
        return error_response(400, "INVALID_SCENARIO", f"Коэффициент {text}")
    if where in ("query", "path") and name in ("route", "routes"):
        return error_response(400, "INVALID_ROUTE", f"Маршрут: {text}")
    if where in ("query", "path"):
        return error_response(400, "INVALID_PARAMETER", f"Параметр {text}")
    if path.startswith(("/api/network-events", "/api/v1/network-events")):
        return error_response(400, "INVALID_EVENT", f"Тело запроса: {text}")
    return error_response(422, "INVALID_REQUEST", f"Тело запроса: {text}")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    """404 неизвестного пути, 405 и прочие ошибки уровня HTTP — тоже
    в едином формате, а не {"detail": "Not Found"}."""
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    if exc.status_code == 404:
        message = (
            f"Эндпойнт {request.url.path} не существует. "
            "Список — GET /api, документация — /api/docs"
        )
    elif exc.status_code == 405:
        message = f"Метод {request.method} не поддерживается для {request.url.path}"
    return error_response(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), message)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Понятное сообщение вместо стектрейса — требование надёжности из ТЗ."""
    log.exception("Необработанная ошибка на %s", request.url.path)
    return error_response(
        500, "INTERNAL_ERROR", "Внутренняя ошибка сервиса. Подробности в логах."
    )


app.include_router(health.router, prefix="/api")
app.include_router(reference.router, prefix="/api")
app.include_router(forecast.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(factors.router, prefix="/api")
app.include_router(network.router, prefix="/api")
app.include_router(validations_api.router, prefix="/api")
# Алиас по разделу 36 контракта: те же обработчики, в документации один раз.
app.include_router(validations_api.router, prefix="/api/v1", include_in_schema=False)


@app.on_event("startup")
def warm_up() -> None:
    """Прогрев: данные грузятся на старте, а не при первом запросе."""
    started = time.perf_counter()
    dataset = get_dataset()
    geo = geo_module.get_geo()
    network_events.get_repository()
    validations.get_repository()
    elapsed = time.perf_counter() - started
    log.info(
        "Готов за %.2f с: прогноз %d строк, история %d строк, "
        "маршрутов с координатами %d",
        elapsed,
        len(dataset.forecast),
        len(dataset.history),
        len(geo.stops_by_route),
    )
    if not dataset.forecast:
        log.warning(
            "Файл прогноза пуст или не найден. Положите submission.csv в %s",
            config.DATA_DIR,
        )


@app.get("/api", summary="Корень API")
def api_root() -> dict:
    return {
        "service": config.APP_TITLE,
        "version": config.APP_VERSION,
        "docs": "/api/docs",
        "endpoints": [
            "GET  /api/health",
            "GET  /api/meta",
            "POST /api/reload",
            "GET  /api/routes",
            "GET  /api/stops?route=",
            "GET  /api/geometry?route=",
            "GET  /api/forecast?routes=&date_from=&date_to=&horizon=",
            "GET  /api/forecast/routes",
            "GET  /api/forecast/stops?route=",
            "GET  /api/forecast/compare",
            "GET  /api/export?format=csv|xlsx",
            "GET  /api/export/submission",
            "GET  /api/factors",
            "GET  /api/scope",
            "GET  /api/network-events",
            "POST /api/network-events",
            "DELETE /api/network-events/{id}",
            "POST /api/ingest/validations  (алиас /api/v1/ingest/validations)",
            "GET  /api/ingest/aggregates?routes=&date_from=&date_to=&granularity=day|hour",
            "GET  /api/ingest/status",
        ],
    }


# Статика фронтенда подключается, только если в каталоге есть index.html.
# Сам каталог в образе есть всегда (service/static/.gitkeep), и пустой
# не должен ломать корень: без интерфейса / отдаёт заглушку со ссылкой на API.
#
# Важно: интерфейс это SPA с несколькими экранами (главный, аналитика,
# вход). При клиентской маршрутизации браузер может запросить /analytics
# напрямую — при обновлении страницы или переходе по ссылке. Такого файла
# на диске нет, поэтому обычный StaticFiles вернул бы 404, хотя в режиме
# разработки через Vite тот же путь работает. Поэтому любой неизвестный
# путь, не начинающийся с /api, отдаёт index.html, а маршрутизацию
# доигрывает фронтенд.
if (config.STATIC_DIR / "index.html").is_file():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    STATIC_ROOT = config.STATIC_DIR.resolve()
    INDEX_FILE = STATIC_ROOT / "index.html"

    # Ассеты сборки отдаются напрямую, без прохода через catch-all.
    for folder in ("assets", "static"):
        sub = STATIC_ROOT / folder
        if sub.is_dir():
            app.mount(
                f"/{folder}",
                StaticFiles(directory=str(sub)),
                name=f"static-{folder}",
            )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # Неизвестные пути API должны отдавать понятный JSON, а не страницу.
        if full_path.startswith("api"):
            return error_response(
                404, "NOT_FOUND",
                f"Эндпойнт /{full_path} не существует. "
                "Список — GET /api, документация — /api/docs",
            )
        if full_path:
            candidate = (STATIC_ROOT / full_path).resolve()
            # Защита от выхода за пределы каталога статики.
            if candidate.is_file() and candidate.is_relative_to(STATIC_ROOT):
                return FileResponse(candidate)
        if INDEX_FILE.is_file():
            return FileResponse(INDEX_FILE)
        return error_response(404, "NOT_FOUND", "index.html пропал из каталога статики")

    log.info("Статика фронтенда подключена из %s", config.STATIC_DIR)
else:

    @app.get("/", summary="Заглушка вместо фронтенда")
    def root() -> dict:
        return {
            "service": config.APP_TITLE,
            "note": "Фронтенд не собран. API доступно по /api, документация — /api/docs",
        }
