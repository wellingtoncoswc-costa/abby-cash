import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Budget as BudgetT, Goal, S } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Bar, Btn, Card, EditBox, Err, Field, centsText, monthKey, today, useAccounts, useCatName, useGet, useSend } from '../ui'

export function BudgetForm({ month }: { month: string }) {
  const { spaceId } = useSpace()
  const catName = useCatName()
  const cur = useGet<BudgetT>(`/spaces/${spaceId}/budgets/${month}`)
  const [v, setV] = useState('')
  const cents = parseBRL(v)
  const save = useSend(() => api('PUT', `/spaces/${spaceId}/budgets/${month}`, { limit_cents: cents!, categories: (cur.data?.categories ?? []).map(({ category_id, limit_cents }) => ({ category_id, limit_cents })) } satisfies S['BudgetIn']), () => setV(''))
  const none = cur.error instanceof ApiError && cur.error.status === 404
  return (
    <>
      {cur.data && (
        <>
          <p className="mb-2">Gasto {formatBRL(cur.data.spent_cents)} de {formatBRL(cur.data.limit_cents)}</p>
          <Bar value={cur.data.spent_cents} max={cur.data.limit_cents} />
          <ul className="my-2">{cur.data.categories.map((c) => <li key={c.category_id} className="flex justify-between"><span>{catName(c.category_id)}</span><span>{formatBRL(c.spent_cents)} / {formatBRL(c.limit_cents)}</span></li>)}</ul>
        </>
      )}
      {none && <p>Sem teto para este mês.</p>}
      <form onSubmit={(e) => { e.preventDefault(); if (cents) save.mutate() }}>
        <Field label="Teto do mês (R$)"><input inputMode="decimal" required placeholder="3.000,00" value={v} onChange={(e) => setV(e.target.value)} /></Field>
        <Err e={save.error} />
        <Btn type="submit" disabled={save.isPending || !cents}>Salvar teto</Btn>
      </form>
    </>
  )
}

export function Budget() {
  const [month, setMonth] = useState(monthKey())
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Teto do mês</h1>
      <Card>
        <Field label="Mês"><input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></Field>
        <BudgetForm month={month} />
      </Card>
    </>
  )
}

function GoalActions({ g }: { g: Goal }) {
  const accounts = useAccounts()
  const [acc, setAcc] = useState('')
  const [amt, setAmt] = useState('')
  const cents = parseBRL(amt)
  const send = useSend((kind: 'contributions' | 'withdrawals') =>
    api('POST', `/goals/${g.id}/${kind}`, (kind === 'contributions' ? { from_account_id: acc, amount_cents: cents!, occurred_on: today() } satisfies S['ContributionIn'] : { to_account_id: acc, amount_cents: cents!, occurred_on: today() } satisfies S['WithdrawalIn'])),
    () => setAmt(''))
  return (
    <form className="mt-2" onSubmit={(e) => e.preventDefault()}>
      <Field label="Conta"><AccountSelect accounts={accounts.data} value={acc} onChange={setAcc} /></Field>
      <Field label="Valor (R$)"><input inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
      <Err e={send.error} />
      <div className="flex gap-2">
        <Btn type="button" disabled={send.isPending || !cents || !acc} onClick={() => send.mutate('contributions')}>Aportar</Btn>
        <Btn type="button" disabled={send.isPending || !cents || !acc} onClick={() => send.mutate('withdrawals')} className="bg-slate-600 hover:bg-slate-700">Retirar</Btn>
      </div>
    </form>
  )
}

export function Goals() {
  const { spaceId } = useSpace()
  const goals = useGet<Goal[]>(`/spaces/${spaceId}/goals`)
  const [f, setF] = useState({ name: '', target: '', deadline: '' })
  const cents = parseBRL(f.target)
  const create = useSend(
    () => api('POST', `/spaces/${spaceId}/goals`, { name: f.name, target_cents: cents!, deadline: f.deadline || null } satisfies S['GoalIn']),
    () => setF({ name: '', target: '', deadline: '' }),
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Metas</h1>
      <Card title="Nova meta">
        <form onSubmit={(e) => { e.preventDefault(); if (cents) create.mutate() }}>
          <Field label="Nome"><input required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Valor alvo (R$)"><input inputMode="decimal" required value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} /></Field>
          <Field label="Prazo (opcional)"><input type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !cents}>Criar meta</Btn>
        </form>
      </Card>
      {(goals.data ?? []).map((g) => (
        <Card key={g.id} title={g.name}>
          <p>{formatBRL(g.saved_cents)} de {formatBRL(g.target_cents)}{g.deadline ? ` · até ${g.deadline.split('-').reverse().join('/')}` : ''}</p>
          <Bar value={g.saved_cents} max={g.target_cents} />
          {g.monthly_needed_cents != null && <p className={g.behind ? 'text-amber-600' : ''}>Necessário por mês: {formatBRL(g.monthly_needed_cents)}{g.behind ? ' (atrasada)' : ''}</p>}
          <GoalActions g={g} />
          <EditBox
            what="meta"
            fields={[{ k: 'name', label: 'Nome da meta', v: g.name }, { k: 'target', label: 'Valor alvo (R$) da meta', v: centsText(g.target_cents) }, { k: 'deadline', label: 'Prazo da meta', v: g.deadline ?? '', type: 'date' }]}
            save={(v) => { const t = parseBRL(v.target); return t ? api('PATCH', `/goals/${g.id}`, { name: v.name, target_cents: t, deadline: v.deadline || null } satisfies S['GoalPatch']) : Promise.reject(new ApiError(422, 'invalid_amount')) }}
            remove={() => api('DELETE', `/goals/${g.id}`)}
          />
        </Card>
      ))}
      <Err e={goals.error} />
    </>
  )
}
