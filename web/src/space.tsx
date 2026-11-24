import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Space } from './api/types'

type Ctx = { spaces: Space[]; spaceId: string; setSpaceId: (id: string) => void }
const C = createContext<Ctx | null>(null)
const KEY = 'space'
const read = () => { try { return localStorage.getItem(KEY) } catch { return null } }

export function SpaceProvider({ spaces, children }: { spaces: Space[]; children: ReactNode }) {
  const [saved, setSaved] = useState(read)
  const spaceId = spaces.find((s) => s.id === saved)?.id ?? spaces[0]?.id ?? ''
  const v = useMemo<Ctx>(() => ({
    spaces, spaceId,
    setSpaceId: (id) => { setSaved(id); try { localStorage.setItem(KEY, id) } catch { /* sem storage */ } },
  }), [spaces, spaceId])
  return <C.Provider value={v}>{children}</C.Provider>
}

export function useSpace() {
  const c = useContext(C)
  if (!c) throw new Error('SpaceProvider ausente')
  return c
}
export const spaceLabel = (s: Space) => (s.type === 'family' ? `Família · ${s.name}` : 'Pessoal')
