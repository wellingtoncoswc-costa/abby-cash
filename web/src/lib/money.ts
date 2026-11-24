/** Centavos (inteiro) -> "R$ 1.234,56". Nunca usa float: separa reais e centavos por divisão inteira. */
export function formatBRL(cents: number): string {
  if (!Number.isSafeInteger(cents)) throw new Error('amount_cents deve ser inteiro')
  const neg = cents < 0
  const abs = Math.abs(cents)
  const reais = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${neg ? '-' : ''}R$ ${reais},${String(abs % 100).padStart(2, '0')}`
}

/** "1.234,56" | "45" | "45,5" -> centavos; null se inválido. */
export function parseBRL(text: string): number | null {
  const m = /^\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*$/.exec(text.replace(/^R\$\s*/, ''))
  if (!m) return null
  const cents = Number(m[1].replace(/\./g, '')) * 100 + Number((m[2] ?? '').padEnd(2, '0'))
  return Number.isSafeInteger(cents) ? cents : null
}
