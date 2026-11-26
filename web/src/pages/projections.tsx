import { useState } from 'react'
import type { Projections } from '../api/types'
import { formatBRL } from '../lib/money'
import { useSpace } from '../space'
import { Card, Err, Field, br, useGet } from '../ui'

const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const lab = (m: string) => `${MES[Number(m.slice(5, 7)) - 1]}/${m.slice(2, 4)}`
const pct = (bp: number | null) => (bp == null ? '—' : `${Math.trunc(bp / 100)},${String(bp % 100).padStart(2, '0')}%`)
const C = { income: 'var(--chart-1)', fixed: 'var(--chart-2)', loans: 'var(--chart-3)', cards: 'var(--chart-4)', bills: 'var(--chart-5)', est: 'color-mix(in oklab, var(--chart-2) 35%, transparent)' }

type Row = { key: string; label: string; income: number; est: boolean; parts: [number, string][] }

function ResultChart({ d, est }: { d: Projections; est: boolean }) {
  const rows: Row[] = [
    ...d.history.map((h): Row => ({ key: `h${h.month}`, label: lab(h.month), income: h.income_cents, est: false, parts: [[h.expense_cents, C.fixed]] })),
    ...d.months.map((m): Row => ({
      key: `p${m.month}`, label: lab(m.month), income: m.income_fixed_cents + (est ? m.income_estimated_cents : 0), est: true,
      parts: [[m.expense_fixed_cents, C.fixed], [m.expense_loans_cents, C.loans], [m.expense_cards_cents, C.cards], [m.expense_bills_cents, C.bills], [est ? m.expense_estimated_cents : 0, C.est]],
    })),
  ]
  const max = Math.max(1, ...rows.flatMap((r) => [r.income, r.parts.reduce((s, p) => s + p[0], 0)]))
  const w = 600 / rows.length
  const y = (v: number) => 140 - (v / max) * 130
  return (
    <svg viewBox="0 0 600 170" className="w-full" role="img" aria-label="Receitas e despesas: 12 meses reais e meses projetados">
      {rows.map((r, i) => {
        let top = 140
        return (
          <g key={r.key} opacity={r.est ? 1 : 0.85}>
            <rect x={i * w + w * 0.1} y={y(r.income)} width={w * 0.36} height={140 - y(r.income)} fill={C.income} rx="1" />
            {r.parts.map(([v, color], j) => { top -= (v / max) * 130; return v > 0 ? <rect key={j} x={i * w + w * 0.52} y={top} width={w * 0.36} height={(v / max) * 130} fill={color} /> : null })}
            <text x={i * w + w / 2} y={155} fontSize="7" textAnchor="middle" fill="currentColor">{r.label}</text>
          </g>
        )
      })}
      <line x1={d.history.length * w} x2={d.history.length * w} y1="0" y2="145" stroke="currentColor" strokeDasharray="3 3" opacity="0.5" />
      <text x={d.history.length * w + 3} y="8" fontSize="7" fill="currentColor">Projeção →</text>
    </svg>
  )
}

function BalanceChart({ d, est }: { d: Projections; est: boolean }) {
  const hist = d.history.map((h) => h.balance_cents)
  const proj = d.months.map((m) => (est ? m.projected_balance_cents : m.projected_balance_committed_cents))
  const comm = d.months.map((m) => m.projected_balance_committed_cents)
  const all = [...hist, ...proj, ...comm]
  const lo = Math.min(...all), hi = Math.max(...all), span = Math.max(1, hi - lo)
  const n = hist.length + proj.length
  const pt = (i: number, v: number) => `${(i / (n - 1)) * 600},${130 - ((v - lo) / span) * 120}`
  const line = (vals: number[], off: number) => vals.map((v, i) => pt(off + i, v)).join(' ')
  const off = hist.length - 1
  return (
    <svg viewBox="0 0 600 150" className="w-full" role="img" aria-label="Saldo real e saldo projetado">
      <polyline points={line(hist, 0)} fill="none" stroke={C.income} strokeWidth="2" vectorEffect="non-scaling-stroke" />
      <polyline points={line([hist[off], ...proj], off)} fill="none" stroke={C.fixed} strokeWidth="2" strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />
      {est && <polyline points={line([hist[off], ...comm], off)} fill="none" stroke={C.loans} strokeWidth="1.5" strokeDasharray="1 3" vectorEffect="non-scaling-stroke" />}
    </svg>
  )
}

function Donut({ parts }: { parts: [string, number, string][] }) {
  const total = parts.reduce((s, p) => s + p[1], 0)
  if (!total) return <p>Sem despesas projetadas.</p>
  const pcts = parts.map((p) => (p[1] / total) * 100)
  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 36 36" className="h-32 w-32" role="img" aria-label="Composição das despesas projetadas">
        {parts.map((p, i) => <circle key={p[0]} cx="18" cy="18" r="15.9155" fill="none" stroke={p[2]} strokeWidth="6" strokeDasharray={`${pcts[i]} ${100 - pcts[i]}`} strokeDashoffset={25 - pcts.slice(0, i).reduce((s, v) => s + v, 0)} />)}
      </svg>
      <ul>{parts.filter((p) => p[1] > 0).map((p) => <li key={p[0]}><span style={{ color: p[2] }}>●</span> {p[0]} {formatBRL(p[1])} ({Math.round((p[1] / total) * 100)}%)</li>)}</ul>
    </div>
  )
}

export function ProjectionsPage() {
  const { spaceId } = useSpace()
  const [months, setMonths] = useState('12')
  const [est, setEst] = useState(true)
  const p = useGet<Projections>(`/spaces/${spaceId}/projections?months=${months}`)
  const d = p.data
  const sum = (f: (m: Projections['months'][number]) => number) => (d ? d.months.reduce((s, m) => s + f(m), 0) : 0)
  const net = d ? d.months.map((m) => (est ? m.net_cents : m.net_committed_cents)) : []
  const avgNet = net.length ? Math.trunc(net.reduce((s, v) => s + v, 0) / net.length) : 0
  const last = d?.loans_ending.at(-1)
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Projeções</h1>
      <Card>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Horizonte"><select value={months} onChange={(e) => setMonths(e.target.value)}><option value="6">6 meses</option><option value="12">12 meses</option></select></Field>
          <label className="mb-3 flex items-center gap-2 self-end"><input type="checkbox" className="size-4 shrink-0" checked={est} onChange={(e) => setEst(e.target.checked)} />Mostrar estimativa de variáveis</label>
        </div>
      </Card>
      <Err e={p.error} />
      {!d ? <p>Carregando…</p> : (
        <>
          <Card title="Resumo">
            <p>Saldo atual: {formatBRL(d.current_balance_cents)}</p>
            <p>Resultado médio projetado por mês: <span className={avgNet < 0 ? 'text-destructive' : ''}>{formatBRL(avgNet)}</span></p>
            <p>Comprometimento da renda fixa no próximo mês: {pct(d.months[1]?.commitment_bp ?? d.months[0].commitment_bp)}</p>
            <p>Média real dos últimos 12 meses: receitas {formatBRL(d.averages.history_income_cents)} · despesas {formatBRL(d.averages.history_expense_cents)}</p>
            {est && <p>Estimativa de variáveis por mês: receitas {formatBRL(d.averages.estimated_income_cents)} · despesas {formatBRL(d.averages.estimated_expense_cents)} (média dos 3 últimos meses)</p>}
            {last && <p>Último financiamento termina em {br(last.last_due_on)}.</p>}
          </Card>
          <Card title="Receitas e despesas">
            <ResultChart d={d} est={est} />
            <p className="text-sm"><span style={{ color: C.income }}>■</span> Receitas · <span style={{ color: C.fixed }}>■</span> Despesas/fixos · <span style={{ color: C.loans }}>■</span> Financiamentos · <span style={{ color: C.cards }}>■</span> Cartão · <span style={{ color: C.bills }}>■</span> Contas · <span style={{ color: C.est }}>■</span> Estimado</p>
          </Card>
          <Card title="Saldo">
            <BalanceChart d={d} est={est} />
            <p className="text-sm">Linha cheia: real · tracejada: projetado{est ? ' · pontilhada: só compromissos' : ''}</p>
          </Card>
          <Card title="Composição das despesas projetadas">
            <Donut parts={[['Fixos', sum((m) => m.expense_fixed_cents), C.fixed], ['Financiamentos e consórcios', sum((m) => m.expense_loans_cents), C.loans], ['Faturas de cartão', sum((m) => m.expense_cards_cents), C.cards], ['Contas a pagar', sum((m) => m.expense_bills_cents), C.bills], ...(est ? [['Variáveis (estimado)', sum((m) => m.expense_estimated_cents), C.est] as [string, number, string]] : [])]} />
          </Card>
          <Card title="Comprometimento da renda fixa">
            <ul>{d.months.map((m) => (
              <li key={m.month}>
                <div className="flex justify-between"><span>{lab(m.month)}</span><span>{pct(m.commitment_bp)}</span></div>
                <div className="h-2 rounded bg-muted" aria-hidden="true"><div className="h-2 rounded" style={{ width: `${Math.min(100, Math.round((m.commitment_bp ?? 0) / 100))}%`, background: (m.commitment_bp ?? 0) > 10000 ? 'var(--destructive)' : C.fixed }} /></div>
              </li>
            ))}</ul>
          </Card>
          <Card title="Fim dos financiamentos e consórcios">
            {d.loans_ending.length === 0 && <p>Nenhum financiamento ou consórcio em andamento.</p>}
            <ul>{d.loans_ending.map((l) => <li key={l.loan_id}>{l.name}: termina em {br(l.last_due_on)} · faltam {l.remaining_count} · libera {formatBRL(l.installment_cents)} por mês</li>)}</ul>
          </Card>
          <Card title="Mês a mês">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th scope="col" className="text-left">Mês</th><th scope="col">Receitas</th><th scope="col">Despesas</th><th scope="col">Resultado</th><th scope="col">Saldo</th></tr></thead>
                <tbody>{d.months.map((m) => {
                  const inc = m.income_fixed_cents + (est ? m.income_estimated_cents : 0)
                  const exp = m.expense_fixed_cents + m.expense_loans_cents + m.expense_cards_cents + m.expense_bills_cents + (est ? m.expense_estimated_cents : 0)
                  return <tr key={m.month}><th scope="row" className="text-left">{lab(m.month)}</th><td className="tabular-nums">{formatBRL(inc)}</td><td className="tabular-nums">{formatBRL(exp)}</td><td className="tabular-nums">{formatBRL(inc - exp)}</td><td className="tabular-nums">{formatBRL(est ? m.projected_balance_cents : m.projected_balance_committed_cents)}</td></tr>
                })}</tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  )
}
