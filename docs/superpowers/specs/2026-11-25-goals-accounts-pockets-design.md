# Metas com contas e caixinhas

## Objetivo
O progresso de uma meta passa a incluir contas e caixinhas ligadas pelo usuário ao criar ou editar a meta.

## Modelo
- `goal_accounts(goal_id, account_id)` e `goal_pockets(goal_id, pocket_id)`; `account_id` e `pocket_id` são `UNIQUE`: cada um fica em no máximo uma meta.
- `Goal.account_id` (informativo) é migrado para `goal_accounts` e removido.
- Conflito cruzado bloqueado: se a conta X está na meta A, a caixinha de X não pode entrar na meta B (e vice-versa). Erro 422 `already_linked`.
- Ligar exige `require_member` no espaço da meta e `use_account` / `visible_pocket` no item.

## Cálculo
`saved = goal_saved (aportes diretos) + Σ account_balance(contas ligadas) + Σ saldo(caixinhas ligadas cuja conta não está ligada)`.
- O saldo da conta já inclui o dinheiro das caixinhas; por isso a caixinha de uma conta ligada à própria meta é ignorada na soma.
- Saldo de caixinha = `pocket_stats.balance` (inclui rendimento ainda não lançado).
- Alimenta `monthly_needed`, `behind` e o selo "Meta batida".

## API / web
- `POST/PATCH /goals` aceitam `account_ids` e `pocket_ids` (a lista substitui a anterior).
- A resposta traz progresso e itens ligados.
- Formulário da meta: multisselect de contas e de caixinhas; itens ligados a outra meta ficam desabilitados com o nome dela.

## Testes
Soma sem duplicar, conflito entre metas, conflito cruzado conta/caixinha, permissão, edição que troca/remove ligações, migração do `account_id` antigo, web (formulário e desabilitados).

## Fora de escopo
Investimentos (spec própria).
