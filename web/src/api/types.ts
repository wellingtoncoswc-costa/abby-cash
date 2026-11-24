import type { components } from './schema'

export type S = components['schemas']
export type Space = S['SpaceOut']
// `institution`: chave do catálogo src/banks.ts (backend novo; schema.d.ts ainda não regenerado).
type Inst = { institution?: string | null; pockets_cents?: number; available_cents?: number }
export type Account = S['AccountOut'] & Inst
export type AccountIn = S['AccountIn'] & Inst
export type AccountPatch = S['AccountPatch'] & Inst
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

// Caixinhas e financiamentos: tipos à mão (backend novo); viram `S[...]` após `npm run gen:api`.
export type Pocket = { id: string; account_id: string; name: string; cdi_bp: number; balance_cents: number; pending_yield_cents: number; month_yield_cents: number }
export type Cdi = { on_date: string; daily_pct: string | number; annual_pct: string | number }
export type Loan = { id: string; kind: 'financing' | 'consortium'; name: string; installment_cents: number; installments_total: number; paid_count: number; remaining_count: number; remaining_cents: number; next_due_on: string | null; last_due_on: string | null; progress_pct: number }
