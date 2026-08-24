# Blueprint: как собрать Telegram-бота по образцу NutriSnap (под другую тему)

Этот документ — практическая инструкция для агента, который будет создавать **новый** проект, похожий на текущий NutriSnap по архитектуре, UX-потокам и деплою, но с **другой предметной областью** (не учёт калорий).

---

## 1) Что именно копируем из референса

Копируем не бизнес-тему, а инженерный каркас:

- асинхронный Telegram-бот на `aiogram` (long polling);
- разнесение логики на роутеры и FSM-модули;
- LLM-анализ входа с fallback по моделям;
- структурированные ответы LLM (JSON schema / Pydantic);
- хранение данных через NocoDB Data API;
- обработка ошибок с разделением на внутренние и внешние;
- Docker + compose + деплой через ветку `build` и GitHub Actions (SSH на VPS);
- точечный прокси только для нужных внешних сервисов.

---

## 2) Целевая структура нового репозитория

Сохраняй плоскую структуру (как в NutriSnap) — это ускоряет старт и упрощает перенос:

```text
<NEW_BOT_REPO>/
├── main.py
├── app_logging.py
├── error_notify.py
├── proxy_config.py
├── db_nocodb.py
├── domain_recognition.py        # аналог food_recognition.py, но под новую тему
├── initial_survey.py            # можно оставить как есть или адаптировать под тему
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── docker-compose.vps.yml
├── deploy.sh
├── deploy_to_build.cmd
└── .github/workflows/deploy.yml
```

---

## 3) Библиотеки и стек (рекомендуемый baseline)

Используй тот же набор, чтобы избежать скрытых несовместимостей:

- `aiogram>=3.4`
- `google-genai>=1.0`
- `pydantic>=2.0`
- `python-dotenv>=1.0`
- `httpx>=0.27`
- `aiohttp-socks>=0.8`
- `Pillow>=10.0` (если есть изображения)
- `timezonefinder>=6.0`, `geopy>=2.4` (если нужны TZ/гео)

Python: `3.10+` (в Docker — `python:3.10-slim`).

---

## 4) Архитектурный шаблон (ядро проекта)

### 4.1 Роли модулей

- `main.py` — точка входа, инициализация `Bot/Dispatcher`, подключение роутеров, главное меню, фоновые циклы, orchestration.
- `domain_recognition.py` — весь тематический AI-поток (вместо еды: твоя тема), FSM, парсинг/нормализация результата, кнопки подтверждения.
- `initial_survey.py` — стартовый опрос пользователя и сбор baseline-профиля.
- `db_nocodb.py` — все CRUD к NocoDB и доменные запросы.
- `proxy_config.py` — прокси только для целевых клиентов (Telegram + LLM).
- `error_notify.py` — единый контур репорта ошибок и уведомлений.
- `app_logging.py` — файл логов + ротация + формат.

### 4.2 Связь модулей (схема)

```text
main.py
  ├── setup_logging()
  ├── install_error_email_hooks()
  ├── db_nocodb (через run_db -> asyncio.to_thread)
  ├── include_router(menu_router)
  ├── include_router(setup_initial_survey(on_complete=...))
  └── include_router(setup_domain_recognition(on_saved=..., on_after_ack=...))
```

### 4.3 Критичный паттерн: sync DB внутри async бота

NocoDB-клиент можно оставить синхронным (`urllib`), а в aiogram вызывать через thread offload:

```python
async def run_db(fn, /, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)
```

Это сохраняет event loop отзывчивым.

---

## 5) Шаблон пользовательского потока (UX/FSM)

## 5.1 Базовый маршрут `/start`

1. Проверяем пользователя в `users`.
2. Если профиля нет -> `start_initial_survey`.
3. Если есть -> главный экран.

## 5.2 Основной тематический поток (аналог food-flow)

```text
Вход пользователя (текст/фото/документ)
  -> "анализирую..."
  -> LLM возвращает structured JSON со status
  -> ветвление:
       recognized   -> превью + confirm-кнопки
       unclear      -> запрос уточнения
       no_match     -> мягкий отказ + повторить ввод
       bad_input    -> попросить переформулировать
  -> подтверждение пользователем или автоподтверждение по таймауту
  -> сохранение в БД
  -> пост-действия (уведомления/напоминания)
```

## 5.3 Статусы результата

Рекомендуемый минимальный набор для новой темы:

- `recognized` — уверенно определён объект/событие;
- `unclear` — похоже на валидный кейс, но не хватает данных;
- `no_match` — объект не относится к теме бота;
- `bad_input` — ввод противоречивый/бессмысленный.

---

## 6) Технические решения и алгоритмы (обязательно повторить)

## 6.1 LLM fallback по моделям

Нужен очередной перебор моделей с коротким timeout:

```python
MODELS_QUEUE = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
]

def generate_with_fallback(contents, schema):
    for model_name in MODELS_QUEUE:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "http_options": {"timeout": 10_000, "retry_options": {"attempts": 1}},
                },
            )
            return resp.text
        except Exception:
            continue
    return None
```

Почему: резко повышает устойчивость при временных 5xx/timeout.

## 6.2 Structured output через Pydantic

Для новой темы делай собственную схему:

```python
class DomainResult(BaseModel):
    status: Literal["recognized", "unclear", "no_match", "bad_input"]
    title: str | None = None
    score: float | None = None
    details: dict[str, Any] | None = None
```

Почему: исключает хаос в JSON-ответах модели и упрощает FSM-ветвление.

## 6.3 Confirm UI + автоподтверждение

- после успешного анализа показывай превью и кнопки;
- сохраняй `confirm_token` в FSM;
- запускай `asyncio.create_task` с таймаутом (например 10 секунд);
- подтверждай автоматически, только если `confirm_token` актуален.

Почему: быстрый UX без потери контроля.

## 6.4 Точечный прокси (а не глобальный)

`proxy_config.py` должен задавать прокси только для Telegram и LLM:

- `TELEGRAM_PROXY` / `OUTBOUND_HTTPS_PROXY` для aiogram session;
- `GEMINI_HTTPS_PROXY` / `OUTBOUND_HTTPS_PROXY` для LLM client;
- остальные сервисы (NocoDB, SMTP, geocoding) — напрямую.

Почему: глобальный `HTTP_PROXY` ломает сторонние интеграции.

---

## 7) Схема данных (NocoDB) для нового бота

Минимум 3 таблицы:

1. `users` — профиль пользователя, TZ, сервисные флаги.
2. `domain_logs` (в NutriSnap это `food_logs`) — подтверждённые события/записи.
3. `reminders` — напоминания и их состояние.

Рекомендации:

- связь делать Link (`users: {id: telegram_id}`);
- хранить `created_at` (unix), логическую дату (`logged_date`-подобное поле), `details_json`;
- добавить retention-политику по дате (очистка старых записей фоновым циклом).

---

## 8) Фоновые задачи, которые стоит оставить

1. `usage_reminder_loop` — проверка активности пользователя.
2. `reminders_maintenance_loop` — сброс флагов/пропущенные окна.
3. `logs_cleanup_loop` — удаление записей старше N дней.

Плюс:

- middleware на stale message (не обрабатывать старые апдейты после downtime);
- единичное уведомление "бот снова онлайн", чтобы пользователь понял, что делать.

---

## 9) Переменные окружения (`.env.example`)

Базовый шаблон:

```env
GEMINI_API_KEY=
TELEGRAM_BOT_API_KEY=
NOCODB_SKYNODE_API_KEY=

OUTBOUND_HTTPS_PROXY=
TELEGRAM_PROXY=
GEMINI_HTTPS_PROXY=

FEEDBACK_TO_EMAIL=
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=465
SMTP_USER=
SMTP_PASSWORD=

LOG_LEVEL=INFO
```

---

## 10) Деплой (SkyNode-паттерн из референса)

## 10.1 Локальный цикл

```bash
python -m venv .venv
pip install -r requirements.txt
python main.py
```

## 10.2 Docker

```bash
docker compose up --build
```

Для VPS:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml up --build -d
```

## 10.3 CI/CD

Паттерн:

- рабочая ветка -> `deploy_to_build.cmd`;
- merge/push в `build`;
- GitHub Actions (`push: build`);
- SSH на VPS;
- `bash deploy.sh`;
- `docker compose up --build -d`.

Секреты GitHub:

- `VPS_HOST`
- `VPS_USER`
- `VPS_SSH_KEY`
- `VPS_DEPLOY_PATH`

---

## 11) Порядок работ агента в новом проекте

1. Создать каркас файлов (из раздела 2).
2. Подключить зависимости и `.env.example`.
3. Реализовать `main.py` + базовое меню + `/start` маршрутизацию.
4. Реализовать `initial_survey.py` (или заглушку с дальнейшим расширением).
5. Реализовать `domain_recognition.py`:
   - промпт(ы),
   - Pydantic schema,
   - fallback моделей,
   - confirm flow.
6. Реализовать `db_nocodb.py` и CRUD (через Data API v3).
7. Включить логирование и error notify.
8. Добавить Docker/compose/deploy scripts/workflow.
9. Проверить локально: `/start`, базовый flow, запись в БД, повторный вход.
10. Проверить прод-деплой через `build` ветку.

---

## 12) Что обязательно заменить при переносе темы

Не переноси дословно “калорийную” семантику:

- переименуй `food_recognition.py` -> `domain_recognition.py`;
- замени поля `calories/proteins/fats/carbs` на поля новой темы;
- обнови промпты и тексты кнопок под новый UX;
- скорректируй названия таблиц и их поля в NocoDB;
- обнови FAQ/инструкции/сообщения для пользователя.

---

## 13) Контрольный чеклист готовности

- [ ] Бот запускается локально без ошибок.
- [ ] `/start` корректно маршрутизирует new/existing user.
- [ ] LLM-ответ парсится по Pydantic схеме.
- [ ] Confirm flow работает (ручной и auto confirm).
- [ ] Записи реально пишутся в NocoDB.
- [ ] Ошибки внешних сервисов обрабатываются мягко для пользователя.
- [ ] Контейнер поднимается через compose.
- [ ] Деплой через `build` триггерит Actions и обновляет VPS.
- [ ] Нет второго polling-процесса с тем же Telegram токеном.

---

## 14) Дополнительно

- По VPS-инфраструктуре и всем нюансам SkyNode используй детальный playbook: `DEPLOY_PLAYBOOK_SkyNode.md`.
- По текущей реализации NutriSnap как референсу архитектуры используй: `README.md` и `cursorcontext.md`.

