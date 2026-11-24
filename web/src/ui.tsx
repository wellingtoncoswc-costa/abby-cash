import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { api, ApiError } from './api/client'
import { useSpace } from './space'
import type { Account } from './api/types'

const MSG: Record<string, string> = {
  invalid_credentials: 'E-mail ou senha incorretos.',
  totp_required: 'Informe o código do autenticador.',
  invalid_totp: 'Código do autenticador inválido.',
  too_many_attempts: 'Muitas tentativas. Aguarde alguns minutos.',
  invalid_invite: 'Convite inválido ou já usado.',
  budget_not_found: 'Teto não definido.',
  family_space_exists: 'Você já tem um espaço familiar.',
  not_found: 'Não encontrado.',
  invalid_code: 'Código inválido.',
  totp_already_enabled: 'O 2FA já está ativo.',
}
export const errText = (e: unknown) =>
  e instanceof ApiError ? (MSG[e.detail] ?? `Não foi possível concluir (${e.detail}).`) : 'Falha de conexão.'

export const Card = ({ title, children }: { title?: string; children: ReactNode }) => (
  <section className="mb-4 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
    {title && <h2 className="mb-2 text-lg font-semibold">{title}</h2>}
    {children}
  </section>
)

export const Btn = ({ className = '', ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button
    {...p}
    className={`rounded-md bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800 disabled:opacity-50 ${className}`}
  />
)

export const Err = ({ e }: { e: unknown }) =>
  e ? <p role="alert" className="my-2 text-sm text-red-600 dark:text-red-400">{errText(e)}</p> : null

export const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="mb-3 block">
    <span className="mb-1 block">{label}</span>
    {children}
  </label>
)

export const Bar = ({ value, max }: { value: number; max: number }) => {
  const pct = max > 0 ? Math.min(100, Math.floor((value * 100) / max)) : 0
  const color = value > max ? 'bg-red-600' : pct >= 80 ? 'bg-amber-500' : 'bg-teal-600'
  return (
    <div className="h-3 w-full overflow-hidden rounded bg-slate-200 dark:bg-slate-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function useGet<T>(path: string | null) {
  return useQuery({ queryKey: [path], queryFn: () => api<T>('GET', path!), enabled: path !== null })
}

/** Mutação que invalida tudo ao concluir (poucos dados; simples e correto). */
export function useSend<V = void, R = unknown>(fn: (v: V) => Promise<R>, onOk?: (r: R) => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => { void qc.invalidateQueries(); onOk?.(r) },
  })
}

export const today = () => new Date().toLocaleDateString('sv-SE') // YYYY-MM-DD local
export const monthKey = (d = new Date()) => d.toLocaleDateString('sv-SE').slice(0, 7)

/** Contas do espaço ativo (para os seletores). */
export function useAccounts(all = false) {
  const { spaceId } = useSpace()
  const q = useGet<Account[]>('/accounts')
  return { ...q, data: q.data?.filter((a) => all || a.space_id === spaceId) ?? [] }
}

export const AccountSelect = ({ value, onChange, accounts }: { value: string; onChange: (v: string) => void; accounts: Account[] }) => (
  <select required value={value} onChange={(e) => onChange(e.target.value)}>
    <option value="">Selecione…</option>
    {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
  </select>
)

export const catName = (id: string | null) => (id ? `Categoria #${id.slice(0, 4)}` : 'Sem categoria')
