import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { ArrowDown, ArrowUp, Download, X } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Area, AreaChart, Bar, CartesianGrid, Cell, ComposedChart, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { OverviewOut, ReportTotals, Tx } from '../api/types'
import { podeAnimar, useCountUp } from '../anim'
import { downloadCsv, type Filters, listQuery, monthRange, parseFilters, PERIODS, pctChange, reportQuery, resolveRange, toCsv, wholeMonth } from '../lib/reports'
import { formatBRL } from '../lib/money'
import { useSpace } from '../space'
import { br, Err, today, useAccounts, useCategories, useCatName, useGet } from '../ui'
import { TxList } from './dashboard'
import { TxDetail } from './transactions'

const SERIES = [1, 2, 3, 4, 5].map((n) => `var(--chart-${n})`).concat([1, 2, 3].map((n) => `color-mix(in oklab, var(--chart-${n}) 60%, transparent)`))
const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const DOW = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
const animar = podeAnimar()
const mesCurto = (m: string) => `${MES[Number(m.slice(5, 7)) - 1]}/${m.slice(2, 4)}`
const pct1 = (bp: number) => `${Math.trunc(bp / 100)},${Math.trunc((bp % 100) / 10)}%`
/** Rótulo de eixo em milhares (aproximado, só para o eixo; valores exatos ficam no tooltip e na tabela). */
const eixo = (c: number) => { const r = Math.trunc(c / 100); return Math.abs(r) >= 1000 ? `${Math.trunc(r / 1000)}k` : String(r) }
const share = (v: number, max: number) => (max > 0 ? Math.max(2, Math.floor((v * 100) / max)) : 0)

const Secao = ({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) => (
  <section className={`border-t border-border pt-4 ${className}`}>
    <h2 className="mb-3 text-sm font-semibold tracking-tight text-muted-foreground">{title}</h2>
    {children}
  </section>
)
const chip = (on: boolean) => `shrink-0 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${on ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-card text-foreground hover:bg-muted'}`
const linha = 'group relative block w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted aria-pressed:bg-muted'

function Tip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 text-sm shadow-lg">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((p) => <p key={p.name} className="tabular flex justify-between gap-4"><span className="text-muted-foreground">{p.name}</span><span className="font-medium">{formatBRL(p.value)}</span></p>)}
    </div>
  )
}

/** Variação vs período anterior. `up` = subir é bom? (receita/saldo: sim; despesa/média: não). */
function Delta({ cur, prev, goodUp }: { cur: number; prev: number; goodUp: boolean }) {
  const p = pctChange(cur, prev)
  if (p === null) return <span className="text-sm opacity-70" aria-label="Sem período anterior para comparar">— vs anterior</span>
  const bom = p === 0 || (p > 0) === goodUp
  const Icon = p < 0 ? ArrowDown : ArrowUp
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-medium ${bom ? 'text-luz' : 'text-warning'}`}>
      {p !== 0 && <Icon className="size-3.5" aria-hidden="true" />}
      {p > 0 ? '+' : ''}{p}%<span className="sr-only">{bom ? ', favorável' : ', atenção'}</span><span className="font-normal opacity-70"> vs anterior</span>
    </span>
  )
}

function Kpi({ label, cur, prev, goodUp, big = false }: { label: string; cur: number; prev: number; goodUp: boolean; big?: boolean }) {
  const v = useCountUp(cur)
  return (
    <div className="min-w-0 px-1 py-3 md:px-5 md:first:pl-0 md:last:pr-0">
      <h3 className="text-sm font-medium opacity-80">{label}</h3>
      <p className={`tabular mt-1 whitespace-nowrap font-semibold tracking-tight ${big ? 'text-2xl md:text-3xl' : 'text-xl md:text-2xl'}`} aria-label={formatBRL(cur)}>{formatBRL(v)}</p>
      <div className="mt-1"><Delta cur={cur} prev={prev} goodUp={goodUp} /></div>
    </div>
  )
}

type Set = (patch: { [K in keyof Filters]?: Filters[K] | undefined }) => void

export function Reports() {
  const { spaceId } = useSpace()
  const nav = useNavigate()
  const f = parseFilters(useSearch({ strict: false }) as unknown as Record<string, unknown>)
  const set: Set = (patch) => void nav({ to: '/analises', search: parseFilters({ ...f, ...patch }) })
  const range = resolveRange(f, today())
  const qs = reportQuery(f, range)
  const path = `/spaces/${spaceId}/reports/overview?${qs}`
  const ov = useQuery({ queryKey: [path], queryFn: () => api<OverviewOut>('GET', path), placeholderData: keepPreviousData })
  const d = ov.data
  return (
    <>
      <h1 className="mb-4 text-xl font-semibold tracking-tight">Análises</h1>
      <FilterBar f={f} set={set} range={range} />
      {ov.error && !d && <div className="mt-6"><Err e={ov.error} /><button type="button" className="font-medium underline" onClick={() => void ov.refetch()}>Tentar novamente</button></div>}
      {!d && !ov.error && <Skeleton />}
      {d && (
        <div className={`mt-5 transition-opacity ${ov.isFetching ? 'opacity-60' : ''}`} aria-busy={ov.isFetching}>
          <Kpis t={d.totals} p={d.previous} />
          {d.totals.tx_count === 0 && d.by_month.every((m) => m.income_cents === 0 && m.expense_cents === 0) ? (
            <div className="mt-8 rounded-2xl bg-muted p-6 text-center">
              <p className="font-medium">Nenhum lançamento neste período</p>
              <p className="mt-1 text-sm text-muted-foreground">Tente outro período ou remova filtros.</p>
              {f.per !== '12m' && <button type="button" className={`${chip(false)} mt-3`} onClick={() => set({ per: '12m' })}>Ampliar para 12 meses</button>}
            </div>
          ) : (
            <>
              <Evolucao d={d} range={range} set={set} />
              <div className="mt-8 grid gap-x-10 gap-y-8 md:grid-cols-5">
                <Categorias d={d} f={f} set={set} className="md:col-span-3" />
                <Estabelecimentos d={d} f={f} set={set} className="md:col-span-2" />
              </div>
              <Dia d={d} set={set} className="mt-8" />
              <div className="mt-8 grid gap-x-10 gap-y-8 md:grid-cols-3">
                <Semana d={d} />
                <Contas d={d} f={f} set={set} />
                <Vencimentos d={d} />
              </div>
              <Maiores d={d} className="mt-8" />
            </>
          )}
        </div>
      )}
      <Detalhe qs={listQuery(f, range)} range={range} spaceId={spaceId} />
    </>
  )
}

function Skeleton() {
  return (
    <div className="mt-5 grid gap-4 motion-safe:animate-pulse" role="status" aria-label="Carregando análises">
      <div className="h-28 rounded-3xl bg-muted" /><div className="h-72 rounded-2xl bg-muted" /><div className="h-40 rounded-2xl bg-muted" />
    </div>
  )
}

function FilterBar({ f, set, range }: { f: Filters; set: Set; range: { start: string; end: string } }) {
  const accounts = useAccounts()
  const cats = useCategories()
  const catName = useCatName()
  const per = f.per ?? 'mes'
  const active: [string, string, () => void][] = []
  if (f.account_id) active.push(['Conta', accounts.data.find((a) => a.id === f.account_id)?.name ?? 'Outra conta', () => set({ account_id: undefined })])
  if (f.category_id) active.push(['Categoria', f.category_id === 'none' ? 'Sem categoria' : catName(f.category_id), () => set({ category_id: undefined })])
  if (f.type) active.push(['Tipo', f.type === 'expense' ? 'Despesas' : 'Receitas', () => set({ type: undefined })])
  if (f.merchant) active.push(['Estabelecimento', f.merchant, () => set({ merchant: undefined })])
  const sel = 'rounded-lg border border-input bg-card px-2 py-1.5 text-sm'
  return (
    <div>
      <div role="group" aria-label="Período" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:flex-wrap md:px-0">
        {PERIODS.map(([p, label]) => (
          <button key={p} type="button" aria-pressed={per === p} className={chip(per === p)} onClick={() => set(p === 'custom' ? { per: 'custom', ...range } : { per: p })}>{label}</button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        {per === 'custom' && (
          <>
            <label className="text-sm"><span className="mb-1 block text-muted-foreground">De</span><input type="date" className={sel} value={range.start} onChange={(e) => e.target.value && set({ per: 'custom', start: e.target.value, end: e.target.value > range.end ? e.target.value : range.end })} /></label>
            <label className="text-sm"><span className="mb-1 block text-muted-foreground">Até</span><input type="date" className={sel} value={range.end} onChange={(e) => e.target.value && set({ per: 'custom', start: e.target.value < range.start ? e.target.value : range.start, end: e.target.value })} /></label>
          </>
        )}
        <label className="text-sm"><span className="mb-1 block text-muted-foreground">Conta</span>
          <select className={sel} value={f.account_id ?? ''} onChange={(e) => set({ account_id: e.target.value || undefined })}><option value="">Todas</option>{accounts.data.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
        <label className="text-sm"><span className="mb-1 block text-muted-foreground">Categoria</span>
          <select className={sel} value={f.category_id ?? ''} onChange={(e) => set({ category_id: e.target.value || undefined })}><option value="">Todas</option><option value="none">Sem categoria</option>{cats.data.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label className="text-sm"><span className="mb-1 block text-muted-foreground">Tipo</span>
          <select className={sel} value={f.type ?? ''} onChange={(e) => set({ type: (e.target.value || undefined) as Filters['type'] })}><option value="">Receitas e despesas</option><option value="expense">Despesas</option><option value="income">Receitas</option></select></label>
      </div>
      {active.length > 0 && (
        <ul className="mt-3 flex flex-wrap items-center gap-2" aria-label="Filtros ativos">
          {active.map(([k, v, off]) => (
            <li key={k}><button type="button" aria-label={`Remover filtro ${k}: ${v}`} onClick={off} className="inline-flex items-center gap-1.5 rounded-full bg-muted py-1 pl-3 pr-2 text-sm hover:bg-border"><span className="text-muted-foreground">{k}:</span> {v}<X className="size-3.5" aria-hidden="true" /></button></li>
          ))}
          <li><button type="button" className="text-sm font-medium underline" onClick={() => set({ account_id: undefined, category_id: undefined, type: undefined, merchant: undefined })}>Limpar filtros</button></li>
        </ul>
      )}
    </div>
  )
}

function Kpis({ t, p }: { t: ReportTotals; p: ReportTotals }) {
  return (
    <section aria-label="Resumo do período" className="grid grid-cols-2 gap-x-4 divide-hero-foreground/15 rounded-3xl bg-hero px-5 py-2 text-hero-foreground md:grid-cols-4 md:divide-x md:px-7 md:py-4">
      <Kpi label="Receitas" cur={t.income_cents} prev={p.income_cents} goodUp />
      <Kpi label="Despesas" cur={t.expense_cents} prev={p.expense_cents} goodUp={false} />
      <Kpi label="Saldo do período" cur={t.net_cents} prev={p.net_cents} goodUp big />
      <Kpi label="Média diária de gasto" cur={t.avg_daily_expense_cents} prev={p.avg_daily_expense_cents} goodUp={false} />
    </section>
  )
}

function Evolucao({ d, range, set }: { d: OverviewOut; range: { start: string; end: string }; set: Set }) {
  const sel = wholeMonth(range)
  const bal = new Map(d.balance_series.map((b) => [b.month, b.balance_cents]))
  const data = d.by_month.map((m) => ({ ...m, label: mesCurto(m.month), balance: bal.get(m.month) }))
  const pick = (month: string | undefined) => { if (month) set({ per: 'custom', ...monthRange(month) }) }
  const op = (m: string) => (sel && sel !== m ? 0.35 : 1)
  return (
    <section className="mt-8" aria-labelledby="h-evo">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="h-evo" className="text-lg font-semibold tracking-tight">Evolução em 12 meses</h2>
        <ul className="flex gap-4 text-sm text-muted-foreground" aria-hidden="true">
          <li><span className="mr-1.5 inline-block size-2.5 rounded-sm" style={{ background: 'var(--chart-1)' }} />Receitas</li>
          <li><span className="mr-1.5 inline-block size-2.5 rounded-sm bg-foreground/70" />Despesas</li>
          <li><span className="mr-1.5 inline-block h-0.5 w-3 align-middle" style={{ background: 'var(--chart-4)' }} />Saldo em conta</li>
        </ul>
      </div>
      <div role="img" aria-label={`Receitas, despesas e saldo dos últimos 12 meses. Clique em um mês para filtrar. Os valores estão na tabela abaixo.`} className="h-64 rounded-2xl border border-border bg-card p-2 md:h-80 md:p-4">
        <ResponsiveContainer>
          <ComposedChart data={data} barGap={2} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <YAxis tickFormatter={eixo} tickLine={false} axisLine={false} width={40} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <Tooltip content={<Tip />} cursor={{ fill: 'var(--muted)', opacity: 0.6 }} />
            <Bar dataKey="income_cents" name="Receitas" radius={[4, 4, 0, 0]} isAnimationActive={animar} cursor="pointer" onClick={(e) => pick((e as unknown as { month?: string }).month)}>
              {data.map((m) => <Cell key={m.month} fill="var(--chart-1)" fillOpacity={op(m.month)} />)}
            </Bar>
            <Bar dataKey="expense_cents" name="Despesas" radius={[4, 4, 0, 0]} isAnimationActive={animar} cursor="pointer" onClick={(e) => pick((e as unknown as { month?: string }).month)}>
              {data.map((m) => <Cell key={m.month} fill="var(--foreground)" fillOpacity={0.7 * op(m.month)} />)}
            </Bar>
            <Line dataKey="balance" name="Saldo em conta" type="monotone" stroke="var(--chart-4)" strokeWidth={2} dot={false} isAnimationActive={animar} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">Ver os 12 meses em tabela</summary>
        <div className="overflow-x-auto">
          <table className="tabular mt-2 w-full text-left">
            <thead className="text-muted-foreground"><tr><th className="py-1 font-medium">Mês</th><th className="font-medium">Receitas</th><th className="font-medium">Despesas</th><th className="font-medium">Saldo em conta</th></tr></thead>
            <tbody>{data.map((m) => (
              <tr key={m.month} className="border-t border-border">
                <th scope="row" className="py-1 font-normal"><button type="button" className="underline-offset-2 hover:underline" aria-pressed={sel === m.month} aria-label={`Filtrar ${mesCurto(m.month)}`} onClick={() => pick(m.month)}>{mesCurto(m.month)}</button></th>
                <td>{formatBRL(m.income_cents)}</td><td>{formatBRL(m.expense_cents)}</td><td>{m.balance === undefined ? '—' : formatBRL(m.balance)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </details>
    </section>
  )
}

function Categorias({ d, f, set, className }: { d: OverviewOut; f: Filters; set: Set; className?: string }) {
  const cats = useCategories()
  const color = (id: string | null) => { const i = cats.data.findIndex((c) => c.id === id); return id && i >= 0 ? SERIES[i % SERIES.length] : 'var(--muted-foreground)' }
  const key = (id: string | null) => id ?? 'none'
  const max = d.by_category[0]?.expense_cents ?? 0
  const toggle = (id: string | null) => set({ category_id: f.category_id === key(id) ? undefined : key(id) })
  return (
    <Secao title="Gastos por categoria" className={className}>
      {d.by_category.length === 0 ? <p className="text-muted-foreground">Nenhum gasto neste período.</p> : (
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          <div className="mx-auto h-36 w-36 shrink-0" aria-hidden="true">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={d.by_category} dataKey="expense_cents" nameKey="name" innerRadius={42} outerRadius={64} paddingAngle={2} stroke="none" isAnimationActive={animar} cursor="pointer" onClick={(e) => toggle((e as unknown as { category_id: string | null }).category_id)}>
                  {d.by_category.map((c) => <Cell key={key(c.category_id)} fill={color(c.category_id)} fillOpacity={f.category_id && f.category_id !== key(c.category_id) ? 0.3 : 1} />)}
                </Pie>
                <Tooltip content={<Tip />} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="min-w-0 flex-1">
            {d.by_category.map((c) => (
              <li key={key(c.category_id)}>
                <button type="button" className={linha} aria-pressed={f.category_id === key(c.category_id)} aria-label={`Filtrar por ${c.name}: ${formatBRL(c.expense_cents)}, ${pct1(c.share_bp)}`} onClick={() => toggle(c.category_id)}>
                  <span className="flex items-baseline justify-between gap-3"><span className="truncate"><span className="mr-2 inline-block size-2.5 rounded-full" style={{ background: color(c.category_id) }} />{c.name}</span><span className="tabular shrink-0 font-medium">{formatBRL(c.expense_cents)} <span className="font-normal text-muted-foreground">{pct1(c.share_bp)}</span></span></span>
                  <span className="mt-1 block h-1.5 rounded-full bg-muted"><span className="block h-full rounded-full motion-safe:transition-[width] motion-safe:duration-500" style={{ width: `${share(c.expense_cents, max)}%`, background: color(c.category_id) }} /></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Secao>
  )
}

const SEM_EST = 'Sem estabelecimento'
function Estabelecimentos({ d, f, set, className }: { d: OverviewOut; f: Filters; set: Set; className?: string }) {
  const max = d.by_merchant[0]?.expense_cents ?? 0
  return (
    <Secao title="Principais estabelecimentos" className={className}>
      {d.by_merchant.length === 0 ? <p className="text-muted-foreground">Nenhum gasto neste período.</p> : (
        <ul>
          {d.by_merchant.map((m) => {
            const body = (
              <>
                <span className="flex items-baseline justify-between gap-3"><span className="truncate">{m.merchant}</span><span className="tabular shrink-0 font-medium">{formatBRL(m.expense_cents)}</span></span>
                <span className="mt-1 block h-1.5 rounded-full bg-muted"><span className="block h-full rounded-full bg-primary/70" style={{ width: `${share(m.expense_cents, max)}%` }} /></span>
              </>
            )
            return (
              <li key={m.merchant}>
                {m.merchant === SEM_EST ? <div className="px-2 py-1.5 text-muted-foreground">{body}</div>
                  : <button type="button" className={linha} aria-pressed={f.merchant === m.merchant} aria-label={`Filtrar por ${m.merchant}: ${formatBRL(m.expense_cents)}`} onClick={() => set({ merchant: f.merchant === m.merchant ? undefined : m.merchant })}>{body}</button>}
              </li>
            )
          })}
        </ul>
      )}
    </Secao>
  )
}

function Dia({ d, set, className }: { d: OverviewOut; set: Set; className?: string }) {
  const peak = d.by_day.reduce((a, b) => (b.expense_cents > a.expense_cents ? b : a), d.by_day[0])
  const pick = (day: string | undefined) => { if (day) set({ per: 'custom', start: day, end: day }) }
  return (
    <Secao title="Gasto por dia" className={className}>
      {d.by_day.length === 0 ? <p className="text-muted-foreground">Sem movimento neste período.</p> : (
        <>
          <div role="img" aria-label={`Gasto diário em ${d.by_day.length} dias com movimento. Maior gasto: ${formatBRL(peak.expense_cents)} em ${br(peak.date)}.`} className="h-36 md:h-44">
            <ResponsiveContainer>
              <AreaChart data={d.by_day.map((x) => ({ ...x, label: br(x.date).slice(0, 5) }))} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} onClick={(s) => pick((s as unknown as { activePayload?: { payload: { date: string } }[] }).activePayload?.[0]?.payload.date)} style={{ cursor: 'pointer' }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={24} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
                <YAxis tickFormatter={eixo} tickLine={false} axisLine={false} width={40} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
                <Tooltip content={<Tip />} />
                <Area dataKey="expense_cents" name="Despesas" type="monotone" stroke="var(--chart-1)" strokeWidth={2} fill="var(--chart-1)" fillOpacity={0.15} isAnimationActive={animar} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Maior dia: <button type="button" className="font-medium text-foreground underline" onClick={() => pick(peak.date)}>{br(peak.date)}</button> · <span className="tabular">{formatBRL(peak.expense_cents)}</span></p>
        </>
      )}
    </Secao>
  )
}

function Semana({ d }: { d: OverviewOut }) {
  const by = new Map(d.by_weekday.map((w) => [w.dow, w]))
  const max = Math.max(0, ...d.by_weekday.map((w) => w.expense_cents))
  return (
    <Secao title="Por dia da semana">
      <ul>{DOW.map((n, i) => {
        const v = by.get(i)?.expense_cents ?? 0
        return <li key={n} className="flex items-center gap-2 py-1 text-sm"><span className="w-8 text-muted-foreground">{n}</span><span className="h-1.5 flex-1 rounded-full bg-muted"><span className="block h-full rounded-full bg-primary/70" style={{ width: `${v ? share(v, max) : 0}%` }} /></span><span className="tabular w-24 text-right">{formatBRL(v)}</span></li>
      })}</ul>
    </Secao>
  )
}

function Contas({ d, f, set }: { d: OverviewOut; f: Filters; set: Set }) {
  return (
    <Secao title="Por conta">
      {d.by_account.length === 0 ? <p className="text-muted-foreground">Sem movimento.</p> : (
        <ul>{d.by_account.map((a) => {
          const body = <span className="flex items-baseline justify-between gap-2"><span className="truncate">{a.name}</span><span className="tabular shrink-0 text-sm"><span className="text-success">+{formatBRL(a.income_cents)}</span> <span>-{formatBRL(a.expense_cents)}</span></span></span>
          return <li key={a.account_id ?? a.name}>{a.account_id
            ? <button type="button" className={linha} aria-pressed={f.account_id === a.account_id} aria-label={`Filtrar pela conta ${a.name}`} onClick={() => set({ account_id: f.account_id === a.account_id ? undefined : a.account_id! })}>{body}</button>
            : <div className="px-2 py-1.5 text-muted-foreground">{body}</div>}</li>
        })}</ul>
      )}
    </Secao>
  )
}

function Vencimentos({ d }: { d: OverviewOut }) {
  return (
    <Secao title="Próximos 30 dias">
      {d.upcoming.length === 0 ? <p className="text-muted-foreground">Nada a vencer.</p> : (
        <ul className="divide-y divide-border">{d.upcoming.map((u) => (
          <li key={`${u.kind}${u.id}`} className="flex justify-between gap-2 py-1.5 text-sm"><span className="min-w-0 truncate">{u.description} <span className="text-muted-foreground">· {br(u.due_on).slice(0, 5)}{u.kind === 'invoice' ? ' · fatura' : ''}</span></span><span className="tabular shrink-0 font-medium">{formatBRL(u.amount_cents)}</span></li>
        ))}</ul>
      )}
    </Secao>
  )
}

function Maiores({ d, className }: { d: OverviewOut; className?: string }) {
  const catName = useCatName()
  if (d.largest.length === 0) return null
  return (
    <Secao title="Maiores despesas do período" className={className}>
      <ol className="divide-y divide-border">{d.largest.map((t) => (
        <li key={t.id} className="flex items-center justify-between gap-3 py-2"><span className="min-w-0 truncate">{t.description || t.merchant || 'Lançamento'}<small className="block text-muted-foreground">{br(t.occurred_on)} · {catName(t.category_id)}</small></span><span className="tabular shrink-0 font-medium">{formatBRL(t.amount_cents)}</span></li>
      ))}</ol>
    </Secao>
  )
}

const STEP = 30
function Detalhe({ qs, range, spaceId }: { qs: string; range: { start: string; end: string }; spaceId: string }) {
  const list = useGet<Tx[]>(`/spaces/${spaceId}/transactions?${qs}&limit=1000`)  // qs = listQuery(): transferências saem no filtro abaixo
  const catName = useCatName()
  const [text, setText] = useState('')
  const [ord, setOrd] = useState<'data' | 'valor'>('data')
  const [n, setN] = useState(STEP)
  const [sel, setSel] = useState<Tx | null>(null)
  const rows = useMemo(() => {
    const t = text.trim().toLowerCase()
    const r = (list.data ?? []).filter((x) => x.type !== 'transfer').filter((x) => !t || `${x.description} ${x.merchant ?? ''}`.toLowerCase().includes(t))
    return r.sort((a, b) => (ord === 'valor' ? b.amount_cents - a.amount_cents : b.occurred_on.localeCompare(a.occurred_on)))
  }, [list.data, text, ord])
  const total = rows.reduce((s, x) => s + (x.type === 'income' ? x.amount_cents : x.type === 'expense' ? -x.amount_cents : 0), 0)
  return (
    <Secao title="Detalhe dos lançamentos" className="mt-10">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="min-w-40 flex-1 text-sm"><span className="mb-1 block text-muted-foreground">Buscar</span><input type="search" className="w-full rounded-lg border border-input bg-card px-2 py-1.5" value={text} onChange={(e) => { setText(e.target.value); setN(STEP) }} placeholder="Descrição ou estabelecimento" /></label>
        <div role="group" aria-label="Ordenar por" className="flex gap-2">
          {(['data', 'valor'] as const).map((o) => <button key={o} type="button" aria-pressed={ord === o} className={chip(ord === o)} onClick={() => setOrd(o)}>{o === 'data' ? 'Data' : 'Valor'}</button>)}
        </div>
        <button type="button" disabled={rows.length === 0} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50" onClick={() => downloadCsv(`analises-${range.start}_${range.end}.csv`, toCsv(rows, catName))}><Download className="size-4" aria-hidden="true" />Exportar CSV</button>
      </div>
      <Err e={list.error} />
      {sel && <TxDetail key={sel.id} t={sel} onClose={() => setSel(null)} />}
      {list.isLoading ? <p>Carregando…</p> : rows.length === 0 ? <p className="text-muted-foreground">Nenhum lançamento neste filtro.</p> : (
        <>
          <p className="mb-1 text-sm text-muted-foreground" role="status">{rows.length} lançamento{rows.length > 1 ? 's' : ''} · saldo do filtro <span className="tabular font-medium text-foreground">{formatBRL(total)}</span></p>
          <TxList items={rows.slice(0, n)} onSelect={setSel} />
          {rows.length > n && <button type="button" className="mt-3 font-medium underline" onClick={() => setN(n + STEP)}>Mostrar mais ({rows.length - n})</button>}
        </>
      )}
    </Secao>
  )
}
