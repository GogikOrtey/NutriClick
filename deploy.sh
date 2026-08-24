#!/usr/bin/env bash
# deploy.sh — обновляет код с ветки build и пересобирает контейнер на SkyNode.
# Используется: вручную на VPS и из GitHub Actions (SSH → bash deploy.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "==> git fetch/reset origin/build"
git fetch origin build
git checkout build
git reset --hard origin/build

echo "==> prepare volumes"
mkdir -p logs
# Bind-mounts в compose: если файла нет, Docker создаёт каталог → deploy/контейнер ломаются.
# Нужна именно для: ensure_bind_file (ниже) и вызовов в этом скрипте перед compose up.
ensure_bind_file() {
  local path="$1"
  if [[ -d "$path" ]]; then
    echo "WARN: $path is a directory (Docker bind artifact) — replacing with JSON file"
    rm -rf "$path"
  fi
  if [[ ! -f "$path" ]]; then
    echo '{}' > "$path"
  fi
}
ensure_bind_file .reminder_day_keys.json
ensure_bind_file .reminder_pending_meal.json

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in $ROOT — copy secrets before deploy." >&2
  exit 1
fi

echo "==> docker compose up --build -d"
docker compose -f docker-compose.yml -f docker-compose.vps.yml up --build -d

echo "==> status"
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
echo "Deploy done."
