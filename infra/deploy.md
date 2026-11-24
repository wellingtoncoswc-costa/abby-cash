# Deploy (servidor compartilhado) — https://abbycash.abbysystems.com.br

Nada daqui é automático. O `abby-chat` e demais contêineres/servers do host **não** são tocados: não pare, não faça prune.

## 0. Pré-requisitos do dono
SSH no servidor; registro DNS **A/AAAA** de `abbycash.abbysystems.com.br` apontando para o servidor; `.env` de produção
(ver abaixo); `age-keygen` rodado e a chave pública em `BACKUP_AGE_RECIPIENT` (a privada fica offline).

## 1. Inspeção prévia (somente leitura)
```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -i chat        # abby-chat está em contêiner?
systemctl status nginx; nginx -V 2>&1 | head -2                   # Nginx no host? versão >= 1.25.1 (http2 on)
nginx -T 2>/dev/null | grep -E 'server_name|listen|include'       # servers existentes, portas 80/443
ss -ltnp | grep -E ':(80|443|18000|18081)\b'                       # portas livres
docker network ls; ip -4 addr | grep 172.29.77                     # sub-rede 172.29.77.0/24 livre?
```
Se o Nginx for um contêiner, os upstreams `127.0.0.1:18000/18081` do `abby-cash.conf` devem apontar para o host
(`host.docker.internal`/gateway). Se `172.29.77.0/24` colidir, mude a sub-rede **e** `TRUSTED_PROXIES` no compose.

## 2. Código e `.env`
```bash
git clone <repo> /opt/abby-cash && cd /opt/abby-cash && git checkout <tag>
cp .env.example .env && chmod 600 .env   # preencher; nunca commitar
```
Obrigatórios em prod: `JWT_SECRET` (32+), `POSTGRES_PASSWORD`, `TOTP_ENC_KEY` (Fernet, ver `.env.example`),
`EVOLUTION_API_KEY`, `EVOLUTION_DB_PASSWORD`, `EVOLUTION_WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
`OPENAI_API_KEY`, `BACKUP_AGE_RECIPIENT`, `BACKUP_ADMIN_CHAT_ID`. `PUBLIC_BASE_URL`, `HSTS`, `TRUSTED_PROXIES` o compose já fixa.
Imagens: `ABBY_REGISTRY=ghcr.io/<dono>` e `ABBY_TAG=vX.Y.Z` (publicadas por `release.yml` na tag); sem elas, `--build` local.

## 3. Subir a stack (projeto `abby-cash`)
```bash
docker compose --env-file .env -f infra/docker-compose.prod.yml config >/dev/null   # valida
docker compose --env-file .env -f infra/docker-compose.prod.yml pull   # ou: up -d --build
docker compose --env-file .env -f infra/docker-compose.prod.yml up -d
curl -s http://127.0.0.1:18000/health    # migrações Alembic rodam no start da API; esperado "worker": true em ~1 min
```
Admin inicial: `docker compose ... exec api python -m app.cli create-admin --email <e> --name <n>`.

## 4. Nginx: adicionar o server novo (sem alterar os existentes)
```bash
sudo cp infra/nginx/abby-proxy.conf /etc/nginx/snippets/abby-proxy.conf
sudo cp infra/nginx/abby-cash.conf /etc/nginx/conf.d/abby-cash.conf
```
O certificado ainda não existe: na 1ª vez comente temporariamente o `server` 443 (ou use só o bloco :80), então:
```bash
sudo mkdir -p /var/www/certbot
sudo nginx -t                                             # DEVE passar
sudo nginx -T > /tmp/nginx-depois.txt                     # compare com a saída do passo 1 e REVISE o diff
sudo systemctl reload nginx                               # só depois de revisar
sudo certbot certonly --webroot -w /var/www/certbot -d abbycash.abbysystems.com.br
# descomentar o server 443, de novo: nginx -t && reload
curl -sI https://abbycash.abbysystems.com.br/health; curl -sI https://<dominio-do-abby-chat>/   # ambos respondem
```

## 5. Webhooks
```bash
# Telegram (usa TELEGRAM_BOT_TOKEN/TELEGRAM_WEBHOOK_SECRET do .env)
docker compose --env-file .env -f infra/docker-compose.prod.yml exec api python -m app.cli telegram-set-webhook
# WhatsApp/Evolution (PUBLIC_BASE_URL já aponta para o domínio):
docker compose --env-file .env -f infra/docker-compose.prod.yml exec api python -m app.cli evolution-set-webhook
```
URLs: `https://abbycash.abbysystems.com.br/webhooks/telegram` e `.../webhooks/whatsapp_evolution`. Cookie de refresh tem `Path=/auth`: web e API na mesma origem (já é).

## 6. Aceite
`/health` com `status: ok` e `worker: true`; abby-chat respondendo; mensagem de teste no Telegram vira lançamento;
backup manual: `docker compose ... exec backup /backup/backup.sh` (depois, ver `infra/backup/restore.md` e testar a restauração).

## Rollback
```bash
ABBY_TAG=<tag-anterior> docker compose --env-file .env -f infra/docker-compose.prod.yml up -d api worker web
```
Migrações são só aditivas por tag; para reverter schema use o backup (`restore.md`). Nginx: remover `/etc/nginx/conf.d/abby-cash.conf`,
`nginx -t && reload` (os outros servers ficam intactos). Nunca `docker system prune` neste host.
