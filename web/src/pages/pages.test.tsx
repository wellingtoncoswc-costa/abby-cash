import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeRouter } from '../router'

const SP = 's1'
const J = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const routes: Record<string, (init: RequestInit) => Response> = {
  '/auth/refresh': () => J({ access_token: 't' }),
  '/spaces': () => J([{ id: SP, type: 'personal', name: 'x' }]),
  '/accounts': () => J([{ id: 'a1', space_id: SP, type: 'checking', name: 'Nubank', initial_balance_cents: 100000, institution: 'nubank', balance_cents: 100000, pockets_cents: 0, available_cents: 100000 }]),
  [`/spaces/${SP}/bills`]: () => J([{ id: 'b1', space_id: SP, kind: 'bill', description: 'Aluguel', amount_cents: 150000, due_on: '2026-12-05', status: 'open', invoice_id: null }]),
  [`/spaces/${SP}/goals`]: () => J([]),
  '/channels': () => J([]),
  '/me': () => J({ id: 'u1', name: 'Ana', email: 'a@x.com', tz: 'America/Sao_Paulo', default_space_id: SP, preferred_channel: null, reminder_time: '09:00:00', weekly_digest: false, is_admin: false, totp_enabled: false }),
  [`/spaces/${SP}/categories`]: () => J([{ id: 'c1', space_id: SP, kind: 'expense', name: 'Mercado', icon: null, color: null }]),
  [`/spaces/${SP}/members`]: () => J([{ user_id: 'u1', name: 'Ana', role: 'owner', joined_at: '2026-11-01T00:00:00Z' }]),
  '/cards/k1/panel': () => J({ invoice: null, limit_cents: null, used_cents: 0, available_cents: null, by_category: [], private_total_cents: 0, top: [], history: [] }),
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
  expect(within(screen.getByRole('group', { name: 'Espaço' })).getByRole('button', { name: 'Pessoal', pressed: true })).toBeInTheDocument()
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

test('onboarding: ícone na lista e banco enviado ao criar/editar conta', async () => {
  routes[`/spaces/${SP}/accounts`] = () => J({ id: 'a2' }, 201)
  routes['/accounts/a1'] = () => J({})
  go('/onboarding')
  await screen.findByRole('button', { name: 'Editar conta' })
  expect(document.querySelector('[data-bank="nubank"]')).not.toBeNull()
  await userEvent.type(screen.getByLabelText('Nome da conta'), 'Salário')
  await userEvent.selectOptions(screen.getAllByLabelText('Banco')[0], 'itau')
  await userEvent.click(screen.getByRole('button', { name: 'Adicionar conta' }))
  const post = calls.find(([u]) => u === `/spaces/${SP}/accounts`)!
  expect(JSON.parse(post[1].body as string).institution).toBe('itau')
  await userEvent.click(screen.getByRole('button', { name: 'Editar conta' }))
  await userEvent.selectOptions(screen.getByLabelText('Banco de Nubank'), '')
  await userEvent.click(screen.getByRole('button', { name: 'Salvar alterações' }))
  const patch = calls.find(([u]) => u === '/accounts/a1')!
  expect(JSON.parse(patch[1].body as string).institution).toBeNull()
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
  expect(await screen.findByRole('dialog', { name: 'Editar lançamento' })).toBeInTheDocument()
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
    expect(screen.queryByLabelText('Valor (R$) (edição)')).toBeNull()
    expect(screen.queryByLabelText('Data (edição)')).toBeNull()
  } finally { txExtra = {} }
})

test('compra parcelada mostra o impacto nas faturas', async () => {
  go('/lancamentos')
  await userEvent.click(await screen.findByRole('button', { name: 'Nova compra no cartão' }))
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

test('edição de contas: só o dono vê o botão', async () => {
  go('/onboarding')
  expect(await screen.findByRole('button', { name: 'Editar conta' })).toBeInTheDocument()
  cleanup()
  routes[`/spaces/${SP}/members`] = () => J([{ user_id: 'u1', name: 'Ana', role: 'member', joined_at: '2026-11-01T00:00:00Z' }])
  go('/onboarding')
  await screen.findByText('Nubank', { exact: false })
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Editar conta' })).toBeNull())
})

test('Admin: conectar WhatsApp mostra o QR e o status', async () => {
  routes['/me'] = () => J({ id: 'u1', name: 'Ana', email: 'a@x.com', tz: 'x', default_space_id: SP, preferred_channel: null, reminder_time: '09:00:00', weekly_digest: false, is_admin: true, totp_enabled: false })
  routes['/admin/whatsapp'] = () => J({ state: 'none', qr: null })
  routes['/admin/whatsapp/qr'] = () => J({ state: 'connecting', qr: 'data:image/png;base64,AAAA' })
  go('/admin')
  expect(await screen.findByText('não configurado')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Conectar número (QR)' }))
  const img = await screen.findByAltText('QR code para parear o WhatsApp')
  expect(img).toHaveAttribute('src', 'data:image/png;base64,AAAA')
  routes['/admin/whatsapp'] = () => J({ state: 'open', qr: null })
  await userEvent.click(screen.getByRole('button', { name: 'Gerar novo QR' }))
  expect(await screen.findByRole('button', { name: 'Desconectar número' })).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByAltText('QR code para parear o WhatsApp')).toBeNull())
})

test('painel: passar o mouse numa categoria troca o centro da rosca', async () => {
  go('/')
  const centro = await screen.findByTestId('centro-rosca')
  expect(within(centro).getByText('Total')).toBeInTheDocument()
  await userEvent.hover(await screen.findByRole('listitem', { name: /Mercado/ }))
  expect(within(centro).getByText('Mercado')).toBeInTheDocument()
  await userEvent.unhover(screen.getByRole('listitem', { name: /Mercado/ }))
  expect(within(centro).getByText('Total')).toBeInTheDocument()
})

test('painel: seção mostra esqueleto enquanto carrega', async () => {
  routes[`/spaces/${SP}/goals`] = () => new Promise(() => {}) as unknown as Response
  go('/')
  expect(await screen.findByLabelText('Carregando metas')).toBeInTheDocument()
  routes[`/spaces/${SP}/goals`] = () => J([])
})

test('painel: mapa de calor mostra o gasto de cada dia', async () => {
  go('/')
  const mapa = await screen.findByRole('img', { name: /Gastos por dia/ })
  expect(within(mapa).getByLabelText('20/11: R$ 1.234,56')).toBeInTheDocument()
})

test('painel: meta batida ganha o selo', async () => {
  routes[`/spaces/${SP}/goals`] = () => J([{ id: 'g1', name: 'Viagem', saved_cents: 100000, target_cents: 100000 }])
  go('/')
  expect(await screen.findByText('Meta batida')).toBeInTheDocument()
  routes[`/spaces/${SP}/goals`] = () => J([])
})

const FATURA = { id: 'i1', card_id: 'k1', closing_on: '2026-08-05', due_on: '2026-08-12', total_cents: 20000, paid_cents: 0, remaining_cents: 20000, status: 'open' }

test('fatura antiga: marcar como paga antes do cadastro e desfazer', async () => {
  routes['/cards/k1/invoices'] = () => J([FATURA])
  let baixada = false
  const estado = () => (baixada ? { ...FATURA, status: 'paid', remaining_cents: 0 } : FATURA)
  routes['/invoices/i1'] = () => J({ ...estado(), statement: { items: [], private_total_cents: 0, total_cents: 20000 } })
  routes['/invoices/i1/settle'] = (init) => { baixada = init.method === 'POST'; return J(estado()) }
  go('/cartoes')
  await userEvent.click(await screen.findByRole('button', { name: /Fatura 05\/08\/2026/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'Marcar como paga (paga antes do cadastro)' }))
  const post = calls.find(([u, i]) => u === '/invoices/i1/settle' && i.method === 'POST')
  expect(post).toBeDefined()
  expect(await screen.findByRole('button', { name: 'Desfazer baixa' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Desfazer baixa' }))
  expect(calls.some(([u, i]) => u === '/invoices/i1/settle' && i.method === 'DELETE')).toBe(true)
})

test('fatura paga aparece com o status na lista', async () => {
  routes['/cards/k1/invoices'] = () => J([{ ...FATURA, status: 'paid', remaining_cents: 0 }])
  go('/cartoes')
  expect(await screen.findByText('paga')).toBeInTheDocument()
})

test('metas: conta já ligada a outra meta fica desabilitada', async () => {
  const base = { saved_cents: 0, target_cents: 100000, deadline: null, monthly_needed_cents: null, behind: false, pocket_ids: [] }
  routes[`/spaces/${SP}/goals`] = () => J([{ ...base, id: 'g1', name: 'Viagem', account_ids: ['a1'] }, { ...base, id: 'g2', name: 'Carro', account_ids: [] }])
  routes[`/spaces/${SP}/pockets`] = () => J([])
  go('/metas')
  const carro = within((await screen.findByRole('heading', { name: 'Carro' })).closest('section')!)
  expect(await carro.findByLabelText(/Nubank/)).toBeDisabled()
  expect(carro.getByText(/já na meta Viagem/)).toBeInTheDocument()
  routes[`/spaces/${SP}/goals`] = () => J([])
})

const INV = {
  assets: [{ id: 'i1', name: 'Petrobras', kind: 'stock', ticker: 'PETR4', quantity: '10', avg_price_cents: 3800, price_cents: 3850, quote_date: '2026-01-15', day_change_bp: 131, contributed_cents: 38000, value_cents: 38500, profit_cents: 500, profit_bp: 131 }],
  by_kind: [{ kind: 'stock', value_cents: 38500 }],
  series: [{ on: '2026-01-14', value_cents: 38000, contributed_cents: 38000 }, { on: '2026-01-15', value_cents: 38500, contributed_cents: 38000 }],
  contributed_cents: 38000, current_cents: 38500, profit_cents: 500, profit_bp: 131,
}

test('investimentos: mostra totais, rentabilidade e ativos', async () => {
  routes[`/spaces/${SP}/investments/dashboard`] = () => J(INV)
  go('/investimentos')
  expect(await screen.findByRole('button', { name: 'Aportar em PETR4' })).toBeInTheDocument()
  expect(screen.getAllByText(/R\$ 385,00/).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/\+1,31%/).length).toBeGreaterThan(0)
})

test('investimentos: aportar em ação envia quantidade e conta', async () => {
  routes[`/spaces/${SP}/investments/dashboard`] = () => J(INV)
  routes['/investments/i1/buys'] = () => J({ id: 'm1' }, 201)
  go('/investimentos')
  await userEvent.click(await screen.findByRole('button', { name: 'Aportar em PETR4' }))
  await userEvent.selectOptions(screen.getByLabelText('Conta'), 'a1')
  await userEvent.type(screen.getByLabelText('Quantidade'), '10')
  await userEvent.click(screen.getByRole('button', { name: 'Confirmar aporte' }))
  const post = calls.find(([u]) => u === '/investments/i1/buys')!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ account_id: 'a1', quantity: '10' })
})

test('investimentos: ativo recém-cadastrado aparece com o caminho para aportar', async () => {
  routes[`/spaces/${SP}/investments/dashboard`] = () => J({
    assets: [{ ...INV.assets[0], quantity: '0', avg_price_cents: null, contributed_cents: 0, value_cents: 0, profit_cents: 0, profit_bp: null }],
    by_kind: [], series: [], contributed_cents: 0, current_cents: 0, profit_cents: 0, profit_bp: null,
  })
  go('/investimentos')
  expect(await screen.findByText(/Sem aportes ainda/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Aportar em PETR4' })).toBeInTheDocument()
})

const PANEL = {
  invoice: { id: 'i1', card_id: 'k1', closing_on: '2026-12-05', due_on: '2026-12-12', total_cents: 50000, paid_cents: 0, remaining_cents: 50000, status: 'open' },
  limit_cents: 200000, used_cents: 50000, available_cents: 150000,
  by_category: [{ category_id: 'c1', total_cents: 50000 }], private_total_cents: 0,
  top: [{ description: 'Supermercado', merchant: null, amount_cents: 30000, occurred_on: '2026-11-20' }],
  history: [{ invoice_id: 'i1', closing_on: '2026-12-05', due_on: '2026-12-12', total_cents: 50000 }],
}
const tile = async () => within((await screen.findByRole('heading', { name: 'Visa' })).closest('section')!)

test('cartões: um card por cartão com resumo, limite e painel', async () => {
  routes['/cards/k1/panel'] = () => J(PANEL)
  routes['/cards/k1/invoices'] = () => J([PANEL.invoice])
  go('/cartoes')
  const card = await tile()
  expect(await card.findByText(/Disponível R\$ 1\.500,00/)).toBeInTheDocument()
  await userEvent.click(card.getByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText('Mercado')).toBeInTheDocument()
  expect(card.getByText(/Supermercado/)).toBeInTheDocument()
})

test('cartões: cadastrar fatura pelo total envia mês e valor', async () => {
  routes['/cards/k1/panel'] = () => J(PANEL)
  routes['/cards/k1/invoices'] = () => J([PANEL.invoice])
  routes['/cards/k1/invoice-totals'] = () => J(PANEL.invoice, 201)
  go('/cartoes')
  const card = await tile()
  await userEvent.click(await card.findByRole('button', { name: 'Cadastrar fatura' }))
  await userEvent.type(card.getByLabelText('Mês de fechamento'), '2026-08')
  await userEvent.type(card.getByLabelText('Valor total (R$)'), '1234,56')
  await userEvent.click(card.getByRole('button', { name: 'Salvar fatura' }))
  const post = calls.find(([u]) => u === '/cards/k1/invoice-totals')!
  expect(JSON.parse(post[1].body as string)).toEqual({ month: '2026-08', total_cents: 123456 })
})

test('cartões: nova compra no cartão', async () => {
  routes['/cards/k1/panel'] = () => J(PANEL)
  routes['/cards/k1/invoices'] = () => J([])
  go('/cartoes')
  const card = await tile()
  await userEvent.click(await card.findByRole('button', { name: 'Nova compra' }))
  await userEvent.type(card.getByLabelText('Valor (R$)'), '45,00')
  await userEvent.click(card.getByRole('button', { name: 'Registrar compra' }))
  const post = calls.find(([u]) => u === `/spaces/${SP}/card-purchases`)!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ card_id: 'k1', amount_cents: 4500, installments: 1 })
})

const ACC_PANEL = {
  month: '2026-11-01', is_default: false, income_cents: 500000, expense_cents: 40000, transfer_net_cents: -20000, private_total_cents: 0,
  by_category: [{ category_id: 'c1', total_cents: 40000 }],
  recent: [{ occurred_on: '2026-11-08', type: 'transfer', description: 'p/ outra', merchant: null, amount_cents: -20000 }],
  pockets: [{ id: 'p1', name: 'Reserva', balance_cents: 15000 }], goals: [{ id: 'g1', name: 'Viagem' }],
}
const accTile = async () => within((await screen.findByRole('heading', { name: 'Nubank' })).closest('section')!)

test('contas: um card por conta com saldo e painel do mês', async () => {
  routes['/accounts/a1/panel'] = () => J(ACC_PANEL)
  go('/contas-bancarias')
  const card = await accTile()
  await userEvent.click(await card.findByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText('Mercado')).toBeInTheDocument()
  expect(card.getByText(/Reserva/)).toBeInTheDocument()
  expect(card.getByText(/Viagem/)).toBeInTheDocument()
  expect(card.getByText(/R\$ 5\.000,00/)).toBeInTheDocument()
})

test('contas: tornar padrão chama a API', async () => {
  routes['/accounts/a1/panel'] = () => J(ACC_PANEL)
  routes[`/spaces/${SP}/default-account`] = () => new Response(null, { status: 204 })
  go('/contas-bancarias')
  const card = await accTile()
  await userEvent.click(await card.findByRole('button', { name: 'Tornar padrão' }))
  const put = calls.find(([u]) => u === `/spaces/${SP}/default-account`)!
  expect(JSON.parse(put[1].body as string)).toEqual({ account_id: 'a1' })
})

test('caixinhas: um card por caixinha com painel de rendimento', async () => {
  routes[`/spaces/${SP}/pockets`] = () => J([{ id: 'p1', space_id: SP, account_id: 'a1', name: 'Reserva', cdi_bp: 10000, balance_cents: 15000, pending_yield_cents: 0, month_yield_cents: 120, created_at: '2026-11-01T00:00:00Z', closed_at: null }])
  routes['/cdi/latest'] = () => J({ on_date: '2026-11-24', daily_pct: '0.05', annual_pct: '14.90' })
  routes['/pockets/p1/panel'] = () => J({ yield_by_month: [{ month: '2026-10-01', yield_cents: 70 }, { month: '2026-11-01', yield_cents: 120 }], goals: [{ id: 'g1', name: 'Viagem' }] })
  routes['/pockets/p1/movements'] = () => J([{ id: 'm1', pocket_id: 'p1', kind: 'deposit', amount_cents: 15000, occurred_on: '2026-11-12', ref_date: null, created_at: '2026-11-12T00:00:00Z' }])
  go('/caixinhas')
  const card = within((await screen.findByRole('heading', { name: 'Reserva' })).closest('section')!)
  expect(card.getByText('R$ 150,00')).toBeInTheDocument()
  await userEvent.click(card.getByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText('Viagem')).toBeInTheDocument()
  expect(card.getByText(/Depósito/)).toBeInTheDocument()
  expect(card.getByLabelText('11/26: R$ 1,20')).toBeInTheDocument()
})

test('metas: painel mostra a composição e o histórico de aportes', async () => {
  const base = { saved_cents: 8000, target_cents: 100000, deadline: null, monthly_needed_cents: null, behind: false, account_ids: [], pocket_ids: [] }
  routes[`/spaces/${SP}/goals`] = () => J([{ ...base, id: 'g1', name: 'Viagem' }])
  routes[`/spaces/${SP}/pockets`] = () => J([])
  routes['/goals/g1/panel'] = () => J({ total_cents: 58000, direct_cents: 8000, accounts: [{ id: 'a1', name: 'Ligada', balance_cents: 50000 }], pockets: [{ id: 'p1', name: 'Reserva', balance_cents: 20000, counted: false }], contributions: [{ occurred_on: '2026-11-10', direction: 'in', amount_cents: 10000 }] })
  go('/metas')
  const card = within((await screen.findByRole('heading', { name: 'Viagem' })).closest('section')!)
  await userEvent.click(await card.findByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText(/Conta Ligada/)).toBeInTheDocument()
  expect(card.getByText(/Reserva \(já na conta\)/)).toBeInTheDocument()
  expect(card.getByText(/10\/11\/2026 Aporte/)).toBeInTheDocument()
  routes[`/spaces/${SP}/goals`] = () => J([])
})

test('investimentos: painel do ativo lista as movimentações', async () => {
  routes[`/spaces/${SP}/investments/dashboard`] = () => J(INV)
  routes['/investments/i1/panel'] = () => J({ movements: [{ id: 'm1', kind: 'buy', occurred_on: '2026-01-14', quantity: '10', unit_price_cents: 3800, amount_cents: 38000 }], series: [{ on: '2026-01-14', value_cents: 38000, contributed_cents: 38000 }, { on: '2026-01-15', value_cents: 38500, contributed_cents: 38000 }] })
  go('/investimentos')
  const card = within((await screen.findByRole('heading', { name: /Petrobras/ })).closest('section')!)
  await userEvent.click(card.getByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText(/10 cotas a R\$ 38,00/)).toBeInTheDocument()
  expect(card.getByRole('img', { name: 'Evolução de PETR4' })).toBeInTheDocument()
})

test('contas: nome do banco, saldo sem caixinhas e saldo negativo em destaque', async () => {
  routes['/accounts'] = () => J([{ id: 'a1', space_id: SP, type: 'checking', name: 'Principal', initial_balance_cents: 0, institution: 'nubank', balance_cents: 10000, pockets_cents: 15000, available_cents: -5000 }])
  routes['/accounts/a1/panel'] = () => J({ month: '2026-11-01', is_default: false, income_cents: 0, expense_cents: 0, transfer_net_cents: 0, private_total_cents: 0, by_category: [], recent: [], pockets: [], goals: [] })
  go('/contas-bancarias')
  const card = within((await screen.findByRole('heading', { name: 'Principal' })).closest('section')!)
  expect(card.getByText(/Nubank/)).toBeInTheDocument()
  expect(card.getByText('-R$ 50,00')).toHaveClass('text-destructive')
  expect(card.getByText(/Guardado em caixinhas \(fora do saldo\)/)).toBeInTheDocument()
  expect(card.getByRole('note')).toHaveTextContent('Saldo negativo')
  routes['/accounts'] = () => J([{ id: 'a1', space_id: SP, type: 'checking', name: 'Nubank', initial_balance_cents: 100000, institution: 'nubank', balance_cents: 100000, pockets_cents: 0, available_cents: 100000 }])
})

test('lançamento: abre em modal já em edição e fecha com Esc', async () => {
  go('/lancamentos')
  await userEvent.click(await screen.findByRole('button', { name: 'Abrir Mercado' }))
  expect(await screen.findByRole('dialog', { name: 'Editar lançamento' })).toBeInTheDocument()
  expect(screen.getByLabelText('Descrição (edição)')).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('cartões: lançar crédito e fatura negativa em destaque', async () => {
  const NEG = { ...PANEL, invoice: { ...PANEL.invoice, total_cents: -5000, remaining_cents: -5000 } }
  routes['/cards/k1/panel'] = () => J(NEG)
  routes['/cards/k1/invoices'] = () => J([NEG.invoice])
  routes['/cards/k1/credits'] = () => J({ id: 't1' }, 201)
  go('/cartoes')
  const card = await tile()
  expect(await card.findByText(/crédito a seu favor/)).toBeInTheDocument()
  await userEvent.click(card.getByRole('button', { name: 'Lançar crédito' }))
  await userEvent.type(card.getByLabelText('Valor do crédito (R$)'), '50,00')
  await userEvent.click(card.getByRole('button', { name: 'Registrar crédito' }))
  const post = calls.find(([u]) => u === '/cards/k1/credits')!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ amount_cents: 5000 })
})

test('lançamentos: só os botões + na tela; o formulário abre em modal', async () => {
  go('/lancamentos')
  const novo = await screen.findByRole('button', { name: 'Novo lançamento' })
  expect(screen.getByRole('button', { name: 'Nova transferência' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Nova compra no cartão' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Valor (R$)')).toBeNull() // sem formulário solto na página
  await userEvent.click(novo)
  expect(await screen.findByRole('dialog', { name: 'Novo lançamento' })).toBeInTheDocument()
  expect(screen.getByLabelText('Valor (R$)')).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('lançamentos: salvar um lançamento envia e fecha o modal', async () => {
  routes['/spaces/s1/transactions'] = (init) => init.method !== 'POST' ? J([]) : J({ id: 't9', space_id: SP, type: 'expense', amount_cents: 4500, occurred_on: '2026-11-25', description: '', merchant: null, category_id: null, account_id: 'a1', counter_account_id: null, installment_total: null }, 201)
  go('/lancamentos')
  await userEvent.click(await screen.findByRole('button', { name: 'Novo lançamento' }))
  await userEvent.type(await screen.findByLabelText('Valor (R$)'), '45,00')
  await userEvent.selectOptions(screen.getByLabelText('Conta'), 'a1')
  await userEvent.click(screen.getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  const post = calls.find(([u, i]) => u === `/spaces/${SP}/transactions` && i.method === 'POST')!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ type: 'expense', amount_cents: 4500, account_id: 'a1' })
  delete routes['/spaces/s1/transactions']
})
