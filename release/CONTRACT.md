# ML → Backend: контракт `forecast_release.duckdb`

Единственный контракт между ML и backend — read-only файл `forecast_release.duckdb`
(`schema_version = 1.0`). Финальный релиз собирается из закоммиченного кода:

```bash
python -m ml.build_release --require-clean --data service/data --output release/forecast_release.duckdb --submission release/submission.csv
python -m ml.build_release --data /data --output /data/forecast_release.duckdb     # в ML-окружении, не в образе сервиса
```

Полное описание таблиц, содержимого `model_prediction` и коэффициентов — `docs/ml_release.md`.

Главные правила:
- **Один релиз — один показываемый прогноз.** `release_metadata.score` относится ровно к значениям
  `forecast_points` (`NULL`, если они не оценивались); `code_git_sha` — коммит, который их воспроизводит.
  Текущий релиз `hackathon-v7`: маршрут 5 = 0, score = 0.88987.
- `model_prediction` — готовый базовый прогноз; backend не применяет повторно ничего из
  `release_metadata.model_prediction_includes` (включая финальную калибровку ×1.012).
- Сценарий всегда считается заново от `model_prediction` (никакого `new_factor / applied_factor`):
  `model_prediction × weather × event × (1 + season_pct/100) × (1 + manual_pct/100)`, затем network overlay
  (FULL_CLOSURE → 0, иначе × произведение активных множителей, затем ≥ 0).
- Погодная опция берётся по сезону даты: `warm` (апрель–сентябрь) или `cold` (октябрь–март); если опции для
  сезона нет — её не показывать. Как подтверждённый эффект показываются только опции с `confirmed = true`.
- Каталог коэффициентов для `factors.py`: `factor_options.csv` / `factor_options.json` рядом с релизом.
- `network_impact_rules`: только измеренные вторичные эффекты. Сейчас одно правило:
  при активном FULL_CLOSURE маршрута 17 → `operational(11) × 1.1079`. Для остальных маршрутов вторичного эффекта нет.
- `forecast_intervals` — необязательная таблица `p10` / `p90`; backend может её не читать.
