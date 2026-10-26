#!/usr/bin/env bash
# Nightly Postgres backup on the server: custom-format pg_dump, verified, 14 days kept.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${DCM_BACKUP_DIR:-$HOME/dhaka-backups}"; KEEP_DAYS="${DCM_BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DEST" && chmod 700 "$DEST"
OUT="$DEST/dcm-$(date +%Y%m%d-%H%M%S).dump"
docker compose -f compose.yaml -f compose.inhouse.yaml exec -T db pg_dump -U dcm -d dcm -Fc > "$OUT.part"
docker compose -f compose.yaml -f compose.inhouse.yaml exec -T db pg_restore --list < "$OUT.part" > /dev/null   # readable?
mv "$OUT.part" "$OUT" && chmod 600 "$OUT"
find "$DEST" -name 'dcm-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
