import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Loan } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { Bar, Btn, Card, EditBox, Err, Field, br, centsText, useGet, useSend } from '../ui'

const KIND = { financing: 'Financiamento', consortium: 'Consórcio' }
const empty = { kind: 'financing', name: '', inst: '', total: '', first: '' }

export function Loans() {
  const { spaceId } = useSpace()
  const loans = useGet<Loan[]>(`/spaces/${spaceId}/loans`)
  const [f, setF] = useState(empty)
  const cents = parseBRL(f.inst)
  const total = /^\d{1,3}$/.test(f.total) ? Number(f.total) : 0
  const ok = !!cents && total >= 1 && total <= 480 && !!f.first
  const create = useSend(() => api('POST', `/spaces/${spaceId}/loans`, { kind: f.kind, name: f.name, installment_cents: cents!, installments_total: total, first_due_on: f.first }), () => setF(empty))
  const list = loans.data ?? []
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Financiamentos e consórcios</h1>
      <Card title="Novo">
        <form onSubmit={(e) => { e.preventDefault(); if (ok) create.mutate() }}>
          <Field label="Tipo">
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="financing">Financiamento</option><option value="consortium">Consórcio</option>
            </select>
          </Field>
          <Field label="Nome"><input required maxLength={200} placeholder="Carro, apartamento…" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Valor da parcela (R$)"><input inputMode="decimal" required value={f.inst} onChange={(e) => setF({ ...f, inst: e.target.value })} /></Field>
          <Field label="Quantidade de parcelas (1 a 480)"><input inputMode="numeric" required value={f.total} onChange={(e) => setF({ ...f, total: e.target.value })} /></Field>
          <Field label="Primeiro vencimento"><input type="date" required value={f.first} onChange={(e) => setF({ ...f, first: e.target.value })} /></Field>
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !ok}>Cadastrar</Btn>
        </form>
      </Card>
      {!loans.isLoading && !list.length && <p>Nenhum financiamento ou consórcio ainda. Cadastre um para acompanhar as parcelas, quanto falta e quando termina.</p>}
      {list.map((l) => (
        <Card key={l.id} title={l.name}>
          <p className="mb-2 text-sm text-muted-foreground">{KIND[l.kind]} · parcela de <span className="tabular-nums">{formatBRL(l.installment_cents)}</span></p>
          <Bar value={l.paid_count} max={l.installments_total} />
          <p className="mt-2">{l.paid_count} de {l.installments_total} pagas</p>
          <p>{l.remaining_count ? <>Faltam {l.remaining_count} {l.remaining_count === 1 ? 'parcela' : 'parcelas'} · <span className="tabular-nums">{formatBRL(l.remaining_cents)}</span></> : 'Quitado.'}</p>
          {l.next_due_on && <p>Próxima parcela: {br(l.next_due_on)}</p>}
          {l.last_due_on && <p>Previsão de término: {br(l.last_due_on)}</p>}
          <EditBox
            what={KIND[l.kind].toLowerCase()}
            fields={[{ k: 'name', label: `Nome de ${l.name}`, v: l.name }, { k: 'inst', label: `Parcela (R$) de ${l.name}`, v: centsText(l.installment_cents) }]}
            save={(v) => { const c = parseBRL(v.inst); return c ? api('PATCH', `/loans/${l.id}`, { name: v.name, installment_cents: c }) : Promise.reject(new ApiError(422, 'invalid_amount')) }}
            remove={() => api('DELETE', `/loans/${l.id}`)}
          />
        </Card>
      ))}
      <Err e={loans.error} />
    </>
  )
}
