# Despesas e receitas fixas

## Objetivo
Cadastro de lançamentos fixos (receita/despesa) com conta de origem/destino, lançamento automático no dia e projeção dos próximos 6 meses.

## Modelo
- `recurring_items`: `id`, `space_id`, `type` (expense|income), `description`, `amount_cents` (>0), `account_id` (mesma conta do espaço; despesa: de onde sai, receita: onde entra), `category_id` opcional, `rule` (JSONB: monthly | yearly | every_n_months, reaproveita `bills.recurrence.Recurrence`), `starts_on`, `ends_on` opcional, `active`, `created_by`, `created_at`.
- `recurring_postings(item_id, due_on)` PK + `transaction_id` (SET NULL): idempotência, cada data lançada uma vez, mesmo se o lançamento for apagado.

## Lançamento automático
Job diário (06:20 SP): para cada item ativo, datas de `starts_on` até hoje (e <= `ends_on`) ainda sem posting viram `create_transaction` (origem `recurring`, data = data devida, ator = `created_by`). Falha em um item não para os outros. Editar valor vale dali em diante; pausar interrompe.

## Projeção
`GET /spaces/{id}/recurring/projection`: 6 meses a partir do atual (mês corrente conta só datas > hoje): receitas, despesas, resultado e saldo projetado (saldo atual das contas do espaço + acumulado); mais as 10 próximas ocorrências em 30 dias, cada uma com a conta. Só considera os fixos.

## API (tudo sob `/spaces/{id}/recurring`, sem prefixo novo no Nginx)
`POST` e `GET` (lista com `next_due_on`), `PATCH /{item}` (inclui `active`), `DELETE /{item}`, `GET /projection`. Só o dono cria/edita/exclui; qualquer membro vê.

## Regras
Excluir conta com fixo: `account_in_use`. Conta deve ser do mesmo espaço (corrente/poupança/carteira). Limpeza de privacidade apaga os fixos do espaço.

## Web
Página "Fixos" (`/fixos`): botão "+" abre modal de cadastro (rótulo "Sai de" para despesa, "Entra em" para receita); painel de projeção no topo; um card por fixo com Pausar/Retomar, editar e excluir.

## Fora de escopo
Semanal/quinzenal, fixos em cartão de crédito, valor variável/estimado, aviso ao usuário a cada lançamento automático.
