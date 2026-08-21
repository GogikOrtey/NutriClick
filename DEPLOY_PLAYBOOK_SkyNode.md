# Playbook: сборка и деплой Python Telegram-бота на SkyNode

Инструкция для агента (и человека): как мы собрали и задеплоили **NutriSnap Twin Bot**, и как повторить тот же пайплайн для **нового аналогичного проекта** на виртуалке SkyNode с быстрым деплоем одной командой / одним пушем.

Связанные файлы в этом репо: `Dockerfile`, `docker-compose.yml`, `docker-compose.vps.yml`, `deploy.sh`, `deploy_to_build.cmd`, `.github/workflows/deploy.yml`, `.env.example`, `proxy_config.py`, `cursorcontext_on_SkyNode.md`, `cursorcontext.md`.

---

## 1. Итоговая схема (как работает прод)

```
Локальный ПК (Windows)                GitHub                         SkyNode VPS
──────────────────────                ──────                         ──────────
код на ветке main/feature
  → deploy_to_build.cmd
      commit (если нужно)
      merge → ветка build
      git push origin build    →   Actions (push: build)
                                       appleboy/ssh-action
                                           SSH ключом        →   cd ~/Project
                                                                 bash deploy.sh
                                                                   git fetch/reset origin/build
                                                                   docker compose … up --build -d
                                                                 контейнер: long polling
```

**Не используем:** webhook бота, systemd unit для самого бота, rsync, cron-деплой, pm2.

**Используем:** Docker + Compose, ветка `build` как триггер, GitHub Actions → SSH → `deploy.sh`.

---

## 2. Виртуалка SkyNode — факты

| Параметр | Значение |
|----------|----------|
| Имя | SkyNode |
| IP | `139.100.204.113` |
| SSH | `ssh gogortey@139.100.204.113` |
| Пользователь | `gogortey` |
| TZ | `+05` |
| Sudo | **без пароля нет** — агент останавливается и просит пользователя выполнить sudo-команду |
| Docker | установлен; Compose plugin без sudo: `~/.docker/cli-plugins/docker-compose` (v2.38.2) |
| Outbound proxy | **mihomo** в `~/proxy`, HTTP `127.0.0.1:7890`, API `127.0.0.1:9090` |
| mihomo unit | `systemd --user` → `mihomo.service`, `Restart=always`, **Linger=yes** |
| Telegram hosts | в `/etc/hosts`: `149.154.167.220 api.telegram.org` (родные IP timeout; IPv6 к TG не ходит) |
| NocoDB | контейнер `nocodb-app`, host network → `127.0.0.1:8080`; снаружи nginx TLS `443` → `proxy_pass http://127.0.0.1:8080` |
| Домен NocoDB | `https://skynode.nocodb.api.gogortey.ru` |
| Тестовый стенд | `~/tg-aiogram-test` |
| Host Python | `python3.12-venv` есть; боты в проде — в Docker **Python 3.10** |

### Команды агента к VPS

```bash
ssh gogortey@139.100.204.113 'команда'
```

Для устойчивых сессий предпочитать `tmux`/`screen`. Интерактивный терминал пользователя в IDE агент видит, но не управляет им напрямую.

### Правило sudo

Если нужна установка пакета / правка `/etc/hosts` / nginx — **остановиться**, написать пользователю точную команду и зачем она, дождаться выполнения, продолжить.

---

## 3. Что уже есть на SkyNode (инфраструктура общая)

Это **не** нужно поднимать заново для каждого бота — только проверить:

1. **mihomo** активен:
   ```bash
   systemctl --user is-active mihomo
   ss -ltn | grep -E '7890|9090'
   ```
   Рестарт: `systemctl --user restart mihomo`

2. **`/etc/hosts`** содержит рабочий IPv4 для Telegram:
   ```
   149.154.167.220 api.telegram.org
   ```

3. **Docker + Compose** работают от пользователя `gogortey`:
   ```bash
   docker version
   docker compose version
   ```
   Если плагина нет — без sudo:
   ```bash
   mkdir -p ~/.docker/cli-plugins
   curl -fsSL "https://github.com/docker/compose/releases/download/v2.38.2/docker-compose-linux-x86_64" \
     -o ~/.docker/cli-plugins/docker-compose
   chmod +x ~/.docker/cli-plugins/docker-compose
   ```

4. **NocoDB** (если проекту нужна та же БД) доступен по HTTPS с VPS и с локалки.

### Исходящая связность (проверено с VPS)

| Сервис | Напрямую | Через mihomo `:7890` |
|--------|----------|----------------------|
| Telegram Bot API | ✅ только после `/etc/hosts` на `149.154.167.220` | ✅ |
| Gemini (с API-ключом) | ❌ **400 geo** | ✅ |
| NocoDB | ✅ | не использовать |
| Yandex SMTP `:465` | ✅ | не использовать |
| Nominatim | ✅ | не использовать |

**Критично:** прокси только точечно (Telegram + Gemini). **Не** ставить на процесс бота `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`.

---

## 4. Как устроен NutriSnap (референс-проект)

### Стек

- Python 3.10, aiogram 3.x, **long polling** (порты снаружи не нужны)
- Google Gemini (`google-genai`)
- NocoDB Data API v3 (`urllib` + `xc-token`)
- SMTP Yandex (отзывы + алерты об ошибках)
- Точечный прокси: `proxy_config.py` + `aiohttp-socks`

### Ключевые пути на VPS

| Что | Путь / имя |
|-----|------------|
| Каталог | `/home/gogortey/NutriSnap_Twin_bot` (`~/NutriSnap_Twin_bot`) |
| Ветка на VPS | `build` |
| Контейнер | `nutrisnap-bot` |
| Сеть контейнера | `network_mode: host` (видит mihomo и `/etc/hosts`) |
| Deploy key VM→GitHub (RO) | `~/.ssh/nutrisnap_github` |
| Ключ Actions→VM | `~/.ssh/nutrisnap_gha` (+ pubkey в `authorized_keys`) |
| Секреты | `~/NutriSnap_Twin_bot/.env` (не в git, не в образ) |

### GitHub Secrets (репо NutriSnap)

| Secret | Значение |
|--------|----------|
| `VPS_HOST` | `139.100.204.113` |
| `VPS_USER` | `gogortey` |
| `VPS_SSH_KEY` | private key из `~/.ssh/nutrisnap_gha` |
| `VPS_DEPLOY_PATH` | `/home/gogortey/NutriSnap_Twin_bot` |

### Env на VPS (фрагмент)

```env
OUTBOUND_HTTPS_PROXY=http://127.0.0.1:7890
TELEGRAM_BOT_API_KEY=...
GEMINI_API_KEY=...
NOCODB_SKYNODE_API_KEY=...
SMTP_USER=...
SMTP_PASSWORD=...
LOG_LEVEL=INFO
```

Локально `OUTBOUND_HTTPS_PROXY` обычно **пустой** (прямые запросы).

### Volumes (файлы должны существовать до первого `up`)

Docker при монтировании несуществующего пути создаёт **каталог**, а не файл. `deploy.sh` создаёт:

- `logs/`
- `.reminder_day_keys.json` → `{}`
- `.reminder_pending_meal.json` → `{}`

### Конфликт токена

Один `TELEGRAM_BOT_API_KEY` = один polling-процесс. Локальный `python main.py` / локальный Docker + прод на VPS одновременно → `TelegramConflictError`. Перед продом остановить локальный экземпляр.

---

## 5. Чеклист: новый проект на ту же виртуалку

Подставь плейсхолдеры:

- `PROJECT` — имя каталога/репо, напр. `MyCool_bot`
- `CONTAINER` — имя контейнера, напр. `mycool-bot`
- `DEPLOY_KEY` — `~/.ssh/<project>_github`
- `GHA_KEY` — `~/.ssh/<project>_gha`
- `REPO_SSH` — `git@github.com:GogikOrtey/<PROJECT>.git`

### 5.1. Файлы в репозитории (обязательный минимум)

Скопируй паттерн NutriSnap и адаптируй имена.

#### `Dockerfile`

```dockerfile
FROM python:3.10-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

#### `docker-compose.yml`

```yaml
services:
  bot:
    build: .
    container_name: CONTAINER   # уникальное имя на VPS!
    env_file: .env
    restart: unless-stopped
    volumes:
      - ./logs:/app/logs
      # любые stateful-файлы — заранее создать на хосте как ФАЙЛЫ
```

#### `docker-compose.vps.yml`

```yaml
# host network: mihomo 127.0.0.1:7890 + /etc/hosts (api.telegram.org)
services:
  bot:
    network_mode: host
```

#### `deploy.sh` (LF endings, executable)

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
git fetch origin build
git checkout build
git reset --hard origin/build
mkdir -p logs
# создать пустые JSON/файлы-volume при необходимости
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in $ROOT" >&2
  exit 1
fi
docker compose -f docker-compose.yml -f docker-compose.vps.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
```

На Windows перед пушем: убедиться, что `deploy.sh` с LF (`git config core.autocrlf` / `.gitattributes`: `*.sh text eol=lf`).

#### `.github/workflows/deploy.yml`

```yaml
name: Deploy to SkyNode
on:
  push:
    branches: [build]
concurrency:
  group: skynode-deploy-PROJECT   # уникальная group на проект!
  cancel-in-progress: false
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy over SSH
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script_stop: true
          script: |
            cd "${{ secrets.VPS_DEPLOY_PATH }}"
            bash deploy.sh
```

#### `deploy_to_build.cmd` (Windows)

Логика как в NutriSnap: опциональный commit → checkout `build` → merge текущей ветки → `git push -u origin build` → возврат на исходную ветку.

#### `.dockerignore`

Исключить как минимум: `.env`, `.git`, `logs`, `*.md`, `.venv`, тесты, IDE-папки. Секреты в образ не копировать.

#### `.env.example`

Шаблон без секретов. На VPS обязательно:

```env
OUTBOUND_HTTPS_PROXY=http://127.0.0.1:7890
```

#### Точечный прокси в коде

Паттерн `proxy_config.py`:

- `OUTBOUND_HTTPS_PROXY` / `TELEGRAM_PROXY` / `GEMINI_HTTPS_PROXY`
- aiogram: `AiohttpSession(proxy=...)` только если задан
- Gemini: `HttpOptions(client_args={proxy, trust_env=False})`
- NocoDB / SMTP / прочий HTTP — **без** прокси

Зависимость: `aiohttp-socks` в `requirements.txt`.

### 5.2. Ветки Git

| Ветка | Назначение |
|-------|------------|
| `main` (или feature) | повседневная разработка |
| `build` | **только** то, что едет на прод; push сюда = деплой |

Первый раз локально:

```bash
git checkout -b build main
git push -u origin build
```

### 5.3. Одноразовая настройка на VPS

Выполнять по SSH. Имена ключей — **свои на каждый проект** (не перетирать чужие).

```bash
# 1) Deploy key: VM → GitHub (read-only)
ssh-keygen -t ed25519 -f ~/.ssh/DEPLOY_KEY -N "" -C "PROJECT-skynode-deploy-ro"

# 2) SSH config для github.com с этим ключом
# В ~/.ssh/config — Host github.com → IdentityFile ~/.ssh/DEPLOY_KEY
# Если на VM уже есть Host github.com для другого проекта — используй
# Host github.com-PROJECT + clone через этот Host alias.

# 3) Ключ GitHub Actions → VM
ssh-keygen -t ed25519 -f ~/.ssh/GHA_KEY -N "" -C "PROJECT-gha-deploy"
cat ~/.ssh/GHA_KEY.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**Ручные шаги пользователя (GitHub UI):**

1. Публичный `DEPLOY_KEY.pub` → Settings репо → Deploy keys → **Allow read access**.
2. Приватный `GHA_KEY` → Settings репо → Secrets → `VPS_SSH_KEY`.
3. Secrets: `VPS_HOST=139.100.204.113`, `VPS_USER=gogortey`, `VPS_DEPLOY_PATH=/home/gogortey/PROJECT`.

**Важно про несколько проектов:** если у `github.com` в `~/.ssh/config` уже прописан другой `IdentityFile`, для нового репо сделай отдельный Host-алиас, иначе clone/pull возьмёт не тот ключ.

Пример:

```
Host github.com-mycool
  HostName github.com
  User git
  IdentityFile ~/.ssh/mycool_github
  IdentitiesOnly yes
```

Клон: `git clone git@github.com-mycool:GogikOrtey/MyCool_bot.git ~/MyCool_bot`

```bash
# 4) Clone
cd ~
git clone REPO_SSH ~/PROJECT
cd ~/PROJECT
git checkout build

# 5) .env на хосте
cp .env.example .env
nano .env   # заполнить секреты + OUTBOUND_HTTPS_PROXY=http://127.0.0.1:7890

# 6) Первый ручной деплой
bash deploy.sh
# или:
docker compose -f docker-compose.yml -f docker-compose.vps.yml up --build -d

# 7) Проверка
docker ps --filter name=CONTAINER
docker logs --tail 80 CONTAINER
```

### 5.4. Повседневный деплой (быстрый путь)

На Windows из корня репо:

```bat
deploy_to_build.cmd
```

Либо вручную:

```bash
git checkout build
git merge <рабочая-ветка>
git push origin build
```

Далее смотреть Actions → job «Deploy to SkyNode» → логи SSH/`deploy.sh`.

На VPS вручную без GitHub:

```bash
ssh gogortey@139.100.204.113
cd ~/PROJECT
bash deploy.sh
```

### 5.5. Эксплуатация контейнера

```bash
cd ~/PROJECT
# статус
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
# логи
docker logs -f CONTAINER
# также файл ./logs/bot.log если смонтирован
# рестарт
docker compose -f docker-compose.yml -f docker-compose.vps.yml restart
# стоп
docker compose -f docker-compose.yml -f docker-compose.vps.yml down
```

Политика: `restart: unless-stopped` — контейнер поднимется после ребута VM (Docker daemon).

---

## 6. NocoDB на SkyNode (если нужна БД)

### Архитектура

```
Бот (host network)
  → HTTPS https://skynode.nocodb.api.gogortey.ru
  → nginx :443 (TLS)
  → NocoDB 127.0.0.1:8080
  → Postgres (внутри/рядом с NocoDB)
```

Бот **не** ходит в Postgres напрямую — только Data API v3 + заголовок `xc-token`.

### Что сделать для нового бота

1. В UI NocoDB создать base / таблицы (или переиспользовать существующую base).
2. Выписать Table IDs и Base ID из Swagger / UI.
3. Создать API token: `https://skynode.nocodb.api.gogortey.ru/account/tokens` → в `.env`.
4. Клиент по образцу `db_nocodb.py` (UTF-8 JSON, Link-поля как `{id: …}`, не сырой SQL `user_id`).
5. Новые запросы сначала в песочнице (`requests_DB_test.py`-паттерн), потом в прод-код.

### Latency (ориентир)

- Public HTTPS cold connect ~57 ms p50; `http://127.0.0.1:8080` ~27 ms p50.
- Keep-alive нивелирует разницу. NutriSnap сейчас ходит на **публичный HTTPS** (простота TLS/DNS), не на localhost.

Опциональная оптимизация для нового проекта на той же VM: `NOCODB_BASE_URL=http://127.0.0.1:8080` в `.env` (только с VPS / host network).

---

## 7. Локальная разработка vs прод

| | Локально (Windows) | SkyNode |
|--|--------------------|---------|
| Запуск | `python main.py` или `docker compose up --build` | compose + `docker-compose.vps.yml` |
| Прокси | пусто | `OUTBOUND_HTTPS_PROXY=http://127.0.0.1:7890` |
| Сеть Docker | bridge по умолчанию | `network_mode: host` |
| Токен бота | отдельный test-bot **или** стоп прод | один прод-токен |
| `.env` | локальный файл | файл на хосте VPS |

---

## 8. Типичные поломки и быстрые проверки

| Симптом | Что проверить |
|---------|----------------|
| Actions fail на SSH | Secrets `VPS_*`, pubkey `GHA_KEY` в `authorized_keys`, путь `VPS_DEPLOY_PATH` |
| `deploy.sh`: `.env not found` | Создать `.env` на VPS вручную |
| `git fetch` permission denied | Deploy key в GitHub; правильный `IdentityFile` / Host-алиас |
| `TelegramConflictError` | Второй экземпляр с тем же токеном (локалка) |
| Gemini 400 geo | mihomo down или прокси не прокинут в клиент / нет `network_mode: host` |
| Timeout `api.telegram.org` | `/etc/hosts` → `149.154.167.220`; IPv6 не использовать |
| NocoDB/SMTP «ломается» через VPN | Случайно выставлен глобальный `HTTP_PROXY` — убрать |
| Volume стал директорией | Удалить ошибочный каталог, создать файл `{}`, перезапустить compose |
| CRLF в `deploy.sh` | `bash\r` ошибки — перевести на LF |
| Контейнер не видит `:7890` | Забыли `-f docker-compose.vps.yml` / нет host network |
| Compose: `docker: 'compose' is not a docker command` | Поставить plugin в `~/.docker/cli-plugins/` |

Проверки с VPS:

```bash
systemctl --user status mihomo
curl -sS -x http://127.0.0.1:7890 -o /dev/null -w '%{http_code}\n' https://api.telegram.org
docker logs --tail 100 CONTAINER
```

---

## 9. Порядок работ агента при «сделай такой же деплой для нового бота»

1. Убедиться, что приложение стартует локально (`main.py` / compose без vps-файла).
2. Добавить в репо: `Dockerfile`, compose×2, `deploy.sh`, workflow, `.dockerignore`, `.env.example`, `deploy_to_build.cmd`, точечный прокси.
3. Создать ветку `build`, запушить (после настройки secrets).
4. По SSH на SkyNode: уникальные SSH-ключи, clone в `~/PROJECT`, `.env` с прокси.
5. Попросить пользователя: Deploy key + GitHub Secrets (приватный ключ в чат/логи не светить лишний раз; лучше пользователь копирует с VM сам).
6. Ручной `bash deploy.sh` → проверить логи.
7. Прогнать `deploy_to_build.cmd` / push `build` → убедиться, что Actions зелёный.
8. Зафиксировать в `cursorcontext.md` нового проекта: пути, secrets names, container name, особенности прокси/БД.
9. Напомнить: не гонять локальный и прод с одним токеном.

---

## 10. Шаблон содержимого для `cursorcontext` нового проекта (фрагмент)

Скопируй и заполни:

```markdown
## Деплой SkyNode
- Каталог VPS: ~/PROJECT
- Ветка: build
- Контейнер: CONTAINER (network_mode: host)
- Триггер: push build → GitHub Actions → bash deploy.sh
- Secrets: VPS_HOST, VPS_USER, VPS_SSH_KEY, VPS_DEPLOY_PATH
- Ключи: ~/.ssh/PROJECT_github (RO→GitHub), ~/.ssh/PROJECT_gha (GHA→VM)
- .env на хосте: OUTBOUND_HTTPS_PROXY=http://127.0.0.1:7890
- Прокси только Telegram+Gemini; NocoDB/SMTP — напрямую
- Compose: docker compose -f docker-compose.yml -f docker-compose.vps.yml
```

---

## 11. Что сознательно не копировать из NutriSnap

- Table IDs / Base ID NocoDB — свои для нового продукта.
- Имена контейнера и concurrency group Actions — **уникальные**, иначе два проекта будут мешать друг другу.
- Бизнес-логику калорий / FSM еды — только если новый бот того же продукта.
- Папку `Старое/` — не использовать как основу.

---

## 12. Краткая история решений (NutriSnap)

1. Long polling проще webhook на этой VM (не нужен входящий TLS для бота).
2. Gemini с IP VPS → geo-block → нужен mihomo без TUN на `127.0.0.1:7890`.
3. Telegram «родные» DNS IP timeout → `/etc/hosts` на DC IP `149.154.167.220`.
4. Чтобы контейнер видел mihomo и hosts — `network_mode: host`.
5. Секреты только в `.env` на хосте (`env_file`), не в образе.
6. Деплой через ветку `build` + Actions SSH — один клик с Windows (`deploy_to_build.cmd`).
7. Compose plugin поставлен в home без sudo (у `gogortey` нет passwordless sudo).

Дата актуальности playbook: 2026-08-09. При расхождении с кодом — верить скриптам/`cursorcontext.md`, затем обновить этот файл.
