import type { Tx } from '../api/types'
import { formatBRL } from './money'

const despesas = (txs: Tx[]) => txs.filter((t) => t.type === 'expense')
const dia = (t: Tx) => Number(t.occurred_on.slice(8, 10))

/** Despesas somadas por dia do mês (transferências e receitas não contam). */
export function gastoPorDia(txs: Tx[]): Map<number, number> {
  const m = new Map<number, number>()
  for (const t of despesas(txs)) m.set(dia(t), (m.get(dia(t)) ?? 0) + t.amount_cents)
  return m
}

const soma = (txs: Tx[]) => txs.reduce((a, t) => a + t.amount_cents, 0)

/** Frases curtas comparando o mês com o mesmo período (até `ate`) do anterior. Vazio se não há base de comparação. */
export function insights(atual: Tx[], anterior: Tx[], ate: number, mesAnterior: string, nome: (id: string | null) => string): string[] {
  const a = despesas(atual).filter((t) => dia(t) <= ate)
  const b = despesas(anterior).filter((t) => dia(t) <= ate)
  const base = soma(b)
  if (base === 0) return []
  const out: string[] = []
  const pct = Math.round(((soma(a) - base) * 100) / base)
  if (Math.abs(pct) >= 5) out.push(`Você gastou ${Math.abs(pct)}% ${pct > 0 ? 'mais' : 'menos'} que no mesmo período de ${mesAnterior}.`)
  const porCat = (xs: Tx[]) => xs.reduce((m, t) => m.set(t.category_id, (m.get(t.category_id) ?? 0) + t.amount_cents), new Map<string | null, number>())
  const pa = porCat(a)
  const pb = porCat(b)
  const [id, delta] = [...pa].map(([k, v]) => [k, v - (pb.get(k) ?? 0)] as const).sort((x, y) => y[1] - x[1])[0] ?? [null, 0]
  if (delta > 0) out.push(`${nome(id)} foi a categoria que mais cresceu: +${formatBRL(delta)}.`)
  return out
}
