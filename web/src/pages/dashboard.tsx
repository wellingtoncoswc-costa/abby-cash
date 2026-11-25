import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { ApiError } from '../api/client'
import type { Account, Bill, Budget, Goal, Tx } from '../api/types'
import { Anel, podeAnimar, useCountUp, useNovos } from '../anim'
import { formatBRL } from '../lib/money'
import { useSpace } from '../space'
import { Bar, br, Err, Esqueleto, monthKey, useCatName, useGet } from '../ui'

const COLORS = [1, 2, 3, 4, 5].map((n) => `var(--chart-${n})`).concat([1, 2, 3].map((n) => `color-mix(in oklab, var(--chart-${n}) 60%, transparent)`))

export function Dashboard() {
  const { spaceId } = useSpace()
  const month = monthKey()
  const [y, m] = month.split('-').map(Number)
  const last = new Date(y, m, 0).getDate()
  const catName = useCatName()
  const budget = useGet<Budget>(`/spaces/${spaceId}/budgets/${month}`)
  const txs = useGet<Tx[]>(`/spaces/${spaceId}/transactions?start=${month}-01&end=${month}-${last}&limit=500`)
  const bills = useGet<Bill[]>(`/spaces/${spaceId}/bills?status=open`)
  const goals = useGet<Goal[]>(`/spaces/${spaceId}/goals`)
  const accounts = useGet<Account[]>('/accounts')
  const noBudget = budget.error instanceof ApiError && budget.error.status === 404
  const byCat = new Map<string, number>()
  for (const t of txs.data ?? []) if (t.type === 'expense') byCat.set(catName(t.category_id), (byCat.get(catName(t.category_id)) ?? 0) + t.amount_cents)
  const pie = [...byCat].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
  const empty = accounts.data && !accounts.data.some((a) => a.space_id === spaceId)
  const mes = new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long' })
  const spent = budget.data?.spent_cents ?? 0
  const limit = budget.data?.limit_cents ?? 0
  const pct = limit > 0 ? Math.min(100, Math.floor((spent * 100) / limit)) : 0
  const gasto = useCountUp(spent)
  const [foco, setFoco] = useState<string | null>(null)
  const emFoco = pie.find((p) => p.name === foco)
  const total = pie.reduce((a, p) => a + p.value, 0)
  const cor = spent > limit ? 'oklch(0.75 0.17 25)' : pct >= 80 ? 'oklch(0.82 0.15 80)' : 'var(--luz)'
  return (
    <>
      <h1 className="mb-4 text-xl font-semibold tracking-tight">Painel de {m.toString().padStart(2, '0')}/{y}</h1>
      {empty && <p className="mb-4 rounded-xl bg-muted p-3 text-sm">Você ainda não tem contas neste espaço. <Link to="/onboarding" className="font-medium underline">Começar a configuração</Link></p>}
      <section aria-label="Gasto no mês" className="mb-8 flex items-center justify-between gap-5 rounded-3xl bg-hero p-5 text-hero-foreground md:p-7">
        {budget.data ? (
          <>
            <div className="min-w-0">
              <h2 className="text-sm font-medium opacity-80">Gasto em {mes}</h2>
              <p className="tabular mt-1 whitespace-nowrap text-3xl font-semibold tracking-tight md:text-5xl" aria-label={formatBRL(spent)}>{formatBRL(gasto)}</p>
              <p className="mt-2 text-sm opacity-80">de <span className="whitespace-nowrap">{formatBRL(limit)}</span> · <span className="whitespace-nowrap">{spent > limit ? `${formatBRL(spent - limit)} acima do teto` : `restam ${formatBRL(limit - spent)}`}</span></p>
            </div>
            <div className="relative">
              <Anel pct={pct} cor={cor} />
              <span className="tabular absolute inset-0 grid place-items-center text-lg font-semibold">{pct}%</span>
            </div>
          </>
        ) : noBudget ? (
          <div>
            <h2 className="text-sm font-medium opacity-80">Gasto em {mes}</h2>
            <p className="mt-1 text-2xl font-semibold tracking-tight">Defina um teto para acompanhar o mês</p>
            <p className="mt-2 text-sm">Sem teto definido. <Link to="/teto" className="font-medium text-hero-foreground underline">Definir teto</Link></p>
          </div>
        ) : <Err e={budget.error} />}
      </section>
      <div className="grid gap-x-10 gap-y-8 md:grid-cols-2">
        <Secao title="Por categoria">
          {!txs.data ? <Esqueleto rotulo="categorias" /> : pie.length === 0 ? <p className="text-muted-foreground">Nenhum gasto neste mês.</p> : (
            <>
              <div className="relative h-44">
                <div className="h-full" aria-hidden="true">
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie data={pie} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72} paddingAngle={2} stroke="none" isAnimationActive={podeAnimar()} animationDuration={1100} animationEasing="ease-out">{pie.map((p, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} fillOpacity={foco && p.name !== foco ? 0.3 : 1} style={{ transition: 'fill-opacity .2s' }} />)}</Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div data-testid="centro-rosca" className="pointer-events-none absolute inset-0 grid place-content-center text-center">
                  <span className="max-w-24 truncate text-xs text-muted-foreground">{emFoco ? emFoco.name : 'Total'}</span>
                  <span className="tabular text-sm font-semibold">{formatBRL(emFoco ? emFoco.value : total)}</span>
                </div>
              </div>
              <ul className="mt-2 divide-y divide-border">{pie.map((p, i) => <li key={p.name} tabIndex={0} aria-label={`${p.name} ${formatBRL(p.value)}`} onMouseEnter={() => setFoco(p.name)} onMouseLeave={() => setFoco(null)} onFocus={() => setFoco(p.name)} onBlur={() => setFoco(null)} className="flex justify-between py-2"><span><span className="mr-2 inline-block size-2.5 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />{p.name}</span><span className="tabular font-medium">{formatBRL(p.value)}</span></li>)}</ul>
            </>
          )}
        </Secao>
        <div className="grid content-start gap-8">
          <Secao title="Próximas contas">
            {!bills.data ? <Esqueleto rotulo="contas" /> : bills.data.length === 0 ? <p className="text-muted-foreground">Nenhuma conta em aberto.</p> : (
              <ul className="divide-y divide-border">{[...(bills.data ?? [])].sort((a, b) => a.due_on.localeCompare(b.due_on)).slice(0, 5).map((b) => <li key={b.id} className="flex justify-between py-2"><span>{b.description} <span className="text-muted-foreground">· {b.due_on.split('-').reverse().join('/')}</span></span><span className="tabular font-medium">{formatBRL(b.amount_cents)}</span></li>)}</ul>
            )}
          </Secao>
          <Secao title="Metas">
            {!goals.data ? <Esqueleto rotulo="metas" /> : goals.data.length === 0 ? <p className="text-muted-foreground">Nenhuma meta.</p> : goals.data.map((g) => (
              <div key={g.id} className="mb-3"><div className="mb-1 flex justify-between"><span>{g.name}</span><span className="tabular text-sm text-muted-foreground">{formatBRL(g.saved_cents)} / {formatBRL(g.target_cents)}</span></div><Bar value={g.saved_cents} max={g.target_cents} /></div>
            ))}
          </Secao>
        </div>
        <div className="md:col-span-2">
          <Secao title="Últimos lançamentos">
            {!txs.data ? <Esqueleto rotulo="lançamentos" /> : txs.data.length === 0 ? <p className="text-muted-foreground">Nenhum lançamento.</p> : <TxList items={txs.data.slice(0, 5)} />}
            <Link to="/lancamentos" className="mt-3 inline-block font-medium underline">Ver todos</Link>
          </Secao>
        </div>
      </div>
    </>
  )
}

const Secao = ({ title, children }: { title: string; children: ReactNode }) => (
  <section>
    <h2 className="mb-2 text-base font-semibold tracking-tight">{title}</h2>
    {children}
  </section>
)

export const TxList = ({ items, onSelect }: { items: Tx[]; onSelect?: (t: Tx) => void }) => {
  const catName = useCatName()
  const accounts = useGet<Account[]>('/accounts')
  const novos = useNovos(items.map((t) => t.id))
  const accName = (id: string | null) => accounts.data?.find((a) => a.id === id)?.name ?? 'Conta'
  return (
    <ul className="divide-y divide-border">
      {items.map((t) => {
        const transfer = t.type === 'transfer'
        const title = transfer ? `Transferência · ${accName(t.account_id)} → ${accName(t.counter_account_id)}` : t.description || t.merchant || 'Lançamento'
        const body = <>{title}{t.installment_total ? ` (${t.installment_number}/${t.installment_total})` : ''}<br /><small>{br(t.occurred_on)} · {transfer ? t.description || 'Entre contas' : catName(t.category_id)}</small></>
        return (
          <li key={t.id} className={`flex items-center justify-between gap-3 py-2.5 ${novos.has(t.id) ? 'novo' : ''}`}>
            {onSelect ? <button type="button" className="text-left underline-offset-2 hover:underline" aria-label={`Abrir ${title}`} onClick={() => onSelect(t)}>{body}</button> : <span>{body}</span>}
            <span className={`tabular shrink-0 font-medium ${t.type === 'income' ? 'text-success' : ''}`}>{t.type === 'income' ? '+' : t.type === 'expense' ? '-' : ''}{formatBRL(t.amount_cents)}</span>
          </li>
        )
      })}
    </ul>
  )
}
