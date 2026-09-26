# Прогноз пассажиропотока трамваев Москвы — ML

Почасовой прогноз посадок на 10 трамвайных маршрутах. ML собирает read-only релиз
`forecast_release.duckdb`, backend держит его в памяти и считает what-if сценарии поверх `model_prediction`.

- Материалы для защиты ML-части: [docs/defense_ml.md](docs/defense_ml.md)
- Контракт ML → backend: [release/CONTRACT.md](release/CONTRACT.md)
- Релиз, `model_prediction`, коэффициенты, вторичные эффекты сети: [docs/ml_release.md](docs/ml_release.md)
- Внешние источники, ссылки и измеренные эффекты: [artifacts/external_sources.md](artifacts/external_sources.md)

## Быстрый старт
```bash
pip install -r requirements-ml.txt
# данные хакатона: dataset/labels/labels_day_train.csv, dataset/labels/labels_day_test.csv (в git не хранятся)
python -m ml.build_release --require-clean --output release/forecast_release.duckdb --submission release/submission.csv
python -m pytest tests -q
```

Релиз `hackathon-v7` (`statistical-v6`): cutoff 2025-10-31, прогноз 2025-11-01 … 2025-12-31,
маршрут 5 = 0, score 0.88987.

## Структура
| Папка | Что внутри |
|---|---|
| `ml/` | сборка релиза (`build_release`), каталог what-if коэффициентов, оценка вторичных эффектов сети |
| `src/` | модель: декомпозиция «уровень × профиль × календарь», `pipeline.forecast` от любой даты среза, события сети, cold start, rolling backtest |
| `configs/` | параметры модели и релиза |
| `data/external/` | внешние источники: календарь, каникулы, погода, световой день, изменения сети (с URL) |
| `scripts/` | получение погоды, ablation внешних источников, rolling backtest |
| `artifacts/` | внешние источники, результаты ablation, rolling backtest и эксперимента с перетеканием |
| `tests/` | проверки пайплайна и релиза |
