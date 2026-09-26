# Один контейнер: API и (если собран) статика фронтенда.
# Соответствует НФТ из ТЗ — «сервис это один контейнер 2–4 vCPU / 2–4 ГБ RAM».

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    RUNTIME_DIR=/runtime \
    STATIC_DIR=/app/static

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# Статика фронтенда: всё, что лежит в service/static/. В git там только
# .gitkeep, и тогда сервис отдаёт одно API. Запасной интерфейс ставится
# копированием: cp frontend-fallback/index.html service/static/ — и он
# войдёт в образ при сборке. Сборка фронтенд-команды кладётся туда же.
COPY static/ ./static/
RUN mkdir -p /data /runtime

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

# ДВА воркера — по числу vCPU из лимита.
#
# Замер на одном воркере: CPU 102% из 200% — второе ядро простаивало,
# холодный p95 318 мс не укладывался в порог ТЗ 300 мс. Упор был
# в пропускную способность одного процесса, а не в стоимость запроса.
#
# Несколько воркеров безопасны только потому, что изменяемое состояние
# не живёт в памяти процесса как неизменный снимок:
#   * события сети и агрегаты приёма — файлы в RUNTIME_DIR; каждый воркер
#     перечитывает файл, как только меняется его подпись (один stat на
#     запрос), а пишет под межпроцессной блокировкой;
#   * POST /api/reload меняет метку перезагрузки — остальные воркеры
#     перечитывают прогноз по ней;
#   * подписи файла событий и метки входят в ключ кеша ответов — при
#     изменении все воркеры сразу промахиваются мимо устаревших ответов.
# Подробности — app/pipeline/shared_state.py.
#
# RUNTIME_DIR обязан быть на локальной ФС (в compose — именованный том):
# на пробросе папки Windows атрибуты файлов могут кешироваться, и соседний
# воркер увидит изменение с опозданием.
#
# Перед демо проверить: python loadtest/consistency.py --url ...
# Если хоть одна проверка FAIL — вернуть "--workers", "1".
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]
