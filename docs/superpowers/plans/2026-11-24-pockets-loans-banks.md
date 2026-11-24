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

## Decisões (backend)
- Data de criação da caixinha = `created_at` convertido para `DEFAULT_TZ`; só dias de CDI **depois** dela rendem. Rendimento que arredonda para 0 não grava `accrual`.
- Depósito/resgate com `occurred_on` no futuro ou anterior ao último `accrual` da caixinha: 422 `invalid_date` (não reescreve rendimento já creditado).
- Resgate acima do saldo: 422 `insufficient_balance`; depósito acima do disponível: 409 `insufficient_available`; excluir com saldo: 422 `pocket_has_balance`. Caixinha excluída (`closed_at`) some da lista e responde 404.
- Receita mensal "Rendimento": uma por caixinha e mês. Se, depois de lançada (resgate no meio do mês), chegam novos dias do mesmo mês, a mesma receita e o `pocket_yield_postings` são **ajustados** (valor/data) em vez de criar outra. Lançamento sem autor (`created_by` NULL, `origin='system'`). Categoria "Rendimentos" (income) criada sob demanda no espaço.
- `PocketOut.balance_cents` inclui rendimento ainda não lançado; `pending_yield_cents` = rendimento creditado e não lançado; `month_yield_cents` = Σ accruals do mês corrente.
- Criar caixinha exige a conta no mesmo espaço do `{sid}` (senão 404/403); qualquer membro do espaço opera (`require_member`).
- Job `sync_cdi_job`: cron de hora em hora (08:30 a 20:30 SP). Só busca no BCB se falta o último dia útil (sem calendário de feriados: em feriado repete a consulta). Falha: contador no Redis; 3 seguidas avisam os admins (Telegram) uma vez por dia; sucesso zera.
- `GET /cdi/latest`: `daily_pct` e `annual_pct` vão como string decimal (nunca float); 404 `cdi_unavailable` se ainda não há taxa.
- Parcelas: mantém-se 3 parcelas não pagas geradas (completa ao criar e ao pagar uma parcela). Parcela de financiamento pode ser editada/paga como conta comum, mas **não apagada** (422 `loan_bill_locked`; use `DELETE /loans/{id}`). Cancelar apaga só parcelas sem pagamento; parcial e paga ficam. Lista de empréstimos omite cancelados; `GET /loans/{id}` mostra com `canceled_at`.
- `remaining_cents` = saldo a pagar das parcelas geradas + (não geradas × valor atual da parcela). `progress_pct` = pagas × 100 // total.
- Conta com caixinha ou empréstimo vinculado não pode ser excluída (`account_in_use`). `AccountOut` agora traz `institution`, `balance_cents`, `pockets_cents`, `available_cents` (em lista, criar, editar e detalhe).
- Migração única `d1e2f3a4b5c6` (head); o `scripts/migrate_check.sh` foi reproduzido manualmente (upgrade head + `alembic check` + downgrade), porque o compose do worktree não tem `.env`.

## Decisões (parcelas históricas)
- Baixa histórica = `bills.settled_historical_at` (timestamptz, migração `b8c9d0e1f2a3`). A parcela fica `status='paid'` sem lançamento; `refresh_status` a mantém `paid`. Como todo consumidor (contas abertas, lembretes, digest, upcoming, chat) já filtra por `status != 'paid'`, ela some de todos sem mudança; `bill_paid_cents` continua somando só lançamentos (não entra em dinheiro pago/relatórios). `pay_bill` recusa baixa histórica (422 `bill_already_paid`). LoanOut conta como paga (`paid_count` = status paid).
- `POST /spaces/{sid}/loans` aceita `paid_installments` (0..total; fora disso 422) e cria as parcelas 1..N como baixa histórica em lote (um flush). `ensure_installments` agora mantém geradas as 3 **primeiras não pagas** por número (percorre 1..total, pula pagas), então funciona com baixas esparsas (ex. #200 de 360) sem preencher o vão.
- `GET /loans/{id}/installments` lista 1..N (calculadas se não geradas) com `state` open|paid_history|paid_real (parcial = open). Financiamento cancelado lista só as existentes.
- `POST|DELETE /loans/{id}/installments/{n}/settle`: idempotentes; materializam se preciso; auditam `loan.installment_settle/unsettle` (só na mudança real). Pagamento real/parcial: 409 `installment_paid_real` / `installment_partial`. n fora de 1..total: 422 `invalid_installment`; financiamento cancelado: 422 `loan_canceled`.
- `POST /loans/{id}/installments/{n}/materialize` (extra, escolha minha): gera a parcela aberta e devolve a conta; o web a usa antes de `POST /bills/{id}/payments` em "Paguei agora".
- Permissão: igual ao PATCH (`visible_loan`: membro do espaço; não-membro 404). Não existe papel "só leitura" no espaço, então não há 403 nesses endpoints.
- Desfazer pagamento real: excluir o lançamento (já reabre a parcela); a UI explica.
- LGPD: export/delete são genéricos por colunas do model, então cobrem o campo novo (teste de export).
- Web: `Ver parcelas` (lista com "mostrar mais" de 24 em 24 até 480, "Ir para a próxima em aberto" e "Ir para a parcela nº"), checkbox com rótulo completo, ícone+texto por estado. Verificado com vite preview + Playwright (API simulada, desktop/celular); o escuro não foi capturado de verdade (tema do app não segue `prefers-color-scheme` no emulador).
