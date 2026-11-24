#!/usr/bin/env bash
# Backup diario: pg_dump -Fc + tar dos anexos, ambos criptografados com age (so a chave PUBLICA fica aqui).
# Retencao local: 7 diarios, 4 semanais (domingo), 6 mensais (dia 1). Falha -> alerta no Telegram.
# Env: BACKUP_AGE_RECIPIENT (obrigatoria), BACKUP_DIR, STORAGE_DIR, PG* (PGHOST/PGUSER/PGPASSWORD/PGDATABASE),
#      BACKUP_RCLONE_REMOTE (opcional, ex.: gdrive:abby-cash-backups; vazio = nao envia).
set -Eeuo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${BACKUP_DIR:=/backups}"
: "${STORAGE_DIR:=/data/storage}"
export PGDATABASE="${PGDATABASE:-abby}"

trap '"$here/alert.sh" "FAILED at line $LINENO (host $(hostname))"; exit 1' ERR

: "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT (age public key) is required}"
ts="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"/{daily,weekly,monthly}
umask 077

d="$BACKUP_DIR/daily"
rm -f -- "$d"/*.tmp # sobras de execucoes que falharam; nunca promovidas
# escreve em .tmp e renomeia logo apos o pipeline: um backup incompleto nunca parece valido
pg_dump -Fc | age -r "$BACKUP_AGE_RECIPIENT" >"$d/abby-db-$ts.dump.age.tmp"
mv "$d/abby-db-$ts.dump.age.tmp" "$d/abby-db-$ts.dump.age"
tar -czf - -C "$STORAGE_DIR" . | age -r "$BACKUP_AGE_RECIPIENT" >"$d/abby-files-$ts.tar.gz.age.tmp"
mv "$d/abby-files-$ts.tar.gz.age.tmp" "$d/abby-files-$ts.tar.gz.age"

# semanal (domingo) e mensal (dia 1): hardlinks, sem duplicar espaco
for kind in db files; do
  for f in "$d"/abby-"$kind"-"$ts".*; do
    if [[ "$(date +%u)" == 7 ]]; then ln -f "$f" "$BACKUP_DIR/weekly/"; fi
    if [[ "$(date +%d)" == 01 ]]; then ln -f "$f" "$BACKUP_DIR/monthly/"; fi
  done
done

prune() { # prune <dir> <manter>: remove os mais antigos de cada prefixo
  local dir="$1" keep="$2" prefix
  for prefix in abby-db- abby-files-; do
    # shellcheck disable=SC2012  # nomes sao so [a-z0-9.-], ls -t e seguro aqui
    { ls -1t "$dir"/"$prefix"* 2>/dev/null || true; } | tail -n +"$((keep + 1))" | xargs -r rm -f --
  done
}
prune "$BACKUP_DIR/daily" 7
prune "$BACKUP_DIR/weekly" 4
prune "$BACKUP_DIR/monthly" 6

# remoto: `copy` (nunca `sync`: um erro local nao apaga o remoto) e retencao so dos NOSSOS arquivos
rprune() { # rprune <subdir> <manter>: apaga do remoto os mais antigos com nossos prefixos
  local sub="$1" keep="$2" prefix f
  for prefix in abby-db- abby-files-; do
    { rclone lsf --files-only "$BACKUP_RCLONE_REMOTE/$sub" 2>/dev/null || true; } |
      { grep "^$prefix" || true; } | sort -r | tail -n +"$((keep + 1))" |
      while IFS= read -r f; do rclone deletefile "$BACKUP_RCLONE_REMOTE/$sub/$f"; done
  done
}
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  rclone copy "$BACKUP_DIR" "$BACKUP_RCLONE_REMOTE" --include "abby-db-*" --include "abby-files-*"
  rprune daily 7; rprune weekly 4; rprune monthly 6
else
  echo "BACKUP_RCLONE_REMOTE not set: skipping remote upload (local backup only)"
fi
echo "backup ok: $ts"
