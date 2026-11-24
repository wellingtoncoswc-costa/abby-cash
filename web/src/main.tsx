import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { initTheme } from './layout'
import { makeRouter } from './router'

initTheme()
const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000 } } })
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <RouterProvider router={makeRouter()} />
    </QueryClientProvider>
  </StrictMode>,
)
