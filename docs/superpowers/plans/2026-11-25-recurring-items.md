# Despesas e receitas fixas — plano (resumido)

> Execução inline, TDD. Spec: `docs/superpowers/specs/2026-11-25-recurring-items-design.md`. Branch `feat/recurring-items`.

1. **Modelo + migração** (`domain/recurring/models.py`, migração após `f7a8b9c0d1e2`; `domain/models.py`; `accounts/service.py::delete_account` +`RecurringItem`; `privacy.py` limpeza/export). Teste: `migrate_check`, privacidade.
2. **Domínio** (`domain/recurring/service.py`): `create_item` (dono; conta do espaço; categoria), `update_item`, `delete_item`, `list_items` (+`next_due_on`), `occurrences`, `post_due` (idempotente), `projection`. Testes `tests/domain/test_recurring.py`: criação/validações, datas (mensal, dia 31, anual, a cada N), lançamento idempotente e recuperação de datas perdidas, pausa e fim, projeção (mês corrente só futuras, saldo acumulado, contas), conta em uso.
3. **Job** (`jobs/recurring.py` + cron 09:20 UTC): `post_recurring_job`; teste de idempotência e falha isolada.
4. **API** (`api/recurring.py`, `main.py`): rotas da spec; teste HTTP (fluxo, validação, só dono, não-membro).
5. **Web** (`pages/recurring.tsx`, `router.tsx`, `layout.tsx`, `api/types.ts`): página `/fixos`, modal "+", projeção, cards; testes em `pages.test.tsx`.
6. **Verificação**: suíte completa backend (uma vez), web, `migrate_check`; merge/push/deploy só com confirmação.
