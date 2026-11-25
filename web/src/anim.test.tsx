import { renderHook } from '@testing-library/react'
import { useNovos } from './anim'
import { makeRouter } from './router'

test('useNovos: a primeira carga não destaca; o que chega depois, sim', () => {
  const { result, rerender } = renderHook(({ ids }) => useNovos(ids), { initialProps: { ids: ['a', 'b'] } })
  expect(result.current.size).toBe(0)
  rerender({ ids: ['c', 'a', 'b'] })
  expect([...result.current]).toEqual(['c'])
  rerender({ ids: ['c', 'a', 'b'] })
  expect([...result.current]).toEqual(['c'])
})

test('ids vazios na primeira carga não fazem a lista inteira parecer nova', () => {
  const { result, rerender } = renderHook(({ ids }) => useNovos(ids), { initialProps: { ids: [] as string[] } })
  rerender({ ids: ['a', 'b'] })
  expect(result.current.size).toBe(0)
})

test('navegação usa transição de página nativa', () => {
  expect(makeRouter().options.defaultViewTransition).toBe(true)
})
