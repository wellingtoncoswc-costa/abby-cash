import { Check, Circle, History, Receipt } from 'lucide-react'
import { useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Installment, Loan, S } from '../api/types'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { AccountSelect, Bar, Btn, Card, EditBox, Err, Field, br, centsText, today, useAccounts, useGet, useSend } from '../ui'

const KIND: Record<string, string> = { financing: 'Financiamento', consortium: 'Consórcio' }
const empty = { kind: 'financing', name: '', inst: '', total: '', first: '', paid: '0' }
const PAGE = 24
const STATE = {
  open: { label: 'Em aberto', Icon: Circle },
  paid_history: { label: 'Paga (já estava paga antes)', Icon: History },
  paid_real: { label: 'Paga (com lançamento)', Icon: Receipt },
} as const

/** "Paguei agora": materializa a parcela (se preciso) e usa o pagamento normal de conta, com conta de origem. */
function PayNow({ loan, it, done }: { loan: Loan; it: Installment; done: () => void }) {
  const accounts = useAccounts()
  const [acc, setAcc] = useState('')
  const [amt, setAmt] = useState(centsText(it.amount_cents))
  const [on, setOn] = useState(today())
  const cents = parseBRL(amt)
  const pay = useSend(async () => {
    const id = it.bill_id ?? (await api<{ id: string }>('POST', `/loans/${loan.id}/installments/${it.number}/materialize`)).id
    return api('POST', `/bills/${id}/payments`, { account_id: acc, amount_cents: cents!, paid_on: on } satisfies S['PayBillIn'])
  }, done)
  return (
    <form className="mt-2 rounded-md bg-muted p-2" onSubmit={(e) => { e.preventDefault(); if (acc && cents) pay.mutate() }}>
      <Field label="Pagar com a conta"><AccountSelect accounts={accounts.data} value={acc} onChange={setAcc} /></Field>
      <Field label="Valor pago (R$)"><input inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
      <Field label="Data do pagamento"><input type="date" required value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      <Err e={pay.error} />
      <Btn type="submit" disabled={pay.isPending || !acc || !cents || !on}>Confirmar pagamento</Btn>
    </form>
  )
}

/** Escolha ao marcar uma parcela: baixa histórica (sem lançamento) ou pagamento real. */
function Choose({ loan, it, close }: { loan: Loan; it: Installment; close: () => void }) {
  const [now, setNow] = useState(false)
  const settle = useSend(() => api('POST', `/loans/${loan.id}/installments/${it.number}/settle`), close)
  return (
    <div role="group" aria-label={`Marcar parcela ${it.number} como paga`} className="mt-2 rounded-md border border-border p-2">
      <p className="mb-2 text-sm">Como esta parcela foi paga?</p>
      <div className="flex flex-wrap gap-2">
        <Btn type="button" autoFocus disabled={settle.isPending} onClick={() => settle.mutate()}>Já estava paga antes</Btn>
        <Btn type="button" disabled={now} onClick={() => setNow(true)}>Paguei agora</Btn>
        <Btn type="button" className="bg-muted-foreground hover:bg-muted-foreground/90" onClick={close}>Cancelar</Btn>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">&quot;Já estava paga antes&quot; só marca a parcela, sem lançamento nem mudança de saldo.</p>
      <Err e={settle.error} />
      {now && <PayNow loan={loan} it={it} done={close} />}
    </div>
  )
}

function Installments({ loan }: { loan: Loan }) {
  const [open, setOpen] = useState(false)
  const q = useGet<Installment[]>(open ? `/loans/${loan.id}/installments` : null)
  const [shown, setShown] = useState(PAGE)
  const [pick, setPick] = useState<number | null>(null)
  const [note, setNote] = useState<number | null>(null)
  const [jump, setJump] = useState('')
  const unsettle = useSend((n: number) => api('DELETE', `/loans/${loan.id}/installments/${n}/settle`))
  const list = q.data ?? []
  const next = list.find((i) => i.state === 'open')?.number
  const refs = useRef<Record<number, HTMLInputElement | null>>({})
  const go = (n: number | undefined) => {
    if (!n || n < 1 || n > list.length) return
    setShown((s) => Math.max(s, n))
    requestAnimationFrame(() => { refs.current[n]?.scrollIntoView?.({ block: 'center' }); refs.current[n]?.focus() })
  }
  const change = (i: Installment) => {
    setNote(null); setPick(null)
    if (i.state === 'open') setPick(i.number)
    else if (i.state === 'paid_real') setNote(i.number)
    else if (confirm(`Desmarcar a parcela ${i.number}? Ela volta a ficar em aberto.`)) unsettle.mutate(i.number)
  }
  return (
    <div className="mt-2">
      <button type="button" className="mr-3 underline" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Ocultar parcelas' : 'Ver parcelas'}</button>
      {open && (
        <div className="mt-2">
          <div className="mb-2 flex flex-wrap items-end gap-2">
            <button type="button" className="underline" disabled={next === undefined} onClick={() => go(next)}>Ir para a próxima em aberto</button>
            <label className="text-sm">Ir para a parcela nº <input className="w-20" inputMode="numeric" value={jump} onChange={(e) => setJump(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); go(Number(jump)) } }} /></label>
          </div>
          <Err e={q.error ?? unsettle.error} />
          <ul className="max-h-96 overflow-y-auto" aria-label={`Parcelas de ${loan.name}`}>
            {list.slice(0, shown).map((i) => {
              const { label, Icon } = STATE[i.state]
              const name = `Parcela ${i.number} de ${loan.installments_total} · ${br(i.due_on)} · ${formatBRL(i.amount_cents)}`
              return (
                <li key={i.number} className={`border-b border-border py-1 ${i.number === next ? 'bg-muted font-medium' : ''}`}>
                  <label className="flex flex-wrap items-center gap-x-2">
                    <input type="checkbox" className="size-5" ref={(el) => { refs.current[i.number] = el }} checked={i.state !== 'open'} aria-label={name} onChange={() => change(i)} />
                    <span className="tabular-nums">{i.number}/{loan.installments_total} · {br(i.due_on)} · {formatBRL(i.amount_cents)}</span>
                    <span className="ml-auto inline-flex items-center gap-1 pl-7 text-sm sm:pl-0"><Icon aria-hidden size={14} />{label}{i.number === next && ' · próxima'}</span>
                  </label>
                  {pick === i.number && <Choose loan={loan} it={i} close={() => setPick(null)} />}
                  {note === i.number && (
                    <p role="status" className="mt-1 rounded-md bg-muted p-2 text-sm">
                      <Check aria-hidden size={14} className="mr-1 inline" />Esta parcela foi paga com lançamento e não pode ser desmarcada aqui. Para desfazer, exclua o lançamento do pagamento; a parcela volta a ficar em aberto.
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
          {shown < list.length && <button type="button" className="mt-2 underline" onClick={() => setShown(shown + PAGE)}>Mostrar mais parcelas ({list.length - shown} restantes)</button>}
        </div>
      )}
    </div>
  )
}

export function Loans() {
  const { spaceId } = useSpace()
  const loans = useGet<Loan[]>(`/spaces/${spaceId}/loans`)
  const [f, setF] = useState(empty)
  const cents = parseBRL(f.inst)
  const total = /^\d{1,3}$/.test(f.total) ? Number(f.total) : 0
  const paid = /^\d{1,3}$/.test(f.paid) ? Number(f.paid) : -1
  const ok = !!cents && total >= 1 && total <= 480 && !!f.first && paid >= 0 && paid <= total
  const create = useSend(() => api('POST', `/spaces/${spaceId}/loans`, { kind: f.kind, name: f.name, installment_cents: cents!, installments_total: total, first_due_on: f.first, paid_installments: paid }), () => setF(empty))
  const list = loans.data ?? []
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Financiamentos e consórcios</h1>
      {!loans.isLoading && !list.length && <p>Nenhum financiamento ou consórcio ainda. Cadastre um para acompanhar as parcelas, quanto falta e quando termina.</p>}
      {list.map((l) => (
        <Card key={l.id} title={l.name}>
          <p className="mb-2 text-sm text-muted-foreground">{KIND[l.kind]} · parcela de <span className="tabular-nums">{formatBRL(l.installment_cents)}</span></p>
          <Bar value={l.paid_count} max={l.installments_total} />
          <p className="mt-2">{l.paid_count} de {l.installments_total} pagas</p>
          <p>{l.remaining_count ? <>Faltam {l.remaining_count} {l.remaining_count === 1 ? 'parcela' : 'parcelas'} · <span className="tabular-nums">{formatBRL(l.remaining_cents)}</span></> : 'Quitado.'}</p>
          {l.next_due_on && <p>Próxima parcela: {br(l.next_due_on)}</p>}
          {l.last_due_on && <p>Previsão de término: {br(l.last_due_on)}</p>}
          <Installments loan={l} />
          <EditBox
            what={KIND[l.kind].toLowerCase()}
            fields={[{ k: 'name', label: `Nome de ${l.name}`, v: l.name }, { k: 'inst', label: `Parcela (R$) de ${l.name}`, v: centsText(l.installment_cents) }]}
            save={(v) => { const c = parseBRL(v.inst); return c ? api('PATCH', `/loans/${l.id}`, { name: v.name, installment_cents: c }) : Promise.reject(new ApiError(422, 'invalid_amount')) }}
            remove={() => api('DELETE', `/loans/${l.id}`)}
          />
        </Card>
      ))}
      <Card title="Cadastrar financiamento ou consórcio">
        <form onSubmit={(e) => { e.preventDefault(); if (ok) create.mutate() }}>
          <Field label="Tipo">
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="financing">Financiamento</option><option value="consortium">Consórcio</option>
            </select>
          </Field>
          <Field label="Nome"><input required maxLength={200} placeholder="Carro, apartamento…" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Valor da parcela (R$)"><input inputMode="decimal" required value={f.inst} onChange={(e) => setF({ ...f, inst: e.target.value })} /></Field>
          <Field label="Quantidade de parcelas (1 a 480)"><input inputMode="numeric" required value={f.total} onChange={(e) => setF({ ...f, total: e.target.value })} /></Field>
          <Field label="Primeiro vencimento"><input type="date" required value={f.first} onChange={(e) => setF({ ...f, first: e.target.value })} /></Field>
          <Field label="Parcelas já pagas">
            <input inputMode="numeric" aria-describedby="paid-help" value={f.paid} onChange={(e) => setF({ ...f, paid: e.target.value })} />
          </Field>
          <p id="paid-help" className="-mt-2 mb-3 text-sm text-muted-foreground">Informe quantas parcelas você já pagou antes de cadastrar (de 0 até o total). Elas entram como já pagas, sem lançamento.</p>
          <Err e={create.error} />
          <Btn type="submit" disabled={create.isPending || !ok}>Cadastrar</Btn>
        </form>
      </Card>
      <Err e={loans.error} />
    </>
  )
}
