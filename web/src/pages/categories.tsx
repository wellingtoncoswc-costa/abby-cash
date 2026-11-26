import { useState } from 'react'
import { api } from '../api/client'
import type { Category, S } from '../api/types'
import { useSpace } from '../space'
import { Btn, Card, EditBox, Err, Field, useCategories, useSend, Modal, PlusButton } from '../ui'

function Row({ c, others }: { c: Category; others: Category[] }) {
  const [to, setTo] = useState('')
  return (
    <li className="py-2">
      {c.name}
      <EditBox
        what="categoria"
        fields={[{ k: 'name', label: `Nome da categoria ${c.name}`, v: c.name }]}
        save={(v) => api('PATCH', `/categories/${c.id}`, { name: v.name } satisfies S['CategoryPatch'])}
        remove={() => api('DELETE', `/categories/${c.id}${to ? `?reassign_to=${to}` : ''}`)}
      />
      <label className="ml-2 text-sm">Ao excluir, mover lançamentos para{' '}
        <select className="!w-auto" value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="">(nenhuma)</option>{others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </label>
    </li>
  )
}

export function Categories() {
  const { spaceId } = useSpace()
  const cats = useCategories()
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ name: '', kind: 'expense' as S['CategoryIn']['kind'] })
  const add = useSend(() => api('POST', `/spaces/${spaceId}/categories`, { name: f.name, kind: f.kind } satisfies S['CategoryIn']), () => { setF({ ...f, name: '' }); setAdding(false) })
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Categorias</h1>
      <div className="mb-4"><PlusButton label="Nova categoria" onClick={() => setAdding(true)} /></div>
      {adding && <Modal title="Nova categoria" onClose={() => setAdding(false)}>
        <form onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
          <Field label="Nome da nova categoria"><input required maxLength={60} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Tipo da categoria"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as typeof f.kind })}><option value="expense">Despesa</option><option value="income">Receita</option></select></Field>
          <Err e={add.error} />
          <Btn type="submit" disabled={add.isPending}>Criar categoria</Btn>
        </form>
      </Modal>}
      {(['expense', 'income'] as const).map((k) => (
        <Card key={k} title={k === 'expense' ? 'Despesas' : 'Receitas'}>
          <ul className="divide-y divide-border">
            {cats.data.filter((c) => c.kind === k).map((c) => <Row key={c.id} c={c} others={cats.data.filter((o) => o.kind === k && o.id !== c.id)} />)}
          </ul>
        </Card>
      ))}
      <Err e={cats.error} />
    </>
  )
}
