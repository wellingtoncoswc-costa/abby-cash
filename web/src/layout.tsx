import { Link, Navigate, Outlet } from '@tanstack/react-router'
import { useEffect } from 'react'
import { logout } from './api/client'
import type { Space } from './api/types'
import { useAuth } from './auth'
import { Marca } from './marca'
import { useTema } from './tema'
import { SpaceProvider, spaceLabel, useSpace } from './space'
import { Err, useGet, useMe } from './ui'

const ADMIN = ['/admin', 'Admin'] as const
const NAV = [
  ['/', 'Painel'], ['/lancamentos', 'Lançamentos'], ['/contas', 'Contas a pagar'], ['/cartoes', 'Cartões'],
  ['/metas', 'Metas'], ['/categorias', 'Categorias'], ['/onboarding', 'Primeiros passos'], ['/teto', 'Teto'], ['/espacos', 'Espaços'], ['/canais', 'Canais'], ['/config', 'Configurações'],
] as const

function Shell() {
  const { spaces, spaceId, setSpaceId } = useSpace()
  const me = useMe()
  const [tema, alternar] = useTema()
  return (
    <div className="mx-auto max-w-3xl pb-8">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 p-3">
        <div className="flex items-center gap-2">
          <Marca className="mr-auto" />
          <select aria-label="Espaço" className="!w-auto" value={spaceId} onChange={(e) => setSpaceId(e.target.value)}>
            {spaces.map((s) => <option key={s.id} value={s.id}>{spaceLabel(s)}</option>)}
          </select>
          <button type="button" aria-label="Alternar tema" className="px-2 text-sm underline" onClick={alternar}>{tema === 'escuro' ? 'Claro' : 'Escuro'}</button>
          <button type="button" className="px-2 text-sm underline" onClick={() => void logout()}>Sair</button>
        </div>
        <nav aria-label="Principal" className="mt-2 flex gap-3 overflow-x-auto whitespace-nowrap text-sm">
          {(me.data?.is_admin ? [...NAV, ADMIN] : NAV).map(([to, label]) => <Link key={to} to={to} activeOptions={{ exact: true }} className="py-1 [&.active]:font-bold [&.active]:underline">{label}</Link>)}
        </nav>
      </header>
      <main className="p-3"><Outlet /></main>
    </div>
  )
}

export function Protected() {
  const { status } = useAuth()
  const spaces = useGet<Space[]>(status === 'in' ? '/spaces' : null)
  useEffect(() => { document.title = 'abby cash' }, [])
  if (status === 'loading') return <p className="p-4">Carregando…</p>
  if (status === 'out') return <Navigate to="/login" />
  if (spaces.error) return <div className="p-4"><Err e={spaces.error} /></div>
  if (!spaces.data) return <p className="p-4">Carregando…</p>
  return <SpaceProvider spaces={spaces.data}><Shell /></SpaceProvider>
}
