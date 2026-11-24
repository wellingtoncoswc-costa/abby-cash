import type { Tx } from '../api/types'
import { csvCell, listQuery, monthRange, parseFilters, pctChange, reportQuery, resolveRange, toCsv, wholeMonth } from './reports'

test('pctChange: inteiros, arredondamento e divisão por zero', () => {
  expect(pctChange(150, 100)).toBe(50)
  expect(pctChange(50, 100)).toBe(-50)
  expect(pctChange(100, 100)).toBe(0)
  expect(pctChange(10, 0)).toBeNull()
  expect(pctChange(0, 0)).toBeNull()
  expect(pctChange(1, 3)).toBe(-67) // -66,67 -> -67
  expect(pctChange(-50, -100)).toBe(50) // prejuízo menor = melhora
  expect(pctChange(2 * 10 ** 12, 10 ** 12)).toBe(100)
})

test('parseFilters normaliza a URL', () => {
  expect(parseFilters({})).toEqual({})
  expect(parseFilters({ per: 'mes' })).toEqual({})
  expect(parseFilters({ per: '30d', type: 'expense', account_id: 'a1', x: 1 })).toEqual({ per: '30d', type: 'expense', account_id: 'a1' })
  expect(parseFilters({ per: 'zzz', type: 'transfer' })).toEqual({})
  expect(parseFilters({ per: 'custom', start: '2026-11-10', end: '2026-11-01' })).toEqual({})
  expect(parseFilters({ per: 'custom', start: '2026-02-31', end: '2026-03-01' })).toEqual({})
  expect(parseFilters({ per: 'custom', start: '2000-01-01', end: '2026-11-01' })).toEqual({})
  expect(parseFilters({ per: 'custom', start: '2026-11-01', end: '2026-11-15', merchant: 123 })).toEqual({ per: 'custom', start: '2026-11-01', end: '2026-11-15', merchant: '123' })
})

test('resolveRange e wholeMonth', () => {
  const h = '2026-11-24'
  expect(resolveRange({}, h)).toEqual({ start: '2026-11-01', end: '2026-11-30' })
  expect(resolveRange({ per: 'anterior' }, h)).toEqual({ start: '2026-10-01', end: '2026-10-31' })
  expect(resolveRange({ per: '30d' }, h)).toEqual({ start: '2026-10-26', end: h })
  expect(resolveRange({ per: '3m' }, h)).toEqual({ start: '2026-09-01', end: h })
  expect(resolveRange({ per: '12m' }, h)).toEqual({ start: '2025-12-01', end: h })
  expect(resolveRange({ per: 'anterior' }, '2026-01-10')).toEqual({ start: '2025-12-01', end: '2025-12-31' })
  expect(wholeMonth(resolveRange({}, h))).toBe('2026-11')
  expect(wholeMonth(resolveRange({ per: '30d' }, h))).toBeNull()
  expect(monthRange('2024-02')).toEqual({ start: '2024-02-01', end: '2024-02-29' })
})

test('reportQuery só inclui filtros ativos', () => {
  expect(reportQuery({ category_id: 'none', merchant: 'Pão & Cia' }, { start: '2026-11-01', end: '2026-11-30' })).toBe('start=2026-11-01&end=2026-11-30&category_id=none&merchant=P%C3%A3o+%26+Cia')
})

test('csvCell escapa aspas e neutraliza fórmulas', () => {
  expect(csvCell('=SUM(A1)')).toBe("'=SUM(A1)")
  expect(csvCell('+1')).toBe("'+1")
  expect(csvCell('-1')).toBe("'-1")
  expect(csvCell('@x')).toBe("'@x")
  expect(csvCell('a;b')).toBe('"a;b"')
  expect(csvCell('diz "oi"')).toBe('"diz ""oi"""')
  expect(csvCell('normal')).toBe('normal')
})

test('toCsv: separador ;, vírgula decimal, valores grandes sem float', () => {
  const tx = (o: Partial<Tx>) => ({ id: 'x', type: 'expense', amount_cents: 0, occurred_on: '2026-11-02', description: '', merchant: null, category_id: null, ...o }) as Tx
  const csv = toCsv([
    tx({ amount_cents: 123456, description: '=HYPERLINK("x")', merchant: 'Padaria; Pão' }),
    tx({ type: 'income', amount_cents: 5, description: 'Salário' }),
    tx({ amount_cents: 10 ** 14 + 1 }),
  ], (id) => (id ? 'Mercado' : 'Sem categoria'))
  const [head, a, b, c] = csv.split('\r\n')
  expect(head).toBe('Data;Tipo;Descrição;Estabelecimento;Categoria;Valor (R$)')
  expect(a).toBe('02/11/2026;Despesa;"\'=HYPERLINK(""x"")";"Padaria; Pão";Sem categoria;-1234,56')
  expect(b).toBe('02/11/2026;Receita;Salário;;Sem categoria;0,05')
  expect(c.endsWith(';-1000000000000,01')).toBe(true)
})

test('listQuery: sem categoria vira uncategorized e usa data efetiva', () => {
  const r = { start: '2026-11-01', end: '2026-11-30' }
  expect(listQuery({ category_id: 'none', account_id: 'a1' }, r)).toBe('start=2026-11-01&end=2026-11-30&account_id=a1&uncategorized=true&effective=true')
  expect(listQuery({ category_id: 'c1' }, r)).toBe('start=2026-11-01&end=2026-11-30&category_id=c1&effective=true')
})
