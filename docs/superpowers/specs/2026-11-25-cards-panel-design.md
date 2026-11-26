# Cartões em cards com painel (fase 1)

## Objetivo
Cada cartão vira um card com resumo, ações (nova compra, cadastrar fatura) e painel de gastos. Padrão a ser repetido nas outras telas em fases seguintes (contas, caixinhas, metas, financiamentos, investimentos), cada uma com spec própria.

## Tela
Formulário "Novo cartão" e, abaixo, um card por cartão (grade no desktop, 1 coluna no celular). Card: cabeçalho (nome, fecha/vence, editar/excluir só dono), resumo (fatura atual com valor/vencimento/status; limite usado e disponível quando há limite), ações "Nova compra" e "Cadastrar fatura", painel expansível (gastos por categoria da fatura escolhida, últimas 6 faturas em colunas clicáveis, 5 maiores compras) e lista de faturas (abrir, pagar, marcar como paga, desfazer — como hoje).

## Backend
- `GET /cards/{id}/panel?invoice=<id>`: só leitura. Fatura escolhida (padrão: a primeira com fechamento >= hoje, senão a mais recente), `limit_cents`, `used_cents` (soma do restante das faturas não pagas), `available_cents` (null sem limite), `by_category` e `top` a partir do extrato da fatura (itens de outros espaços entram só em `private_total_cents`), `history` (6 últimas faturas, mais antiga primeiro).
- `POST /cards/{id}/invoice-totals {month: "YYYY-MM" (mês de fechamento), total_cents}`: cria uma compra única "Fatura MM/AAAA" no dia do fechamento daquela fatura (compra no dia do fechamento cai na fatura que fecha), sem categoria. Sem tabela nova. Devolve a fatura.
- "Nova compra" usa `POST /spaces/{id}/card-purchases` existente.

## Testes
Painel (limite, categorias, ordem do histórico, fatura padrão, privacidade, fatura de outro cartão = 404), fatura pelo total caindo na fatura certa (incl. fechamento em mês curto) e somando ao existente, web (um card por cartão, painel, nova compra, cadastrar fatura).

## Fora de escopo
Comparação entre cartões, alertas de limite, exportação, outras telas.
