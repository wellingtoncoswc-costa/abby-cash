import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { api, ApiError } from './api/client'
import { spaceLabel, useSpace } from './space'
import type { Account, Category, Me, Member } from './api/types'

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
  insufficient_available: 'Valor maior que o disponível na conta (saldo menos o que está nas caixinhas).',
  invalid_transfer: 'Escolha duas contas diferentes.',
  not_editable: 'Este lançamento não pode ser editado; exclua e lance de novo.',
  insufficient_balance: 'Valor maior que o saldo da caixinha.',
  installment_paid_real: 'Esta parcela foi paga com lançamento; exclua o lançamento para desfazer.',
  installment_partial: 'Esta parcela tem pagamento parcial; exclua o lançamento para desfazer.',
  bill_already_paid: 'Esta parcela já está paga.',
  invalid_paid_installments: 'Parcelas já pagas: informe de 0 até o total.',
  invalid_setting: 'Configuração inválida.',
}
export const errText = (e: unknown) =>
  e instanceof ApiError ? (MSG[e.detail] ?? `Não foi possível concluir (${e.detail}).`) : 'Falha de conexão.'

export const Card = ({ title, children }: { title?: string; children: ReactNode }) => (
  <section className="mb-4 rounded-2xl border border-border bg-card p-4 md:p-5">
    {title && <h2 className="mb-3 text-base font-semibold tracking-tight">{title}</h2>}
    {children}
  </section>
)

export const Btn = ({ className = '', ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button
    {...p}
    className={`rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50 ${className}`}
  />
)

export const Err = ({ e }: { e: unknown }) =>
  e ? <p role="alert" className="my-2 text-sm text-destructive">{errText(e)}</p> : null

export const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="mb-3 block">
    <span className="mb-1 block">{label}</span>
    {children}
  </label>
)

/** Espaço reservado enquanto a seção carrega (some sozinho quando os dados chegam). */
export const Esqueleto = ({ rotulo, linhas = 3 }: { rotulo: string; linhas?: number }) => (
  <div role="status" aria-label={`Carregando ${rotulo}`} className="grid gap-2">
    {Array.from({ length: linhas }, (_, i) => <div key={i} className="h-5 animate-pulse rounded-md bg-muted" style={{ width: `${100 - i * 12}%` }} />)}
  </div>
)

export const Bar = ({ value, max }: { value: number; max: number }) => {
  const pct = max > 0 ? Math.min(100, Math.floor((value * 100) / max)) : 0
  const color = value > max ? 'bg-destructive' : pct >= 80 ? 'bg-warning' : 'bg-primary'
  const [on, setOn] = useState(false)
  useEffect(() => { const id = requestAnimationFrame(() => setOn(true)); return () => cancelAnimationFrame(id) }, [])
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className={`h-full rounded-full ${color} transition-[width] duration-700 ease-out`} style={{ width: `${on ? pct : 0}%` }} />
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

/** Contas de TODOS os espaços do usuário; rótulo "Nome · Espaço" quando há mais de um espaço. */
export function useAllAccounts() {
  const { spaces } = useSpace()
  const q = useGet<Account[]>('/accounts')
  const label = (a: Account) => {
    const sp = spaces.find((s) => s.id === a.space_id)
    return spaces.length > 1 && sp ? `${a.name} · ${spaceLabel(sp)}` : a.name
  }
  return { ...q, data: q.data ?? [], label }
}

export const AccountSelect = ({ value, onChange, accounts }: { value: string; onChange: (v: string) => void; accounts: Account[] }) => (
  <select required value={value} onChange={(e) => onChange(e.target.value)}>
    <option value="">Selecione…</option>
    {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
  </select>
)

export const useMe = () => useGet<Me>('/me')

/** Dono do espaço atual? Edição estrutural (contas, cartões, metas) é só dele; o dado vem do /members. */
export function useIsOwner(): boolean {
  const { spaceId } = useSpace()
  const me = useMe()
  const members = useGet<Member[]>(`/spaces/${spaceId}/members`)
  return !!me.data && !!members.data?.some((m) => m.user_id === me.data!.id && m.role === 'owner')
}

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
export function EditBox({ fields, save, remove, what, canEdit = true, startOpen = false }: { fields: EF[]; save: (v: Record<string, string>) => Promise<unknown>; remove: () => Promise<unknown>; what: string; canEdit?: boolean; startOpen?: boolean }) {
  const [open, setOpen] = useState(startOpen)
  const [v, setV] = useState(() => Object.fromEntries(fields.map((f) => [f.k, f.v])))
  const sv = useSend(() => save(v), () => setOpen(false))
  const del = useSend(remove)
  if (!canEdit) return null
  if (!open) return <button type="button" className="mt-1 mr-3 underline" onClick={() => { setV(Object.fromEntries(fields.map((f) => [f.k, f.v]))); setOpen(true) }}>Editar {what}</button>
  return (
    <form className="mt-2 rounded-md bg-muted p-2" onSubmit={(e) => { e.preventDefault(); sv.mutate() }}>
      {fields.map((f) => <Field key={f.k} label={f.label}>
        {f.options ? <select value={v[f.k]} onChange={(e) => setV({ ...v, [f.k]: e.target.value })}>{f.options.map(([o, l]) => <option key={o} value={o}>{l}</option>)}</select>
          : <input type={f.type} value={v[f.k]} onChange={(e) => setV({ ...v, [f.k]: e.target.value })} />}
      </Field>)}
      <Err e={sv.error ?? del.error} />
      <div className="flex gap-2">
        <Btn type="submit" disabled={sv.isPending}>Salvar alterações</Btn>
        <Btn type="button" className="bg-muted-foreground hover:bg-muted-foreground/90" onClick={() => setOpen(false)}>Cancelar</Btn>
        <Btn type="button" className="bg-destructive hover:bg-destructive/90" disabled={del.isPending} onClick={() => { if (confirm(`Excluir ${what}?`)) del.mutate() }}>Excluir</Btn>
      </div>
    </form>
  )
}

/** Centavos -> "1234,56" (campo de edição). */
export const centsText = (c: number) => `${c < 0 ? '-' : ''}${Math.trunc(Math.abs(c) / 100)},${String(Math.abs(c) % 100).padStart(2, '0')}`

/** Janela modal: fecha com Esc, clique no fundo ou no botão Fechar; o foco entra no diálogo. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div role="dialog" aria-modal="true" aria-label={title} className="my-8 w-full max-w-lg rounded-2xl border border-border bg-card p-4 shadow-xl md:p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          <button type="button" aria-label="Fechar" className="rounded-md px-2 py-1 text-lg leading-none" onClick={onClose}>×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

/** Botão redondo só com o "+": o formulário de cadastro abre num Modal. */
export const PlusButton = ({ label, onClick }: { label: string; onClick: () => void }) => (
  <button type="button" aria-label={label} title={label} onClick={onClick}
    className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm hover:bg-primary/90">
    <Plus aria-hidden="true" />
  </button>
)
