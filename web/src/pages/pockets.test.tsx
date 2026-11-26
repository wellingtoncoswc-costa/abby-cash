import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeRouter } from '../router'
import { parsePct } from './pockets'

const J = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const pocket = { id: 'p1', account_id: 'a1', name: 'Reserva', cdi_bp: 11250, balance_cents: 150000, pending_yield_cents: 0, month_yield_cents: 1234 }
const loan = { id: 'l1', kind: 'financing', name: 'Carro', installment_cents: 85000, installments_total: 48, paid_count: 12, remaining_count: 36, remaining_cents: 3060000, next_due_on: '2026-12-10', last_due_on: '2029-11-10', progress_pct: 25 }
let calls: [string, RequestInit][] = []
let cdi = true

function go(path: string) {
  calls = []
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    calls.push([url, init])
    const m = init.method ?? 'GET'
    if (url === '/auth/refresh') return J({ access_token: 't' })
    if (url === '/spaces') return J([{ id: 's1', type: 'personal', name: 'x' }])
    if (url === '/accounts') return J([{ id: 'a1', space_id: 's1', type: 'checking', name: 'Nubank', initial_balance_cents: 0, institution: 'nubank', available_cents: 50000, pockets_cents: 150000 }])
    if (url === '/me') return J({ id: 'u1', is_admin: false })
    if (url === '/cdi/latest') return cdi ? J({ on_date: '2026-11-24', daily_pct: '0.0500', annual_pct: '10.65' }) : J({ detail: 'not_found' }, 404)
    if (url === '/spaces/s1/pockets') return m === 'GET' ? J([pocket]) : J(pocket, 201)
    if (url === '/spaces/s1/loans') return m === 'GET' ? J([loan]) : J(loan, 201)
    if (url === '/pockets/p1/deposit') return J({ detail: 'insufficient_available' }, 409)
    return J({}, 204)
  })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={makeRouter(createMemoryHistory({ initialEntries: [path] }))} /></QueryClientProvider>)
}
const body = (u: string, m: string) => JSON.parse(calls.find(([x, i]) => x === u && i.method === m)![1].body as string)

test('parsePct sem float', () => {
  expect([parsePct('120'), parsePct('102,5'), parsePct('0,01'), parsePct('0'), parsePct('1000,01'), parsePct('abc')]).toEqual([12000, 10250, 1, null, null, null])
})

test('caixinhas: lista, CDI, criar com atalho e outro %', async () => {
  go('/caixinhas')
  expect(await screen.findByText('Reserva')).toBeInTheDocument()
  expect(screen.getByText('R$ 1.500,00')).toBeInTheDocument()
  expect(screen.getByText(/112,50% do CDI/)).toBeInTheDocument()
  expect(screen.getByText('CDI hoje: 10,65% a.a.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Nova caixinha' }))
  await userEvent.type(screen.getByLabelText('Nome'), 'Viagem')
  await userEvent.selectOptions(screen.getByLabelText('Conta'), 'a1')
  await userEvent.click(screen.getByRole('button', { name: '120%' }))
  await userEvent.click(screen.getByRole('button', { name: 'Criar caixinha' }))
  expect(body('/spaces/s1/pockets', 'POST')).toEqual({ account_id: 'a1', name: 'Viagem', cdi_bp: 12000 })
  await userEvent.click(await screen.findByRole('button', { name: 'Nova caixinha' }))
  await userEvent.type(screen.getByLabelText('Nome'), 'Outra')
  await userEvent.clear(screen.getByLabelText('Outro percentual do CDI'))
  await userEvent.type(screen.getByLabelText('Outro percentual do CDI'), '102,5')
  await userEvent.click(screen.getByRole('button', { name: 'Criar caixinha' }))
  expect(calls.filter(([u, i]) => u === '/spaces/s1/pockets' && i.method === 'POST').map(([, i]) => JSON.parse(i.body as string).cdi_bp)).toEqual([12000, 10250])
})

test('caixinhas: aviso acima do disponível, erro 409 em PT-BR e resgate', async () => {
  cdi = false
  go('/caixinhas')
  const v = await screen.findByLabelText('Valor (R$) para Reserva')
  expect(screen.queryByText(/CDI hoje/)).toBeNull()
  expect(screen.getByText('R$ 500,00')).toBeInTheDocument()
  await userEvent.type(v, '600,00')
  expect(screen.getByRole('status')).toHaveTextContent('maior que o disponível')
  expect(screen.getByRole('button', { name: 'Depositar' })).toBeDisabled()
  await userEvent.clear(v)
  await userEvent.type(v, '100,00')
  await userEvent.click(screen.getByRole('button', { name: 'Depositar' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('maior que o disponível')
  await userEvent.click(screen.getByRole('button', { name: 'Resgatar' }))
  expect(body('/pockets/p1/withdraw', 'POST').amount_cents).toBe(10000)
  cdi = true
})

test('caixinhas: editar e excluir com confirmação', async () => {
  vi.stubGlobal('confirm', () => true)
  go('/caixinhas')
  await userEvent.click(await screen.findByRole('button', { name: /Editar caixinha/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'Excluir' }))
  expect(calls.some(([u, i]) => u === '/pockets/p1' && i.method === 'DELETE')).toBe(true)
})

test('financiamentos: progresso, falta, cadastro e exclusão', async () => {
  vi.stubGlobal('confirm', () => true)
  go('/financiamentos')
  expect(await screen.findByText('Carro')).toBeInTheDocument()
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25')
  expect(screen.getByText(/Faltam 36 parcelas/)).toHaveTextContent('R$ 30.600,00')
  expect(screen.getByText('Próxima parcela: 10/12/2026')).toBeInTheDocument()
  expect(screen.getByText('Previsão de término: 10/11/2029')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Novo financiamento ou consórcio' }))
  await userEvent.type(screen.getByLabelText('Nome'), 'Moto')
  await userEvent.type(screen.getByLabelText('Valor da parcela (R$)'), '500,00')
  await userEvent.type(screen.getByLabelText('Quantidade de parcelas (1 a 480)'), '481')
  await userEvent.type(screen.getByLabelText('Primeiro vencimento'), '2026-12-15')
  expect(screen.getByRole('button', { name: 'Cadastrar' })).toBeDisabled()
  await userEvent.clear(screen.getByLabelText('Quantidade de parcelas (1 a 480)'))
  await userEvent.type(screen.getByLabelText('Quantidade de parcelas (1 a 480)'), '24')
  await userEvent.click(screen.getByRole('button', { name: 'Cadastrar' }))
  expect(body('/spaces/s1/loans', 'POST')).toEqual({ kind: 'financing', name: 'Moto', installment_cents: 50000, installments_total: 24, first_due_on: '2026-12-15', paid_installments: 0 })
  await userEvent.click(screen.getByRole('button', { name: /Editar financiamento/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Excluir' }))
  expect(calls.some(([u, i]) => u === '/loans/l1' && i.method === 'DELETE')).toBe(true)
})

const inst = (n: number, state = 'open', bill_id: string | null = null) => ({ number: n, due_on: `2026-${String(n + 11).padStart(2, '0')}-10`, amount_cents: 85000, state, bill_id })

function goInst(rows: unknown[]) {
  go('/financiamentos')
  const base = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    if (url === '/loans/l1/installments') { calls.push([url, init]); return J(rows) }
    if (url.startsWith('/loans/l1/installments/')) { calls.push([url, init]); return J(inst(1, init.method === 'DELETE' ? 'open' : 'paid_history', 'b1')) }
    if (url === '/bills/b9/payments') { calls.push([url, init]); return J({}, 201) }
    return base(url, init)
  })
}

test('parcelas: marcar como já paga antes e desmarcar com confirmação', async () => {
  goInst([inst(1, 'paid_history', 'b1'), inst(2, 'paid_real', 'b2'), inst(3, 'open', 'b3'), inst(4)])
  await userEvent.click(await screen.findByRole('button', { name: 'Ver parcelas' }))
  const hist = await screen.findByRole('checkbox', { name: 'Parcela 1 de 48 · 10/12/2026 · R$ 850,00' })
  expect(hist).toBeChecked()
  expect(screen.getByText(/Paga \(já estava paga antes\)/)).toBeInTheDocument()
  expect(screen.getByText(/Paga \(com lançamento\)/)).toBeInTheDocument()
  expect(screen.getByText(/Em aberto · próxima/)).toBeInTheDocument()
  // pagamento real: explica e não desfaz
  await userEvent.click(screen.getByRole('checkbox', { name: /Parcela 2 de 48/ }))
  expect(screen.getByRole('status')).toHaveTextContent('exclua o lançamento')
  expect(calls.some(([u, i]) => u.includes('/settle') && i.method === 'DELETE')).toBe(false)
  // histórica: confirma e desfaz
  vi.stubGlobal('confirm', () => true)
  await userEvent.click(hist)
  expect(calls.some(([u, i]) => u === '/loans/l1/installments/1/settle' && i.method === 'DELETE')).toBe(true)
  // aberta: escolhe "já estava paga antes" (sem lançamento)
  await userEvent.click(screen.getByRole('checkbox', { name: /Parcela 4 de 48/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Já estava paga antes' }))
  expect(calls.some(([u, i]) => u === '/loans/l1/installments/4/settle' && i.method === 'POST')).toBe(true)
  expect(calls.some(([u]) => u.startsWith('/bills/'))).toBe(false)
})

test('parcelas: "Paguei agora" exige conta e materializa antes de pagar', async () => {
  goInst([inst(1, 'open', null)])
  await userEvent.click(await screen.findByRole('button', { name: 'Ver parcelas' }))
  await userEvent.click(await screen.findByRole('checkbox', { name: /Parcela 1 de 48/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Paguei agora' }))
  expect(screen.getByRole('button', { name: 'Confirmar pagamento' })).toBeDisabled()
  await userEvent.selectOptions(screen.getByLabelText('Pagar com a conta'), 'a1')
  const { fetch: f } = globalThis
  vi.stubGlobal('fetch', async (u: string, i: RequestInit = {}) => (u === '/loans/l1/installments/1/materialize' ? (calls.push([u, i]), J({ id: 'b9' })) : f(u, i)))
  await userEvent.click(screen.getByRole('button', { name: 'Confirmar pagamento' }))
  const pay = calls.find(([u]) => u === '/bills/b9/payments')!
  expect(JSON.parse(pay[1].body as string)).toMatchObject({ account_id: 'a1', amount_cents: 85000 })
  expect(calls.findIndex(([u]) => u.endsWith('/materialize'))).toBeLessThan(calls.findIndex(([u]) => u === '/bills/b9/payments'))
})

test('cadastro: parcelas já pagas valida 0..total e vai no corpo', async () => {
  go('/financiamentos')
  await screen.findByText('Carro')
  await userEvent.click(screen.getByRole('button', { name: 'Novo financiamento ou consórcio' }))
  await userEvent.type(screen.getByLabelText('Nome'), 'Moto')
  await userEvent.type(screen.getByLabelText('Valor da parcela (R$)'), '500,00')
  await userEvent.type(screen.getByLabelText('Quantidade de parcelas (1 a 480)'), '24')
  await userEvent.type(screen.getByLabelText('Primeiro vencimento'), '2026-12-15')
  const paid = screen.getByLabelText('Parcelas já pagas')
  expect(paid).toHaveValue('0')
  expect(paid).toHaveAccessibleDescription(/Informe quantas parcelas você já pagou antes de cadastrar/)
  await userEvent.clear(paid)
  await userEvent.type(paid, '25')
  expect(screen.getByRole('button', { name: 'Cadastrar' })).toBeDisabled()
  await userEvent.clear(paid)
  await userEvent.type(paid, '10')
  await userEvent.click(screen.getByRole('button', { name: 'Cadastrar' }))
  expect(body('/spaces/s1/loans', 'POST')).toMatchObject({ installments_total: 24, paid_installments: 10 })
})
