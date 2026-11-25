import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { BankIcon, BankSelect } from './bank-icon'
import { BANKS, BANK_LIST, bankOf } from './banks'

const tile = (c: HTMLElement) => c.querySelector('[data-bank]') as HTMLElement

describe('BankIcon', () => {
  it('mostra o logo quando o banco tem um', () => {
    const { container } = render(<BankIcon institution="nubank" name="Minha conta" />)
    expect(tile(container).dataset.bank).toBe('nubank')
    expect(container.querySelector('svg path')).not.toBeNull()
  })
  it('usa monograma da marca quando não há logo', () => {
    const { container } = render(<BankIcon institution="itau" name="Itaú PJ" />)
    expect(tile(container)).toHaveTextContent('It')
    expect(container.querySelector('svg')).toBeNull()
    expect(tile(container).style.background).not.toBe('')
  })
  it.each([[null], [undefined], ['inexistente'], ['outro'], ['constructor']])('chave %s → inicial neutra do nome da conta', (k) => {
    const { container } = render(<BankIcon institution={k} name="carteira" />)
    expect(tile(container).dataset.bank).toBe('neutral')
    expect(tile(container)).toHaveTextContent('C')
    expect(tile(container).className).toContain('bg-muted')
  })
  it('é decorativo e respeita o tamanho', () => {
    const { container } = render(<BankIcon institution="inter" name="x" size={40} />)
    expect(tile(container)).toHaveAttribute('aria-hidden', 'true')
    expect(tile(container).style.width).toBe('40px')
  })
})

describe('catálogo', () => {
  it('chaves válidas para o backend e nomes únicos', () => {
    for (const k of Object.keys(BANKS)) expect(k).toMatch(/^[a-z0-9_]{1,40}$/)
    expect(new Set(BANK_LIST.map((b) => b.name)).size).toBe(BANK_LIST.length)
    expect(bankOf('toString')).toBeUndefined()
  })
})

describe('BankSelect', () => {
  function Host() {
    const [v, setV] = useState('')
    return <BankSelect value={v} onChange={setV} name="Conta" />
  }
  it('lista os bancos e troca o ícone ao selecionar', async () => {
    const { container } = render(<Host />)
    expect(tile(container).dataset.bank).toBe('neutral')
    await userEvent.selectOptions(screen.getByLabelText('Banco'), 'nubank')
    expect(tile(container).dataset.bank).toBe('nubank')
    expect(screen.getByRole('option', { name: 'Banco do Brasil' })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Banco'), '')
    expect(tile(container).dataset.bank).toBe('neutral')
  })
})
