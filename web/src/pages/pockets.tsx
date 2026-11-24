import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Account, Cdi, Pocket } from '../api/types'
import { BankIcon } from '../bank-icon'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { Btn, Card, EditBox, Err, Field, centsText, today, useAccounts, useGet, useSend } from '../ui'

/** "120" | "112,5" -> cdi_bp inteiro (12000 | 11250), sem float; null se inválido (faixa 1..100000). */
export function parsePct(text: string): number | null {
  const m = /^\s*(\d{1,4})(?:[,.](\d{1,2}))?\s*$/.exec(text)
  if (!m) return null
  const bp = Number(m[1]) * 100 + Number((m[2] ?? '').padEnd(2, '0'))
  return bp >= 1 && bp <= 100000 ? bp : null
}
const pctText = (bp: number) => (bp % 100 ? centsText(bp) : String(bp / 100))

function CdiPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Rende quanto do CDI (%)">
      <div className="flex flex-wrap gap-2">
        {['100', '110', '120'].map((p) => (
          <button key={p} type="button" aria-pressed={value === p} onClick={() => onChange(p)}
            className={`rounded-full border px-3 py-1 text-sm ${value === p ? 'border-primary bg-primary text-primary-foreground' : 'border-border'}`}>{p}%</button>
        ))}
        <input aria-label="Outro percentual do CDI" inputMode="decimal" placeholder="Outro, ex. 102,5" className="w-40" value={value} onChange={(e) => onChange(e.target.value)} />
      </div>
    </Field>
  )
}

function PocketActions({ p, acc }: { p: Pocket; acc?: Account }) {
  const [amt, setAmt] = useState('')
  const cents = parseBRL(amt)
  const send = useSend((kind: 'deposit' | 'withdraw') => api('POST', `/pockets/${p.id}/${kind}`, { amount_cents: cents!, occurred_on: today() }), () => setAmt(''))
  const over = cents != null && acc?.available_cents != null && cents > acc.available_cents
  return (
    <form className="mt-2" onSubmit={(e) => e.preventDefault()}>
      <Field label={`Valor (R$) para ${p.name}`}><input inputMode="decimal" placeholder="100,00" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
      {acc?.available_cents != null && <p className="mb-2 text-sm text-muted-foreground">Disponível na conta: <span className="tabular-nums">{formatBRL(acc.available_cents)}</span></p>}
      {over && <p role="status" className="mb-2 text-sm text-warning">Esse valor é maior que o disponível na conta; só dá para resgatar, não depositar.</p>}
      <Err e={send.error} />
      <div className="flex gap-2">
        <Btn type="button" disabled={send.isPending || !cents || over} onClick={() => send.mutate('deposit')}>Depositar</Btn>
        <Btn type="button" disabled={send.isPending || !cents} onClick={() => send.mutate('withdraw')} className="bg-muted-foreground hover:bg-muted-foreground/90">Resgatar</Btn>
      </div>
    </form>
  )
}

export function Pockets() {
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const pockets = useGet<Pocket[]>(`/spaces/${spaceId}/pockets`)
  const cdi = useGet<Cdi>('/cdi/latest')
  const [f, setF] = useState({ name: '', account: '', pct: '100' })
  const bp = parsePct(f.pct)
  const create = useSend(() => api('POST', `/spaces/${spaceId}/pockets`, { account_id: f.account, name: f.name, cdi_bp: bp! }), () => setF({ ...f, name: '' }))
  const list = pockets.data ?? []
  return (
    <>
      <h1 className="mb-1 text-xl font-bold">Caixinhas</h1>
      {cdi.data && <p className="mb-3 text-sm text-muted-foreground">CDI hoje: {String(cdi.data.annual_pct).replace('.', ',')}% a.a.</p>}
      <Card title="Nova caixinha">
        <form onSubmit={(e) => { e.preventDefault(); if (bp && f.account) create.mutate() }}>
          <Field label="Nome"><input required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Conta">
            <select required value={f.account} onChange={(e) => setF({ ...f, account: e.target.value })}>
              <option value="">Selecione…</option>
              {accounts.data.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <CdiPicker value={f.pct} onChange={(pct) => setF({ ...f, pct })} />
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !bp || !f.account}>Criar caixinha</Btn>
        </form>
      </Card>
      {!pockets.isLoading && !list.length && <p className="mb-4">Você ainda não tem caixinhas. Crie a primeira para separar um dinheiro que rende pelo CDI.</p>}
      {accounts.data.filter((a) => list.some((p) => p.account_id === a.id)).map((a) => (
        <Card key={a.id} title="">
          <div className="mb-3 flex items-center gap-2"><BankIcon institution={a.institution} name={a.name} /><h2 className="font-semibold">{a.name}</h2></div>
          {list.filter((p) => p.account_id === a.id).map((p) => (
            <div key={p.id} className="mb-3 rounded-xl bg-muted/50 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{p.name}</span>
                <span className="text-lg font-semibold tabular-nums">{formatBRL(p.balance_cents)}</span>
              </div>
              <p className="text-sm text-muted-foreground">{pctText(p.cdi_bp)}% do CDI · rendeu <span className="tabular-nums">{formatBRL(p.month_yield_cents)}</span> no mês</p>
              <PocketActions p={p} acc={a} />
              <EditBox
                what="caixinha"
                fields={[{ k: 'name', label: `Nome de ${p.name}`, v: p.name }, { k: 'pct', label: `% do CDI de ${p.name}`, v: pctText(p.cdi_bp) }]}
                save={(v) => { const b = parsePct(v.pct); return b ? api('PATCH', `/pockets/${p.id}`, { name: v.name, cdi_bp: b }) : Promise.reject(new ApiError(422, 'invalid_amount')) }}
                remove={() => api('DELETE', `/pockets/${p.id}`)}
              />
            </div>
          ))}
        </Card>
      ))}
      <Err e={pockets.error} />
    </>
  )
}
