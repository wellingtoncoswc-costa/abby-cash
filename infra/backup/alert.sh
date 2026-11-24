#!/usr/bin/env bash
# Avisa o admin no Telegram: alert.sh "mensagem". Sem token/chat configurados, so registra no log.
set -uo pipefail
msg="${1:-backup failed}"
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${BACKUP_ADMIN_CHAT_ID:-}" ]]; then
  echo "alert (telegram not configured): $msg" >&2
  exit 0
fi
# o token vai por stdin (-K -): nao aparece em `ps`
printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TELEGRAM_BOT_TOKEN" |
  curl -fsS -m 20 -K - --data-urlencode "chat_id=$BACKUP_ADMIN_CHAT_ID" \
    --data-urlencode "text=Abby Cash backup: $msg" >/dev/null || echo "alert delivery failed" >&2
