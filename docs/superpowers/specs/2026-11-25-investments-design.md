# Investimentos

## Objetivo
Nova seção para cadastrar ativos (ações, FIIs, CDB, LCI, LCA), registrar aportes/resgates, acompanhar preço do dia e rentabilidade em um dashboard.

## Modelo (centavos `BIGINT`, `space_id` em tudo)
- `investments`: `id`, `space_id`, `kind` (`stock|fii|cdb|lci|lca`), `name`, `ticker` (só stock/fii), `rate_type` (`cdi_pct|fixed`) + `rate_bp` (só renda fixa), `maturity_on` (opcional), `closed_at`.
- `investment_movements`: `investment_id`, `kind` (`buy|redeem`), `occurred_on`, `quantity` (decimal, só renda variável), `unit_price_cents` (preço da data, guardado), `amount_cents`, `account_id`, `transaction_id`, `origin`, `source_message_id`.
- `price_quotes(ticker, on_date, close_cents)`: fechamento diário; PK (ticker, on_date). Base da evolução e das comparações.

## Cotação (brapi.dev)
- `investments/quotes.py` no estilo de `pockets/cdi.py`: `httpx` sem redirect, token `BRAPI_TOKEN`, resposta validada com pydantic.
- Job diário (ARQ) grava o fechamento de todos os tickers ativos (idempotente); cadastro de ativo novo busca na hora.
- Falha da brapi: mantém o último preço e a tela mostra a data dele. Ticker inexistente: 422 `unknown_ticker`.
- Aporte: preço preenchido com o fechamento da data, editável; valor = quantidade × preço.

## Renda fixa
Valor calculado, não cotado, bruto (sem IR/IOF). `cdi_pct`: rende `CDI diário × %` usando `cdi_rates`. `fixed`: `(1+taxa)^(dias/252)` ao ano. Aporte é valor em R$.

## Aporte e resgate
`buy` exige conta de origem (`use_account`) e gera transferência (sem categoria, fora do teto); `redeem` inverso, limitado à posição. Padrão de `goals.contribute/withdraw`. Tudo via `require_member`.

## API / web
- `/investments` (CRUD), `/investments/{id}/movements`, `/investments/dashboard`.
- Menu "Investimentos": lista, formulário de ativo/aporte e dashboard (cards investido/atual/lucro R$ e %, linha valor da carteira vs aportado, rosca por tipo, tabela por ativo: quantidade, preço médio, preço atual, variação do dia, rentabilidade). Gráficos conforme skill `dataviz`.

## Fora do escopo
Proventos, IR/IOF, IPCA+, comparação com CDI/Ibovespa, alertas de preço, chat do assistente.

## Testes
Cliente brapi com transporte mockado, cálculo de renda fixa com valores conhecidos, aporte/resgate (saldo, limite da posição, conta alheia), idempotência do job, dashboard agregado, componentes web.
