import type { Tx } from '../api/types'
import { gastoPorDia, insights } from './insights'

const tx = (occurred_on: string, amount_cents: number, category_id = 'c1', type = 'expense') => ({ occurred_on, amount_cents, category_id, type }) as Tx
const nome = (id: string | null) => (id === 'c2' ? 'Lazer' : 'Mercado')

test('gastoPorDia soma só despesas por dia do mês', () => {
  const m = gastoPorDia([tx('2026-11-03', 1000), tx('2026-11-03', 500), tx('2026-11-04', 9999, 'c1', 'income'), tx('2026-11-05', 700, 'c1', 'transfer')])
  expect([...m]).toEqual([[3, 1500]])
})

test('insights compara o mesmo período do mês anterior', () => {
  const ant = [tx('2026-10-02', 10000), tx('2026-10-20', 99999)] // dia 20 fica fora: hoje é dia 10
  const atual = [tx('2026-11-02', 8000)]
  expect(insights(atual, ant, 10, 'outubro', nome)).toEqual(['Você gastou 20% menos que no mesmo período de outubro.'])
})

test('insights aponta a categoria que mais cresceu', () => {
  const ant = [tx('2026-10-02', 10000, 'c1'), tx('2026-10-03', 1000, 'c2')]
  const atual = [tx('2026-11-02', 10000, 'c1'), tx('2026-11-03', 6000, 'c2')]
  expect(insights(atual, ant, 10, 'outubro', nome)).toEqual([
    'Você gastou 45% mais que no mesmo período de outubro.',
    'Lazer foi a categoria que mais cresceu: +R$ 50,00.',
  ])
})

test('sem mês anterior não há insight', () => {
  expect(insights([tx('2026-11-02', 100)], [], 10, 'outubro', nome)).toEqual([])
})
