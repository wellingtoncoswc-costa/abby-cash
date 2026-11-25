# Análises: dashboards interativos com visão detalhada

Objetivo (dono, 2026-11-24): "dashboards interativos que dão visão detalhada dos dados lançados". Nova área **Análises** no web, alimentada por
agregações no servidor (centavos int, nunca float; `require_member`; espaço pessoal privado; lançamentos de outros espaços nunca entram).

## Contabilidade (igual ao Painel/teto — reutilizar o mesmo código, não reimplementar)
- Despesa e receita: `type` expense/income. **Transferências** (pagamento de fatura, aporte/resgate de meta, transferência entre contas) NÃO contam.
- Compra no cartão conta na data de **vencimento da fatura** (a mesma regra de `domain/budgets`): use a função/consulta existente de "data efetiva" e
  filtre/agrupe por ela, para que o total do mês bata com `spent_cents` do teto. Teste obrigatório: `expense_cents` do mês == `spent_cents` do `/budgets/{mês}`.
- Rendimento de caixinha é receita "Rendimentos" (já é um lançamento `income`).

## API (um endpoint de visão geral + o que já existe para o detalhe)
`GET /spaces/{sid}/reports/overview?start=YYYY-MM-DD&end=YYYY-MM-DD[&account_id=][&category_id=][&card_id=][&merchant=][&type=expense|income]`
(`start<=end`, janela máxima 3660 dias, senão 422 `invalid_range`; filtros opcionais combináveis; `category_id=none` = sem categoria).
Resposta `OverviewOut` (tudo em centavos int; datas ISO):
- `totals {income_cents, expense_cents, net_cents, tx_count, avg_daily_expense_cents}` e `previous` (mesma forma, período anterior de igual duração imediatamente antes de `start`).
- `by_category [{category_id|null, name, expense_cents, count, share_bp}]` (despesa; `share_bp` = parte do total em pontos-base, soma ≈ 10000; ordenado desc; categorias sem gasto fora).
- `by_merchant [{merchant, expense_cents, count}]` (top 10; merchant vazio agrupado como "Sem estabelecimento").
- `by_account [{account_id|null, name, income_cents, expense_cents}]` (null = cartão/sem conta, nome "Cartão de crédito"/"Sem conta").
- `by_day [{date, income_cents, expense_cents}]` (só dias com movimento; data efetiva).
- `by_month [{month 'YYYY-MM', income_cents, expense_cents, net_cents}]`: **12 meses terminando no mês de `end`**, ignorando `start` (para o gráfico de evolução), respeitando os demais filtros.
- `by_weekday [{dow 0..6 (0=segunda), expense_cents, count}]`.
- `largest [{id, occurred_on, description, merchant, category_id|null, amount_cents, type}]` (5 maiores despesas do período).
- `balance_series [{month, balance_cents}]`: saldo total das contas do espaço ao fim de cada um dos mesmos 12 meses (saldo inicial + lançamentos até o fim do mês; sem filtros de categoria/estabelecimento).
- `upcoming [{kind bill|invoice, id, description, due_on, amount_cents}]`: contas a pagar e faturas em aberto com vencimento nos próximos 30 dias a partir de hoje (independe do período).
- Detalhe/drill-down: o web usa `GET /spaces/{sid}/transactions` existente; se ele não aceitar `category_id`, `account_id`, `merchant`, `type` e `start/end` combinados, ESTENDA-o de forma retrocompatível (e `limit` até 1000) e teste.
Performance: consultas agregadas em SQL (GROUP BY), nada de carregar todos os lançamentos em Python; índices existentes bastam, mas confira o plano de execução com ~50 mil lançamentos num teste/seed local e registre o resultado.
Segurança/privacidade: só lançamentos do espaço `{sid}` (membro obrigatório; não-membro 404 como nos outros routers); em espaço compartilhado vale a regra existente (lançamentos #pessoal não pertencem ao espaço compartilhado, então não aparecem). Rate limit como os demais GETs pesados se houver padrão.
Testes obrigatórios: paridade com `spent_cents`; transferência não conta; cartão por vencimento da fatura; período anterior; filtros combinados; `category_id=none`; 12 meses com buracos; janela inválida; não-membro 404; isolamento entre espaços; `balance_series` bate com o saldo atual no último mês; valores grandes (10**12) sem overflow/float.

## Web (`/analises`, item "Análises" no menu, ícone lucide ChartNoAxesCombined ou similar)
Design: identidade Vidro/Luz (docs/design), só tokens; Recharts já instalado; cores de série por `--chart-1..5` (categoria mantém a mesma cor em todos os gráficos); animações só em resposta a dados/ação; `prefers-reduced-motion` respeitado; responsivo (celular em coluna, filtros em chips roláveis).
- Barra de filtros: períodos rápidos (Este mês, Mês passado, 30 dias, 3 meses, 12 meses, Personalizado com 2 `input type=date`), conta, categoria, tipo; **estado na URL** (search params) para compartilhar/voltar; "Limpar filtros".
- Faixa de KPIs: Receitas, Despesas, Saldo do período, Média diária de gasto, cada um com variação % vs período anterior (seta e cor semântica: despesa maior = atenção, não vermelho agressivo).
- Gráficos (todos clicáveis = filtro cruzado): evolução 12 meses (barras receita × despesa + linha do saldo; clicar um mês seleciona o mês); gastos por categoria (rosca + barras horizontais ordenadas; clicar filtra por categoria); gasto por dia (área; clicar um dia filtra o dia); por dia da semana; top estabelecimentos (clicar filtra); por conta; evolução do saldo; próximos vencimentos; maiores lançamentos.
- Lista de lançamentos filtrada ("Detalhe"): busca por texto, ordenação por data/valor, total do filtro, abrir/editar reaproveitando o que existir em `pages/transactions.tsx`, **exportar CSV** (cliente, UTF-8 com BOM, `;` e vírgula decimal, centavos formatados sem float).
- Estados: carregando (esqueleto), vazio ("Nenhum lançamento neste período" com atalho para ampliar), erro.
- Chips dos filtros ativos removíveis; ao clicar num elemento do gráfico mostrar feedback imediato (chip aparece).
Tipos à mão até o backend ser mesclado (`OverviewOut` conforme acima); depois `npm run gen:api`.

## Decisões (backend)
- Data efetiva única: `EFFECTIVE_ON` em `domain/budgets/service.py` (cartão = `Invoice.due_on`, resto = `occurred_on`); `month_spending` foi reescrito sobre ela (uma consulta, mesmos testes verdes) e o overview/lista a reutilizam, então o total do mês bate com `spent_cents`.
- `GET /transactions` ganhou, de forma retrocompatível: `type`, `merchant` (rótulo; vazio = "Sem estabelecimento"), `uncategorized=true` (sem categoria), `effective=true` (start/end/ordem por data efetiva, para o drill-down bater com os gráficos; padrão segue `occurred_on`) e `limit` até 1000. `category_id=none` existe só no overview.
- `by_account`: conta nula vira duas linhas distintas ("Cartão de crédito" para compras de cartão, "Sem conta" para o resto); filtro `account_id` casa `account_id` ou `counter_account_id` (como a lista) e por isso exclui compras de cartão.
- `largest[].occurred_on` é a data real do lançamento (não a efetiva); `by_day` usa a data efetiva.
- `merchant` agrupa pelo texto exato (trim), sem normalização de caixa/acentos.
- `share_bp` = `v*10000 // total` (divisão inteira; soma pode ficar até alguns bp abaixo de 10000). `avg_daily_expense_cents` = despesa // dias do período (inclusivo).
- `balance_series`: soma dos saldos iniciais das contas do espaço + efeito por mês agrupado no SQL (receita +, despesa −, transferência − na origem e + no destino); inclui lançamentos futuros até o fim de cada mês. Ignora filtros.
- `upcoming`: contas `open|partial` do espaço (inclui espelho de fatura, `kind=invoice`) com vencimento em [hoje, hoje+30] no fuso do usuário; valor = restante (valor − pago).
- Janela máxima: `end-start >= 3660` dias ou `start>end` -> 422 `invalid_range`. Sem rate limit (não há padrão para GETs). Sem índice novo.
- Performance (50 mil lançamentos num único espaço, DB de teste): overview completo 0,30 s (1 mês) / 0,38 s (33 meses); a consulta base faz seq scan (16 ms por agregação) porque a data efetiva não é sargável; aceitável, revisar (índice por `space_id,occurred_on` + prefiltro) só se passar de ~200 mil lançamentos.
