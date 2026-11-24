import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeRouter } from '../router'

const J = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const acc = (id: string, name: string, space: string, bal: number, pockets = 0) => ({ id, space_id: space, type: 'checking', name, initial_balance_cents: 0, institution: null, balance_cents: bal, pockets_cents: pockets, available_cents: bal - pockets })
const TX = { id: 't1', space_id: 's1', type: 'transfer', amount_cents: 30000, occurred_on: '2026-11-20', description: '', merchant: null, category_id: null, account_id: 'a1', counter_account_id: 'a2', installment_total: null }
let calls: [string, RequestInit][] = []

function go(path: string, accounts: unknown[], spaces: unknown[] = [{ id: 's1', type: 'personal', name: 'x' }], reply: (u: string, i: RequestInit) => Response | null = () => null) {
  calls = []
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    calls.push([url, init])
    const r = reply(url, init)
    if (r) return r
    if (url === '/auth/refresh') return J({ access_token: 't' })
    if (url === '/spaces') return J(spaces)
    if (url === '/accounts') return J(accounts)
    if (url === '/me') return J({ id: 'u1', name: 'Ana', email: 'a@x.com', tz: 'America/Sao_Paulo', default_space_id: 's1', preferred_channel: null, reminder_time: '09:00:00', weekly_digest: false, is_admin: false, totp_enabled: false })
    if (url.includes('/categories') || url.includes('/members') || url === '/cards' || url.includes('/budgets') || url.includes('/bills') || url.includes('/goals')) return J(url.includes('/budgets') ? { detail: 'budget_not_found' } : [], url.includes('/budgets') ? 404 : 200)
    if (url.includes('/transactions')) return J([TX])
    return J({ detail: 'x' }, 404)
  })
  const router = makeRouter(createMemoryHistory({ initialEntries: [path] }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={router} /></QueryClientProvider>)
}
afterEach(cleanup)

test('transferir: destino exclui a origem, mostra disponível, envia no espaço da origem e confirma', async () => {
  const accounts = [acc('a1', 'Nubank', 's1', 100000), acc('a2', 'Itaú', 's1', 5000), acc('a3', 'Conjunta', 's2', 0)]
  const spaces = [{ id: 's1', type: 'personal', name: 'x' }, { id: 's2', type: 'family', name: 'Casa' }]
  go('/lancamentos', accounts, spaces, (u, i) => (u === '/spaces/s1/transactions' && i.method === 'POST' ? J({ ...TX }, 201) : null))
  await userEvent.selectOptions(await screen.findByLabelText('Conta de origem'), 'a1')
  expect(screen.getByText('Disponível na origem: R$ 1.000,00')).toBeInTheDocument()
  const dest = screen.getByLabelText('Conta de destino')
  expect(Array.from(dest.querySelectorAll('option')).map((o) => o.textContent)).toEqual(['Selecione…', 'Itaú · Pessoal', 'Conjunta · Família · Casa'])
  await userEvent.selectOptions(dest, 'a3')
  await userEvent.type(screen.getByLabelText('Valor da transferência (R$)'), '300,00')
  await userEvent.click(screen.getByRole('button', { name: 'Transferir' }))
  const post = calls.find(([u, i]) => u === '/spaces/s1/transactions' && i.method === 'POST')!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ type: 'transfer', amount_cents: 30000, account_id: 'a1', counter_account_id: 'a3' })
  expect(await screen.findByText('Transferido.')).toBeInTheDocument()
})

test('transferir: avisa e bloqueia quando excede o disponível com caixinhas', async () => {
  go('/lancamentos', [acc('a1', 'Nubank', 's1', 100000, 80000), acc('a2', 'Itaú', 's1', 0)])
  await userEvent.selectOptions(await screen.findByLabelText('Conta de origem'), 'a1')
  await userEvent.selectOptions(screen.getByLabelText('Conta de destino'), 'a2')
  await userEvent.type(screen.getByLabelText('Valor da transferência (R$)'), '250')
  expect(screen.getByText('Valor maior que o disponível (R$ 200,00); o resto está em caixinhas.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Transferir' })).toBeDisabled()
})

test('transferir: erro do servidor aparece em português', async () => {
  go('/lancamentos', [acc('a1', 'Nubank', 's1', 100), acc('a2', 'Itaú', 's1', 0)], undefined, (u, i) => (u.includes('/transactions') && i.method === 'POST' ? J({ detail: 'insufficient_available' }, 409) : null))
  await userEvent.selectOptions(await screen.findByLabelText('Conta de origem'), 'a1')
  await userEvent.selectOptions(screen.getByLabelText('Conta de destino'), 'a2')
  await userEvent.type(screen.getByLabelText('Valor da transferência (R$)'), '5')
  await userEvent.click(screen.getByRole('button', { name: 'Transferir' }))
  expect(await screen.findByText(/Valor maior que o disponível na conta/)).toBeInTheDocument()
})

test('lista mostra Transferência · Origem → Destino sem sinal e o detalhe só exclui', async () => {
  go('/lancamentos', [acc('a1', 'Nubank', 's1', 0), acc('a2', 'Itaú', 's1', 0)], undefined, (u, i) => (u === '/transactions/t1' && i.method === 'DELETE' ? new Response(null, { status: 204 }) : null))
  const open = await screen.findByRole('button', { name: 'Abrir Transferência · Nubank → Itaú' })
  expect(screen.getByText('R$ 300,00')).toBeInTheDocument()
  await userEvent.click(open)
  expect(screen.queryByRole('button', { name: /Editar/ })).toBeNull()
  vi.stubGlobal('confirm', () => true)
  await userEvent.click(screen.getByRole('button', { name: 'Excluir transferência' }))
  expect(calls.some(([u, i]) => u === '/transactions/t1' && i.method === 'DELETE')).toBe(true)
})
