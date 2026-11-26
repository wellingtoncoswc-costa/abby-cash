import { useState } from 'react'
import { api } from '../api/client'
import type { InvAsset, InvDashboard } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Btn, Card, Err, Field, today, useAccounts, useGet, useSend } from '../ui'

const KIND: Record<string, string> = { stock: 'Ações', fii: 'Fundos imobiliários', cdb: 'CDB', lci: 'LCI', lca: 'LCA' }
const VARIAVEL = ['stock', 'fii']
const pad2 = (n: number) => String(n).padStart(2, '0')
/** Pontos-base -> "+1,31%" (só inteiros). */
const fmtBp = (bp: number | null) => (bp == null ? '—' : `${bp < 0 ? '-' : '+'}${Math.trunc(Math.abs(bp) / 100)},${pad2(Math.abs(bp) % 100)}%`)
const fmtSigned = (c: number) => (c > 0 ? `+${formatBRL(c)}` : formatBRL(c))
/** "110" / "12,5" -> 11000 / 1250 (% x 100), sem float. */
const toBp = (v: string) => {
  const [i, f = ''] = v.trim().replace('.', ',').split(',')
  return /^\d+$/.test(i) && /^\d*$/.test(f) ? Number(i) * 100 + Number((f + '00').slice(0, 2)) : 0
}
const label = (a: InvAsset) => a.ticker ?? a.name

function Resumo({ d }: { d: InvDashboard }) {
  return (
    <Card title="Resumo">
      <p>Investido: {formatBRL(d.contributed_cents)}</p>
      <p>Valor atual: {formatBRL(d.current_cents)}</p>
      <p>Rentabilidade: {fmtSigned(d.profit_cents)} ({fmtBp(d.profit_bp)})</p>
    </Card>
  )
}

function Evolucao({ d }: { d: InvDashboard }) {
  const s = d.series
  if (s.length < 2) return null
  const max = Math.max(1, ...s.flatMap((p) => [p.value_cents, p.contributed_cents]))
  const pts = (k: 'value_cents' | 'contributed_cents') => s.map((p, i) => `${(i / (s.length - 1)) * 300},${100 - (p[k] / max) * 100}`).join(' ')
  return (
    <Card title="Evolução">
      <svg viewBox="0 0 300 100" className="w-full" role="img" aria-label={`Evolução: valor da carteira ${formatBRL(d.current_cents)} contra ${formatBRL(d.contributed_cents)} aportados`} preserveAspectRatio="none">
        <polyline points={pts('contributed_cents')} fill="none" stroke="var(--chart-3)" strokeWidth="1.5" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
        <polyline points={pts('value_cents')} fill="none" stroke="var(--chart-1)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="text-sm"><span style={{ color: 'var(--chart-1)' }}>━</span> Valor da carteira · <span style={{ color: 'var(--chart-3)' }}>╌</span> Aportado</p>
    </Card>
  )
}

function Alocacao({ d }: { d: InvDashboard }) {
  const total = d.by_kind.reduce((n, k) => n + k.value_cents, 0)
  if (!total) return null
  const pcts = d.by_kind.map((k) => (k.value_cents / total) * 100)
  const starts = pcts.map((_, i) => pcts.slice(0, i).reduce((n, p) => n + p, 0))
  return (
    <Card title="Alocação">
      <svg viewBox="0 0 36 36" className="mx-auto h-32 w-32" role="img" aria-label="Alocação por tipo">
        {d.by_kind.map((k, i) => {
          const pct = pcts[i]
          return <circle key={k.kind} cx="18" cy="18" r="15.9155" fill="none" stroke={`var(--chart-${(i % 5) + 1})`} strokeWidth="6" strokeDasharray={`${pct} ${100 - pct}`} strokeDashoffset={25 - starts[i]} />
        })}
      </svg>
      <ul>{d.by_kind.map((k, i) => <li key={k.kind}><span style={{ color: `var(--chart-${(i % 5) + 1})` }}>●</span> {KIND[k.kind]} {Math.round((k.value_cents / total) * 100)}% · {formatBRL(k.value_cents)}</li>)}</ul>
    </Card>
  )
}

function MovimentoForm({ a, kind, onDone }: { a: InvAsset; kind: 'buys' | 'redeems'; onDone: () => void }) {
  const accounts = useAccounts()
  const [f, setF] = useState({ acc: '', on: today(), qty: '', price: '', amount: '' })
  const variavel = VARIAVEL.includes(a.kind)
  const amount = parseBRL(f.amount)
  const price = f.price ? parseBRL(f.price) : undefined
  const body = variavel
    ? { account_id: f.acc, occurred_on: f.on, quantity: f.qty, ...(price ? { unit_price_cents: price } : {}) }
    : { account_id: f.acc, occurred_on: f.on, amount_cents: amount }
  const send = useSend(() => api('POST', `/investments/${a.id}/${kind}`, body), onDone)
  const ok = !!f.acc && (variavel ? !!f.qty : !!amount)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ok) send.mutate() }}>
      <Field label="Conta"><AccountSelect accounts={accounts.data} value={f.acc} onChange={(v) => setF({ ...f, acc: v })} /></Field>
      <Field label="Data"><input type="date" value={f.on} onChange={(e) => setF({ ...f, on: e.target.value })} /></Field>
      {variavel ? (
        <>
          <Field label="Quantidade"><input inputMode="decimal" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} /></Field>
          <Field label="Preço unitário (R$) — vazio usa o fechamento do dia"><input inputMode="decimal" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></Field>
        </>
      ) : (
        <Field label="Valor (R$)"><input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
      )}
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !ok}>{kind === 'buys' ? 'Confirmar aporte' : 'Confirmar resgate'}</Btn>
    </form>
  )
}

function Ativo({ a }: { a: InvAsset }) {
  const [open, setOpen] = useState<'buys' | 'redeems' | null>(null)
  return (
    <Card title={`${a.name}${a.ticker ? ` · ${a.ticker}` : ''}`}>
      <p>{KIND[a.kind]} · valor {formatBRL(a.value_cents)} · aportado {formatBRL(a.contributed_cents)}</p>
      {a.contributed_cents === 0 && <p>Sem aportes ainda. Clique em “Aportar em {label(a)}” para informar {VARIAVEL.includes(a.kind) ? 'a quantidade de cotas e a data' : 'o valor aportado e a data'}.</p>}
      <p>Rentabilidade: {fmtSigned(a.profit_cents)} ({fmtBp(a.profit_bp)})</p>
      {a.quantity != null && (
        <p>
          {a.quantity} cotas · preço médio {a.avg_price_cents != null ? formatBRL(a.avg_price_cents) : '—'} · atual {a.price_cents != null ? formatBRL(a.price_cents) : '—'}
          {a.quote_date ? ` (${a.quote_date.split('-').reverse().join('/')})` : ''} · dia {fmtBp(a.day_change_bp)}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <Btn type="button" onClick={() => setOpen(open === 'buys' ? null : 'buys')}>Aportar em {label(a)}</Btn>
        <Btn type="button" className="bg-muted-foreground hover:bg-muted-foreground/90" onClick={() => setOpen(open === 'redeems' ? null : 'redeems')}>Resgatar de {label(a)}</Btn>
      </div>
      {open && <MovimentoForm a={a} kind={open} onDone={() => setOpen(null)} />}
    </Card>
  )
}

function NovoAtivo() {
  const { spaceId } = useSpace()
  const empty = { kind: 'stock', name: '', ticker: '', rateType: 'cdi_pct', rate: '', maturity: '' }
  const [f, setF] = useState(empty)
  const variavel = VARIAVEL.includes(f.kind)
  const send = useSend(
    () => api('POST', `/spaces/${spaceId}/investments`, variavel
      ? { kind: f.kind, name: f.name, ticker: f.ticker }
      : { kind: f.kind, name: f.name, rate_type: f.rateType, rate_bp: toBp(f.rate), maturity_on: f.maturity || null }),
    () => setF(empty),
  )
  return (
    <Card title="Novo ativo">
      <form onSubmit={(e) => { e.preventDefault(); send.mutate() }}>
        <Field label="Tipo">
          <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Nome"><input required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        {variavel ? (
          <Field label="Ticker (ex.: PETR4)"><input required maxLength={12} value={f.ticker} onChange={(e) => setF({ ...f, ticker: e.target.value })} /></Field>
        ) : (
          <>
            <Field label="Rentabilidade">
              <select value={f.rateType} onChange={(e) => setF({ ...f, rateType: e.target.value })}>
                <option value="cdi_pct">% do CDI</option>
                <option value="fixed">Prefixada a.a.</option>
              </select>
            </Field>
            <Field label="Taxa (%)"><input inputMode="decimal" required value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} /></Field>
            <Field label="Vencimento (opcional)"><input type="date" value={f.maturity} onChange={(e) => setF({ ...f, maturity: e.target.value })} /></Field>
          </>
        )}
        <Err e={send.error} />
        <Btn type="submit" disabled={send.isPending || (!variavel && !toBp(f.rate))}>Cadastrar ativo</Btn>
      </form>
    </Card>
  )
}

export function Investments() {
  const { spaceId } = useSpace()
  const dash = useGet<InvDashboard>(`/spaces/${spaceId}/investments/dashboard`)
  const d = dash.data
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Investimentos</h1>
      <Err e={dash.error} />
      {d && !d.assets.length && <p className="mb-4">Você ainda não tem investimentos. Cadastre o primeiro ativo e faça um aporte.</p>}
      {d && d.assets.length > 0 && (<><Resumo d={d} /><Evolucao d={d} /><Alocacao d={d} />{d.assets.map((a) => <Ativo key={a.id} a={a} />)}</>)}
      <NovoAtivo />
    </>
  )
}
