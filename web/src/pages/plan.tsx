import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Budget as BudgetT, Goal, GoalPanel, Pocket, S } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Bar, Btn, Card, EditBox, Err, Field, br, centsText, monthKey, today, useAccounts, useCatName, useGet, useIsOwner, useSend, Modal, PlusButton } from '../ui'

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
        <Btn type="button" disabled={send.isPending || !cents || !acc} onClick={() => send.mutate('withdrawals')} className="bg-muted-foreground hover:bg-muted-foreground/90">Retirar</Btn>
      </div>
    </form>
  )
}

type Links = { accounts: string[]; pockets: string[] }

/** Quem já está em OUTRA meta (direto ou via conta/caixinha) fica indisponível, com o nome dela. */
function takenBy(goals: Goal[], self: string | undefined, pockets: Pocket[]) {
  const acc = new Map<string, string>(), pk = new Map<string, string>()
  const pocketAcc = new Map(pockets.map((p) => [p.id, p.account_id]))
  for (const g of goals.filter((x) => x.id !== self)) {
    for (const a of g.account_ids) {
      acc.set(a, g.name)
      pockets.filter((p) => p.account_id === a).forEach((p) => pk.set(p.id, g.name))
    }
    for (const p of g.pocket_ids) {
      pk.set(p, g.name)
      const a = pocketAcc.get(p)
      if (a) acc.set(a, g.name)
    }
  }
  return { acc, pk }
}

function GoalLinks({ goals, self, value, onChange }: { goals: Goal[]; self?: string; value: Links; onChange: (v: Links) => void }) {
  const accounts = useAccounts()
  const { spaceId } = useSpace()
  const pockets = useGet<Pocket[]>(`/spaces/${spaceId}/pockets`).data ?? []
  const taken = takenBy(goals, self, pockets)
  const toggle = (k: keyof Links, id: string) =>
    onChange({ ...value, [k]: value[k].includes(id) ? value[k].filter((x) => x !== id) : [...value[k], id] })
  const row = (k: keyof Links, id: string, label: string, by?: string) => (
    <label key={id} className="mb-1 flex items-center gap-2">
      <input type="checkbox" className="size-4 shrink-0" checked={value[k].includes(id)} disabled={!!by} onChange={() => toggle(k, id)} />
      {label}{by && <small> · já na meta {by}</small>}
    </label>
  )
  return (
    <fieldset className="mb-2">
      <legend>Contas e caixinhas da meta</legend>
      {accounts.data.map((a) => row('accounts', a.id, a.name, taken.acc.get(a.id)))}
      {pockets.map((p) => row('pockets', p.id, `Caixinha ${p.name}`, taken.pk.get(p.id)))}
    </fieldset>
  )
}

function GoalPanelView({ g }: { g: Goal }) {
  const p = useGet<GoalPanel>(`/goals/${g.id}/panel`)
  const d = p.data
  if (!d) return <p>Carregando…</p>
  return (
    <div className="mt-2">
      <h3 className="font-semibold">De onde vem o progresso</h3>
      <ul>
        <li className="flex justify-between"><span>Aportes diretos</span><span>{formatBRL(d.direct_cents)}</span></li>
        {d.accounts.map((a) => <li key={a.id} className="flex justify-between"><span>Conta {a.name}</span><span>{formatBRL(a.balance_cents)}</span></li>)}
        {d.pockets.map((k) => <li key={k.id} className="flex justify-between"><span>Caixinha {k.name}{k.counted ? '' : ' (já na conta)'}</span><span>{formatBRL(k.balance_cents)}</span></li>)}
        <li className="flex justify-between font-medium"><span>Total</span><span>{formatBRL(d.total_cents)}</span></li>
      </ul>
      <h3 className="mt-2 font-semibold">Aportes e retiradas</h3>
      {d.contributions.length === 0 && <p>Nenhum aporte direto ainda.</p>}
      <ul>{d.contributions.map((c, i) => <li key={i} className="flex justify-between"><span>{br(c.occurred_on)} {c.direction === 'in' ? 'Aporte' : 'Retirada'}</span><span>{c.direction === 'in' ? '' : '-'}{formatBRL(c.amount_cents)}</span></li>)}</ul>
      <Err e={p.error} />
    </div>
  )
}

function GoalPanelToggle({ g }: { g: Goal }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Btn type="button" className="mt-2 bg-muted-foreground hover:bg-muted-foreground/90" onClick={() => setOpen(!open)}>{open ? 'Ocultar painel' : 'Ver painel'}</Btn>
      {open && <GoalPanelView g={g} />}
    </>
  )
}

function GoalLinksEditor({ g, goals, canEdit }: { g: Goal; goals: Goal[]; canEdit: boolean }) {
  const [v, setV] = useState<Links>({ accounts: g.account_ids, pockets: g.pocket_ids })
  const save = useSend(() => api('PATCH', `/goals/${g.id}`, { account_ids: v.accounts, pocket_ids: v.pockets } satisfies S['GoalPatch']))
  return (
    <>
      <GoalLinks goals={goals} self={g.id} value={v} onChange={setV} />
      <Err e={save.error} />
      {canEdit && <Btn type="button" disabled={save.isPending} onClick={() => save.mutate()}>Salvar vínculos</Btn>}
    </>
  )
}

export function Goals() {
  const owner = useIsOwner()
  const { spaceId } = useSpace()
  const goals = useGet<Goal[]>(`/spaces/${spaceId}/goals`)
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ name: '', target: '', deadline: '' })
  const [links, setLinks] = useState<Links>({ accounts: [], pockets: [] })
  const cents = parseBRL(f.target)
  const create = useSend(
    () => api('POST', `/spaces/${spaceId}/goals`, { name: f.name, target_cents: cents!, deadline: f.deadline || null, account_ids: links.accounts, pocket_ids: links.pockets } satisfies S['GoalIn']),
    () => { setF({ name: '', target: '', deadline: '' }); setLinks({ accounts: [], pockets: [] }); setAdding(false) },
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Metas</h1>
      <div className="mb-4"><PlusButton label="Nova meta" onClick={() => setAdding(true)} /></div>
      {adding && <Modal title="Nova meta" onClose={() => setAdding(false)}>
        <form onSubmit={(e) => { e.preventDefault(); if (cents) create.mutate() }}>
          <Field label="Nome"><input required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Valor alvo (R$)"><input inputMode="decimal" required value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} /></Field>
          <Field label="Prazo (opcional)"><input type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
          <GoalLinks goals={goals.data ?? []} value={links} onChange={setLinks} />
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !cents}>Criar meta</Btn>
        </form>
      </Modal>}
      {(goals.data ?? []).map((g) => (
        <Card key={g.id} title={g.name}>
          <p>{formatBRL(g.saved_cents)} de {formatBRL(g.target_cents)}{g.deadline ? ` · até ${g.deadline.split('-').reverse().join('/')}` : ''}</p>
          <Bar value={g.saved_cents} max={g.target_cents} />
          {g.monthly_needed_cents != null && <p className={g.behind ? 'text-warning' : ''}>Necessário por mês: {formatBRL(g.monthly_needed_cents)}{g.behind ? ' (atrasada)' : ''}</p>}
          <GoalActions g={g} />
          <GoalPanelToggle g={g} />
          <GoalLinksEditor g={g} goals={goals.data ?? []} canEdit={owner} />
          <EditBox
            what="meta"
            canEdit={owner}
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
