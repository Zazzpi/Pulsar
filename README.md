# Pulsar — WMS Sales Monitor

Desktop-приложение для отдела продаж: найти клиента, наблюдать за ним 90 дней,
видеть текущие остатки, заказы, приёмки, отгрузки и события, требующие внимания.
Исходная WMS остаётся самостоятельной системой. Pulsar не изменяет её данные.

```text
ПК менеджера                         Сервер
+----------------------+   HTTPS     +-----------------------------+
| PyQt6 + requests     | ----------> | Django API + авторизация    |
| SQLite: local cache  |   JSON      | LocMemCache                 |
+----------------------+             | ORM: watches, notes, metrics|
                                     +-------------+---------------+
                                                   |
                            +----------------------+------------------+
                            |                                         |
                   PostgreSQL Pulsar                      Read-only repository
                   собственные данные                     SELECT + TLS + timeout
                                                                      |
                                                       PostgreSQL существующей WMS
                                                       public / lk_wms
```

В DEMO репозиторий WMS заменяется набором связанных тестовых данных. API и desktop
используют тот же контракт. Production WMS в Docker Compose не включена.

## Быстрый запуск DEMO

Нужны Git, Docker с Compose и Python 3.12+ для desktop.

```bash
git clone https://github.com/Zazzpi/Pulsar.git
cd Pulsar
python3 scripts/setup_demo.py
docker compose up -d --build
docker compose ps
```

`setup_demo.py` создаёт локальный `.env` со случайными паролями, не перезаписывая
существующий файл. Логин — значение `DEMO_USERNAME`, пароль — `DEMO_PASSWORD`
из этого файла. `.env` не попадает в Git. После первоначальной сборки достаточно
`docker compose up -d`.

API: `http://127.0.0.1:8000/api/health/`. Docker запускает миграции собственной
PostgreSQL и создаёт пользователя DEMO. Порт БД наружу не опубликован.

Desktop запускается на компьютере с графическим окружением:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r desktop/requirements.txt
python -m desktop.main
```

В Windows: `py -3 -m venv .venv`, затем `.venv\Scripts\activate`.
Для Linux должны быть доступны системные библиотеки Qt/OpenGL/XCB; в headless
окружении для проверки используется `QT_QPA_PLATFORM=offscreen`.

Войдите, найдите клиента, откройте карточку и нажмите «Отслеживать 90 дней».
Вкладки загружаются по мере открытия. Чтобы проверить offline-сценарий, сначала
откройте нужные вкладки, остановите backend (`docker compose stop backend`) и
откройте сохранённые данные. Вернуть сервер: `docker compose start backend`.

## Разработка без Docker

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
export APP_DB_ENGINE=sqlite WMS_MODE=mock
python backend/manage.py migrate
python backend/manage.py createsuperuser
python backend/manage.py runserver 127.0.0.1:8000
```

SQLite здесь используется только как удобная **разработческая** БД backend.
Основной Compose-вариант использует PostgreSQL. Django не загружает `.env`
самостоятельно: Compose передаёт его через `env_file`, а при ручном запуске
переменные нужно установить в окружении процесса.

## Структура

```text
backend/config/          настройки Django, маршрутизация БД
backend/accounts/        вход и отзыв токенов
backend/monitoring/      наблюдения, заметки, snapshots, API/cache
backend/wms/             параметризованный SQL и mock repository
desktop/api/             HTTP-клиент
desktop/cache/           локальный SQLite cache
desktop/services/        загрузка и обновление данных
desktop/workers/         фоновые задачи Qt
desktop/ui/              окна и вкладки
scripts/                 подготовка окружения и проверки
tests/                   интеграционные проверки
README_FOR_ME.md         шпаргалка для объяснения решения
```

## Настройки

Пример конфигурации: [.env.example](.env.example).

| Переменная | Назначение |
| --- | --- |
| `APP_ENV` | `development` или `production` |
| `DJANGO_SECRET_KEY` | Секрет Django; обязателен для production |
| `DJANGO_ALLOWED_HOSTS` | Разрешённые имена API через запятую |
| `TRUST_PROXY_HEADERS` | `1` только за доверенным HTTPS reverse proxy |
| `APP_DB_ENGINE` | `postgresql` в Compose, `sqlite` для разработки |
| `APP_DB_NAME/USER/PASSWORD/HOST/PORT` | Только собственная БД Pulsar |
| `WMS_MODE` | `mock` или `postgres` |
| `WMS_DB_NAME/USER/PASSWORD/HOST/PORT` | Подключение сервера к существующей WMS |
| `WMS_DB_SSLMODE` | `require`; для проверки сертификата рекомендуется `verify-full` |
| `DEMO_USERNAME/DEMO_PASSWORD` | Создание пользователя в mock-режиме |
| `SUMMARY_CACHE_TTL`, `STOCK_CACHE_TTL` | Время серверного кэширования в секундах |
| `ORDERS_CACHE_TTL`, `RECEIVING_CACHE_TTL`, `SHIPMENTS_CACHE_TTL` | TTL подробных вкладок |
| `DEADLINE_WARNING_HOURS` | ASSUMPTION: близкий дедлайн — 24 часа |
| `INTEGRATION_STALE_HOURS` | Устаревшая синхронизация — 1 час по карте |
| `PULSAR_PORT` | Локальный порт Compose, по умолчанию 8000 |
| `WMS_API_URL` | На desktop: URL gateway, по умолчанию `http://127.0.0.1:8000` |
| `WMS_CACHE_PATH` | На desktop: путь к локальному SQLite cache |
| `WMS_HTTP_TIMEOUT_SECONDS` | Таймаут HTTP desktop, по умолчанию 15 секунд |
| `WMS_REFRESH_SECONDS` | Период обновления открытой вкладки desktop, по умолчанию 60 секунд |

Desktop получает только адрес API и пользовательскую авторизацию. Переменные
`WMS_DB_*` ему не нужны и не должны передаваться на компьютер менеджера.

## API

Авторизация: `POST /api/auth/login/` с JSON `username`, `password`.
Ответ содержит `token`, `user`; последующие запросы передают
`Authorization: Bearer <token>`. Выход: `POST /api/auth/logout/`.

| Метод и путь | Содержимое |
| --- | --- |
| `GET /api/clients/?q=…` | Поиск клиентов |
| `GET /api/clients/<id>/summary/` | Сводка и предупреждения |
| `GET /api/clients/<id>/stock/` | Текущий остаток |
| `GET /api/clients/<id>/orders/` | Заказы |
| `GET /api/clients/<id>/receivings/` | Приёмки |
| `GET /api/clients/<id>/shipments/` | Отгрузки через заказы клиента |
| `GET /api/clients/<id>/movements/` | История движений |
| `GET/POST /api/watches/` | Мои наблюдения; создание с `wms_client_id` |
| `DELETE /api/watches/<id>/` | Остановить своё наблюдение |
| `GET/POST /api/clients/<id>/notes/` | Мои заметки; создание с `body` |
| `GET /api/clients/<id>/metrics/` | Собственные дневные snapshots |
| `GET /api/health/` | Проверка доступности API и собственной БД |

Списки возвращают `results`, `page`, `page_size`, `has_next`. По умолчанию —
50 строк, максимум — 100. История ограничивается `from`/`to` в формате `YYYY-MM-DD`;
интервал `[from, to)` не более 90 дней. `to` не включается; для включения текущего
дня укажите завтрашнюю дату. Границы — полночь UTC. Текущие остатки не
ограничиваются историческим окном.

## Как читается WMS

Основные связи:

```text
public.clients_client.id
  <- public.products_product.client_id
       <- public.stocks_stock.product_id
       <- public.movements_movement.product_id
  <- public.orders_order.client_id
       <- public.shipments_shipment.order_id
  <- public.receivings_receiving.client_id
  <- public.tasks_task.client_id
  <- public.integrations_integration.client_id
  =  lk_wms.*.contractor_id (логическая связь без FK)
```

Остаток берётся из `public.stocks_stock`; доступно = `quantity - reserved_quantity`.
`movements_movement.quantity` положительно: направление задаёт `movement_type`.
Потоки приёмки/отгрузки считаются по исходным движениям `reversal_of_id IS NULL`;
это показатель исходных операций, а не восстановленный остаток. Начисления —
`SUM(amount)` вместе с отрицательными сторно.

В SQL всегда указаны `public`/`lk_wms`. Пользовательские значения передаются
параметрами, имена таблиц не берутся из запроса. Repository выполняет только
`SELECT`. Подключение WMS принудительно read-only, с таймаутом SQL. Для production
нужен отдельный пользователь PostgreSQL, которому администратор WMS выдаст
только чтение нужных таблиц. Сервис Pulsar не создаёт и не меняет эти разрешения.

Миграции существуют только для собственной БД. Смена источника на существующий
HTTP API WMS требует другого repository с тем же интерфейсом; desktop менять
не нужно. Сам HTTP-адаптер WMS не реализован: его контракт не предоставлен.

## Кэш и работа без сети

Серверный `django.core.cache` уменьшает повторные обращения к WMS. Ключ включает
клиента, ресурс, страницу и фильтры. В MVP используется `LocMemCache`, один
процесс Gunicorn с несколькими потоками. Нажатие «Обновить» обращается к API;
данные WMS могут отставать до окончания TTL серверного кэша.

Локальный SQLite хранит полученные JSON и время обновления отдельно для API и
пользователя. Сначала показывается сохранённый ответ, затем выполняется HTTP
в фоне. При ошибке остаются данные с предупреждением об их возможной неактуальности.
Сохраняются только открытые страницы; полный offline-дубликат WMS не создаётся.

Пароли и токены в локальном кэше не хранятся. Режим просмотра сохранённых данных
явно отделён от входа на сервер; изменение наблюдений и заметок требует сети.
SQLite не зашифрован: доступ к файлу должен защищаться средствами ОС. На общем
компьютере локальные данные доступны человеку с доступом к профилю ОС.

## 90 дней и snapshots

`ClientWatch` принадлежит пользователю; `ends_at = started_at + 90 дней`.
Повторное нажатие при активном наблюдении не продлевает его неявно. Заметки
также привязаны к пользователю. Для дневной истории предусмотрена собственная
таблица `ClientDailyMetric` и команда:

```bash
docker compose exec backend python manage.py snapshot_metrics
```

Её можно запускать раз в день через cron/systemd. Она собирает снимок для
отслеживаемых клиентов и не пишет в WMS. История начинается с первого запуска:
прошлые остатки из текущего состояния WMS не восстанавливаются.

## Безопасность и развёртывание

Пароли обрабатывает Django; сервер хранит хэши API-токенов. Наблюдения и заметки
доступны только создавшему их пользователю. ASSUMPTION для MVP: любой
авторизованный сотрудник может видеть всех клиентов WMS; разграничение по
назначенным менеджерам требует отдельного бизнес-правила.

Для production установите `APP_ENV=production`, постоянный `DJANGO_SECRET_KEY`,
разрешённые хосты и HTTPS reverse proxy. WMS должна быть доступна только backend.
Desktop допускает HTTP только для локальной разработки; для удалённого API нужен
HTTPS. TLS-терминация и сертификаты зависят от инфраструктуры и в Compose DEMO
не включены. За доверенным reverse proxy установите `TRUST_PROXY_HEADERS=1`;
proxy должен сам устанавливать `X-Forwarded-Proto` и удалять присланное клиентом
значение. Не публикуйте разработческий `runserver` наружу.

При ошибке upstream API отвечает контролируемой ошибкой, а desktop показывает
кэш. В журнал не записываются пароли, токены, параметры подключения и текст
исключений драйвера, который мог бы содержать секреты.

## Проверки

```bash
pip install -r requirements-dev.txt
APP_DB_ENGINE=sqlite WMS_MODE=mock python backend/manage.py check
APP_DB_ENGINE=sqlite WMS_MODE=mock python backend/manage.py makemigrations --check --dry-run
APP_DB_ENGINE=sqlite WMS_MODE=mock QT_QPA_PLATFORM=offscreen pytest
docker compose config --quiet
```

Проверяются расчёты остатков, SQL-параметры, ограничения чтения, пагинация,
серверный кэш, авторизация, изоляция пользователей, 90-дневные наблюдения,
ошибки HTTP, SQLite и базовое создание Qt-интерфейса. CI выполняет эти проверки
при push и pull request. Результаты фактически выполненной проверки сборки
описаны в [docs/VALIDATION.md](docs/VALIDATION.md).

## Ограничения и развитие

- Карта — аналитическое описание, не полный DDL. Не задействованы неописанные
  связи строк документов и сканов. План/факт приёмки по строкам и детализация
  упаковок потребуют подтверждённых FK. Имена отсутствующих полей не выдумываются.
- Порог близкого дедлайна — настраиваемое допущение; загрузка отдельного клиента
  по ячейкам не вычисляется, поскольку такого бизнес-правила нет в карте.
- Нет фоновой очереди, push-уведомлений и восстановления пропущенных daily snapshots.
- Нет установщика desktop: MVP запускается как Python-пакет.
- Production WMS и её объёмы требуют отдельной проверки планов запросов и доступа.
  Нет утверждения, что DEMO проверяет реальную production-схему.
- Для нескольких процессов/серверов заменить LocMemCache на Redis. Следующий
  шаг снижения нагрузки — reporting PostgreSQL replica; desktop сохранит API.

Технологии и понятия для защиты проекта: [README_FOR_ME.md](README_FOR_ME.md).
