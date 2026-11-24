import { useState } from 'react'
import { api } from '../api/client'
import type { S, Tx } from '../api/types'
import { parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Btn, Card, Err, Field, today, useAccounts, useGet, useSend } from '../ui'
import { TxList } from './dashboard'

export function Transactions() {
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const [flt, setFlt] = useState({ start: '', end: '', account_id: '', category_id: '' })
  const qs = new URLSearchParams(Object.entries(flt).filter(([, v]) => v)).toString()
  const list = useGet<Tx[]>(`/spaces/${spaceId}/transactions?limit=100${qs ? `&${qs}` : ''}`)
  const [f, setF] = useState({ type: 'expense' as S['TransactionIn']['type'], amount: '', description: '', account_id: '', occurred_on: today() })
  const cents = parseBRL(f.amount)
  const create = useSend(
    () => api('POST', `/spaces/${spaceId}/transactions`, { type: f.type, amount_cents: cents!, description: f.description, account_id: f.account_id, occurred_on: f.occurred_on } satisfies S['TransactionIn']),
    () => setF({ ...f, amount: '', description: '' }),
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Lançamentos</h1>
      <Card title="Novo lançamento">
        <form onSubmit={(e) => { e.preventDefault(); if (cents) create.mutate() }}>
          <Field label="Tipo"><select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as typeof f.type })}><option value="expense">Despesa</option><option value="income">Receita</option></select></Field>
          <Field label="Valor (R$)"><input inputMode="decimal" required placeholder="45,00" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Descrição"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Field label="Data"><input type="date" required value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
          <Field label="Conta"><AccountSelect accounts={accounts.data} value={f.account_id} onChange={(v) => setF({ ...f, account_id: v })} /></Field>
          {f.amount && !cents && <p role="alert" className="text-sm text-red-600">Valor inválido.</p>}
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !cents}>Salvar</Btn>
        </form>
      </Card>
      <Card title="Filtros">
        <div className="grid grid-cols-2 gap-2">
          <Field label="De"><input type="date" value={flt.start} onChange={(e) => setFlt({ ...flt, start: e.target.value })} /></Field>
          <Field label="Até"><input type="date" value={flt.end} onChange={(e) => setFlt({ ...flt, end: e.target.value })} /></Field>
          <Field label="Conta (filtro)"><select value={flt.account_id} onChange={(e) => setFlt({ ...flt, account_id: e.target.value })}><option value="">Todas</option>{accounts.data.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          <Field label="ID da categoria"><input value={flt.category_id} onChange={(e) => setFlt({ ...flt, category_id: e.target.value.trim() })} /></Field>
        </div>
      </Card>
      <Card>{list.isLoading ? <p>Carregando…</p> : (list.data ?? []).length === 0 ? <p>Nenhum lançamento.</p> : <TxList items={list.data ?? []} />}<Err e={list.error} /></Card>
    </>
  )
}
