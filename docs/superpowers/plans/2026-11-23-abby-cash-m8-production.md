# M8 — Produção (parte do repositório)

Escopo: só arquivos e testes. Nada é implantado, nenhum servidor/Nginx/contêiner é tocado, rclone não é executado.
Domínio: `abbycash.abbysystems.com.br` (web e API na mesma origem; cookie de refresh `Path=/auth`).

## T8.3 Observabilidade e endurecimento (`backend/`)
- `app/core/http.py`: logs JSON (`request_id` por contextvar, header `X-Request-ID` validado ou gerado); access log próprio só
  com método/path/status/ms (sem query, sem corpo); uvicorn `--no-access-log`; `httpx` em WARNING (URL do bot tem token);
  exceções logam só o tipo. Cabeçalhos: nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, HSTS só com `HSTS=true`.
  CORS restrito à origem de `PUBLIC_BASE_URL`.
- `client_ip()`: `X-Forwarded-For` só se o peer está em `TRUSTED_PROXIES` (padrão: ninguém); percorre da direita p/ esquerda.
  Usado por login, registro, exclusão de conta e webhooks.
- Heartbeat do worker (cron 30 s) em `worker:heartbeat`; `/health` devolve `worker` e `worker_last_seen_s`; sempre 200, `degraded`
  se o heartbeat está ausente/velho (`HEARTBEAT_STALE_S`, 90).
- Rate limit de webhook por IP (`WEBHOOK_RATE_PER_MIN`, 600) via `incr_ttl`.
- TOTP em repouso: `EncryptedStr` (Fernet, `TOTP_ENC_KEY`, prefixo `enc:`); leitura aceita texto puro legado e a próxima escrita cifra;
  chave obrigatória em prod; migração só alarga a coluna. Perder a chave = perder os 2FA (usuários reconfiguram).
- Job diário apaga refresh tokens expirados ou revogados há > 1 dia.
- CI: `pip-audit` (backend) e `npm audit --omit=dev --audit-level=high` (web) **falham** o CI em vulnerabilidade conhecida;
  advisory sem correção disponível → ignorar explicitamente (`--ignore-vuln`) com justificativa em commit. gitleaks mantido.

## T8.1 Deploy (escrito, não executado)
`infra/nginx/abby-cash.conf` + `abby-proxy.conf` (server novo, TLS Let's Encrypt, CSP, rate limit, SPA, upload 12 MB),
`infra/deploy.md`, `infra/web.Dockerfile` (build estático + nginx interno), `.github/workflows/release.yml` (GHCR em tag),
compose de prod completo (api/web só em `127.0.0.1`, healthchecks, limites, restart, volumes `storage`/`backups`, sub-rede fixa).

## T8.2 Backups
`infra/backup/{backup.sh,alert.sh,entrypoint.sh,Dockerfile,restore.md,test_backup.sh}`; serviço `backup` (cron 03:00) no compose.
`pg_dump -Fc` + tar dos anexos, ambos `age` (chave pública), retenção local 7/4/6, alerta no Telegram em falha.
Envio ao Drive é **opcional** (`BACKUP_RCLONE_REMOTE`); sem ele loga e segue. `test_backup.sh` roda o fluxo com stubs de
pg_dump/age (sem rclone) e testa retenção e alerta. Scripts passam `shellcheck -S warning`.

## Pontos que dependem do dono
- Acesso SSH ao servidor e execução do `infra/deploy.md` (inclui revisar o diff do Nginx antes do reload).
- Criar o registro DNS A/AAAA de `abbycash.abbysystems.com.br` para o servidor (depois, certbot).
- Par de chaves `age` (`age-keygen`): chave pública em `BACKUP_AGE_RECIPIENT`; **privada guardada offline**.
- Valores no `.env`: `TOTP_ENC_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD`, `EVOLUTION_API_KEY/DB_PASSWORD/WEBHOOK_SECRET`,
  `TELEGRAM_*`, `OPENAI_API_KEY`, `BACKUP_ADMIN_CHAT_ID`.
- Visibilidade dos pacotes no GHCR (privados exigem `docker login ghcr.io` no servidor) e `ABBY_REGISTRY`.
- Depois: `rclone config` (remote `gdrive`) e `BACKUP_RCLONE_REMOTE=gdrive:abby-cash-backups` (instalar rclone na imagem do backup).
