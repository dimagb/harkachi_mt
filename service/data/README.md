# Каталог данных

Положите сюда:

- `submission.csv` — прогноз в формате сдачи: `route;date;hour;prediction`
- `labels/labels_day_train.csv`, `labels/labels_day_test.csv` — история
- `spravochniki/*.xlsx` — справочники с координатами остановок

Каталог монтируется в контейнер только на чтение.
Чтобы обновить прогноз, замените `submission.csv` и вызовите `POST /api/reload`.
