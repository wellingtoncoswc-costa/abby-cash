# Abby Cash

Monorepo: `backend/` (FastAPI + SQLAlchemy async + ARQ, uv), `web/` (Vite React TS), `infra/` (compose).
Planos: `docs/superpowers/plans/`. Use o mindset ponytail (mínimo de código); TDD, lint, tipos e verificação são obrigatórios.

## Comandos

```bash
docker compose -f infra/docker-compose.dev.yml up -d postgres redis   # infra dos testes
cd backend && uv run pytest
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd web && npm run lint && npm run typecheck && npm test
```

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
- Modelo de IA via env `AI_MODEL` (padrão `claude-opus-5-5`); STT via env `STT_MODEL` (padrão `small`).
- Não alterar nem derrubar o `abby-chat` no servidor compartilhado.
- Commits pequenos, mensagens em inglês no formato Conventional Commits.
