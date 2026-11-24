import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { api, ApiError } from './api/client'
import { useSpace } from './space'
import type { Account, Category, Me } from './api/types'

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
  invalid_amount: 'Valor inválido.',
  admin_only: 'Apenas administradores.',
  invalid_setting: 'Configuração inválida.',
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

export const useMe = () => useGet<Me>('/me')

export function useCategories() {
  const { spaceId } = useSpace()
  const q = useGet<Category[]>(`/spaces/${spaceId}/categories`)
  return { ...q, data: q.data ?? [] }
}

/** id -> nome da categoria do espaço ativo ("Sem categoria" se vazio/desconhecido). */
export function useCatName() {
  const { data } = useCategories()
  return (id: string | null) => (id ? (data.find((c) => c.id === id)?.name ?? 'Outra categoria') : 'Sem categoria')
}

export const CategorySelect = ({ value, onChange, label = 'Categoria' }: { value: string; onChange: (v: string) => void; label?: string }) => {
  const { data } = useCategories()
  return (
    <Field label={label}>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Sem categoria</option>
        {data.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </Field>
  )
}

export const br = (d: string) => d.split('-').reverse().join('/')

type EF = { k: string; label: string; v: string; type?: string; options?: [string, string][] }
/** Editar/excluir inline: campos em texto; o chamador converte em `save`. */
export function EditBox({ fields, save, remove, what }: { fields: EF[]; save: (v: Record<string, string>) => Promise<unknown>; remove: () => Promise<unknown>; what: string }) {
  const [open, setOpen] = useState(false)
  const [v, setV] = useState(() => Object.fromEntries(fields.map((f) => [f.k, f.v])))
  const sv = useSend(() => save(v), () => setOpen(false))
  const del = useSend(remove)
  if (!open) return <button type="button" className="mt-1 mr-3 underline" onClick={() => { setV(Object.fromEntries(fields.map((f) => [f.k, f.v]))); setOpen(true) }}>Editar {what}</button>
  return (
    <form className="mt-2 rounded-md bg-slate-50 p-2 dark:bg-slate-900" onSubmit={(e) => { e.preventDefault(); sv.mutate() }}>
      {fields.map((f) => <Field key={f.k} label={f.label}>
        {f.options ? <select value={v[f.k]} onChange={(e) => setV({ ...v, [f.k]: e.target.value })}>{f.options.map(([o, l]) => <option key={o} value={o}>{l}</option>)}</select>
          : <input type={f.type} value={v[f.k]} onChange={(e) => setV({ ...v, [f.k]: e.target.value })} />}
      </Field>)}
      <Err e={sv.error ?? del.error} />
      <div className="flex gap-2">
        <Btn type="submit" disabled={sv.isPending}>Salvar alterações</Btn>
        <Btn type="button" className="bg-slate-600 hover:bg-slate-700" onClick={() => setOpen(false)}>Cancelar</Btn>
        <Btn type="button" className="bg-red-700 hover:bg-red-800" disabled={del.isPending} onClick={() => { if (confirm(`Excluir ${what}?`)) del.mutate() }}>Excluir</Btn>
      </div>
    </form>
  )
}

/** Centavos -> "1234,56" (campo de edição). */
export const centsText = (c: number) => `${c < 0 ? '-' : ''}${Math.trunc(Math.abs(c) / 100)},${String(Math.abs(c) % 100).padStart(2, '0')}`
