#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 与 docker compose 共用同一份 .env，避免挂载路径和属主不一致
if [ -f "$SCRIPT_DIR/../.env" ]; then
    set -a
    . "$SCRIPT_DIR/../.env"
    set +a
fi

M2_ROOT="${M2_ROOT:-/mnt/m2}"
APP_UID="${PUID:-1000}"
APP_GID="${PGID:-1000}"

if ! mountpoint -q "$M2_ROOT"; then
    echo "错误：$M2_ROOT 未挂载。先配置 /etc/fstab 并执行: sudo mount $M2_ROOT" >&2
    exit 1
fi

install -d -m 0755 \
    "$M2_ROOT/media" \
    "$M2_ROOT/media/Bangumi" \
    "$M2_ROOT/downloads" \
    "$M2_ROOT/downloads/incomplete" \
    "$M2_ROOT/backups" \
    "$M2_ROOT/appdata" \
    "$M2_ROOT/appdata/demo" \
    "$M2_ROOT/appdata/rss" \
    "$M2_ROOT/appdata/rss/config" \
    "$M2_ROOT/appdata/rss/data" \
    "$M2_ROOT/appdata/qbittorrent"

chown -R "$APP_UID:$APP_GID" \
    "$M2_ROOT/appdata" \
    "$M2_ROOT/downloads" \
    "$M2_ROOT/backups"

# 只设置媒体库根目录属主，不递归改动已有媒体文件
chown "$APP_UID:$APP_GID" "$M2_ROOT/media" "$M2_ROOT/media/Bangumi"

echo "目录就绪：$M2_ROOT (UID:GID=$APP_UID:$APP_GID)"
echo "下一步：cp .env.example .env 并按需修改，然后执行 deploy/bootstrap.sh"
