# Abby Cash

Controle financeiro pessoal/familiar com lançamentos por chat (Telegram/WhatsApp), API FastAPI, worker ARQ e web React.

## Dev

```bash
cp .env.example .env
docker compose -f infra/docker-compose.dev.yml up -d --build   # api :8000, web :5173
curl localhost:8000/health
```

Testes: veja `CLAUDE.md`.

Prod: `docker compose --env-file .env -f infra/docker-compose.prod.yml up -d` (o `--env-file` é necessário para `${POSTGRES_PASSWORD}`; o postgres não recebe o `.env` inteiro).

## WhatsApp (Evolution API)

1. Tenha um **chip dedicado** (número só do bot; não use o seu pessoal) num celular com WhatsApp instalado.
2. Preencha no `.env`: `EVOLUTION_URL=http://evolution:8080`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE` (ex.: `abby`), `EVOLUTION_DB_PASSWORD` (só `[A-Za-z0-9_-]`: vai dentro de uma URL; obrigatória, como `EVOLUTION_API_KEY`), `EVOLUTION_WEBHOOK_SECRET` (16+ caracteres `[A-Za-z0-9_-]`), enviado no header `x-webhook-secret` (não há fallback por query string). Imagem fixada: `evoapicloud/evolution-api:v2.3.7`; banco e Redis da Evolution ficam na rede isolada `evolution-net`.
3. Suba o serviço: `docker compose --env-file .env -f infra/docker-compose.prod.yml up -d evolution`.
4. Crie a instância e leia o **QR code** com o celular do chip (WhatsApp > Aparelhos conectados): `POST /instance/create` com o header `apikey` (instance `abby`, `qrcode: true`), pela rede interna (`docker compose exec api ...`). Um QR é exibido uma vez; refaça se expirar.
5. Registre o webhook: `docker compose exec api python -m app.cli evolution-set-webhook --url http://api:8000/webhooks/whatsapp_evolution`.
6. No painel, gere o código de vínculo do canal `whatsapp_evolution` e mande-o por WhatsApp ao número do bot.

Se a instância cair, o admin recebe um aviso no Telegram (verificação a cada 5 min, um aviso por incidente).

## Produção

Domínio `abbycash.abbysystems.com.br` (web e API na mesma origem). Passo a passo em `infra/deploy.md`; Nginx em `infra/nginx/`;
backups (age, retenção 7/4/6, envio ao Drive opcional) em `infra/backup/` com `restore.md`. Imagens em tag: `.github/workflows/release.yml` (GHCR).
Variáveis novas: `TOTP_ENC_KEY` (obrigatória), `TRUSTED_PROXIES`, `HSTS`, `BACKUP_AGE_RECIPIENT`, `BACKUP_ADMIN_CHAT_ID`, `BACKUP_RCLONE_REMOTE`, `REDIS_PASSWORD` (obrigatória em prod; Redis com senha), `ABBY_TAG` (obrigatória), `MSG_RATE_PER_HOUR`, `AI_DAILY_TOKEN_BUDGET`, `STT_DAILY_SECONDS`.
`TRUSTED_PROXIES` em prod é só o gateway do Nginx (`172.29.77.1/32`).
`/health` retorna `worker` e `worker_last_seen_s` (heartbeat do worker no Redis).
