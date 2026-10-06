#!/bin/bash
# Nightly Job Hunter backup (constitution IX); failures are sent to the admins on Telegram. Cron:
#   30 3 * * * BACKUP_DRIVE=/mnt/backup /opt/docker/job-hunter/backup.sh >> ~/logs/job-hunter-backup.log 2>&1
set -euo pipefail

BACKUP_DRIVE="${BACKUP_DRIVE:-/mnt/backup}"   # a mounted backup drive
DEST="$BACKUP_DRIVE/manual-backups/job-hunter"
APP_DIR="/opt/docker/job-hunter"
KEEP_REMOTE=30
KEEP_LOCAL=3
STAMP=$(date +%Y%m%d)

cd "$APP_DIR"

# Telegram alert to the admins (Settings -> Notifications chat id); never fails the script.
alert() {
    docker compose exec -T job-hunter jobhunter notify-admins "Job Hunter backup FAILED: $1" \
        >/dev/null 2>&1 || echo "$(date): the Telegram alert could not be sent either" >&2
}
trap 'alert "a step failed (line $LINENO). See ~/logs/job-hunter-backup.log"' ERR

if ! mountpoint -q "$BACKUP_DRIVE" 2>/dev/null; then
    echo "$(date): ERROR: backup drive not mounted at $BACKUP_DRIVE" >&2
    alert "the backup drive is not mounted at $BACKUP_DRIVE. Is it plugged in?"
    exit 1
fi

docker compose exec -T job-hunter jobhunter backup "/data/backups/jobhunter-$STAMP.db" >/dev/null
mkdir -p "$DEST"
cp -p "data/backups/jobhunter-$STAMP.db" "$DEST/"
# Uploaded resumes (FR-039)
if [ -d data/uploads ]; then
    tar -czf "data/backups/uploads-$STAMP.tar.gz" -C data uploads
    cp -p "data/backups/uploads-$STAMP.tar.gz" "$DEST/"
fi

# Keep the newest copies only.
ls -1t "$DEST"/jobhunter-*.db 2>/dev/null | tail -n +$((KEEP_REMOTE + 1)) | xargs -r rm -- || true
ls -1t data/backups/jobhunter-*.db 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -- || true
ls -1t "$DEST"/uploads-*.tar.gz 2>/dev/null | tail -n +$((KEEP_REMOTE + 1)) | xargs -r rm -- || true
ls -1t data/backups/uploads-*.tar.gz 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -- || true

echo "$(date): backup ok -> $DEST/jobhunter-$STAMP.db"
