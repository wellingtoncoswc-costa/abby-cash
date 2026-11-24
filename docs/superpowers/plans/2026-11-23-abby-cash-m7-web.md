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
Resolvidas no backend e usadas na web: categorias (CRUD), `GET /me` + `PATCH /me/settings`, editar/excluir lançamento/conta/cartão/conta a pagar/meta, filtros cartão/autor + `X-Total-Count`, listar/sair/remover membros, `POST /admin/signup-invites`, `GET /attachments/{id}`, response models no OpenAPI.
Restam:
- Sem alterar papéis de membros; sem listar faturas de todos os cartões (só por cartão); sem upload de anexo pela web (o comprovante vem do WhatsApp/Telegram).
- `POST card-purchases` não devolve mensagem de impacto: a web calcula "Nx de R$ …, em N fatura(s)" a partir das parcelas devolvidas.
- Cookie de refresh é `Secure`: em dev só funciona em `localhost` (ou HTTPS).
- Nginx de produção precisa encaminhar as rotas novas (`/me`, `/categories`, `/transactions`, `/attachments`, `/admin`).

## Não feito / pendências
- Limites por categoria no teto (a API aceita, a tela só preserva os existentes); papéis de membros.
- Teste de ícones/instalação do PWA só verificado pelo build (manifest + sw gerados), não em dispositivo.
- Recibo (imagem) e página Admin cobertos só por Vitest/pytest, não por Playwright.
