#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! docker compose version >/dev/null 2>&1; then
    echo "未找到 docker compose，请先安装 Docker Engine + Compose v2" >&2
    exit 1
fi

docker compose build backend
docker compose run --rm backend python scripts/init_db.py
docker compose run --rm backend python scripts/seed_local_storage.py
docker compose up -d --build

PORT="$(docker compose port nginx 80 | awk -F: '{print $NF}')"
echo "服务已启动：http://<树莓派内网IP>:${PORT}/"
echo "qBittorrent WebUI 端口见 .env 的 QB_HOST_PORT（默认 8081）"
