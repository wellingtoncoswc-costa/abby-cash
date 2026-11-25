import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Bill, Card as CardT, Invoice, S, Statement } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Btn, Card, EditBox, Err, Field, br, centsText, today, useAccounts, useGet, useIsOwner, useSend } from '../ui'

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

export function Cards() {
  const owner = useIsOwner()
  const { spaceId } = useSpace()
  const cards = useGet<CardT[]>('/cards')
  const mine = (cards.data ?? []).filter((c) => c.space_id === spaceId)
  const [sel, setSel] = useState('')
  const [invId, setInvId] = useState<string | null>(null)
  const invoices = useGet<Invoice[]>(sel ? `/cards/${sel}/invoices` : null)
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
      <Card title="Meus cartões">
        {mine.length === 0 ? <p>Nenhum cartão neste espaço.</p> : (
          <Field label="Cartão"><select value={sel} onChange={(e) => { setSel(e.target.value); setInvId(null) }}><option value="">Selecione…</option>{mine.map((c) => <option key={c.id} value={c.id}>{c.name} (fecha {c.closing_day}, vence {c.due_day})</option>)}</select></Field>
        )}
        {sel && mine.find((c) => c.id === sel) && (() => { const c = mine.find((x) => x.id === sel)!; return (
          <EditBox key={c.id} what="cartão" canEdit={owner} fields={[{ k: 'name', label: 'Nome do cartão (edição)', v: c.name }, { k: 'closing_day', label: 'Dia do fechamento (edição)', v: String(c.closing_day), type: 'number' }, { k: 'due_day', label: 'Dia do vencimento (edição)', v: String(c.due_day), type: 'number' }, { k: 'limit', label: 'Limite (R$, vazio = sem limite)', v: c.limit_cents ? centsText(c.limit_cents) : '' }]}
            save={(v) => { const l = v.limit ? parseBRL(v.limit) : null; return v.limit && !l ? Promise.reject(new ApiError(422, 'invalid_amount')) : api('PATCH', `/cards/${c.id}`, { name: v.name, closing_day: Number(v.closing_day), due_day: Number(v.due_day), limit_cents: l } satisfies S['CardPatch']) }}
            remove={() => api('DELETE', `/cards/${c.id}`).then(() => setSel(''))} />) })()}
        {(invoices.data ?? []).map((i) => (
          <div key={i.id} className="border-t border-border py-2">
            <button type="button" className="flex w-full justify-between text-left" aria-expanded={invId === i.id} onClick={() => setInvId(invId === i.id ? null : i.id)}>
              <span>Fatura {br(i.closing_on)} · vence {br(i.due_on)}{i.status === 'paid' && <> · <span>paga</span></>}</span><span>{formatBRL(i.total_cents)}</span>
            </button>
            {invId === i.id && <InvoiceView id={i.id} />}
          </div>
        ))}
        <Err e={invoices.error} />
      </Card>
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
