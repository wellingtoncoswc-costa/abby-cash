#!/usr/bin/env bash
# Cron do backup: 03:00 todo dia. O crond do busybox nao herda o ambiente: exporta para um arquivo.
set -euo pipefail
export -p | grep -E 'BACKUP_|PG|STORAGE_DIR|TELEGRAM_BOT_TOKEN|TZ=' > /etc/backup.env || true
chmod 600 /etc/backup.env
echo '0 3 * * * . /etc/backup.env; /backup/backup.sh > /proc/1/fd/1 2>&1' > /etc/crontabs/root
exec crond -f -l 8
