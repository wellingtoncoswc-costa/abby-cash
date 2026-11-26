import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ApiError, apiPage, fetchBlob } from '../api/client'
import type { Card as CardT, Member, S, Tx } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Btn, Card, CategorySelect, EditBox, Err, Field, Modal, br, centsText, today, useAccounts, useAllAccounts, useCategories, useGet, useSend } from '../ui'
import { TxList } from './dashboard'

const PAGE = 20

/** Comprovante: busca autenticada vira blob URL, revogada ao desmontar. */
export function Receipt({ id }: { id: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [fail, setFail] = useState(false)
  useEffect(() => {
    let u: string | null = null
    let dead = false
    fetchBlob(`/attachments/${id}`).then((b) => { if (!dead) setUrl((u = URL.createObjectURL(b))) }).catch(() => setFail(true))
    return () => { dead = true; if (u) URL.revokeObjectURL(u) }
  }, [id])
  if (fail) return <p>Comprovante indisponível.</p>
  return url ? <img src={url} alt="Comprovante" className="mt-2 max-h-96 rounded-md" /> : <p>Carregando comprovante…</p>
}

function TransferDetail({ t, onClose }: { t: Tx; onClose: () => void }) {
  const { data, label } = useAllAccounts()
  const name = (id: string | null) => { const a = data.find((x) => x.id === id); return a ? label(a) : 'Conta' }
  const del = useSend(() => api('DELETE', `/transactions/${t.id}`), onClose)
  return (
    <div>
      <p>Transferência · {name(t.account_id)} → {name(t.counter_account_id)} · {formatBRL(t.amount_cents)} · {br(t.occurred_on)}</p>
      {t.description && <p>{t.description}</p>}
      <p className="text-sm">Transferências não podem ser editadas. Exclua e lance de novo para corrigir.</p>
      <Err e={del.error} />
      <Btn type="button" className="mt-2 bg-destructive hover:bg-destructive/90" disabled={del.isPending} onClick={() => { if (confirm('Excluir transferência?')) del.mutate() }}>Excluir transferência</Btn>
      <button type="button" className="mt-2 ml-3 underline" onClick={onClose}>Fechar</button>
    </div>
  )
}

export function TxDetail({ t, onClose }: { t: Tx; onClose: () => void }) {
  const transfer = t.type === 'transfer'
  return (
    <Modal title={transfer ? 'Detalhes da transferência' : 'Editar lançamento'} onClose={onClose}>
      {transfer ? <TransferDetail t={t} onClose={onClose} /> : <ExpenseDetail t={t} onClose={onClose} />}
    </Modal>
  )
}

function ExpenseDetail({ t, onClose }: { t: Tx; onClose: () => void }) {
  const cats = useCategories()
  const locked = !!(t.card_id || t.installment_group_id) // valor e data mexem na fatura: só pelo chat/recriando
  const init: Record<string, string> = { amount: centsText(t.amount_cents), description: t.description, merchant: t.merchant ?? '', occurred_on: t.occurred_on, category_id: t.category_id ?? '' }
  const net = (v: Record<string, string>) => {
    const body: S['TransactionPatch'] = {}
    if (v.description !== init.description) body.description = v.description
    if (v.merchant !== init.merchant) body.merchant = v.merchant || null
    if (v.category_id !== init.category_id) body.category_id = v.category_id || null
    if (!locked && v.occurred_on !== init.occurred_on) body.occurred_on = v.occurred_on
    if (!locked && v.amount !== init.amount) {
      const cents = parseBRL(v.amount)
      if (!cents) return Promise.reject(new ApiError(422, 'invalid_amount'))
      body.amount_cents = cents
    }
    return Object.keys(body).length ? api('PATCH', `/transactions/${t.id}`, body) : Promise.resolve()
  }
  return (
    <div>
      <p>{t.description || t.merchant || 'Lançamento'} · {formatBRL(t.amount_cents)}{t.installment_total ? ` · parcela ${t.installment_number}/${t.installment_total}` : ''}</p>
      {locked && <p role="note" className="text-sm">Valor e data de compras no cartão ou parceladas não podem ser editados aqui (afetam a fatura). Exclua e lance de novo para corrigir.</p>}
      <EditBox
        startOpen
        what="lançamento"
        fields={[
          ...(locked ? [] : [{ k: 'amount', label: 'Valor (R$) (edição)', v: init.amount }]),
          { k: 'description', label: 'Descrição (edição)', v: t.description },
          { k: 'merchant', label: 'Estabelecimento (edição)', v: t.merchant ?? '' },
          ...(locked ? [] : [{ k: 'occurred_on', label: 'Data (edição)', v: init.occurred_on, type: 'date' }]),
          { k: 'category_id', label: 'Categoria (edição)', v: t.category_id ?? '', options: [['', 'Sem categoria'], ...cats.data.map((c): [string, string] => [c.id, c.name])] },
        ]}
        save={(v) => net(v).then(onClose)}
        remove={() => api('DELETE', `/transactions/${t.id}`).then(onClose)}
      />
      {t.installment_group_id && <p className="text-sm">Excluir apaga todas as parcelas.</p>}
      {t.attachment_id && <Receipt id={t.attachment_id} />}
      <button type="button" className="mt-2 block underline" onClick={onClose}>Fechar</button>
    </div>
  )
}

function TransferForm() {
  const { data: accounts, label } = useAllAccounts()
  const [f, setF] = useState({ from: '', to: '', amount: '', description: '', occurred_on: today() })
  const src = accounts.find((a) => a.id === f.from)
  const cents = parseBRL(f.amount)
  const over = !!src && src.pockets_cents > 0 && !!cents && cents > src.available_cents // sem caixinhas o saldo pode ficar negativo
  const send = useSend(
    () => api('POST', `/spaces/${src!.space_id}/transactions`, { type: 'transfer', amount_cents: cents!, description: f.description, account_id: f.from, counter_account_id: f.to, occurred_on: f.occurred_on } satisfies S['TransactionIn']),
    () => setF({ ...f, amount: '', description: '' }),
  )
  const opts = (skip: string) => accounts.filter((a) => a.id !== skip).map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)
  return (
    <Card title="Transferir entre contas">
      {accounts.length < 2 ? <p>Cadastre pelo menos duas contas para transferir.</p> : (
        <form onSubmit={(e) => { e.preventDefault(); send.reset(); if (cents && !over) send.mutate() }}>
          <Field label="Conta de origem"><select required value={f.from} onChange={(e) => setF({ ...f, from: e.target.value, to: f.to === e.target.value ? '' : f.to })}><option value="">Selecione…</option>{opts('')}</select></Field>
          {src && <p className="mb-3 text-sm">Disponível na origem: {formatBRL(src.available_cents)}</p>}
          <Field label="Conta de destino"><select required value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })}><option value="">Selecione…</option>{opts(f.from)}</select></Field>
          <Field label="Valor da transferência (R$)"><input inputMode="decimal" required placeholder="300,00" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Data da transferência"><input type="date" required value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
          <Field label="Descrição da transferência (opcional)"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          {f.amount && !cents && <p role="alert" className="text-sm text-destructive">Valor inválido.</p>}
          {over && <p role="alert" className="text-sm text-destructive">Valor maior que o disponível ({formatBRL(src!.available_cents)}); o resto está em caixinhas.</p>}
          <Err e={send.error} />
          <Btn type="submit" disabled={send.isPending || !cents || !f.from || !f.to || over}>Transferir</Btn>
          {send.isSuccess && <p role="status" className="mt-2">Transferido.</p>}
        </form>
      )}
    </Card>
  )
}

function PurchaseForm() {
  const { spaceId } = useSpace()
  const cards = useGet<CardT[]>('/cards')
  const mine = (cards.data ?? []).filter((c) => c.space_id === spaceId)
  const [f, setF] = useState({ card_id: '', amount: '', installments: '1', description: '', category_id: '', occurred_on: today() })
  const cents = parseBRL(f.amount)
  const buy = useSend(
    () => api<Tx[]>('POST', `/spaces/${spaceId}/card-purchases`, { card_id: f.card_id, amount_cents: cents!, installments: Number(f.installments), description: f.description, category_id: f.category_id || null, occurred_on: f.occurred_on } satisfies S['PurchaseIn']),
    () => setF({ ...f, amount: '', description: '' }),
  )
  const r = buy.data
  const invoices = r ? new Set(r.map((t) => t.invoice_id)).size : 0
  return (
    <Card title="Compra no cartão">
      {mine.length === 0 ? <p>Cadastre um cartão primeiro.</p> : (
        <form onSubmit={(e) => { e.preventDefault(); if (cents) buy.mutate() }}>
          <Field label="Cartão"><select required value={f.card_id} onChange={(e) => setF({ ...f, card_id: e.target.value })}><option value="">Selecione…</option>{mine.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
          <Field label="Valor total (R$)"><input inputMode="decimal" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Parcelas"><input type="number" min={1} max={48} required value={f.installments} onChange={(e) => setF({ ...f, installments: e.target.value })} /></Field>
          <Field label="Descrição da compra"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <CategorySelect label="Categoria da compra" value={f.category_id} onChange={(v) => setF({ ...f, category_id: v })} />
          <Field label="Data da compra"><input type="date" required value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
          <p className="mb-2 text-sm text-muted-foreground">Compra antiga? Informe a data real: as parcelas já vencidas vão para as faturas passadas, que você marca como pagas em Cartões.</p>
          <Err e={buy.error} />
          <Btn type="submit" disabled={buy.isPending || !cents || !f.card_id}>Lançar compra</Btn>
        </form>
      )}
      {r && r.length > 0 && <p role="status" className="mt-2">Compra lançada em {r.length}x de {formatBRL(r[0].amount_cents)} (total {formatBRL(r.reduce((s, t) => s + t.amount_cents, 0))}), distribuída em {invoices} fatura(s).</p>}
    </Card>
  )
}

export function Transactions() {
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const cats = useCategories()
  const cards = useGet<CardT[]>('/cards')
  const members = useGet<Member[]>(`/spaces/${spaceId}/members`)
  const [flt, setFlt] = useState({ start: '', end: '', account_id: '', category_id: '', card_id: '', created_by: '' })
  const [page, setPage] = useState(0)
  const [sel, setSel] = useState<Tx | null>(null)
  const qs = new URLSearchParams(Object.entries(flt).filter(([, v]) => v)).toString()
  const path = `/spaces/${spaceId}/transactions?limit=${PAGE}&offset=${page * PAGE}${qs ? `&${qs}` : ''}`
  const list = useQuery({ queryKey: [path], queryFn: () => apiPage<Tx>(path) })
  const setF2 = (k: keyof typeof flt, v: string) => { setFlt({ ...flt, [k]: v }); setPage(0) }
  const [f, setF] = useState({ type: 'expense' as S['TransactionIn']['type'], amount: '', description: '', account_id: '', category_id: '', occurred_on: today() })
  const cents = parseBRL(f.amount)
  const create = useSend(
    () => api('POST', `/spaces/${spaceId}/transactions`, { type: f.type, amount_cents: cents!, description: f.description, account_id: f.account_id, category_id: f.category_id || null, occurred_on: f.occurred_on } satisfies S['TransactionIn']),
    () => setF({ ...f, amount: '', description: '' }),
  )
  const total = list.data?.total ?? 0
  const items = list.data?.items ?? []
  const sf = (k: keyof typeof flt, label: string, opts: [string, string][], all = 'Todos') => (
    <Field label={label}><select value={flt[k]} onChange={(e) => setF2(k, e.target.value)}><option value="">{all}</option>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Lançamentos</h1>
      <Card title="Novo lançamento">
        <form onSubmit={(e) => { e.preventDefault(); if (cents) create.mutate() }}>
          <Field label="Tipo"><select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as typeof f.type })}><option value="expense">Despesa</option><option value="income">Receita</option></select></Field>
          <Field label="Valor (R$)"><input inputMode="decimal" required placeholder="45,00" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Descrição"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <CategorySelect value={f.category_id} onChange={(v) => setF({ ...f, category_id: v })} />
          <Field label="Data"><input type="date" required value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
          <Field label="Conta"><AccountSelect accounts={accounts.data} value={f.account_id} onChange={(v) => setF({ ...f, account_id: v })} /></Field>
          {f.amount && !cents && <p role="alert" className="text-sm text-destructive">Valor inválido.</p>}
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !cents}>Salvar</Btn>
        </form>
      </Card>
      <TransferForm />
      <PurchaseForm />
      <Card title="Filtros">
        <div className="grid grid-cols-2 gap-2">
          <Field label="De"><input type="date" value={flt.start} onChange={(e) => setF2('start', e.target.value)} /></Field>
          <Field label="Até"><input type="date" value={flt.end} onChange={(e) => setF2('end', e.target.value)} /></Field>
          {sf('account_id', 'Conta (filtro)', accounts.data.map((a) => [a.id, a.name]))}
          {sf('category_id', 'Categoria (filtro)', cats.data.map((c) => [c.id, c.name]))}
          {sf('card_id', 'Cartão (filtro)', (cards.data ?? []).filter((c) => c.space_id === spaceId).map((c) => [c.id, c.name]))}
          {sf('created_by', 'Autor (filtro)', (members.data ?? []).map((m) => [m.user_id, m.name]))}
        </div>
      </Card>
      {sel && <TxDetail key={sel.id} t={sel} onClose={() => setSel(null)} />}
      <Card>
        {list.isLoading ? <p>Carregando…</p> : items.length === 0 ? <p>Nenhum lançamento.</p> : <TxList items={items} onSelect={setSel} />}
        <Err e={list.error} />
        {total > PAGE && (
          <div className="mt-2 flex items-center justify-between">
            <Btn type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</Btn>
            <span>{page * PAGE + 1}–{Math.min(total, (page + 1) * PAGE)} de {total}</span>
            <Btn type="button" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Próxima</Btn>
          </div>
        )}
      </Card>
    </>
  )
}
