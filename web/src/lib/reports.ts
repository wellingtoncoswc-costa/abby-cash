import type { Tx } from '../api/types'
import { centsText } from '../ui'

export const PERIODS = [['mes', 'Este mês'], ['anterior', 'Mês passado'], ['30d', '30 dias'], ['3m', '3 meses'], ['12m', '12 meses'], ['custom', 'Personalizado']] as const
export type Per = (typeof PERIODS)[number][0]
export type Filters = { per?: Per; start?: string; end?: string; account_id?: string; category_id?: string; type?: 'expense' | 'income'; merchant?: string }

const DAY = /^\d{4}-\d{2}-\d{2}$/
const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const parse = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
const validDay = (s: unknown): s is string => typeof s === 'string' && DAY.test(s) && ymd(parse(s)) === s
export const days = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86400000)

/** Normaliza o search da URL: descarta lixo, `custom` sem datas válidas (ou janela > 3660 dias) vira o padrão. */
export function parseFilters(raw: Record<string, unknown>): Filters {
  const s = (k: string, max: number) => { const v = raw[k]; return v === undefined || v === null || v === '' ? undefined : String(v).slice(0, max) }
  const per = PERIODS.find(([p]) => p === raw.per)?.[0]
  const out: Filters = {}
  if (per === 'custom' && validDay(raw.start) && validDay(raw.end) && raw.start <= raw.end && days(raw.start, raw.end) <= 3660) Object.assign(out, { per, start: raw.start, end: raw.end })
  else if (per && per !== 'mes' && per !== 'custom') out.per = per
  const account_id = s('account_id', 64); if (account_id) out.account_id = account_id
  const category_id = s('category_id', 64); if (category_id) out.category_id = category_id
  const merchant = s('merchant', 200); if (merchant) out.merchant = merchant
  if (raw.type === 'expense' || raw.type === 'income') out.type = raw.type
  return out
}

/** Janela [start, end] do filtro (datas locais YYYY-MM-DD); `hoje` injetável para teste. */
export function resolveRange(f: Filters, hoje: string): { start: string; end: string } {
  const t = parse(hoje)
  const m = (off: number) => new Date(t.getFullYear(), t.getMonth() + off, 1)
  const last = (d: Date) => ymd(new Date(d.getFullYear(), d.getMonth() + 1, 0))
  switch (f.per) {
    case 'anterior': return { start: ymd(m(-1)), end: last(m(-1)) }
    case '30d': return { start: ymd(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 29)), end: hoje }
    case '3m': return { start: ymd(m(-2)), end: hoje }
    case '12m': return { start: ymd(m(-11)), end: hoje }
    case 'custom': return { start: f.start!, end: f.end! }
    default: return { start: ymd(m(0)), end: last(m(0)) }
  }
}

/** Mês 'YYYY-MM' se a janela é exatamente um mês cheio; senão null. */
export function wholeMonth({ start, end }: { start: string; end: string }): string | null {
  const first = `${start.slice(0, 7)}-01`
  const lastDay = ymd(new Date(Number(start.slice(0, 4)), Number(start.slice(5, 7)), 0))
  return start === first && end === lastDay ? start.slice(0, 7) : null
}
export const monthRange = (month: string) => ({ start: `${month}-01`, end: ymd(new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)) })

/** Query string do overview/lista (a mesma para os dois). */
export function reportQuery(f: Filters, r: { start: string; end: string }): string {
  const q = new URLSearchParams({ start: r.start, end: r.end })
  for (const k of ['account_id', 'category_id', 'type', 'merchant'] as const) if (f[k]) q.set(k, f[k])
  return q.toString()
}

/** Query da lista de detalhe (GET /transactions): `none` vira `uncategorized`, datas efetivas (bate com os gráficos). */
export function listQuery(f: Filters, r: { start: string; end: string }): string {
  const q = new URLSearchParams(reportQuery({ ...f, category_id: f.category_id === 'none' ? undefined : f.category_id }, r))
  if (f.category_id === 'none') q.set('uncategorized', 'true')
  q.set('effective', 'true')
  return q.toString()
}

/** Variação % inteira (arredondada, meio longe de zero) de prev para cur; null se prev == 0. Só inteiros. */
export function pctChange(cur: number, prev: number): number | null {
  if (prev === 0) return null
  const n = Math.abs((cur - prev) * 100)
  const d = Math.abs(prev)
  const a = 2 * n + d
  const q = (a - (a % (2 * d))) / (2 * d)
  return cur < prev ? -q : q
}

/** Texto de célula CSV: aspas escapadas e fórmulas neutralizadas (= + - @ no início). */
export function csvCell(v: string): string {
  const s = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v
  return /[;"\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

/** CSV (`;`, vírgula decimal gerada de centavos inteiros). O BOM entra no download. */
export function toCsv(rows: Tx[], catName: (id: string | null) => string): string {
  const br = (d: string) => d.split('-').reverse().join('/')
  const head = ['Data', 'Tipo', 'Descrição', 'Estabelecimento', 'Categoria', 'Valor (R$)']
  const lines = rows.map((t) => [
    br(t.occurred_on), t.type === 'income' ? 'Receita' : t.type === 'expense' ? 'Despesa' : csvCell(t.type),
    csvCell(t.description), csvCell(t.merchant ?? ''), csvCell(catName(t.category_id)),
    centsText(t.type === 'expense' ? -t.amount_cents : t.amount_cents), // gerado de inteiro: não passa por csvCell (o '-' é sinal, não fórmula)
  ].join(';'))
  return [head.join(';'), ...lines].join('\r\n')
}

export function downloadCsv(name: string, csv: string) {
  const url = URL.createObjectURL(new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
