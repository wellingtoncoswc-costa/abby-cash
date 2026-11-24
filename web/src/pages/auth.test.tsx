import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { makeRouter } from '../router'

test('login pede o 2FA quando a API exige', async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === '/auth/refresh') return new Response('{}', { status: 401 })
    return new Response(JSON.stringify({ detail: 'totp_required' }), { status: 401 })
  })
  vi.stubGlobal('fetch', fetchMock)
  const router = makeRouter(createMemoryHistory({ initialEntries: ['/login'] }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={router} /></QueryClientProvider>)
  await userEvent.type(await screen.findByLabelText('E-mail'), 'a@b.co')
  await userEvent.type(screen.getByLabelText('Senha'), 'senha-correta')
  await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
  expect(await screen.findByLabelText(/Código do autenticador/)).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('Informe o código do autenticador.')
})
