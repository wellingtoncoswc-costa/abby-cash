import type { components } from './schema'

// O OpenAPI do backend não descreve as respostas (todas `object`); estes são os campos lidos pela web.
export type S = components['schemas']
export type Space = { id: string; type: 'personal' | 'family' | string; name: string }
export type Account = { id: string; space_id: string; type: string; name: string; initial_balance_cents: number }
export type Card = { id: string; space_id: string; name: string; closing_day: number; due_day: number; limit_cents: number | null }
export type Invoice = { id: string; card_id: string; closing_on: string; due_on: string; total_cents: number; paid_cents: number; remaining_cents: number; status: string }
export type Tx = { id: string; space_id: string; type: 'expense' | 'income' | 'transfer'; amount_cents: number; occurred_on: string; description: string; merchant: string | null; category_id: string | null; account_id: string | null }
export type Bill = { id: string; space_id: string; kind: string; description: string; amount_cents: number; due_on: string; status: 'open' | 'paid' | 'partial'; invoice_id: string | null }
export type Goal = { id: string; space_id: string; name: string; target_cents: number; deadline: string | null; saved_cents: number; monthly_needed_cents: number | null; behind: boolean }
export type Budget = { month: string; limit_cents: number; spent_cents: number; categories: { category_id: string; limit_cents: number; spent_cents: number }[] }
export type Statement = { items: { id: string; type: string; amount_cents: number; occurred_on: string; description: string; merchant: string | null }[]; private_total_cents: number; total_cents: number }
export type LinkCode = { code: string; expires_in_s: number; deep_link: string | null }
export type ChannelLinkRow = { channel: string; verified_at: string | null }
