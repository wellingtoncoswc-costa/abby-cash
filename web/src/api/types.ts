import type { components } from './schema'

export type S = components['schemas']
export type Space = S['SpaceOut']
export type Account = S['AccountOut']
export type AccountIn = S['AccountIn']
export type AccountPatch = S['AccountPatch']
export type Card = S['CardOut']
export type Invoice = S['InvoiceOut']
export type Tx = S['TransactionOut']
export type Bill = S['BillOut']
export type Goal = S['GoalProgressOut']
export type Budget = S['BudgetOut']
export type Category = S['CategoryOut']
export type Me = S['MeOut']
export type Member = S['MemberOut']
// Respostas ainda sem modelo no OpenAPI (object): campos lidos pela web.
export type Statement = { items: { id: string; type: string; amount_cents: number; occurred_on: string; description: string; merchant: string | null }[]; private_total_cents: number; total_cents: number }
export type LinkCode = { code: string; expires_in_s: number; deep_link: string | null }
export type ChannelLinkRow = { channel: string; verified_at: string | null }

export type Pocket = S['PocketOut']
export type Cdi = S['CdiLatestOut']
export type Loan = S['LoanOut']

// Visão geral de Análises. Tipos à mão; virar `S[...]` após `npm run gen:api` (backend ainda não mesclado).
export type ReportTotals = { income_cents: number; expense_cents: number; net_cents: number; tx_count: number; avg_daily_expense_cents: number }
export type OverviewOut = {
  totals: ReportTotals
  previous: ReportTotals
  by_category: { category_id: string | null; name: string; expense_cents: number; count: number; share_bp: number }[]
  by_merchant: { merchant: string; expense_cents: number; count: number }[]
  by_account: { account_id: string | null; name: string; income_cents: number; expense_cents: number }[]
  by_day: { date: string; income_cents: number; expense_cents: number }[]
  by_month: { month: string; income_cents: number; expense_cents: number; net_cents: number }[]
  by_weekday: { dow: number; expense_cents: number; count: number }[]
  largest: { id: string; occurred_on: string; description: string; merchant: string | null; category_id: string | null; amount_cents: number; type: string }[]
  balance_series: { month: string; balance_cents: number }[]
  upcoming: { kind: 'bill' | 'invoice'; id: string; description: string; due_on: string; amount_cents: number }[]
}
