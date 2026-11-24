import type { components } from './schema'

export type S = components['schemas']
export type Space = S['SpaceOut']
// `institution`: chave do catálogo src/banks.ts (backend novo; schema.d.ts ainda não regenerado).
type Inst = { institution?: string | null }
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
