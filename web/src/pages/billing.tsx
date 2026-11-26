import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Bill, Card as CardT, CardPanel, Invoice, S, Statement } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Btn, Card, CategorySelect, EditBox, Err, Field, br, centsText, today, useAccounts, useCatName, useGet, useIsOwner, useSend } from '../ui'

/** Formulário de pagamento: conta de origem obrigatória; valor vazio = o que falta (só contas). */
function PayForm({ path, defaultCents, requireAmount }: { path: string; defaultCents?: number; requireAmount?: boolean }) {
  const accounts = useAccounts()
  const [acc, setAcc] = useState('')
  const [amt, setAmt] = useState(defaultCents ? `${Math.floor(defaultCents / 100)},${String(defaultCents % 100).padStart(2, '0')}` : '')
  const cents = amt ? parseBRL(amt) : null
  const pay = useSend(() => api('POST', path, { account_id: acc, amount_cents: cents ?? undefined, paid_on: today() } satisfies S['PayBillIn']))
  const invalid = !acc || (amt !== '' && !cents) || (!!requireAmount && !cents)
  return (
    <form className="mt-2 rounded-md bg-muted p-2" onSubmit={(e) => { e.preventDefault(); if (!invalid) pay.mutate() }}>
      <Field label="Pagar com a conta"><AccountSelect accounts={accounts.data} value={acc} onChange={setAcc} /></Field>
      <Field label={requireAmount ? 'Valor a pagar (R$)' : 'Valor (R$, vazio = o que falta)'}><input inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
      <Err e={pay.error} />
      <Btn type="submit" disabled={pay.isPending || invalid}>Confirmar pagamento</Btn>
    </form>
  )
}

export function Billing() {
  const { spaceId } = useSpace()
  const bills = useGet<Bill[]>(`/spaces/${spaceId}/bills`)
  const [open, setOpen] = useState<string | null>(null)
  const [f, setF] = useState({ description: '', amount: '', due_on: today() })
  const cents = parseBRL(f.amount)
  const create = useSend(
    () => api('POST', `/spaces/${spaceId}/bills`, { description: f.description, amount_cents: cents!, due_on: f.due_on } satisfies S['BillIn']),
    () => setF({ ...f, description: '', amount: '' }),
  )
  const label: Record<string, string> = { open: 'Em aberto', partial: 'Parcial', paid: 'Paga' }
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Contas a pagar</h1>
      <Card title="Nova conta">
        <form onSubmit={(e) => { e.preventDefault(); if (cents) create.mutate() }}>
          <Field label="Descrição"><input required maxLength={200} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Field label="Valor (R$)"><input inputMode="decimal" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Vencimento"><input type="date" required value={f.due_on} onChange={(e) => setF({ ...f, due_on: e.target.value })} /></Field>
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !cents}>Adicionar</Btn>
        </form>
      </Card>
      <Card>
        {(bills.data ?? []).length === 0 ? <p>Nenhuma conta cadastrada.</p> : (
          <ul className="divide-y divide-border">
            {[...(bills.data ?? [])].sort((a, b) => a.due_on.localeCompare(b.due_on)).map((b) => (
              <li key={b.id} className="py-2">
                <div className="flex justify-between"><span>{b.description}<br /><small>{br(b.due_on)} · {label[b.status]}{b.kind === 'invoice' ? ' · fatura' : ''}</small></span><span>{formatBRL(b.amount_cents)}</span></div>
                {b.status !== 'paid' && b.kind !== 'invoice' && (open === b.id ? <PayForm path={`/bills/${b.id}/payments`} /> : <button type="button" className="mt-1 mr-3 underline" onClick={() => setOpen(b.id)}>Pagar</button>)}
                {b.kind !== 'invoice' && <EditBox what="conta" fields={[{ k: 'description', label: 'Descrição da conta', v: b.description }, { k: 'amount', label: 'Valor da conta (R$)', v: centsText(b.amount_cents) }, { k: 'due_on', label: 'Vencimento da conta', v: b.due_on, type: 'date' }]} save={(v) => { const c = parseBRL(v.amount); return c ? api('PATCH', `/bills/${b.id}`, { description: v.description, amount_cents: c, due_on: v.due_on } satisfies S['BillPatch']) : Promise.reject(new ApiError(422, 'invalid_amount')) }} remove={() => api('DELETE', `/bills/${b.id}`)} />}
              </li>
            ))}
          </ul>
        )}
        <Err e={bills.error} />
      </Card>
    </>
  )
}

function InvoiceView({ id }: { id: string }) {
  const inv = useGet<Invoice & { statement: Statement }>(`/invoices/${id}`)
  const settle = useSend((on: boolean) => api(on ? 'POST' : 'DELETE', `/invoices/${id}/settle`))
  if (!inv.data) return <p>Carregando…</p>
  const { statement: st } = inv.data
  const baixa = inv.data.status === 'paid' && inv.data.paid_cents === 0 && inv.data.total_cents > 0 // sem pagamento real: veio da baixa histórica
  return (
    <div>
      <p>Total {formatBRL(inv.data.total_cents)} · pago {formatBRL(inv.data.paid_cents)} · restante {formatBRL(inv.data.remaining_cents)}</p>
      <ul>{st.items.map((i) => <li key={i.id} className="flex justify-between"><span>{br(i.occurred_on)} {i.description || i.merchant}</span><span>{formatBRL(i.amount_cents)}</span></li>)}</ul>
      {st.private_total_cents !== 0 && <p className="flex justify-between font-medium"><span>Outros lançamentos (privados)</span><span>{formatBRL(st.private_total_cents)}</span></p>}
      {baixa && <Btn type="button" disabled={settle.isPending} onClick={() => settle.mutate(false)}>Desfazer baixa</Btn>}
      {!baixa && inv.data.paid_cents === 0 && inv.data.total_cents > 0 && <Btn type="button" disabled={settle.isPending} onClick={() => settle.mutate(true)}>Marcar como paga (paga antes do cadastro)</Btn>}
      <Err e={settle.error} />
      {inv.data.remaining_cents > 0 && <PayForm path={`/invoices/${id}/payments`} defaultCents={inv.data.remaining_cents} requireAmount />}
    </div>
  )
}

const pctOf = (v: number, max: number) => (max > 0 ? Math.round((v / max) * 100) : 0)

function CardPanelView({ card, invoiceId, onPick }: { card: CardT; invoiceId: string | null; onPick: (id: string) => void }) {
  const p = useGet<CardPanel>(`/cards/${card.id}/panel${invoiceId ? `?invoice=${invoiceId}` : ''}`)
  const catName = useCatName()
  if (!p.data) return <p>Carregando…</p>
  const d = p.data
  const maxCat = Math.max(1, ...d.by_category.map((c) => c.total_cents))
  const maxH = Math.max(1, ...d.history.map((h) => h.total_cents))
  return (
    <div className="mt-2">
      <h3 className="font-semibold">Gastos por categoria{d.invoice ? ` · fatura ${br(d.invoice.closing_on)}` : ''}</h3>
      {d.by_category.length === 0 && <p>Sem compras nesta fatura.</p>}
      <ul>{d.by_category.map((c) => (
        <li key={c.category_id ?? 'none'}>
          <div className="flex justify-between"><span>{catName(c.category_id)}</span><span>{formatBRL(c.total_cents)}</span></div>
          <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${pctOf(c.total_cents, maxCat)}%` }} /></div>
        </li>
      ))}</ul>
      {d.private_total_cents !== 0 && <p>Outros lançamentos (privados): {formatBRL(d.private_total_cents)}</p>}
      <h3 className="mt-3 font-semibold">Últimas faturas</h3>
      <div className="flex items-end gap-2" role="group" aria-label="Últimas faturas">
        {d.history.map((h) => (
          <button key={h.invoice_id} type="button" aria-label={`Fatura ${br(h.closing_on)}: ${formatBRL(h.total_cents)}`} aria-pressed={d.invoice?.id === h.invoice_id}
            className="flex flex-col items-center text-xs" onClick={() => onPick(h.invoice_id)}>
            <span className="w-8 rounded-t bg-primary" style={{ height: `${Math.max(4, pctOf(h.total_cents, maxH) * 0.8)}px` }} />
            <span>{h.closing_on.slice(5, 7)}/{h.closing_on.slice(2, 4)}</span>
          </button>
        ))}
      </div>
      <h3 className="mt-3 font-semibold">Maiores compras</h3>
      <ul>{d.top.map((t, i) => <li key={i} className="flex justify-between"><span>{br(t.occurred_on)} {t.description || t.merchant}</span><span>{formatBRL(t.amount_cents)}</span></li>)}</ul>
    </div>
  )
}

function PurchaseForm({ card, done }: { card: CardT; done: () => void }) {
  const [f, setF] = useState({ amount: '', installments: '1', description: '', category_id: '', occurred_on: today() })
  const cents = parseBRL(f.amount)
  const send = useSend(
    () => api('POST', `/spaces/${card.space_id}/card-purchases`, { card_id: card.id, amount_cents: cents!, installments: Number(f.installments), description: f.description, category_id: f.category_id || null, occurred_on: f.occurred_on } satisfies S['PurchaseIn']),
    done,
  )
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (cents) send.mutate() }}>
      <Field label="Valor (R$)"><input inputMode="decimal" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Parcelas"><input type="number" min={1} max={48} value={f.installments} onChange={(e) => setF({ ...f, installments: e.target.value })} /></Field>
      <Field label="Data"><input type="date" value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
      <Field label="Descrição"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <CategorySelect value={f.category_id} onChange={(v) => setF({ ...f, category_id: v })} />
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !cents}>Registrar compra</Btn>
    </form>
  )
}

function CreditForm({ card, done }: { card: CardT; done: () => void }) {
  const [f, setF] = useState({ amount: '', description: '', occurred_on: today() })
  const cents = parseBRL(f.amount)
  const send = useSend(() => api('POST', `/cards/${card.id}/credits`, { amount_cents: cents!, description: f.description, occurred_on: f.occurred_on }), done)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (cents) send.mutate() }}>
      <Field label="Valor do crédito (R$)"><input inputMode="decimal" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Data"><input type="date" value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
      <Field label="Descrição (ex.: estorno)"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !cents}>Registrar crédito</Btn>
    </form>
  )
}

function InvoiceTotalForm({ card, done }: { card: CardT; done: () => void }) {
  const [f, setF] = useState({ month: '', total: '' })
  const cents = parseBRL(f.total)
  const send = useSend(() => api('POST', `/cards/${card.id}/invoice-totals`, { month: f.month, total_cents: cents! }), done)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (cents && f.month) send.mutate() }}>
      <Field label="Mês de fechamento"><input type="month" required value={f.month} onChange={(e) => setF({ ...f, month: e.target.value })} /></Field>
      <Field label="Valor total (R$)"><input inputMode="decimal" required value={f.total} onChange={(e) => setF({ ...f, total: e.target.value })} /></Field>
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !cents || !f.month}>Salvar fatura</Btn>
    </form>
  )
}

function CardTile({ c, owner }: { c: CardT; owner: boolean }) {
  const [open, setOpen] = useState<'purchase' | 'credit' | 'invoice' | 'panel' | null>(null)
  const [pick, setPick] = useState<string | null>(null)
  const [invId, setInvId] = useState<string | null>(null)
  const sum = useGet<CardPanel>(`/cards/${c.id}/panel`)
  const invoices = useGet<Invoice[]>(`/cards/${c.id}/invoices`)
  const toggle = (k: 'purchase' | 'credit' | 'invoice' | 'panel') => setOpen(open === k ? null : k)
  const cur = sum.data?.invoice
  return (
    <Card title={c.name}>
      <p>Fecha dia {c.closing_day} · vence dia {c.due_day}</p>
      {cur && <p>Fatura atual <span className={cur.total_cents < 0 ? 'text-destructive' : ''}>{formatBRL(cur.total_cents)}</span>{cur.total_cents < 0 ? ' (crédito a seu favor)' : ` · vence ${br(cur.due_on)}`}{cur.status === 'paid' ? ' · paga' : ''}</p>}
      {sum.data?.limit_cents != null && <p>Limite {formatBRL(sum.data.limit_cents)} · usado {formatBRL(sum.data.used_cents)} · Disponível {formatBRL(sum.data.available_cents ?? 0)}</p>}
      <div className="my-2 flex flex-wrap gap-2">
        <Btn type="button" onClick={() => toggle('purchase')}>Nova compra</Btn>
        <Btn type="button" onClick={() => toggle('credit')}>Lançar crédito</Btn>
        <Btn type="button" onClick={() => toggle('invoice')}>Cadastrar fatura</Btn>
        <Btn type="button" onClick={() => toggle('panel')} className="bg-muted-foreground hover:bg-muted-foreground/90">{open === 'panel' ? 'Ocultar painel' : 'Ver painel'}</Btn>
      </div>
      {open === 'purchase' && <PurchaseForm card={c} done={() => setOpen(null)} />}
      {open === 'credit' && <CreditForm card={c} done={() => setOpen(null)} />}
      {open === 'invoice' && <InvoiceTotalForm card={c} done={() => setOpen(null)} />}
      {open === 'panel' && <CardPanelView card={c} invoiceId={pick} onPick={setPick} />}
      {(invoices.data ?? []).map((i) => (
        <div key={i.id} className="border-t border-border py-2">
          <button type="button" className="flex w-full justify-between text-left" aria-expanded={invId === i.id} onClick={() => setInvId(invId === i.id ? null : i.id)}>
            <span>Fatura {br(i.closing_on)} · vence {br(i.due_on)}{i.status === 'paid' && <> · <span>paga</span></>}</span><span className={i.total_cents < 0 ? 'text-destructive' : ''}>{formatBRL(i.total_cents)}{i.total_cents < 0 ? ' (crédito)' : ''}</span>
          </button>
          {invId === i.id && <InvoiceView id={i.id} />}
        </div>
      ))}
      <Err e={invoices.error} />
      <EditBox what="cartão" canEdit={owner} fields={[{ k: 'name', label: 'Nome do cartão (edição)', v: c.name }, { k: 'closing_day', label: 'Dia do fechamento (edição)', v: String(c.closing_day), type: 'number' }, { k: 'due_day', label: 'Dia do vencimento (edição)', v: String(c.due_day), type: 'number' }, { k: 'limit', label: 'Limite (R$, vazio = sem limite)', v: c.limit_cents ? centsText(c.limit_cents) : '' }]}
        save={(v) => { const l = v.limit ? parseBRL(v.limit) : null; return v.limit && !l ? Promise.reject(new ApiError(422, 'invalid_amount')) : api('PATCH', `/cards/${c.id}`, { name: v.name, closing_day: Number(v.closing_day), due_day: Number(v.due_day), limit_cents: l } satisfies S['CardPatch']) }}
        remove={() => api('DELETE', `/cards/${c.id}`)} />
    </Card>
  )
}

export function Cards() {
  const owner = useIsOwner()
  const { spaceId } = useSpace()
  const cards = useGet<CardT[]>('/cards')
  const mine = (cards.data ?? []).filter((c) => c.space_id === spaceId)
  const [f, setF] = useState({ name: '', closing_day: '5', due_day: '12', limit: '' })
  const lim = f.limit ? parseBRL(f.limit) : null
  const create = useSend(
    () => api('POST', `/spaces/${spaceId}/cards`, { name: f.name, closing_day: Number(f.closing_day), due_day: Number(f.due_day), limit_cents: lim } satisfies S['CardIn']),
    () => setF({ ...f, name: '', limit: '' }),
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Cartões e faturas</h1>
      <Card title="Novo cartão"><CardForm f={f} setF={setF} onSubmit={() => create.mutate()} err={create.error} busy={create.isPending} lim={lim} /></Card>
      {!cards.isLoading && mine.length === 0 && <p className="mb-4">Nenhum cartão neste espaço.</p>}
      <div className="grid gap-4 md:grid-cols-2">{mine.map((c) => <CardTile key={c.id} c={c} owner={owner} />)}</div>
      <Err e={cards.error} />
    </>
  )
}

type CF = { name: string; closing_day: string; due_day: string; limit: string }
export function CardForm({ f, setF, onSubmit, err, busy, lim }: { f: CF; setF: (f: CF) => void; onSubmit: () => void; err: unknown; busy: boolean; lim: number | null }) {
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
      <Field label="Nome do cartão"><input required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Dia do fechamento"><input type="number" min={1} max={31} required value={f.closing_day} onChange={(e) => setF({ ...f, closing_day: e.target.value })} /></Field>
        <Field label="Dia do vencimento"><input type="number" min={1} max={31} required value={f.due_day} onChange={(e) => setF({ ...f, due_day: e.target.value })} /></Field>
      </div>
      <Field label="Limite (R$, opcional)"><input inputMode="decimal" value={f.limit} onChange={(e) => setF({ ...f, limit: e.target.value })} /></Field>
      {f.limit && !lim && <p role="alert" className="text-sm text-destructive">Limite inválido.</p>}
      <Err e={err} />
      <Btn type="submit" disabled={busy || (!!f.limit && !lim)}>Adicionar cartão</Btn>
    </form>
  )
}
