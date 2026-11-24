import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { refresh, setOnLogout } from './api/client'

type Status = 'loading' | 'in' | 'out'
const C = createContext<{ status: Status; setStatus: (s: Status) => void }>({ status: 'loading', setStatus: () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const qc = useQueryClient()
  useEffect(() => {
    setOnLogout(() => { qc.clear(); setStatus('out') })
    void refresh().then((ok) => setStatus(ok ? 'in' : 'out'))
  }, [qc])
  return <C.Provider value={{ status, setStatus }}>{children}</C.Provider>
}
export const useAuth = () => useContext(C)
