# Plano M7 — Web PWA (resumo)

Stack: React + TS, TanStack Router (rotas por código) + Query, Tailwind v4, Recharts, vite-plugin-pwa, Vitest/Testing Library, Playwright.
Tipos: `web/src/api/schema.d.ts` gerado do OpenAPI do FastAPI (`npm run gen:api`, ver README); respostas do backend são `object` sem schema, então os modelos de leitura ficam em `src/api/types.ts` (centavos sempre `number` inteiro).

## Decisões
- Token de acesso só em memória (`src/api/client.ts`); refresh via cookie httpOnly `/auth/refresh` (single-flight); 401 → refresh uma vez → repete; falha → logout.
- Mesma origem: o dev server do Vite faz proxy dos caminhos da API (cookie tem `path=/auth`); em produção o Nginx serve web + API no mesmo host.
- Dinheiro: `formatBRL(cents)` e `parseBRL(text)` (sem float) em `src/lib/money.ts`.
- Sem `dangerouslySetInnerHTML`; todo texto passa pelo React. Tema claro/escuro (classe `dark`, padrão do sistema).
- Fatia vertical primeiro (T7.1 + painel + lançamentos), depois o resto.

## Tarefas
- T7.1 cliente, auth (login/2FA/cadastro com convite), layout, seletor de espaço, PWA.
- T7.2 onboarding (contas, cartão, teto, vínculo de canal com código e link t.me).
- T7.3 painel do mês. T7.4 lançamentos (lista, filtros, criar).
- T7.5 contas a pagar, cartões e faturas (origem obrigatória, pagamento parcial, privados).
- T7.6 teto e metas (aportes/retiradas). T7.7 espaços/convites, canais, configurações, privacidade.
- Testes: Vitest (money, client, páginas com fetch mockado); Playwright `e2e/` contra backend local.

## Lacunas de API
- Sem rotas de categorias (listar/CRUD): painel e lançamentos mostram "Categoria #xxxx"; filtro por categoria só aceita id; tela de categorias não existe.
- Sem `GET /me` nem `PATCH` de configurações (fuso, horário dos lembretes, canal preferido, resumo semanal): tela de configurações é somente informativa/desabilitada.
- Sem editar/excluir lançamento, nem anexos, nem filtro por cartão/autor na listagem.
- Sem listar membros de um espaço nem alterar papéis (só convidar e remover por id).
- Sem editar/excluir contas, cartões, contas a pagar, metas; sem listar faturas de todos os cartões (por cartão, sim).
- Código de convite de plataforma (cadastro) não tem rota de criação; o convite de espaço (`/invite/{token}`) é aceito após login.
- Cookie de refresh é `Secure`: em dev só funciona em `localhost` (ou HTTPS).

## Não feito / pendências
Atualizado ao final do marco (ver relatório).
