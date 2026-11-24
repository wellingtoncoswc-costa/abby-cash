import { siMercadopago, siNubank, siPicpay, siPagseguro } from 'simple-icons'

/** Catálogo de bancos: a chave é o valor gravado em `accounts.institution`. `logo` = path SVG (simple-icons, CC0, viewBox 24); sem logo → monograma. */
export type Bank = { name: string; color: string; fg: string; mono: string; logo?: string }

const W = '#ffffff'
const D = '#1a1a1a'
const b = (name: string, color: string, mono: string, fg = W, logo?: { path: string }): Bank => ({ name, color, fg, mono, logo: logo?.path })

// Cores de marca são dado do catálogo (não são tokens do tema). Neon e Next: sem logo no simple-icons (o "neon" de lá é outra empresa).
export const BANKS = {
  nubank: b('Nubank', '#820ad1', 'Nu', W, siNubank),
  itau: b('Itaú', '#ec7000', 'It'),
  bradesco: b('Bradesco', '#cc092f', 'Br'),
  santander: b('Santander', '#ec0000', 'Sa'),
  bancodobrasil: b('Banco do Brasil', '#fae128', 'BB', D),
  caixa: b('Caixa', '#005ca9', 'CX'),
  inter: b('Inter', '#ff7a00', 'In'),
  c6: b('C6 Bank', '#242424', 'C6'),
  btg: b('BTG Pactual', '#001e62', 'BTG'),
  xp: b('XP', '#1a1a1a', 'XP'),
  picpay: b('PicPay', '#21c25e', 'Pic', W, siPicpay),
  mercadopago: b('Mercado Pago', '#00b1ea', 'MP', W, siMercadopago),
  sicoob: b('Sicoob', '#003641', 'Sc'),
  sicredi: b('Sicredi', '#3fa110', 'Sr'),
  safra: b('Safra', '#00205b', 'Sf'),
  original: b('Original', '#00a859', 'Or'),
  neon: b('Neon', '#00b8d4', 'Ne', D),
  next: b('Next', '#00ff5f', 'Nx', D),
  pagbank: b('PagBank', '#ffc801', 'PB', D, siPagseguro),
  outro: b('Outro', '', '?'),
} satisfies Record<string, Bank>

export type BankKey = keyof typeof BANKS
export const bankOf = (key?: string | null): Bank | undefined => (key && Object.hasOwn(BANKS, key) ? BANKS[key as BankKey] : undefined)
export const BANK_LIST = (Object.keys(BANKS) as BankKey[]).map((k) => ({ key: k, name: BANKS[k].name }))
