import { Link } from '@tanstack/react-router'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { ApiError } from '../api/client'
import type { Account, Bill, Budget, Goal, Tx } from '../api/types'
import { formatBRL } from '../lib/money'
import { useSpace } from '../space'
import { Bar, Card, br, Err, monthKey, useCatName, useGet } from '../ui'

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
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Painel de {m.toString().padStart(2, '0')}/{y}</h1>
      {empty && <Card><p>Você ainda não tem contas neste espaço. <Link to="/onboarding" className="underline">Começar a configuração</Link></p></Card>}
      <Card title="Gasto no mês">
        {budget.data ? (
          <>
            <p className="mb-2 text-2xl font-semibold">{formatBRL(budget.data.spent_cents)} <span className="text-base font-normal">de {formatBRL(budget.data.limit_cents)}</span></p>
            <Bar value={budget.data.spent_cents} max={budget.data.limit_cents} />
          </>
        ) : noBudget ? <p>Sem teto definido. <Link to="/teto" className="underline">Definir teto</Link></p> : <Err e={budget.error} />}
      </Card>
      <Card title="Por categoria">
        {pie.length === 0 ? <p>Nenhum gasto neste mês.</p> : (
          <>
            <div className="h-48" aria-hidden="true">
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={pie} dataKey="value" nameKey="name" innerRadius={40}>{pie.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie>
                  <Tooltip formatter={(v) => formatBRL(Number(v))} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul>{pie.map((p, i) => <li key={p.name} className="flex justify-between"><span><span className="mr-2 inline-block size-3 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />{p.name}</span><span>{formatBRL(p.value)}</span></li>)}</ul>
          </>
        )}
      </Card>
      <Card title="Próximas contas">
        {(bills.data ?? []).length === 0 ? <p>Nenhuma conta em aberto.</p> : (
          <ul>{[...(bills.data ?? [])].sort((a, b) => a.due_on.localeCompare(b.due_on)).slice(0, 5).map((b) => <li key={b.id} className="flex justify-between"><span>{b.description} · {b.due_on.split('-').reverse().join('/')}</span><span>{formatBRL(b.amount_cents)}</span></li>)}</ul>
        )}
      </Card>
      <Card title="Metas">
        {(goals.data ?? []).length === 0 ? <p>Nenhuma meta.</p> : (goals.data ?? []).map((g) => (
          <div key={g.id} className="mb-2"><div className="flex justify-between"><span>{g.name}</span><span>{formatBRL(g.saved_cents)} / {formatBRL(g.target_cents)}</span></div><Bar value={g.saved_cents} max={g.target_cents} /></div>
        ))}
      </Card>
      <Card title="Últimos lançamentos">
        {(txs.data ?? []).length === 0 ? <p>Nenhum lançamento.</p> : <TxList items={(txs.data ?? []).slice(0, 5)} />}
        <Link to="/lancamentos" className="mt-2 inline-block underline">Ver todos</Link>
      </Card>
    </>
  )
}

export const TxList = ({ items, onSelect }: { items: Tx[]; onSelect?: (t: Tx) => void }) => {
  const catName = useCatName()
  return (
    <ul className="divide-y divide-border">
      {items.map((t) => {
        const title = t.description || t.merchant || 'Lançamento'
        const body = <>{title}{t.installment_total ? ` (${t.installment_number}/${t.installment_total})` : ''}<br /><small>{br(t.occurred_on)} · {catName(t.category_id)}</small></>
        return (
          <li key={t.id} className="flex justify-between py-2">
            {onSelect ? <button type="button" className="text-left underline-offset-2 hover:underline" aria-label={`Abrir ${title}`} onClick={() => onSelect(t)}>{body}</button> : <span>{body}</span>}
            <span className={t.type === 'income' ? 'text-success' : ''}>{t.type === 'income' ? '+' : t.type === 'expense' ? '-' : ''}{formatBRL(t.amount_cents)}</span>
          </li>
        )
      })}
    </ul>
  )
}
