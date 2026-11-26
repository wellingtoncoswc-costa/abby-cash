# Projeções (painel) e financiamentos na projeção

## Objetivo
Cada mês projetado soma TUDO que se espera entrar e sair: fixos, parcelas de financiamentos/consórcios, faturas de cartão, contas a pagar em aberto e uma estimativa dos gastos/receitas variáveis. Painel "Projeções" com histórico + projeção.

## Regras do mês projetado
- Janela: mês corrente + (N-1) seguintes, N = 6 ou 12. No mês corrente só entra o que vence depois de hoje; o que já venceu e segue em aberto (parcela, conta, fatura) cai no mês corrente.
- **Fixos** (receita/despesa): datas depois de hoje (`recurring.occurrences`).
- **Financiamentos/consórcios**: parcelas não pagas (`list_installments`, estado `open`) de financiamentos não cancelados.
- **Faturas**: restante de cada fatura em aberto (`invoice_remaining`) no mês do vencimento.
- **Contas a pagar**: contas manuais em aberto (sem `loan_id`, sem baixa histórica) pelo restante; se houver fixo com mesma descrição (sem diferenciar maiúsculas) e mesmo valor no mesmo mês, vale o fixo.
- **Estimativa de variáveis**: média dos 3 meses completos anteriores de despesas à vista (sem cartão, sem conta a pagar, origem != recurring) e de receitas (sem cartão, origem != recurring); no mês corrente proporcional aos dias restantes.
- Saldo projetado = saldo atual das contas + resultado acumulado; também a versão só com compromissos (sem estimativa).
- Comprometimento (bp) = (fixos + parcelas + faturas + contas) / (receita fixa) por mês; nulo sem receita fixa.

## Histórico
Últimos 12 meses reais (receitas/despesas pela mesma regra de Análises, cartão pelo vencimento) e saldo ao fim de cada mês.

## API
`GET /spaces/{id}/projections?months=6|12` (qualquer membro; só leitura; sem Nginx novo). A projeção de Fixos (`/recurring/projection`) passa a incluir parcelas de financiamentos/consórcios.

## Web
Página "Projeções" (`/projecoes`): colunas de resultado histórico+projetado, linha de saldo (real, projetado e só compromissos), rosca da composição, comprometimento da renda por mês, fim dos financiamentos, quadro de médias, chave "mostrar estimativa", seletor 6/12 meses.

## Fora de escopo
Cenários "e se", receita/despesa recorrente de contas a pagar além do que já foi gerado (hoje 3 meses à frente).
