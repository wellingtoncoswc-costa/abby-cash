import { formatBRL, parseBRL } from './money'

test('formatBRL', () => {
  expect(formatBRL(123456)).toBe('R$ 1.234,56')
  expect(formatBRL(0)).toBe('R$ 0,00')
  expect(formatBRL(5)).toBe('R$ 0,05')
  expect(formatBRL(100000000)).toBe('R$ 1.000.000,00')
  expect(formatBRL(-4500)).toBe('-R$ 45,00')
  expect(() => formatBRL(45.5)).toThrow()
})

test('parseBRL', () => {
  expect(parseBRL('1.234,56')).toBe(123456)
  expect(parseBRL('45')).toBe(4500)
  expect(parseBRL('45,5')).toBe(4550)
  expect(parseBRL('R$ 0,99')).toBe(99)
  expect(parseBRL('1,234')).toBeNull()
  expect(parseBRL('abc')).toBeNull()
  expect(parseBRL('')).toBeNull()
})
