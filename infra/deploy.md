# Deploy (servidor compartilhado) — https://abbycash.abbysystems.com.br

Nada daqui é automático. O `abby-chat` e demais contêineres/servers do host **não** são tocados: não pare, não faça prune.

## 0. Pré-requisitos do dono
SSH no servidor; registro DNS **A/AAAA** de `abbycash.abbysystems.com.br` apontando para o servidor; `.env` de produção
(ver abaixo); `age-keygen` rodado e a chave pública em `BACKUP_AGE_RECIPIENT` (a privada fica offline).

## 1. Inspeção prévia (somente leitura)
```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -i chat        # abby-chat está em contêiner?
systemctl status nginx; nginx -V 2>&1 | head -2                   # Nginx no host? o conf usa `listen 443 ssl` sem http2 de propósito: no 1.24 `http2` no listen vale para o socket :443 compartilhado e mudaria os outros sites
nginx -T 2>/dev/null | grep -E 'server_name|listen|include'       # servers existentes, portas 80/443
ss -ltnp | grep -E ':(80|443|18000|18081)\b'                       # portas livres
docker network ls; ip -4 addr | grep 172.29.77                     # sub-rede 172.29.77.0/24 livre?
```
Se o Nginx for um contêiner, os upstreams `127.0.0.1:18000/18081` do `abby-cash.conf` devem apontar para o host
(`host.docker.internal`/gateway). Se `172.29.77.0/24` colidir, mude a sub-rede, o `gateway` **e** `TRUSTED_PROXIES` no compose.
`TRUSTED_PROXIES=172.29.77.1/32`: só o gateway fixo de `abby-cash-net` (por onde o Nginx do host chega) pode mandar `X-Forwarded-For`.
**Confirme que nenhum CDN/proxy (Cloudflare etc.) fica na frente do Nginx do host.** Se houver, o IP do cliente chega errado:
configure `real_ip_header`/`set_real_ip_from` (módulo `realip`) com os IPs do CDN antes de confiar em rate limit/IP.

## 2. Código e `.env`
```bash
git clone <repo> /opt/abby-cash && cd /opt/abby-cash && git checkout <tag>
cp .env.example .env && chmod 600 .env   # preencher; nunca commitar
```
Obrigatórios em prod: `JWT_SECRET` (32+), `POSTGRES_PASSWORD`, `TOTP_ENC_KEY` (Fernet, ver `.env.example`),
`EVOLUTION_API_KEY`, `EVOLUTION_DB_PASSWORD`, `EVOLUTION_WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`
(webhook secrets e `EVOLUTION_API_KEY`: 16+ chars, sem `change-me`; a API recusa subir em prod com valores fracos),
`REDIS_PASSWORD` (só `[A-Za-z0-9_-]`, 16+), `ABBY_TAG`, `OPENAI_API_KEY`, `BACKUP_AGE_RECIPIENT`, `BACKUP_ADMIN_CHAT_ID`. `PUBLIC_BASE_URL`, `HSTS`, `TRUSTED_PROXIES` o compose já fixa.
Imagens: `ABBY_REGISTRY=ghcr.io/<dono>` e `ABBY_TAG=vX.Y.Z` (publicadas por `release.yml` na tag; `ABBY_TAG` é obrigatório, sem `latest`).
Tetos opcionais: `MSG_RATE_PER_HOUR` (60), `AI_DAILY_TOKEN_BUDGET` (200000/espaço/24h), `STT_DAILY_SECONDS` (1800/espaço/24h).
Redes: a Evolution fica em `evolution-net` (com o banco/Redis dela) e na `evolution-bridge`, compartilhada só com api/worker; não alcança o Redis/Postgres do app.
Contêineres rodam sem root, `cap_drop: ALL`, `read_only`. Volume `storage` já existente (criado como root) precisa de
`docker run --rm -v abby-cash_storage:/s alpine chown -R 10001:10001 /s` antes de subir a nova imagem.

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
# diretórios compartilhados: nunca sobrescrever. Conferir antes; `cp -n` não substitui arquivo existente.
ls -l /etc/nginx/snippets/abby-cash-proxy.conf /etc/nginx/conf.d/abby-cash.conf 2>&1   # esperado: "No such file"
sudo cp -n infra/nginx/abby-cash-proxy.conf /etc/nginx/snippets/abby-cash-proxy.conf
sudo cp -n infra/nginx/abby-cash.conf /etc/nginx/conf.d/abby-cash.conf
ls -l /etc/nginx/snippets/abby-cash-proxy.conf /etc/nginx/conf.d/abby-cash.conf         # ambos presentes
```
Se algum já existir, compare (`diff`) e atualize à mão. O server não loga corpos de requisição.
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
```
WhatsApp/Evolution: defina `EVOLUTION_INSTANCE=abby-cash` no `.env` e suba a stack (`up -d evolution api worker`). O pareamento é no painel:
**Admin › WhatsApp › Conectar número (QR)** (só admin). Ele cria a instância, registra o webhook interno
(`EVOLUTION_WEBHOOK_URL`, `http://api:8000/...` pela `evolution-bridge`) e mostra o QR; escaneie com o chip dedicado
(WhatsApp › Aparelhos conectados). Alternativa por linha de comando: `python -m app.cli evolution-set-webhook`.
URLs: `https://abbycash.abbysystems.com.br/webhooks/telegram` e `.../webhooks/whatsapp_evolution`. Cookie de refresh tem `Path=/auth`: web e API na mesma origem (já é).

## 6. Aceite
`/health` com `status: ok` e `worker: true`; abby-chat respondendo; mensagem de teste no Telegram vira lançamento;
backup manual: `docker compose ... exec backup /backup/backup.sh` (depois, ver `infra/backup/restore.md` e testar a restauração).
**Cópia fora do servidor é fortemente recomendada (obrigatória antes de confiar nos backups):** o volume local morre com o host.
Configure `BACKUP_RCLONE_REMOTE` (ex.: `gdrive:abby-cash-backups`) e o remoto uma vez:
`docker compose ... run --rm --entrypoint rclone backup config` (grava no volume `rclone_conf`). O envio usa `rclone copy` e a retenção
remota (7/4/6) só apaga arquivos com prefixo `abby-db-`/`abby-files-`; nunca `sync`.

## Rollback
```bash
ABBY_TAG=<tag-anterior> docker compose --env-file .env -f infra/docker-compose.prod.yml up -d api worker web
```
Migrações são só aditivas por tag; para reverter schema use o backup (`restore.md`). Nginx: remover `/etc/nginx/conf.d/abby-cash.conf` e `/etc/nginx/snippets/abby-cash-proxy.conf`,
`nginx -t && reload` (os outros servers ficam intactos). Nunca `docker system prune` neste host.
