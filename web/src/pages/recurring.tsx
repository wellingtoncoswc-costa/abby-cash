import { useState } from 'react'
import { api } from '../api/client'
import type { RecurringItem, RecurringProjection } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Btn, Card, EditBox, Err, Field, Modal, PlusButton, br, centsText, today, useAccounts, useCategories, useGet, useIsOwner, useSend } from '../ui'

const REPEAT: Record<string, string> = { monthly: 'Mensal', yearly: 'Anual', every_n_months: 'A cada N meses' }
const MONTH = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const rule = (r: Record<string, unknown>) => r.kind === 'yearly' ? `Anual, dia ${r.day}/${r.month}` : r.kind === 'every_n_months' ? `A cada ${r.n} meses, dia ${r.day}` : `Mensal, dia ${r.day}`

function Projection({ spaceId }: { spaceId: string }) {
  const p = useGet<RecurringProjection>(`/spaces/${spaceId}/recurring/projection`)
  const d = p.data
  if (!d) return <Err e={p.error} />
  const max = Math.max(1, ...d.months.flatMap((m) => [m.income_cents, m.expense_cents]))
  return (
    <Card title="Projeção dos próximos 6 meses">
      <ul>{d.months.map((m) => (
        <li key={m.month} className="mb-2">
          <div className="flex justify-between"><span>{MONTH[Number(m.month.slice(5, 7)) - 1]}/{m.month.slice(2, 4)}</span><span className="tabular-nums">Saldo projetado {formatBRL(m.projected_balance_cents)}</span></div>
          <div className="h-2 rounded bg-muted" aria-hidden="true"><div className="h-2 rounded" style={{ width: `${Math.round((m.income_cents / max) * 100)}%`, background: 'var(--chart-1)' }} /></div>
          <div className="mt-1 h-2 rounded bg-muted" aria-hidden="true"><div className="h-2 rounded" style={{ width: `${Math.round((m.expense_cents / max) * 100)}%`, background: 'var(--chart-4)' }} /></div>
          <div className="flex justify-between text-sm text-muted-foreground"><span>Receitas {formatBRL(m.income_cents)}</span><span>Despesas {formatBRL(m.expense_cents)}{m.expense_loans_cents > 0 ? ` (financiamentos ${formatBRL(m.expense_loans_cents)})` : ''}</span><span>Resultado {formatBRL(m.net_cents)}</span></div>
        </li>
      ))}</ul>
      <h3 className="mt-3 font-semibold">Próximos 30 dias</h3>
      {d.upcoming.length === 0 && <p>Nenhum lançamento fixo previsto.</p>}
      <ul>{d.upcoming.map((u, i) => <li key={i} className="flex justify-between"><span>{br(u.due_on)} {u.description} · {u.type === 'income' ? 'entra em' : 'sai de'} {u.account_name}</span><span className="tabular-nums">{u.type === 'income' ? '' : '-'}{formatBRL(u.amount_cents)}</span></li>)}</ul>
    </Card>
  )
}

function NewItem({ onDone }: { onDone: () => void }) {
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const cats = useCategories()
  const [f, setF] = useState({ type: 'expense', description: '', amount: '', repeat: 'monthly', day: '5', month: '1', n: '2', account_id: '', category_id: '', starts_on: today(), ends_on: '' })
  const cents = parseBRL(f.amount)
  const body = {
    type: f.type, description: f.description, amount_cents: cents!, account_id: f.account_id, category_id: f.category_id || null,
    rule: { kind: f.repeat, day: Number(f.day), ...(f.repeat === 'yearly' ? { month: Number(f.month) } : {}), ...(f.repeat === 'every_n_months' ? { n: Number(f.n) } : {}) },
    starts_on: f.starts_on, ends_on: f.ends_on || null,
  }
  const send = useSend(() => api('POST', `/spaces/${spaceId}/recurring`, body), onDone)
  const set = (k: keyof typeof f, v: string) => setF({ ...f, [k]: v })
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (cents && f.account_id) send.mutate() }}>
      <Field label="Tipo"><select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value, category_id: '' })}><option value="expense">Despesa fixa</option><option value="income">Receita fixa</option></select></Field>
      <Field label="Descrição"><input required maxLength={200} value={f.description} onChange={(e) => set('description', e.target.value)} /></Field>
      <Field label="Valor (R$)"><input inputMode="decimal" required value={f.amount} onChange={(e) => set('amount', e.target.value)} /></Field>
      <Field label="Repetição"><select value={f.repeat} onChange={(e) => set('repeat', e.target.value)}>{Object.entries(REPEAT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Dia do mês"><input type="number" min={1} max={31} required value={f.day} onChange={(e) => set('day', e.target.value)} /></Field>
        {f.repeat === 'yearly' && <Field label="Mês"><select value={f.month} onChange={(e) => set('month', e.target.value)}>{MONTH.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></Field>}
        {f.repeat === 'every_n_months' && <Field label="A cada quantos meses"><input type="number" min={1} max={120} required value={f.n} onChange={(e) => set('n', e.target.value)} /></Field>}
      </div>
      <Field label={f.type === 'income' ? 'Entra em' : 'Sai de'}><AccountSelect accounts={accounts.data} value={f.account_id} onChange={(v) => set('account_id', v)} /></Field>
      <Field label="Categoria"><select value={f.category_id} onChange={(e) => set('category_id', e.target.value)}><option value="">Sem categoria</option>{cats.data.filter((c) => c.kind === f.type).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Início"><input type="date" required value={f.starts_on} onChange={(e) => set('starts_on', e.target.value)} /></Field>
        <Field label="Fim (opcional)"><input type="date" value={f.ends_on} onChange={(e) => set('ends_on', e.target.value)} /></Field>
      </div>
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !cents || !f.account_id}>Salvar fixo</Btn>
    </form>
  )
}

function ItemCard({ it, owner }: { it: RecurringItem; owner: boolean }) {
  const accounts = useAccounts(true)
  const acc = accounts.data.find((a) => a.id === it.account_id)
  const toggle = useSend(() => api('PATCH', `/spaces/${it.space_id}/recurring/${it.id}`, { active: !it.active }))
  return (
    <Card title={it.description}>
      <p className="flex items-baseline justify-between"><span>{it.type === 'income' ? 'Receita' : 'Despesa'} · {rule(it.rule)}</span><span className={`text-lg font-semibold tabular-nums ${it.type === 'income' ? '' : 'text-destructive'}`}>{it.type === 'income' ? '' : '-'}{formatBRL(it.amount_cents)}</span></p>
      <p>{it.type === 'income' ? 'Entra em' : 'Sai de'} {acc?.name ?? 'conta'}</p>
      <p>{it.active ? (it.next_due_on ? `Próxima data: ${br(it.next_due_on)}` : 'Encerrado') : 'Pausado'}{it.ends_on ? ` · até ${br(it.ends_on)}` : ''}</p>
      {owner && <Btn type="button" className="mt-2 bg-muted-foreground hover:bg-muted-foreground/90" disabled={toggle.isPending} onClick={() => toggle.mutate()}>{it.active ? 'Pausar' : 'Retomar'}</Btn>}
      <Err e={toggle.error} />
      <EditBox what="fixo" canEdit={owner}
        fields={[{ k: 'description', label: `Descrição de ${it.description}`, v: it.description }, { k: 'amount', label: `Valor (R$) de ${it.description}`, v: centsText(it.amount_cents) }, { k: 'account_id', label: `${it.type === 'income' ? 'Entra em' : 'Sai de'} (${it.description})`, v: it.account_id, options: accounts.data.map((a): [string, string] => [a.id, a.name]) }, { k: 'ends_on', label: `Fim de ${it.description}`, v: it.ends_on ?? '', type: 'date' }]}
        save={(v) => { const c = parseBRL(v.amount); return c ? api('PATCH', `/spaces/${it.space_id}/recurring/${it.id}`, { description: v.description, amount_cents: c, account_id: v.account_id, ends_on: v.ends_on || null }) : Promise.reject(new Error('invalid_amount')) }}
        remove={() => api('DELETE', `/spaces/${it.space_id}/recurring/${it.id}`)} />
    </Card>
  )
}

export function Recurring() {
  const { spaceId } = useSpace()
  const owner = useIsOwner()
  const items = useGet<RecurringItem[]>(`/spaces/${spaceId}/recurring`)
  const [add, setAdd] = useState(false)
  const list = items.data ?? []
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Despesas e receitas fixas</h1>
      {owner && <div className="mb-4"><PlusButton label="Novo fixo" onClick={() => setAdd(true)} /></div>}
      {add && <Modal title="Novo fixo" onClose={() => setAdd(false)}><NewItem onDone={() => setAdd(false)} /></Modal>}
      <Projection spaceId={spaceId} />
      {!items.isLoading && list.length === 0 && <p className="mb-4">Nenhum fixo ainda. Cadastre salário, aluguel, assinaturas… e o app lança no dia e projeta os próximos meses.</p>}
      <div className="grid gap-4 md:grid-cols-2">{list.map((it) => <ItemCard key={it.id} it={it} owner={owner} />)}</div>
      <Err e={items.error} />
    </>
  )
}
