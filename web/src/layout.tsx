import { Link, Navigate, Outlet } from '@tanstack/react-router'
import { ArrowLeftRight, CreditCard, Gauge, LayoutDashboard, LogOut, type LucideIcon, Menu, MessageCircle, Moon, Receipt, Rocket, Settings, Shield, Sun, Tags, Target, Users, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { logout } from './api/client'
import type { Space } from './api/types'
import { useAuth } from './auth'
import { Marca } from './marca'
import { useTema } from './tema'
import { SpaceProvider, spaceLabel, useSpace } from './space'
import { Err, useGet, useMe } from './ui'

type Item = readonly [to: string, label: string, Icon: LucideIcon]
const PRINCIPAL: Item[] = [
  ['/', 'Painel', LayoutDashboard], ['/lancamentos', 'Lançamentos', ArrowLeftRight], ['/contas', 'Contas a pagar', Receipt],
  ['/cartoes', 'Cartões', CreditCard], ['/metas', 'Metas', Target],
]
const MAIS: Item[] = [
  ['/categorias', 'Categorias', Tags], ['/teto', 'Teto', Gauge], ['/espacos', 'Espaços', Users], ['/canais', 'Canais', MessageCircle],
  ['/onboarding', 'Primeiros passos', Rocket], ['/config', 'Configurações', Settings],
]
const ADMIN: Item = ['/admin', 'Admin', Shield]
const BARRA = PRINCIPAL.filter(([to]) => ['/', '/lancamentos', '/contas', '/metas'].includes(to))
// rótulo do trilho: escondido recolhido (sem cortar texto), aparece com o trilho aberto
const rotulo = 'whitespace-nowrap max-md:opacity-100 opacity-0 transition-opacity duration-150 group-hover/rail:opacity-100 group-focus-within/rail:opacity-100'
const link = 'flex h-10 items-center gap-3 rounded-lg px-[13px] text-sm font-medium text-sidebar-foreground transition-colors hover:bg-sidebar-accent [&.active]:bg-sidebar-accent [&.active]:text-sidebar-primary'

/** Largura de desktop (sem matchMedia, como nos testes: desktop). */
function useDesktop() {
  const q = '(min-width: 768px)'
  const [d, setD] = useState(() => typeof matchMedia !== 'function' || matchMedia(q).matches)
  useEffect(() => {
    if (typeof matchMedia !== 'function') return
    const m = matchMedia(q)
    const f = () => setD(m.matches)
    m.addEventListener('change', f)
    return () => m.removeEventListener('change', f)
  }, [])
  return d
}

function Espacos() {
  const { spaces, spaceId, setSpaceId } = useSpace()
  return (
    <div role="group" aria-label="Espaço" className="inline-flex rounded-full bg-muted p-1">
      {spaces.map((s) => (
        <button key={s.id} type="button" aria-pressed={s.id === spaceId} onClick={() => setSpaceId(s.id)}
          className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${s.id === spaceId ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
          {spaceLabel(s)}
        </button>
      ))}
    </div>
  )
}

function Tema({ className = '' }: { className?: string }) {
  const [tema, alternar] = useTema()
  return (
    <button type="button" aria-label="Alternar tema" onClick={alternar} className={className}>
      {tema === 'escuro' ? <Sun className="size-5 shrink-0" /> : <Moon className="size-5 shrink-0" />}
      <span className={rotulo}>{tema === 'escuro' ? 'Claro' : 'Escuro'}</span>
    </button>
  )
}

function Trilho({ itens }: { itens: Item[] }) {
  return (
    <nav aria-label="Principal" className="group/rail fixed inset-y-0 left-0 z-20 flex w-16 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar px-1.5 py-3 transition-[width,box-shadow] duration-200 ease-out hover:w-60 hover:shadow-xl focus-within:w-60">
      <Marca recolhivel className="mb-4 px-1.5" />
      <div className="flex flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden">
        {itens.map(([to, label, Icon]) => (
          <Link key={to} to={to} activeOptions={{ exact: true }} className={link}>
            <Icon className="size-5 shrink-0" /><span className={rotulo}>{label}</span>
          </Link>
        ))}
      </div>
      <Tema className={`${link} w-full`} />
      <button type="button" onClick={() => void logout()} className={`${link} w-full`}><LogOut className="size-5 shrink-0" /><span className={rotulo}>Sair</span></button>
    </nav>
  )
}

function Barra({ itens }: { itens: Item[] }) {
  const [aberto, setAberto] = useState(false)
  const item = 'relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-muted-foreground transition-colors [&.active]:text-primary'
  return (
    <>
      <nav aria-label="Principal" className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
        {BARRA.map(([to, label, Icon]) => (
          <Link key={to} to={to} activeOptions={{ exact: true }} className={item}>
            <Icon className="size-5" /><span>{label.split(' ')[0]}</span>
          </Link>
        ))}
        <button type="button" aria-expanded={aberto} onClick={() => setAberto(true)} className={item}><Menu className="size-5" /><span>Mais</span></button>
      </nav>
      {aberto && (
        <div className="fixed inset-0 z-30 flex items-end bg-foreground/40" onClick={() => setAberto(false)}>
          <div role="dialog" aria-label="Mais opções" className="w-full rounded-t-2xl bg-background p-4 pb-8" style={{ animation: 'sheet-in .22s ease-out' }} onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between"><span className="font-semibold">Mais</span><button type="button" aria-label="Fechar" onClick={() => setAberto(false)}><X className="size-5" /></button></div>
            <div className="grid grid-cols-2 gap-2" onClick={() => setAberto(false)}>
              {itens.filter(([to]) => !BARRA.some(([b]) => b === to)).map(([to, label, Icon]) => (
                <Link key={to} to={to} className="flex items-center gap-3 rounded-xl bg-muted px-3 py-3 text-sm font-medium text-foreground"><Icon className="size-5 text-primary" />{label}</Link>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <Tema className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-border py-2.5 text-sm font-medium" />
              <button type="button" onClick={() => void logout()} className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-border py-2.5 text-sm font-medium"><LogOut className="size-5" />Sair</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Shell() {
  const me = useMe()
  const desktop = useDesktop()
  const itens = [...PRINCIPAL, ...MAIS, ...(me.data?.is_admin ? [ADMIN] : [])]
  return (
    <div className={desktop ? 'pl-16' : 'pb-20'}>
      {desktop ? <Trilho itens={itens} /> : <Barra itens={itens} />}
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-background/90 px-4 py-3 backdrop-blur">
        {!desktop && <Marca className="mr-auto" />}
        <Espacos />
      </header>
      <main className="mx-auto max-w-5xl p-4 md:p-6"><Outlet /></main>
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
