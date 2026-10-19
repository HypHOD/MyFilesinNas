#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 与 docker compose 共用同一份 .env，保证能定位到数据库目录
if [ -f "$SCRIPT_DIR/../.env" ]; then
    set -a
    . "$SCRIPT_DIR/../.env"
    set +a
fi

M2_ROOT="${M2_ROOT:-/mnt/m2}"
DEST="$M2_ROOT/backups"
STAMP="$(date +%F-%H%M)"

mkdir -p "$DEST"

if [ -f "$M2_ROOT/appdata/demo/zfile.db" ]; then
    sqlite3 "$M2_ROOT/appdata/demo/zfile.db" ".backup '$DEST/zfile-$STAMP.db'"
fi

if [ -f "$M2_ROOT/appdata/rss/data/data.db" ]; then
    sqlite3 "$M2_ROOT/appdata/rss/data/data.db" ".backup '$DEST/rss-$STAMP.db'"
fi

find "$DEST" -maxdepth 1 -name '*.db' -mtime +14 -delete

echo "备份完成：$DEST"
