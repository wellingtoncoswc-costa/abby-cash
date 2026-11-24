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
  '/me': () => J({ id: 'u1', name: 'Ana', email: 'a@x.com', tz: 'America/Sao_Paulo', default_space_id: SP, preferred_channel: null, reminder_time: '09:00:00', weekly_digest: false, is_admin: false, totp_enabled: false }),
  [`/spaces/${SP}/categories`]: () => J([{ id: 'c1', space_id: SP, kind: 'expense', name: 'Mercado', icon: null, color: null }]),
  [`/spaces/${SP}/members`]: () => J([{ user_id: 'u1', name: 'Ana', role: 'owner', joined_at: '2026-11-01T00:00:00Z' }]),
  '/cards': () => J([{ id: 'k1', space_id: SP, name: 'Visa', closing_day: 5, due_day: 12, limit_cents: null, payment_account_id: null }]),
  [`/spaces/${SP}/card-purchases`]: () => J([1, 2].map((n) => ({ id: `p${n}`, invoice_id: `i${n}`, amount_cents: 5000, installment_number: n, installment_total: 2 })), 201),
  '/attachments/att1': () => new Response('x', { headers: { 'Content-Type': 'image/png' } }),
  '/transactions/t1': () => new Response(null, { status: 204 }),
  '/spaces/s1/transactions/': () => J({}),
  '/channels/link-code': () => J({ code: '123456', expires_in_s: 600, deep_link: 'https://t.me/abby_bot?start=123456' }),
}
let calls: [string, RequestInit][] = []

let txExtra: Record<string, unknown> = {}
function go(path: string) {
  calls = []
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    calls.push([url, init])
    const key = Object.keys(routes).find((k) => url === k || url.startsWith(`${k}?`))
    if (key) return routes[key](init)
    if (url.includes('/budgets/')) return J({ detail: 'budget_not_found' }, 404)
    if (url.includes('/transactions')) return J([{ id: 't1', space_id: SP, type: 'expense', amount_cents: 123456, occurred_on: '2026-11-20', description: 'Mercado', merchant: null, category_id: 'c1', account_id: 'a1', attachment_id: 'att1', installment_total: null, ...txExtra }])
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

test('categorias aparecem pelo nome', async () => {
  go('/lancamentos')
  expect((await screen.findAllByText('Mercado', { exact: false })).length).toBeGreaterThan(0)
  expect(screen.queryByText('Categoria #', { exact: false })).toBeNull()
})

test('detalhe do lançamento: comprovante, edição e exclusão', async () => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: vi.fn() }))
  vi.stubGlobal('confirm', () => true)
  go('/lancamentos')
  await userEvent.click(await screen.findByRole('button', { name: 'Abrir Mercado' }))
  expect(await screen.findByAltText('Comprovante')).toHaveAttribute('src', 'blob:x')
  expect(calls.find(([u]) => u === '/attachments/att1')![1].headers).toMatchObject({ Authorization: 'Bearer t' })
  await userEvent.click(screen.getByRole('button', { name: 'Editar lançamento' }))
  await userEvent.clear(screen.getByLabelText('Descrição (edição)'))
  await userEvent.type(screen.getByLabelText('Descrição (edição)'), 'Feira')
  await userEvent.click(screen.getByRole('button', { name: 'Salvar alterações' }))
  const patch = calls.find(([u, i]) => u === '/transactions/t1' && i.method === 'PATCH')!
  expect(JSON.parse(patch[1].body as string)).toEqual({ description: 'Feira' })
})

test('lançamento de cartão/parcelado: sem valor e data, com aviso', async () => {
  txExtra = { card_id: 'k1', installment_group_id: 'g1', installment_number: 1, installment_total: 2 }
  try {
    go('/lancamentos')
    await userEvent.click(await screen.findByRole('button', { name: 'Abrir Mercado' }))
    expect(await screen.findByRole('note')).toHaveTextContent('não podem ser editados')
    await userEvent.click(screen.getByRole('button', { name: 'Editar lançamento' }))
    expect(screen.queryByLabelText('Valor (R$) (edição)')).toBeNull()
    expect(screen.queryByLabelText('Data (edição)')).toBeNull()
  } finally { txExtra = {} }
})

test('compra parcelada mostra o impacto nas faturas', async () => {
  go('/lancamentos')
  await userEvent.selectOptions(await screen.findByLabelText('Cartão'), 'k1')
  await userEvent.type(screen.getByLabelText('Valor total (R$)'), '100,00')
  await userEvent.clear(screen.getByLabelText('Parcelas'))
  await userEvent.type(screen.getByLabelText('Parcelas'), '2')
  await userEvent.click(screen.getByRole('button', { name: 'Lançar compra' }))
  expect(await screen.findByText(/2x de R\$ 50,00 \(total R\$ 100,00\).*2 fatura/)).toBeInTheDocument()
  expect(JSON.parse(calls.find(([u]) => u.endsWith('/card-purchases'))![1].body as string)).toMatchObject({ card_id: 'k1', installments: 2, amount_cents: 10000 })
})

test('configurações salvam via PATCH /me/settings', async () => {
  go('/config')
  const tz = await screen.findByLabelText('Fuso horário')
  await userEvent.clear(tz)
  await userEvent.type(tz, 'Europe/Lisbon')
  await userEvent.click(screen.getByLabelText('Receber resumo semanal'))
  await userEvent.click(screen.getByRole('button', { name: 'Salvar preferências' }))
  const p = calls.find(([u, i]) => u === '/me/settings' && i.method === 'PATCH')!
  expect(JSON.parse(p[1].body as string)).toEqual({ tz: 'Europe/Lisbon', reminder_time: '09:00', preferred_channel: null, weekly_digest: true })
})

test('menu Admin só para administradores', async () => {
  go('/')
  await screen.findByText('Sem teto definido.', { exact: false })
  expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull()
  routes['/me'] = () => J({ id: 'u1', name: 'Ana', email: 'a@x.com', tz: 'x', default_space_id: SP, preferred_channel: null, reminder_time: '09:00:00', weekly_digest: false, is_admin: true, totp_enabled: false })
  go('/')
  expect(await screen.findByRole('link', { name: 'Admin' })).toBeInTheDocument()
})
