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
