#!/usr/bin/env bash
# Teste do fluxo do backup.sh sem Postgres/age/rclone reais: stubs no PATH.
# Verifica: arquivos gerados, retencao (7 diarios), pulo do rclone sem remoto, alerta em falha.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/storage" "$tmp/b"
echo anexo >"$tmp/storage/a.txt"
printf '#!/bin/sh\necho DUMP\n' >"$tmp/bin/pg_dump"
printf '#!/bin/sh\ncat\n' >"$tmp/bin/age" # "criptografia" identidade
printf "#!/bin/sh\necho \"\$1\" >> %s/alerts\n" "$tmp" >"$tmp/alert_stub"
chmod +x "$tmp"/bin/* "$tmp/alert_stub"
cp "$here/backup.sh" "$tmp/backup.sh"
cp "$tmp/alert_stub" "$tmp/alert.sh"
export PATH="$tmp/bin:$PATH" BACKUP_DIR="$tmp/b" STORAGE_DIR="$tmp/storage" BACKUP_AGE_RECIPIENT=age1x

for _ in 1 2 3 4 5 6 7 8 9; do # 9 execucoes, timestamps distintos
  bash "$tmp/backup.sh" >"$tmp/out" 2>&1 || { cat "$tmp/out" "$tmp/alerts"; exit 1; }
  sleep 1
done
grep -q "skipping remote upload" "$tmp/out"
[[ "$(ls "$tmp"/b/daily/abby-db-* | wc -l)" == 7 ]]
[[ "$(ls "$tmp"/b/daily/abby-files-* | wc -l)" == 7 ]]
[[ "$(ls "$tmp"/b/daily/*.tmp 2>/dev/null | wc -l)" == 0 ]]

# remoto: copy + poda so dos nossos prefixos (nunca sync)
cat >"$tmp/bin/rclone" <<STUB
#!/bin/sh
echo "\$@" >> $tmp/rclone.log
if [ "\$1" = lsf ]; then printf 'other.txt\n'; for i in 1 2 3 4 5 6 7 8 9; do echo abby-db-2026010\$i.dump.age; done; fi
STUB
chmod +x "$tmp/bin/rclone"
BACKUP_RCLONE_REMOTE=r:x bash "$tmp/backup.sh" >/dev/null 2>&1
grep -q "^copy " "$tmp/rclone.log"; ! grep -q "sync" "$tmp/rclone.log"
grep -q "deletefile r:x/daily/abby-db-20260101" "$tmp/rclone.log"
! grep -q "other.txt" <(grep deletefile "$tmp/rclone.log")
rm "$tmp/bin/rclone"

# falha (pg_dump quebrado) -> alerta e status != 0
printf '#!/bin/sh\nexit 1\n' >"$tmp/bin/pg_dump"
if bash "$tmp/backup.sh" >/dev/null 2>&1; then echo "expected failure"; exit 1; fi
grep -q FAILED "$tmp/alerts"
echo "backup test ok"
