import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { BankIcon, BankSelect } from '../bank-icon'
import { BANK_LIST } from '../banks'
import type { AccountIn, AccountPatch, S } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { Btn, Card, EditBox, Err, Field, centsText, monthKey, useAccounts, useIsOwner, useSend } from '../ui'
import { CardForm } from './billing'
import { BudgetForm } from './plan'
import { LinkChannel } from './settings'

export function Onboarding() {
  const owner = useIsOwner()
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const [a, setA] = useState({ type: 'checking', name: '', balance: '', institution: '' })
  const bal = a.balance ? parseBRL(a.balance) : 0
  const addAcc = useSend(
    () => api('POST', `/spaces/${spaceId}/accounts`, { type: a.type as 'checking', name: a.name, initial_balance_cents: bal ?? 0, institution: a.institution || null } satisfies AccountIn),
    () => setA({ ...a, name: '', balance: '', institution: '' }),
  )
  const [c, setC] = useState({ name: '', closing_day: '5', due_day: '12', limit: '' })
  const lim = c.limit ? parseBRL(c.limit) : null
  const addCard = useSend(
    () => api('POST', `/spaces/${spaceId}/cards`, { name: c.name, closing_day: Number(c.closing_day), due_day: Number(c.due_day), limit_cents: lim } satisfies S['CardIn']),
    () => setC({ ...c, name: '', limit: '' }),
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Primeiros passos</h1>
      <Card title="1. Contas">
        <ul className="mb-2">{accounts.data.map((x) => (
          <li key={x.id}><span className="flex items-center gap-2"><BankIcon institution={x.institution} name={x.name} />{x.name} · {formatBRL(x.initial_balance_cents)}</span>
            <EditBox what="conta" canEdit={owner} fields={[{ k: 'name', label: `Nome da conta ${x.name}`, v: x.name }, { k: 'bal', label: `Saldo inicial (R$) de ${x.name}`, v: centsText(x.initial_balance_cents) }, { k: 'inst', label: `Banco de ${x.name}`, v: x.institution ?? '', options: [['', 'Não informado'], ...BANK_LIST.map((b) => [b.key, b.name] as [string, string])] }]}
              save={(v) => { const b = parseBRL(v.bal); return b === null ? Promise.reject(new ApiError(422, 'invalid_amount')) : api('PATCH', `/accounts/${x.id}`, { name: v.name, initial_balance_cents: b, institution: v.inst || null } satisfies AccountPatch) }}
              remove={() => api('DELETE', `/accounts/${x.id}`)} />
          </li>
        ))}</ul>
        <form onSubmit={(e) => { e.preventDefault(); if (bal !== null) addAcc.mutate() }}>
          <Field label="Tipo"><select value={a.type} onChange={(e) => setA({ ...a, type: e.target.value })}><option value="checking">Conta corrente</option><option value="savings">Poupança</option><option value="wallet">Carteira</option></select></Field>
          <Field label="Nome da conta"><input required maxLength={100} value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></Field>
          <Field label="Banco"><BankSelect value={a.institution} onChange={(v) => setA({ ...a, institution: v })} name={a.name} /></Field>
          <Field label="Saldo inicial (R$)"><input inputMode="decimal" placeholder="0,00" value={a.balance} onChange={(e) => setA({ ...a, balance: e.target.value })} /></Field>
          <Err e={addAcc.error} />
          <Btn type="submit" disabled={addAcc.isPending || bal === null}>Adicionar conta</Btn>
        </form>
      </Card>
      <Card title="2. Cartão de crédito"><CardForm f={c} setF={setC} onSubmit={() => addCard.mutate()} err={addCard.error} busy={addCard.isPending} lim={lim} />{addCard.isSuccess && <p>Cartão adicionado.</p>}</Card>
      <Card title="3. Teto do mês"><BudgetForm month={monthKey()} /></Card>
      <Card title="4. Vincular Telegram ou WhatsApp"><LinkChannel /></Card>
      <Link to="/" className="underline">Ir para o painel</Link>
    </>
  )
}

export function Invite() {
  const { token } = useParams({ strict: false }) as { token?: string }
  const nav = useNavigate()
  const accept = useSend(() => api('POST', '/spaces/invites/accept', { token: token ?? '' }), () => void nav({ to: '/espacos' }))
  return (
    <Card title="Convite para um espaço">
      <p className="mb-2">Aceitar entrar no espaço familiar?</p>
      <Err e={accept.error} />
      <Btn onClick={() => accept.mutate()} disabled={accept.isPending}>Aceitar convite</Btn>
    </Card>
  )
}
