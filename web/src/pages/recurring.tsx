import { api } from '../api/client'
import type { RecurringItem } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { Btn, Card, EditBox, Err, br, centsText, useAccounts, useGet, useIsOwner, useSend } from '../ui'

const rule = (r: Record<string, unknown>) => r.kind === 'yearly' ? `Anual, dia ${r.day}/${r.month}` : r.kind === 'every_n_months' ? `A cada ${r.n} meses, dia ${r.day}` : `Mensal, dia ${r.day}`

export function ItemCard({ it, owner }: { it: RecurringItem; owner: boolean }) {
  const accounts = useAccounts(true)
  const acc = accounts.data.find((a) => a.id === it.account_id)
  const toggle = useSend(() => api('PATCH', `/spaces/${it.space_id}/recurring/${it.id}`, { active: !it.active }))
  return (
    <Card title={it.description}>
      <p className="flex items-baseline justify-between"><span>{it.type === 'income' ? 'Receita' : 'Despesa'} · {rule(it.rule)}</span><span className={`text-lg font-semibold tabular-nums ${it.type === 'income' ? '' : 'text-destructive'}`}>{it.type === 'income' ? '' : '-'}{formatBRL(it.amount_cents)}</span></p>
      <p>{it.type === 'income' ? 'Entra em' : 'Sai de'} {acc?.name ?? 'conta'}</p>
      <p>{it.active ? (it.next_due_on ? `Próxima data: ${br(it.next_due_on)}` : 'Encerrado') : 'Pausado'} · {it.ends_on ? `até ${br(it.ends_on)}` : 'fixo, sem término'}</p>
      {owner && <Btn type="button" className="mt-2 bg-muted-foreground hover:bg-muted-foreground/90" disabled={toggle.isPending} onClick={() => toggle.mutate()}>{it.active ? 'Pausar' : 'Retomar'}</Btn>}
      <Err e={toggle.error} />
      <EditBox what="fixo" canEdit={owner}
        fields={[{ k: 'description', label: `Descrição de ${it.description}`, v: it.description }, { k: 'amount', label: `Valor (R$) de ${it.description}`, v: centsText(it.amount_cents) }, { k: 'account_id', label: `${it.type === 'income' ? 'Entra em' : 'Sai de'} (${it.description})`, v: it.account_id, options: accounts.data.map((a): [string, string] => [a.id, a.name]) }, { k: 'ends_on', label: `Fim de ${it.description}`, v: it.ends_on ?? '', type: 'date' }]}
        save={(v) => { const c = parseBRL(v.amount); return c ? api('PATCH', `/spaces/${it.space_id}/recurring/${it.id}`, { description: v.description, amount_cents: c, account_id: v.account_id, ends_on: v.ends_on || null }) : Promise.reject(new Error('invalid_amount')) }}
        remove={() => api('DELETE', `/spaces/${it.space_id}/recurring/${it.id}`)} />
    </Card>
  )
}

/** Fixos e recorrentes do espaço (despesas e receitas), em cards. */
export function RecurringSection() {
  const { spaceId } = useSpace()
  const owner = useIsOwner()
  const items = useGet<RecurringItem[]>(`/spaces/${spaceId}/recurring`)
  const list = items.data ?? []
  if (!list.length && !items.error) return null
  return (
    <section aria-labelledby="h-fixas" className="mt-6">
      <h2 id="h-fixas" className="mb-3 text-lg font-semibold tracking-tight">Fixas e recorrentes</h2>
      <div className="grid gap-4 md:grid-cols-2">{list.map((it) => <ItemCard key={it.id} it={it} owner={owner} />)}</div>
      <Err e={items.error} />
    </section>
  )
}
