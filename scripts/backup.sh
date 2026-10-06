#!/bin/bash
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGUSER="${PGUSER:-appuser}"
PGPASSWORD="${PGPASSWORD:-secret}"
PGDATABASE="${PGDATABASE:-taskmaster}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${PGDATABASE}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"
echo "[$(date)] Starting backup → $BACKUP_FILE"
PGPASSWORD="$PGPASSWORD" pg_dump -h "$PGHOST" -U "$PGUSER" "$PGDATABASE" | gzip -9 > "$BACKUP_FILE"
gzip -t "$BACKUP_FILE" && echo "[$(date)] Integrity OK"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[$(date)] Done: $BACKUP_FILE ($(du -sh $BACKUP_FILE | cut -f1))"
