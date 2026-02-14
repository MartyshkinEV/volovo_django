1) Структура
- Проект Django с пакетом config (asgi.py, wsgi.py, settings.py, urls.py), приложениями: api, formsapp, tracking (есть management/commands), volovo_api (urls.py, services.py), webapp (urls.py).
- Шаблоны: templates/putevoy (base и partials), при этом есть дублирующий корневой файл putevoy.html — убрать или переместить в templates.
- Статика: static/putevoy (css/js) и дубликаты в static/admin/putevoy (js) — оставить одну копию в static/putevoy, убрать из static/admin.
- В static/ присутствует полный набор статических файлов Django admin (css/js/vendor) — их не коммитят, они попадают в STATIC_ROOT через collectstatic. Удалить из репозитория.
- Опечатка в пути security.txt: static/.well-know/security.txt — должно быть static/.well-known/security.txt.
- В корне лежат db.sqlite3 (нельзя хранить в гите), putevoy.txt (переместить в docs/ или templates/ если используется), Камаз-маз.xlsx (вынести в data/ и игнорировать гитом).
- Есть лишний файл/папка "cd" в корне — удалить.
- У api нет urls.py — рекомендуется добавить и инклюдить из config/urls.py.
- Миграции присутствуют во всех приложениях — ок.

2) Конфиги
- settings.py нужно разделить на модули: settings/base.py, settings/dev.py, settings/prod.py. Использовать django-environ (или pydantic-settings) для загрузки переменных окружения (.env).
- Переменные из окружения: SECRET_KEY, DEBUG, ALLOWED_HOSTS, DATABASE_URL, CACHE_URL (Redis), EMAIL_URL, TIME_ZONE (например Europe/Moscow), LANGUAGE_CODE (ru-ru), CSRF_TRUSTED_ORIGINS.
- База: в dev — SQLite допускается, в prod — PostgreSQL через DATABASE_URL.
- Static/Media: STATIC_URL, STATIC_ROOT (например, var/static/), MEDIA_URL, MEDIA_ROOT (var/media/). Для dev — STATICFILES_DIRS указывать на каталог(и) со статикой (без коммита админских файлов).
- Безопасность в прод-окружении: SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_HSTS_SECONDS>=31536000, SECURE_HSTS_INCLUDE_SUBDOMAINS=True, SECURE_HSTS_PRELOAD=True.
- Логи: настраивать LOGGING с JSON-форматом в prod (уровни INFO/ERROR), вывод в stdout/stderr, отдельный канал для django.request и запросов БД на DEBUG в dev.
- CORS/CSRF: при наличии фронта на другом домене — подключить django-cors-headers; CORS_ALLOWED_ORIGINS из окружения.
- ASGI: предпочесть ASGI-сервер (uvicorn/daphne) для будущей поддержки фоновых задач/вебсокетов.
- Добавить пример .env.example (без секретов) и README по настройке.
- Убедиться, что TEMPLATES['DIRS'] включает папку templates/, а app_dirs=True.
- Для management-команд импорта (tracking) параметры подключений (Mongo и др.) брать из окружения.

3) Безопасность
- Секреты (SECRET_KEY, ключи интеграций, строки подключения) не хранить в репозитории. Ротировать, если попадали в код/историю.
- db.sqlite3 удалить из репозитория и истории (git filter-repo), добавить в .gitignore.
- Админка: сменить стандартный URL, включить Django-admin 2FA (django-admin-two-factor), ограничить доступ по IP/VPN. Защитить от брутфорса (django-axes или rate limit на уровне Nginx).
- Заголовки безопасности: X-Content-Type-Options, X-Frame-Options (DENY), Referrer-Policy, Content-Security-Policy (через django-csp).
- CSRF и сессии: обеспечить CSRF в формах/views; SESSION_COOKIE_HTTPONLY=True, CSRF_COOKIE_HTTPONLY=True.
- Rate limiting для API (django-ratelimit) и защита от DDoS на уровне reverse-proxy.
- Проверка пользовательских загрузок (если появятся): валидация контента и размеров, антивирус (clamd) для чувствительных сценариев.
- Исправить путь security.txt на .well-known/security.txt и актуализировать контакт (security@домен).
- Проверить импортные команды (import_from_mongo, import_fortmonitor) на обработку ошибок, таймауты, ретраи, валидацию входных данных, отсутствие хардкода кредов.
- Обновить .gitignore, чтобы исключать: db.sqlite3, data/*.xlsx, var/, venv/, __pycache__/, *.pyc, *.log, .env.
- Регулярные обновления зависимостей и применение security advisories (pip-audit, dependabot).

4) Деплой
- Контейнеризация: Dockerfile + docker-compose.yml (web, db, redis). В образ включить: pip install -r requirements.txt, collectstatic, миграции.
- Запуск: prod через gunicorn (WSGI) или uvicorn (ASGI), например:
  - uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 4
  - или gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4 --timeout 120
- Реверс-прокси: Nginx с TLS (Let’s Encrypt), сжатие, кэширование статических, проксирование /static/ и /media/.
- Статика: whitenoise или отдача через Nginx из STATIC_ROOT; админские файлы не хранить в гите, собирать collectstatic.
- Миграции: python manage.py migrate на каждый релиз; сбор статики: python manage.py collectstatic --noinput.
- Бэкапы: БД (pg_dump), MEDIA (объектное хранилище S3/MinIO) с ротацией и проверкой восстановления.
- Мониторинг и алертинг: Sentry для ошибок, Prometheus/Grafana (через django-prometheus), healthcheck endpoint (/healthz) и liveness/readiness пробы в оркестраторе.
- Планировщик: периодические команды импорта через Celery beat или cronjob (python manage.py import_from_mongo …).
- Среды: dev/stage/prod с отдельными .env и базами, фича-флаги при необходимости.
- CI/CD: GitHub Actions — тесты, линтеры, сборка образа, деплой на stage/prod, миграции и collectstatic в пайплайне.

5) Django best practices
- Разделить настройки на base/dev/prod; использовать переменные окружения.
- Строгая структура статических и шаблонов: убрать дубли (root putevoy.html, static/admin/putevoy/*), все шаблоны в templates/с namespace appов.
- URL-конфигурации на уровне каждого приложения (api/urls.py, webapp/urls.py, volovo_api/urls.py) с include и namespace.
- Использовать CBV там, где уместно; бизнес-логику — в services/доменных слоях (есть volovo_api/services.py — продолжать в том же стиле).
- Модели: явно задавать related_name, db_index на часто фильтруемых полях (особенно tracking: timestamps, foreign keys, odo_km, speed_kmh). Добавлять constraints/validators.
- Таймзона: использовать timezone-aware даты (settings.USE_TZ=True), операции через django.utils.timezone.
- Пользовательская модель пользователя (если требуется расширение) — настроить AUTH_USER_MODEL на ранней стадии.
- Оптимизация запросов: select_related/prefetch_related, аннотации, пагинация в API/вьюхах таблиц.
- Тесты: покрыть модели, views, management-команды; фикстуры или factory_boy; минимальное покрытие 70%+.
- Кодстайл: black, isort, flake8, mypy (опционально), pre-commit хуки.
- Локализация/интернационализация: i18n для шаблонов и строк, RU/EN при необходимости.
- Документация: README, доки по импортам (tracking), описание формата данных.
- Зависимости: requirements.in/requirements.txt с pin версиями; обновления через pip-tools.

6) TODO
- Удалить из репозитория и истории db.sqlite3; обновить .gitignore.
- Удалить статические файлы Django admin из static/admin/*; оставить только свой фронт в static/putevoy/*.
- Удалить дубликаты static/admin/putevoy/*, оставить файлы в static/putevoy/*.
- Исправить путь security.txt на static/.well-known/security.txt и обновить контакт.
- Переместить/удалить корневые putevoy.html и putevoy.txt; оставить шаблоны в templates/.
- Вынести Камаз-маз.xlsx в data/ и игнорировать гитом; не хранить чувствительные данные в репозитории.
- Удалить лишний артефакт "cd" из корня.
- Добавить api/urls.py и подключить в config/urls.py с namespace.
- Разделить настройки на base/dev/prod; внедрить django-environ; добавить .env.example.
- Перейти на PostgreSQL в prod; настроить Redis-кэш; добавить настройки CORS при необходимости.
- Включить прод-настройки безопасности: SSL redirect, secure cookies, HSTS, security headers, CSP.
- Настроить логирование (JSON в prod), Sentry интеграцию.
- Подготовить Dockerfile и docker-compose; описать процедуру деплоя в README.
- Настроить CI/CD (GitHub Actions): линтеры, тесты, сборка, деплой, миграции, collectstatic.
- Добавить healthcheck endpoint (/healthz) и метрики (django-prometheus).
- Проверить management-команды импорта: вынести креды в окружение, добавить таймауты/ретраи/валидацию, логирование и алерты.
- Добавить индексы на поля tracking (время, foreign keys, odo_km, speed_kmh) и профильные запросы.
- Покрыть тестами модели, views и команды импорта; минимизировать использование фикстур в пользу фабрик.
- Внедрить pre-commit с black/isort/flake8/mypy; добавить .editorconfig.
- Обновить robots.txt/humans.txt, удалить static/llms.txt если не используется в проде.

Создано ботом ghbot.
