import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeRouter } from '../router'

const SP = 's1'
const J = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const T = (o: Record<string, number>) => ({ income_cents: 0, expense_cents: 0, net_cents: 0, tx_count: 0, avg_daily_expense_cents: 0, ...o })
let overview: () => Response
let calls: string[] = []
let csv = ''
let bom = false
let history: ReturnType<typeof createMemoryHistory>

const full = () => J({
  totals: T({ income_cents: 500000, expense_cents: 150000, net_cents: 350000, tx_count: 4, avg_daily_expense_cents: 5000 }),
  previous: T({ income_cents: 500000, expense_cents: 100000, net_cents: 400000, avg_daily_expense_cents: 0 }),
  by_category: [{ category_id: 'c1', name: 'Mercado', expense_cents: 100000, count: 2, share_bp: 6667 }, { category_id: null, name: 'Sem categoria', expense_cents: 50000, count: 1, share_bp: 3333 }],
  by_merchant: [{ merchant: 'Padaria', expense_cents: 40000, count: 2 }, { merchant: 'Sem estabelecimento', expense_cents: 10000, count: 1 }],
  by_account: [{ account_id: 'a1', name: 'Nubank', income_cents: 500000, expense_cents: 150000 }],
  by_day: [{ date: '2026-11-02', income_cents: 0, expense_cents: 150000 }],
  by_month: [{ month: '2026-10', income_cents: 1, expense_cents: 2, net_cents: -1 }, { month: '2026-11', income_cents: 500000, expense_cents: 150000, net_cents: 350000 }],
  by_weekday: [{ dow: 0, expense_cents: 150000, count: 3 }],
  largest: [{ id: 't1', occurred_on: '2026-11-02', description: 'Geladeira', merchant: null, category_id: 'c1', amount_cents: 90000, type: 'expense' }],
  balance_series: [{ month: '2026-11', balance_cents: 777700 }],
  upcoming: [{ kind: 'bill', id: 'b1', description: 'Aluguel', due_on: '2026-12-05', amount_cents: 150000 }],
})

function go(path: string) {
  calls = []
  vi.stubGlobal('fetch', async (url: string) => {
    calls.push(url)
    if (url === '/auth/refresh') return J({ access_token: 't' })
    if (url === '/spaces') return J([{ id: SP, type: 'personal', name: 'x' }])
    if (url === '/me') return J({ id: 'u1', name: 'Ana', email: 'a@x.com', is_admin: false })
    if (url === '/accounts') return J([{ id: 'a1', space_id: SP, type: 'checking', name: 'Nubank' }])
    if (url === `/spaces/${SP}/categories`) return J([{ id: 'c1', space_id: SP, kind: 'expense', name: 'Mercado' }])
    if (url.includes('/reports/overview')) return overview()
    if (url.includes('/transactions?')) return J([
      { id: 't1', space_id: SP, type: 'expense', amount_cents: 123456, occurred_on: '2026-11-20', description: '=SOMA(1)', merchant: 'Padaria', category_id: 'c1' },
      { id: 't2', space_id: SP, type: 'income', amount_cents: 500000, occurred_on: '2026-11-05', description: 'Salário', merchant: null, category_id: null },
    ])
    return J({ detail: 'x' }, 404)
  })
  history = createMemoryHistory({ initialEntries: [path] })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={makeRouter(history)} /></QueryClientProvider>)
}
const overviewUrl = () => calls.filter((u) => u.includes('/reports/overview')).at(-1)!

beforeEach(() => {
  overview = full
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 10, 24, 12) })
  csv = ''
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => { void b.arrayBuffer().then((a) => { const u = new Uint8Array(a); bom = u[0] === 0xef && u[1] === 0xbb && u[2] === 0xbf; csv = new TextDecoder('utf-8', { ignoreBOM: true }).decode(u).slice(1) }); return 'blob:x' }, revokeObjectURL: () => {} }))
  HTMLAnchorElement.prototype.click = () => {}
})
afterEach(() => vi.useRealTimers())

test('filtros da URL viram a querystring e a lista usa a mesma janela', async () => {
  go('/analises?per=custom&start=2026-11-01&end=2026-11-15&type=expense&category_id=none&merchant=Padaria')
  await screen.findByText('Evolução em 12 meses')
  expect(overviewUrl()).toBe(`/spaces/${SP}/reports/overview?start=2026-11-01&end=2026-11-15&category_id=none&type=expense&merchant=Padaria`)
  await waitFor(() => expect(calls.some((u) => u.startsWith(`/spaces/${SP}/transactions?start=2026-11-01&end=2026-11-15`) && u.endsWith('&limit=1000'))).toBe(true))
})

test('padrão é este mês; URL inválida é normalizada', async () => {
  go('/analises?per=lixo&type=x')
  await screen.findByText('Evolução em 12 meses')
  expect(overviewUrl()).toBe(`/spaces/${SP}/reports/overview?start=2026-11-01&end=2026-11-30`)
  expect(screen.getByRole('button', { name: 'Este mês', pressed: true })).toBeInTheDocument()
})

test('período rápido e clique em categoria viram filtro (chip + URL + refetch)', async () => {
  go('/analises')
  await userEvent.click(await screen.findByRole('button', { name: '30 dias' }))
  await waitFor(() => expect(overviewUrl()).toContain('start=2026-10-26&end=2026-11-24'))
  await userEvent.click(await screen.findByRole('button', { name: /Filtrar por Mercado/ }))
  await waitFor(() => expect(overviewUrl()).toContain('category_id=c1'))
  expect(history.location.search).toContain('category_id')
  expect(screen.getByRole('button', { name: 'Remover filtro Categoria: Mercado' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Remover filtro Categoria: Mercado' }))
  await waitFor(() => expect(overviewUrl()).not.toContain('category_id'))
  await userEvent.click(screen.getByRole('button', { name: /Filtrar por Padaria/ }))
  await waitFor(() => expect(overviewUrl()).toContain('merchant=Padaria'))
  await userEvent.click(await screen.findByRole('button', { name: 'Limpar filtros' }))
  await waitFor(() => expect(overviewUrl()).not.toContain('merchant'))
})

test('KPIs e variação em inteiros; divisão por zero vira "—"', async () => {
  go('/analises')
  const kpis = await screen.findByRole('region', { name: 'Resumo do período' })
  expect(within(kpis).getByLabelText('R$ 5.000,00')).toBeInTheDocument()
  expect(within(kpis).getByText('+50%', { exact: false })).toBeInTheDocument() // despesas 1000 -> 1500
  expect(within(kpis).getByText('0%')).toBeInTheDocument() // receitas iguais
  expect(within(kpis).getByText('-13%', { exact: false })).toBeInTheDocument() // saldo 4000 -> 3500
  expect(within(kpis).getByLabelText('Sem período anterior para comparar')).toBeInTheDocument() // média: prev 0
})

test('tabela dos 12 meses: clicar em um mês filtra o mês', async () => {
  go('/analises')
  await userEvent.click(await screen.findByRole('button', { name: 'Filtrar out/26' }))
  await waitFor(() => expect(overviewUrl()).toContain('start=2026-10-01&end=2026-10-31'))
})

test('exporta CSV do filtro com BOM, ; e proteção de fórmula', async () => {
  go('/analises')
  await userEvent.click(await screen.findByRole('button', { name: 'Exportar CSV' }))
  await waitFor(() => expect(csv).not.toBe(''))
  expect(bom).toBe(true)
  expect(csv.startsWith('Data;Tipo')).toBe(true)
  expect(csv).toContain("20/11/2026;Despesa;'=SOMA(1);Padaria;Mercado;-1234,56")
  expect(csv).toContain('05/11/2026;Receita;Salário;;Sem categoria;5000,00')
})

test('detalhe: busca, total do filtro e ordenação', async () => {
  go('/analises')
  await screen.findByText(/2 lançamentos/)
  await userEvent.type(screen.getByLabelText('Buscar'), 'salár')
  expect(await screen.findByText(/1 lançamento ·/)).toHaveTextContent('R$ 5.000,00')
})

test('estado vazio oferece ampliar para 12 meses', async () => {
  overview = () => J({ ...(JSON.parse(JSON.stringify({})) as object), totals: T({}), previous: T({}), by_category: [], by_merchant: [], by_account: [], by_day: [], by_month: [], by_weekday: [], largest: [], balance_series: [], upcoming: [] })
  go('/analises')
  expect(await screen.findByText('Nenhum lançamento neste período')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Ampliar para 12 meses' }))
  await waitFor(() => expect(overviewUrl()).toContain('start=2025-12-01&end=2026-11-24'))
})

test('estado de erro com tentar novamente', async () => {
  overview = () => J({ detail: 'invalid_range' }, 422)
  go('/analises')
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  overview = full
  await userEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }))
  expect(await screen.findByText('Evolução em 12 meses')).toBeInTheDocument()
})

test('menu tem Análises', async () => {
  go('/analises')
  expect(await screen.findByRole('link', { name: /Análises/ })).toHaveAttribute('href', '/analises')
})
