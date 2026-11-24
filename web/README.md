# Abby Cash — web (PWA)

React + TypeScript + Vite, TanStack Router/Query, Tailwind, Recharts, vite-plugin-pwa. Textos em pt-BR; dinheiro sempre em centavos (`formatBRL`).

```bash
npm ci
npm run dev            # proxy da API em http://localhost:8000 (API_URL para mudar); o cookie de refresh exige mesma origem
npm run lint && npm run typecheck && npm test && npm run build
```

## Cliente da API
`src/api/schema.d.ts` é gerado do OpenAPI do FastAPI (as respostas do backend não são tipadas, ver `src/api/types.ts`):

```bash
cd backend && uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json
cd ../web && npm run gen:api     # OPENAPI=/caminho.json para outro arquivo
```

O token de acesso fica só em memória; o refresh usa o cookie httpOnly (`/auth/refresh`).

## E2E (Playwright)
Usa o Postgres/Redis de dev (`docker compose -f infra/docker-compose.dev.yml up -d postgres redis`), cria um banco descartável, sobe a API e o Vite em portas livres e roda `e2e/flows.spec.ts` (cadastro com convite → login → painel; onboarding).

```bash
npx playwright install chromium-headless-shell   # uma vez
bash e2e/run.sh
```

## PWA
Manifest e service worker gerados no `npm run build` (instalável; a API nunca é cacheada). Em produção, o Nginx deve servir web e API na mesma origem.
