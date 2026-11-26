# Contas em cards com painel (fase 2)

## Objetivo
Página "Contas bancárias" (rota `/contas-bancarias`; `/contas` já é contas a pagar) com um card por conta, no mesmo padrão dos cartões (fase 1).

## Tela
Formulário "Nova conta" (tipo, nome, banco, saldo inicial) e, abaixo, um card por conta (grade, 1 coluna no celular). Card: ícone do banco, nome, tipo, selo "padrão"; resumo (saldo, guardado em caixinhas, disponível); ações "Transferir" (leva a `/lancamentos`, onde a transferência já existe), "Tornar padrão", editar/excluir só dono (EditBox existente); "Ver painel": seletor de mês, entradas, saídas, saldo líquido de transferências, gastos por categoria, 10 últimas movimentações, caixinhas da conta (saldo de cada) e metas ligadas.

## Backend
`GET /accounts/{id}/panel?month=YYYY-MM` (padrão: mês atual no fuso do usuário), só leitura, sem tabela nova: reaproveita `account_statement` (privacidade: itens de espaços de que o usuário não é membro viram `private_total_cents`), caixinhas abertas da conta com `pocket_stats`, metas ligadas à conta ou às caixinhas dela (só de espaços do visualizador) e `is_default` (conta padrão do usuário no espaço da conta). Entradas = receitas, saídas = despesas, transferências à parte (`transfer_net_cents`).

## Fora de escopo
Evolução do saldo, comparação entre contas, exportação; "Primeiros passos" não muda; sem mudança no Nginx (`/accounts` já liberado).
