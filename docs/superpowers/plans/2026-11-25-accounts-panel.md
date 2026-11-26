# Contas em cards com painel (fase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Página "Contas bancárias" com um card por conta e painel mensal.

**Architecture:** Função de domínio `account_panel` (`domain/accounts/panel.py`) sobre `account_statement`, `pocket_stats` e as ligações de meta; endpoint `GET /accounts/{id}/panel`; web `pages/accounts.tsx` no padrão de `CardTile` (`billing.tsx`).

Spec: `docs/superpowers/specs/2026-11-25-accounts-panel-design.md`. Branch `feat/accounts-panel`. Rode o pytest **uma vez por vez**.

### Task 1: Painel da conta (domínio + API)

**Files:** create `backend/app/domain/accounts/panel.py`, `backend/tests/domain/test_accounts_panel.py`; modify `backend/app/api/schemas.py`, `backend/app/api/accounts.py`.

- [ ] **Step 1: Teste que falha** (`tests/domain/test_accounts_panel.py`)

```python
from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.accounts.panel import account_panel
from app.domain.goals.service import create_goal, update_goal
from app.domain.pockets.service import create_pocket, deposit
from app.domain.transactions.service import create_transaction
from tests.factories import category_id, make_account, make_user

NOV = date(2026, 11, 1)


async def _tx(session, user, acc, type_, cents, on, cat=None, desc="x", counter=None):
    return await create_transaction(
        session, actor_id=user.id, space_id=acc.space_id, type=type_, amount_cents=cents,
        occurred_on=on, account_id=acc.id, category_id=cat, description=desc,
        counter_account_id=counter,
    )  # fmt: skip


async def test_panel_month_totals_categories_pockets_goals(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    other = await make_account(session, sp, name="Outra", initial=0)
    mercado = await category_id(session, sp, "Mercado")
    salario = await category_id(session, sp, "Salário", "income")
    await _tx(session, a, acc, "income", 500_000, date(2026, 11, 5), salario, "Salário")
    await _tx(session, a, acc, "expense", 30_000, date(2026, 11, 6), mercado, "Mercado")
    await _tx(session, a, acc, "expense", 10_000, date(2026, 11, 7), mercado, "Feira")
    await _tx(session, a, acc, "transfer", 20_000, date(2026, 11, 8), None, "p/ outra", other.id)
    await _tx(session, a, acc, "expense", 99_000, date(2026, 10, 30), mercado, "mês anterior")
    pk = await create_pocket(
        session, actor_id=a.id, space_id=sp, account_id=acc.id, name="Reserva", cdi_bp=10000
    )
    await deposit(session, actor_id=a.id, pocket_id=pk.id, amount_cents=15_000, on=date(2026, 11, 9))
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=100_000,
        created_on=NOV, account_ids=[acc.id],
    )  # fmt: skip
    p = await account_panel(session, a.id, acc.id, month=NOV, today=date(2026, 11, 20))
    assert (p["income_cents"], p["expense_cents"], p["transfer_net_cents"]) == (500_000, 40_000, -20_000)
    assert p["by_category"] == [{"category_id": mercado, "total_cents": 40_000}]
    assert [r["description"] for r in p["recent"]][:2] == ["p/ outra", "Feira"]  # mais recentes primeiro
    assert [(x["id"], x["balance_cents"]) for x in p["pockets"]] == [(pk.id, 15_000)]
    assert [g["id"] for g in p["goals"]] == [goal.id] and p["is_default"] is False


async def test_panel_guards_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id)
    with pytest.raises(HTTPException) as e:
        await account_panel(session, b.id, acc.id, month=NOV, today=NOV)
    assert e.value.status_code in (403, 404)
```

(Ajuste a assinatura de `create_transaction` ao real: `grep -n "async def create_transaction" -A8 backend/app/domain/transactions/service.py`; se `account_id`/`counter_account_id` forem outros kwargs, adapte o helper `_tx`.) Run `cd backend && uv run pytest tests/domain/test_accounts_panel.py -q` → FAIL.

- [ ] **Step 2: Implementação** (`accounts/panel.py`)

```python
from collections import defaultdict
from calendar import monthrange
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import visible_account
from app.domain.accounts.statement import account_statement
from app.domain.goals.models import Goal, GoalAccount, GoalPocket
from app.domain.pockets.models import Pocket
from app.domain.pockets.service import pocket_stats
from app.domain.spaces.models import SpaceMember


async def account_panel(
    session: AsyncSession, viewer_id: UUID, account_id: UUID, *, month: date, today: date
) -> dict[str, Any]:  # fmt: skip
    """Mês `month` (qualquer dia): entradas, saídas, transferências, categorias, últimas
    movimentações, caixinhas e metas ligadas. Itens de espaços alheios só em `private_total_cents`."""
    acc = await visible_account(session, viewer_id, account_id)
    start = month.replace(day=1)
    end = month.replace(day=monthrange(month.year, month.month)[1])
    stmt = await account_statement(session, viewer_id, acc.id, start, end)
    income = expense = transfer = 0
    by_cat: dict[UUID | None, int] = defaultdict(int)
    for it in stmt.items:
        if it.type == "income":
            income += it.amount_cents
        elif it.type == "expense":
            expense += -it.amount_cents
            by_cat[it.category_id] += -it.amount_cents
        else:
            transfer += it.amount_cents
    mine = select(SpaceMember.space_id).where(SpaceMember.user_id == viewer_id)
    pockets = list(
        await session.scalars(
            select(Pocket).where(Pocket.account_id == acc.id, Pocket.closed_at.is_(None))
        )
    )
    goals = list(
        await session.scalars(
            select(Goal)
            .where(
                Goal.space_id.in_(mine),
                or_(
                    Goal.id.in_(select(GoalAccount.goal_id).where(GoalAccount.account_id == acc.id)),
                    Goal.id.in_(
                        select(GoalPocket.goal_id).where(
                            GoalPocket.pocket_id.in_([p.id for p in pockets])
                        )
                    ),
                ),
            )
            .order_by(Goal.name)
        )
    )
    default_id = await session.scalar(
        select(SpaceMember.default_account_id).where(
            SpaceMember.user_id == viewer_id, SpaceMember.space_id == acc.space_id
        )
    )
    return {
        "month": start,
        "is_default": default_id == acc.id,
        "income_cents": income,
        "expense_cents": expense,
        "transfer_net_cents": transfer,
        "private_total_cents": stmt.private_total_cents,
        "by_category": [
            {"category_id": k, "total_cents": v}
            for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
        ],
        "recent": [
            {"occurred_on": it.occurred_on, "type": it.type, "description": it.description,
             "merchant": it.merchant, "amount_cents": it.amount_cents}
            for it in sorted(stmt.items, key=lambda x: x.occurred_on, reverse=True)[:10]
        ],  # fmt: skip
        "pockets": [
            {"id": p.id, "name": p.name, "balance_cents": (await pocket_stats(session, p.id, today)).balance}
            for p in pockets
        ],
        "goals": [{"id": g.id, "name": g.name} for g in goals],
    }
```

(`sorted(..., reverse=True)` mantém a ordem de inserção entre itens do mesmo dia invertida; se o teste acusar a ordem "Feira" vs "p/ outra" em datas diferentes isso já resolve, pois 11/08 > 11/07.)

`schemas.py`:

```python
class AccountPanelOut(Out):
    month: date
    is_default: bool
    income_cents: int
    expense_cents: int
    transfer_net_cents: int
    private_total_cents: int
    by_category: list[PanelCategoryOut]
    recent: list[AccountMoveOut]
    pockets: list[AccountPanelPocketOut]
    goals: list[AccountPanelGoalOut]
```
com (antes dela) `AccountMoveOut(occurred_on: date, type: str, description: str, merchant: str | None, amount_cents: int)`, `AccountPanelPocketOut(id: UUID, name: str, balance_cents: int)`, `AccountPanelGoalOut(id: UUID, name: str)`, todas `(Out)`. `PanelCategoryOut` já existe (fase 1; confira que está definida antes no arquivo, senão mova).

`api/accounts.py`:

```python
@router.get("/accounts/{account_id}/panel", response_model=AccountPanelOut)
async def panel(
    account_id: UUID, user: CurrentUser, session: Session,
    month: Annotated[str | None, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> dict[str, Any]:  # fmt: skip
    today = local_today(user.tz)
    first = date(int(month[:4]), int(month[5:]), 1) if month else today.replace(day=1)
    return await account_panel(session, user.id, account_id, month=first, today=today)
```

(Para `Field(pattern=...)` em query use `Query(pattern=...)`: `from fastapi import Query` e `month: Annotated[str | None, Query(pattern=...)] = None`. Rota registrada antes de `/accounts/{account_id}/statement`? Não conflita: caminhos distintos.)

Teste de API (acrescente a `tests/api/test_accounts_panel_api.py`):

```python
from tests.factories import auth, make_account, make_user


async def test_panel_over_http(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=10_000)
    r = await client.get(f"/accounts/{acc.id}/panel?month=2026-11", headers=auth(a))
    assert r.status_code == 200 and r.json()["month"] == "2026-11-01"
    assert r.json()["income_cents"] == 0 and r.json()["pockets"] == []
    bad = await client.get(f"/accounts/{acc.id}/panel?month=2026-13", headers=auth(a))
    assert bad.status_code == 422
    other = await make_user(session, "b@x.com")
    assert (await client.get(f"/accounts/{acc.id}/panel", headers=auth(other))).status_code in (403, 404)
```

- [ ] **Step 3:** `uv run pytest tests/domain/test_accounts_panel.py tests/api/test_accounts_panel_api.py -q` → PASS; `uv run ruff check --fix . && uv run ruff format . && uv run mypy app` limpos (organize imports; mypy: `Query` com `Annotated`).
- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(accounts): account panel endpoint"`

### Task 2: Web — página Contas bancárias

**Files:** create `web/src/pages/accounts.tsx`; modify `router.tsx`, `layout.tsx`, `api/types.ts`, `pages/pages.test.tsx`; regenerate `api/schema.d.ts`.

- [ ] **Step 1: Tipos** — `cd backend && uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json && cd ../web && npm run gen:api`; em `api/types.ts`: `export type AccountPanel = S['AccountPanelOut']`.

- [ ] **Step 2: Testes que falham** (fim de `pages.test.tsx`; o mock `/accounts` devolve a conta `a1` "Nubank")

```tsx
const ACC_PANEL = {
  month: '2026-11-01', is_default: false, income_cents: 500000, expense_cents: 40000, transfer_net_cents: -20000, private_total_cents: 0,
  by_category: [{ category_id: 'c1', total_cents: 40000 }],
  recent: [{ occurred_on: '2026-11-08', type: 'transfer', description: 'p/ outra', merchant: null, amount_cents: -20000 }],
  pockets: [{ id: 'p1', name: 'Reserva', balance_cents: 15000 }], goals: [{ id: 'g1', name: 'Viagem' }],
}
const accTile = async () => within((await screen.findByRole('heading', { name: 'Nubank' })).closest('section')!)

test('contas: um card por conta com saldo e painel do mês', async () => {
  routes['/accounts/a1/panel'] = () => J(ACC_PANEL)
  go('/contas-bancarias')
  const card = await accTile()
  await userEvent.click(await card.findByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText('Mercado')).toBeInTheDocument()
  expect(card.getByText(/Reserva/)).toBeInTheDocument()
  expect(card.getByText(/Viagem/)).toBeInTheDocument()
  expect(card.getByText(/R\$ 5\.000,00/)).toBeInTheDocument()
})

test('contas: tornar padrão chama a API', async () => {
  routes['/accounts/a1/panel'] = () => J(ACC_PANEL)
  routes[`/spaces/${SP}/default-account`] = () => new Response(null, { status: 204 })
  go('/contas-bancarias')
  const card = await accTile()
  await userEvent.click(await card.findByRole('button', { name: 'Tornar padrão' }))
  const put = calls.find(([u]) => u === `/spaces/${SP}/default-account`)!
  expect(JSON.parse(put[1].body as string)).toEqual({ account_id: 'a1' })
})
```

Run `cd web && npm test -- pages` → FAIL.

- [ ] **Step 3: Implementação** (`pages/accounts.tsx`)

```tsx
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AccountIn, AccountPanel, AccountPatch, Account } from '../api/types'
import { BankIcon, BankSelect } from '../bank-icon'
import { BANK_LIST } from '../banks'
import { formatBRL, parseBRL } from '../lib/money'
import { useSpace } from '../space'
import { Btn, Card, EditBox, Err, Field, br, centsText, monthKey, useAccounts, useCatName, useGet, useIsOwner, useSend } from '../ui'

const TYPE: Record<string, string> = { checking: 'Conta corrente', savings: 'Poupança', wallet: 'Carteira' }
const pctOf = (v: number, max: number) => (max > 0 ? Math.round((v / max) * 100) : 0)

function PanelView({ a }: { a: Account }) {
  const [month, setMonth] = useState(monthKey())
  const p = useGet<AccountPanel>(`/accounts/${a.id}/panel?month=${month}`)
  const catName = useCatName()
  const d = p.data
  return (
    <div className="mt-2">
      <Field label="Mês"><input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></Field>
      <Err e={p.error} />
      {!d ? <p>Carregando…</p> : (
        <>
          <p>Entradas {formatBRL(d.income_cents)} · Saídas {formatBRL(d.expense_cents)} · Transferências {formatBRL(d.transfer_net_cents)}</p>
          {d.private_total_cents !== 0 && <p>Outros lançamentos (privados): {formatBRL(d.private_total_cents)}</p>}
          <h3 className="mt-2 font-semibold">Gastos por categoria</h3>
          {d.by_category.length === 0 && <p>Sem gastos no mês.</p>}
          <ul>{d.by_category.map((c) => (
            <li key={c.category_id ?? 'none'}>
              <div className="flex justify-between"><span>{catName(c.category_id)}</span><span>{formatBRL(c.total_cents)}</span></div>
              <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${pctOf(c.total_cents, d.by_category[0].total_cents)}%` }} /></div>
            </li>
          ))}</ul>
          <h3 className="mt-2 font-semibold">Últimas movimentações</h3>
          <ul>{d.recent.map((r, i) => <li key={i} className="flex justify-between"><span>{br(r.occurred_on)} {r.description || r.merchant}</span><span>{formatBRL(r.amount_cents)}</span></li>)}</ul>
          {d.pockets.length > 0 && (<><h3 className="mt-2 font-semibold">Caixinhas</h3><ul>{d.pockets.map((k) => <li key={k.id} className="flex justify-between"><span>{k.name}</span><span>{formatBRL(k.balance_cents)}</span></li>)}</ul></>)}
          {d.goals.length > 0 && (<><h3 className="mt-2 font-semibold">Metas ligadas</h3><ul>{d.goals.map((g) => <li key={g.id}>{g.name}</li>)}</ul></>)}
        </>
      )}
    </div>
  )
}

function AccountTile({ a, owner }: { a: Account; owner: boolean }) {
  const { spaceId } = useSpace()
  const [open, setOpen] = useState(false)
  const sum = useGet<AccountPanel>(`/accounts/${a.id}/panel`)
  const makeDefault = useSend(() => api('PUT', `/spaces/${a.space_id || spaceId}/default-account`, { account_id: a.id }))
  return (
    <Card title={a.name}>
      <p className="flex items-center gap-2"><BankIcon institution={a.institution} name={a.name} />{TYPE[a.type] ?? a.type}{sum.data?.is_default && <> · <strong>padrão</strong></>}</p>
      <p>Saldo {formatBRL(a.balance_cents)} · em caixinhas {formatBRL(a.pockets_cents)} · disponível {formatBRL(a.available_cents)}</p>
      <div className="my-2 flex flex-wrap gap-2">
        <Link to="/lancamentos" className="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground">Transferir</Link>
        {!sum.data?.is_default && <Btn type="button" disabled={makeDefault.isPending} onClick={() => makeDefault.mutate()}>Tornar padrão</Btn>}
        <Btn type="button" onClick={() => setOpen(!open)} className="bg-muted-foreground hover:bg-muted-foreground/90">{open ? 'Ocultar painel' : 'Ver painel'}</Btn>
      </div>
      <Err e={makeDefault.error} />
      {open && <PanelView a={a} />}
      <EditBox what="conta" canEdit={owner} fields={[{ k: 'name', label: `Nome da conta ${a.name}`, v: a.name }, { k: 'bal', label: `Saldo inicial (R$) de ${a.name}`, v: centsText(a.initial_balance_cents) }, { k: 'inst', label: `Banco de ${a.name}`, v: a.institution ?? '', options: [['', 'Não informado'], ...BANK_LIST.map((b) => [b.key, b.name] as [string, string])] }]}
        save={(v) => { const b = parseBRL(v.bal); return b === null ? Promise.reject(new ApiError(422, 'invalid_amount')) : api('PATCH', `/accounts/${a.id}`, { name: v.name, initial_balance_cents: b, institution: v.inst || null } satisfies AccountPatch) }}
        remove={() => api('DELETE', `/accounts/${a.id}`)} />
    </Card>
  )
}

export function Accounts() {
  const owner = useIsOwner()
  const { spaceId } = useSpace()
  const accounts = useAccounts()
  const [f, setF] = useState({ type: 'checking', name: '', balance: '', institution: '' })
  const bal = f.balance ? parseBRL(f.balance) : 0
  const add = useSend(
    () => api('POST', `/spaces/${spaceId}/accounts`, { type: f.type as 'checking', name: f.name, initial_balance_cents: bal ?? 0, institution: f.institution || null } satisfies AccountIn),
    () => setF({ ...f, name: '', balance: '', institution: '' }),
  )
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Contas bancárias</h1>
      <Card title="Nova conta">
        <form onSubmit={(e) => { e.preventDefault(); if (bal !== null) add.mutate() }}>
          <Field label="Tipo"><select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="checking">Conta corrente</option><option value="savings">Poupança</option><option value="wallet">Carteira</option></select></Field>
          <Field label="Nome da conta"><input required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Banco"><BankSelect value={f.institution} onChange={(v) => setF({ ...f, institution: v })} name={f.name} /></Field>
          <Field label="Saldo inicial (R$)"><input inputMode="decimal" placeholder="0,00" value={f.balance} onChange={(e) => setF({ ...f, balance: e.target.value })} /></Field>
          <Err e={add.error} />
          <Btn type="submit" disabled={add.isPending || bal === null}>Adicionar conta</Btn>
        </form>
      </Card>
      {!accounts.isLoading && accounts.data.length === 0 && <p className="mb-4">Nenhuma conta neste espaço.</p>}
      <div className="grid gap-4 md:grid-cols-2">{accounts.data.map((a) => <AccountTile key={a.id} a={a} owner={owner} />)}</div>
    </>
  )
}
```

(Confirme que `Account` e `AccountIn`/`AccountPatch` saem de `../api/types` — o `onboarding.tsx` importa `AccountIn, AccountPatch` de lá; `Account` já é usado em `pockets.tsx`. Se `useAccounts` filtra por espaço ativo, `a.space_id` é o espaço ativo e o `PUT` vai certo.)

Registro: `router.tsx` — `import { Accounts } from './pages/accounts'` e `page('/contas-bancarias', Accounts)`; `layout.tsx` — `['/contas-bancarias', 'Contas bancárias', Wallet]` em `PRINCIPAL` logo antes de `/cartoes` (importe `Wallet` de `lucide-react`).

- [ ] **Step 4:** `cd web && npm run lint && npm run typecheck && npm test && npm run build` → verde.
- [ ] **Step 5: Commit** — `git add web backend && git commit -m "feat(web): bank accounts page with one card per account"`

### Task 3: Verificação e entrega

- [ ] `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app && bash scripts/migrate_check.sh` (sem migração nova).
- [ ] Web: lint, typecheck, test, build.
- [ ] Deploy só com confirmação explícita do usuário (backup, pull em `/home/vipsfibra/abby-cash-prod`, nova `ABBY_TAG`, build `api web`, `up -d api worker web`). Sem mudança no Nginx.
