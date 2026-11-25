# Abby Cash

Monorepo: `backend/` (FastAPI + SQLAlchemy async + ARQ, uv), `web/` (Vite React TS), `infra/` (compose).
Planos: `docs/superpowers/plans/`. Use o mindset ponytail (mínimo de código); TDD, lint, tipos e verificação são obrigatórios.

## Comandos

```bash
docker compose -f infra/docker-compose.dev.yml up -d postgres redis   # infra dos testes
cd backend && uv run pytest   # usa DB `<db>_test` (criado sozinho) e Redis DB 15; nunca o DB de dev
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd web && npm run lint && npm run typecheck && npm test
```

Prod: `docker compose --env-file .env -f infra/docker-compose.prod.yml up -d` (o `--env-file` é necessário para `${POSTGRES_PASSWORD}`; o postgres não recebe o `.env` inteiro).

## Restrições globais

- Valores monetários **sempre `int` em centavos** (coluna `BIGINT`). Proibido `float` para dinheiro em qualquer camada, inclusive JSON da API (campo `amount_cents`).
- Moeda BRL, idioma pt-BR, fuso padrão `America/Sao_Paulo`; datas de competência (`date`) calculadas **no fuso do usuário**, timestamps em UTC (`timestamptz`).
- Toda tabela financeira tem `space_id`; todo acesso passa por `require_member(session, user_id, space_id)`.
- Segredos só via variáveis de ambiente; `.env` no `.gitignore`; `.env.example` versionado; `gitleaks` no CI.
- Formato de valor nas mensagens: `R$ 1.234,56`.
- Confirmação após todo lançamento via chat: `✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank` + linha `Responda "corrigir" se errei.`
- Comprovante por foto **nunca** grava sem confirmação explícita.
- Alertas de teto em **80%, 100% e acima de 100%**, uma vez por limiar/escopo/mês.
- Lembretes de conta: **1 dia antes e no dia**, às **09:00** no fuso do usuário (configurável), aviso de atraso no dia seguinte.
- Cadastro **somente por convite**.
- Pagamentos (conta a pagar e fatura) **sempre têm conta de origem** (`checking`/`savings`/`wallet`) e geram lançamento.
- Modelo de IA via env `AI_MODEL` (padrão `gpt-4.1`, provedor OpenAI); STT via env `STT_MODEL` (padrão `small`).
- Não alterar nem derrubar o `abby-chat` no servidor compartilhado.
- Commits pequenos, mensagens em inglês no formato Conventional Commits.

## Domínio financeiro (M2)
- Funções de domínio recebem `session` primeiro e sempre passam por `require_member`/`use_account`/`use_card`; erros viram `DomainError` (422) ou 404/403.
- Teto: compra no cartão conta pelo mês de **vencimento** da fatura; pagamento de fatura e aporte de meta são transferências e não contam.
- Pagamento (conta ou fatura) exige conta de origem e gera lançamento; extrato compartilhado agrega itens de outros espaços em `private_total_cents`.
- Migrações: `bash backend/scripts/migrate_check.sh` (upgrade head + alembic check em banco descartável).

## Assistente no chat (M3)
- Telegram: webhook `POST /webhooks/telegram` (segredo no header) ou `python -m app.cli telegram-poll` em dev; `telegram-set-webhook` em produção.
- Fluxo: `ingest` (idempotente) → job `process_inbound` (lock por remetente) → atalhos ou `OpenAIIntentParser` (`AI_MODEL`, saída estruturada; a categoria vem por **índice**) → domínio → resposta.
- O modelo só dá dicas: espaço, conta e categoria são resolvidos a partir das entidades do próprio remetente; texto digitado vence o valor do modelo (com aviso).
- Vínculo: código de 6 dígitos (10 min, 1 vivo por usuário, limites por remetente e global). `docs/api_keys/` e `.env` nunca vão para o git.
- Avaliação real do modelo (manual, gasta API): `cd backend && uv run python scripts/run_eval.py`.
- `purge-inbound` apaga mensagens antigas; o texto é zerado quando a mensagem termina.

## Produção (M8)
- Deploy: `infra/deploy.md` (domínio `abbycash.abbysystems.com.br`, Nginx do host com server novo `infra/nginx/abby-cash.conf`; web e API na mesma origem). Nunca mexer no `abby-chat`/outros contêineres.
- Logs JSON com `request_id`; nunca logar texto de mensagem, tokens ou PII. IP do cliente só via `app.core.http.client_ip` (`TRUSTED_PROXIES`).
- `/health` expõe `worker` (heartbeat no Redis); `TOTP_ENC_KEY` (Fernet) cifra `users.totp_secret`; obrigatória em prod.
- Backup: `infra/backup/` (age + retenção 7/4/6, rclone opcional por `BACKUP_RCLONE_REMOTE`); teste: `bash infra/backup/test_backup.sh`. Restauração: `infra/backup/restore.md`.
