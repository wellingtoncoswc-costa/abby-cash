import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeRouter } from '../router'

const SP = 's1'
const J = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const routes: Record<string, (init: RequestInit) => Response> = {
  '/auth/refresh': () => J({ access_token: 't' }),
  '/spaces': () => J([{ id: SP, type: 'personal', name: 'x' }]),
  '/accounts': () => J([{ id: 'a1', space_id: SP, type: 'checking', name: 'Nubank', initial_balance_cents: 100000 }]),
  [`/spaces/${SP}/bills`]: () => J([{ id: 'b1', space_id: SP, kind: 'bill', description: 'Aluguel', amount_cents: 150000, due_on: '2026-12-05', status: 'open', invoice_id: null }]),
  [`/spaces/${SP}/goals`]: () => J([]),
  '/channels': () => J([]),
  '/channels/link-code': () => J({ code: '123456', expires_in_s: 600, deep_link: 'https://t.me/abby_bot?start=123456' }),
}
let calls: [string, RequestInit][] = []

function go(path: string) {
  calls = []
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    calls.push([url, init])
    const key = Object.keys(routes).find((k) => url === k || url.startsWith(`${k}?`))
    if (key) return routes[key](init)
    if (url.includes('/budgets/')) return J({ detail: 'budget_not_found' }, 404)
    if (url.includes('/transactions')) return J([{ id: 't1', space_id: SP, type: 'expense', amount_cents: 123456, occurred_on: '2026-11-20', description: 'Mercado', merchant: null, category_id: null, account_id: 'a1' }])
    return J({ detail: 'x' }, 404)
  })
  const router = makeRouter(createMemoryHistory({ initialEntries: [path] }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={router} /></QueryClientProvider>)
}

test('painel mostra valores em R$ e pede teto', async () => {
  go('/')
  expect(await screen.findByText('Sem teto definido.', { exact: false })).toBeInTheDocument()
  expect((await screen.findAllByText('-R$ 1.234,56')).length).toBeGreaterThan(0)
  expect(screen.getByLabelText('Espaço')).toHaveDisplayValue('Pessoal')
})

test('pagar conta exige conta de origem', async () => {
  go('/contas')
  await userEvent.click(await screen.findByRole('button', { name: 'Pagar' }))
  const confirm = screen.getByRole('button', { name: 'Confirmar pagamento' })
  expect(confirm).toBeDisabled()
  await userEvent.selectOptions(screen.getByLabelText('Pagar com a conta'), 'a1')
  expect(confirm).toBeEnabled()
  await userEvent.click(confirm)
  const post = calls.find(([u]) => u === '/bills/b1/payments')!
  expect(JSON.parse(post[1].body as string).account_id).toBe('a1')
})

test('onboarding mostra código e link t.me', async () => {
  go('/onboarding')
  await userEvent.click(await screen.findByRole('button', { name: 'Vincular Telegram' }))
  const box = await screen.findByRole('status')
  expect(within(box).getByText('123456')).toBeInTheDocument()
  expect(within(box).getByRole('link')).toHaveAttribute('href', 'https://t.me/abby_bot?start=123456')
})
