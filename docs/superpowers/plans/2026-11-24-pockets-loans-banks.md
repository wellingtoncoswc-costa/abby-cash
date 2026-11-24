# Caixinhas com rendimento, financiamentos/consórcios e ícones de bancos

Decisões do dono (2026-11-24): CDI vem **automático do Banco Central** (SGS série 12, CDI diário em % a.d.); por caixinha o usuário só
configura **% do CDI** (100, 110, 120 ou outro). Rendimento cresce todo dia útil no saldo da caixinha e é lançado como **receita mensal
"Rendimento"** na conta. Financiamentos/consórcios = **parcelas fixas informadas** (valor, quantidade, 1º vencimento).
Ícones: logos reais do pacote `simple-icons` (CC0) embutidos + monograma colorido de fallback.
Regras globais do projeto valem: centavos int, nunca float (taxas em `Decimal`), `require_member`, auditoria só com UUID, LGPD export/delete.

## 1. Banco da conta (ícone)
- `accounts.institution` `VARCHAR(40) NULL` (chave do catálogo, ex. `nubank`, `itau`; `[a-z0-9_]{1,40}`; o catálogo de nomes/logos fica no web, o backend só valida o formato).
- Entra em criar/editar/listar conta (`AccountIn/Update/Out`).

## 2. Caixinhas
Modelo (migração única, uma só head do Alembic):
- `pockets(id, space_id, account_id, name, cdi_bp int, created_at, closed_at null)`; `cdi_bp` = percentual do CDI × 100 (120,00% = 12000), faixa 1..100000.
- `pocket_movements(id, pocket_id, kind deposit|withdraw|accrual, amount_cents BIGINT>0, occurred_on date, ref_date date null, created_at)`; `accrual` tem `ref_date` = dia do CDI (único por pocket+ref_date → idempotente).
- `cdi_rates(on_date PK, daily_pct numeric(14,10))`.
- `pocket_yield_postings(pocket_id, month 'YYYY-MM', transaction_id, amount_cents)` PK (pocket_id, month) → idempotência do lançamento mensal.
Saldo da caixinha `P` = Σ deposit − Σ withdraw + Σ accrual. Depósito/resgate NÃO são lançamentos (são transferências internas da conta; não contam em teto/receita).
Conta: `pockets_cents` = Σ (P − rendimento ainda não lançado) das caixinhas; `available_cents` = saldo da conta − `pockets_cents`. Expor ambos em `AccountOut` (se `balance_cents` ainda não existir ali, expor também).
Regras: depósito ≤ `available_cents` (senão 409 `insufficient_available`); resgate ≤ P (antes de resgatar, lança o rendimento pendente como receita na conta, então P = lançado); excluir só com P = 0 (soft: `closed_at`); mudar `cdi_bp` vale daqui para frente.
Rendimento: para cada `cdi_rates.on_date` d sem accrual na caixinha e d > data de criação: `yield = round_half_even(P_no_início_de_d × daily_pct/100 × cdi_bp/10000)` em `Decimal`, centavos int, gravado como `accrual` (saldo no início de d = movimentos com `occurred_on < d`).
Lançamento mensal: para cada mês fechado (e no resgate, para o mês corrente até o último accrual) cria **uma** receita `income` na conta da caixinha, descrição "Rendimento — <nome>", categoria sistema "Rendimentos" (criar se faltar; ver `domain/categories`), data = último dia útil com accrual, e grava `pocket_yield_postings`. Mês sem rendimento > 0: nada.
CDI: job diário (ARQ, 08:30 America/Sao_Paulo e repetição de hora em hora até haver o último dia útil) busca `https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial=dd/MM/yyyy` (timeout 10s, sem seguir redirect para host diferente, valida `data`/`valor` com Pydantic; `valor` "0.055131" é % ao dia) e faz upsert em `cdi_rates`; em seguida roda accrual+lançamentos. Falha repetida → alerta ao admin pelo mecanismo existente de alertas (`jobs/health`).
API (todas via `require_member` do espaço da conta):
- `POST/GET /spaces/{sid}/pockets`, `PATCH/DELETE /pockets/{id}` (nome, `cdi_bp`); `POST /pockets/{id}/deposit|withdraw {amount_cents, occurred_on?}`; `GET /pockets/{id}/movements`.
- `GET /cdi/latest` → `{on_date, daily_pct, annual_pct}` (anual ≈ ((1+d/100)^252−1)×100, só para exibir).
- `PocketOut`: `id, account_id, name, cdi_bp, balance_cents, pending_yield_cents, month_yield_cents`.
Espaço pessoal continua privado (nada de caixinha pessoal aparece a não-membros).

## 3. Financiamentos e consórcios
- `loans(id, space_id, kind financing|consortium, name, installment_cents, installments_total 1..480, first_due_on, category_id null, account_id null, notes null, created_at, canceled_at null)`.
- As parcelas são **contas a pagar** (`bills`) ligadas ao empréstimo (`bills.loan_id` + `installment_number`, descrição "<nome> (n/N)"): gerar de forma preguiçosa (as próximas 3 em aberto, mais a seguinte ao pagar/por job), reutilizando a infraestrutura de `domain/bills/recurrence.py` se couber; vencimento por `add_months` respeitando fim de mês (dia nominal, igual à regra já usada em recorrência). Pagar continua pelo fluxo existente de pagamento de conta (conta de origem obrigatória, gera lançamento).
- API: `POST/GET /spaces/{sid}/loans`, `GET /loans/{id}` → `LoanOut{id,kind,name,installment_cents,installments_total,paid_count,remaining_count,remaining_cents,next_due_on,last_due_on,progress_pct}`, `PATCH /loans/{id}` (nome/valor da parcela das futuras), `DELETE /loans/{id}` (cancela parcelas em aberto, mantém as pagas).
- Aparece em "Contas a pagar" como as demais contas.

## 4. Web
- Catálogo `web/src/banks.ts` (chave, nome, cor, logo `simple-icons` quando existir) + `<BankIcon institution name />` (logo ou monograma). Seletor "Banco" ao criar/editar conta; ícone nas listas e seletores de conta.
- Páginas: **Caixinhas** (por conta; criar com nome + % do CDI com atalhos 100/110/120 + campo outro; depositar/resgatar; saldo, rendimento do mês e CDI atual) e **Financiamentos e consórcios** (cadastrar; progresso; quanto falta; próxima parcela). Itens novos no menu (Mais no celular).

## Testes obrigatórios
Rendimento (Decimal, arredondamento, idempotência, dia sem CDI), saldo/disponível, depósito acima do disponível, resgate lança rendimento pendente, lançamento mensal único, parcelas de fim de mês (31/jan → 28/fev), 480 parcelas, isolamento de espaço (403/404 para não-membro; pessoal privado), LGPD export/delete incluem as tabelas novas, migração com head única.
