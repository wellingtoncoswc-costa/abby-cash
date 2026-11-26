import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Account, AccountIn, AccountPanel, AccountPatch } from '../api/types'
import { BankIcon, BankSelect } from '../bank-icon'
import { BANK_LIST } from '../banks'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { Btn, Card, EditBox, Err, Field, br, centsText, monthKey, useAccounts, useCatName, useGet, useIsOwner, useSend, Modal, PlusButton } from '../ui'

const TYPE: Record<string, string> = { checking: 'Conta corrente', savings: 'Poupança', wallet: 'Carteira' }
const pctOf = (v: number, max: number) => (max > 0 ? Math.round((v / max) * 100) : 0)

function PanelView({ a }: { a: Account }) {
  const [month, setMonth] = useState(monthKey())
  const p = useGet<AccountPanel>(`/accounts/${a.id}/panel?month=${month}`)
  const catName = useCatName()
  const d = p.data
  return (
    <div className="mt-2">
      <Field label="Mês"><input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></Field>
      <Err e={p.error} />
      {!d ? <p>Carregando…</p> : (
        <>
          <p>Entradas {formatBRL(d.income_cents)} · Saídas {formatBRL(d.expense_cents)} · Transferências {formatBRL(d.transfer_net_cents)}</p>
          {d.private_total_cents !== 0 && <p>Outros lançamentos (privados): {formatBRL(d.private_total_cents)}</p>}
          <h3 className="mt-2 font-semibold">Gastos por categoria</h3>
          {d.by_category.length === 0 && <p>Sem gastos no mês.</p>}
          <ul>{d.by_category.map((c) => (
            <li key={c.category_id ?? 'none'}>
              <div className="flex justify-between"><span>{catName(c.category_id)}</span><span>{formatBRL(c.total_cents)}</span></div>
              <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${pctOf(c.total_cents, d.by_category[0].total_cents)}%` }} /></div>
            </li>
          ))}</ul>
          <h3 className="mt-2 font-semibold">Últimas movimentações</h3>
          <ul>{d.recent.map((r, i) => <li key={i} className="flex justify-between"><span>{br(r.occurred_on)} {r.description || r.merchant}</span><span>{formatBRL(r.amount_cents)}</span></li>)}</ul>
          {d.pockets.length > 0 && (<><h3 className="mt-2 font-semibold">Caixinhas</h3><ul>{d.pockets.map((k) => <li key={k.id} className="flex justify-between"><span>{k.name}</span><span>{formatBRL(k.balance_cents)}</span></li>)}</ul></>)}
          {d.goals.length > 0 && (<><h3 className="mt-2 font-semibold">Metas ligadas</h3><ul>{d.goals.map((g) => <li key={g.id}>{g.name}</li>)}</ul></>)}
        </>
      )}
    </div>
  )
}

function AccountTile({ a, owner }: { a: Account; owner: boolean }) {
  const [open, setOpen] = useState(false)
  const sum = useGet<AccountPanel>(`/accounts/${a.id}/panel`)
  const makeDefault = useSend(() => api('PUT', `/spaces/${a.space_id}/default-account`, { account_id: a.id }))
  return (
    <Card title={a.name}>
      <p className="flex items-center gap-2"><BankIcon institution={a.institution} name={a.name} />{BANK_LIST.find((b) => b.key === a.institution)?.name ?? 'Banco não informado'} · {TYPE[a.type] ?? a.type}{sum.data?.is_default && <> · <strong>padrão</strong></>}</p>
      <p className="flex items-baseline justify-between"><span>Saldo</span><span className={`text-lg font-semibold tabular-nums ${a.available_cents < 0 ? 'text-destructive' : ''}`}>{formatBRL(a.available_cents)}</span></p>
      {a.pockets_cents > 0 && <p className="text-sm text-muted-foreground">Guardado em caixinhas (fora do saldo): <span className="tabular-nums">{formatBRL(a.pockets_cents)}</span></p>}
      {a.available_cents < 0 && <p role="note" className="text-sm text-destructive">Saldo negativo.</p>}
      <div className="my-2 flex flex-wrap gap-2">
        <Link to="/lancamentos" className="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground">Transferir</Link>
        {!sum.data?.is_default && <Btn type="button" disabled={makeDefault.isPending} onClick={() => makeDefault.mutate()}>Tornar padrão</Btn>}
        <Btn type="button" onClick={() => setOpen(!open)} className="bg-muted-foreground hover:bg-muted-foreground/90">{open ? 'Ocultar painel' : 'Ver painel'}</Btn>
      </div>
      <Err e={makeDefault.error} />
      {open && <PanelView a={a} />}
      <EditBox what="conta" canEdit={owner} fields={[{ k: 'name', label: `Nome da conta ${a.name}`, v: a.name }, { k: 'bal', label: `Saldo inicial (R$) de ${a.name}`, v: centsText(a.initial_balance_cents) }, { k: 'inst', label: `Banco de ${a.name}`, v: a.institution ?? '', options: [['', 'Não informado'], ...BANK_LIST.map((b) => [b.key, b.name] as [string, string])] }]}
        save={(v) => { const b = parseBRL(v.bal); return b === null ? Promise.reject(new ApiError(422, 'invalid_amount')) : api('PATCH', `/accounts/${a.id}`, { name: v.name, initial_balance_cents: b, institution: v.inst || null } satisfies AccountPatch) }}
        remove={() => api('DELETE', `/accounts/${a.id}`)} />
    </Card>
  )
}

export function Accounts() {
  const owner = useIsOwner()
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ type: 'checking', name: '', balance: '', institution: '' })
  const bal = f.balance ? parseBRL(f.balance) : 0
  const add = useSend(
    () => api('POST', `/spaces/${spaceId}/accounts`, { type: f.type as 'checking', name: f.name, initial_balance_cents: bal ?? 0, institution: f.institution || null } satisfies AccountIn),
    () => { setF({ ...f, name: '', balance: '', institution: '' }); setAdding(false) },
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Contas bancárias</h1>
      <div className="mb-4"><PlusButton label="Nova conta" onClick={() => setAdding(true)} /></div>
      {adding && <Modal title="Nova conta" onClose={() => setAdding(false)}>
        <form onSubmit={(e) => { e.preventDefault(); if (bal !== null) add.mutate() }}>
          <Field label="Tipo"><select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="checking">Conta corrente</option><option value="savings">Poupança</option><option value="wallet">Carteira</option></select></Field>
          <Field label="Nome da conta"><input required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Banco"><BankSelect value={f.institution} onChange={(v) => setF({ ...f, institution: v })} name={f.name} /></Field>
          <Field label="Saldo inicial (R$)"><input inputMode="decimal" placeholder="0,00" value={f.balance} onChange={(e) => setF({ ...f, balance: e.target.value })} /></Field>
          <Err e={add.error} />
          <Btn type="submit" disabled={add.isPending || bal === null}>Adicionar conta</Btn>
        </form>
      </Modal>}
      {!accounts.isLoading && accounts.data.length === 0 && <p className="mb-4">Nenhuma conta neste espaço.</p>}
      <div className="grid gap-4 md:grid-cols-2">{accounts.data.map((a) => <AccountTile key={a.id} a={a} owner={owner} />)}</div>
    </>
  )
}
