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
export type Installment = S['InstallmentOut']

// Visão geral de Análises (tipo gerado do OpenAPI).
export type ReportTotals = { income_cents: number; expense_cents: number; net_cents: number; tx_count: number; avg_daily_expense_cents: number }
export type OverviewOut = S['OverviewOut']
