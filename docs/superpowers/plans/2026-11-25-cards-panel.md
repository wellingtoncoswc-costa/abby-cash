# Cartões em cards com painel (fase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada cartão vira um card com resumo, "Nova compra", "Cadastrar fatura" e um painel de gastos (por categoria, últimas 6 faturas, maiores compras).

**Architecture:** Dois endpoints novos em `api/cards.py` sobre funções de domínio novas (`cards/panel.py`, `register_invoice_total` em `cards/service.py`); sem tabela nova. O painel reaproveita `invoice_statement` (categoria e privacidade já resolvidas) e `invoice_summary`. A web troca o seletor por um `CardTile` por cartão.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest; React + TS + vitest.

Spec: `docs/superpowers/specs/2026-11-25-cards-panel-design.md`. Branch: `feat/cards-panel` (já criada a partir da `main`). Rode o pytest **uma vez por vez** (banco de teste compartilhado).

## File Structure

- Create `backend/app/domain/cards/panel.py`, `backend/tests/domain/test_cards_panel.py`.
- Modify `backend/app/domain/cards/service.py` (+`register_invoice_total`), `backend/app/api/cards.py` (+2 endpoints), `backend/app/api/schemas.py` (+`CardPanelOut`), `backend/tests/api/test_cards_api.py` (se existir; senão criar `test_cards_panel_api.py`).
- Modify `web/src/pages/billing.tsx` (`Cards` → grade de `CardTile`), `web/src/pages/pages.test.tsx`, `web/src/api/schema.d.ts` (gerado).

---

### Task 1: Cadastrar fatura pelo total (domínio)

**Files:** modify `backend/app/domain/cards/service.py`; test `backend/tests/domain/test_cards_panel.py`.

- [ ] **Step 1: Teste que falha** (`tests/domain/test_cards_panel.py`)

```python
from datetime import date

from app.domain.cards.service import invoice_total, register_card_purchase, register_invoice_total
from tests.factories import make_card, make_user

D = date(2026, 11, 25)


async def test_invoice_total_lands_on_the_requested_invoice(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, closing_day=10, due_day=20)
    inv = await register_invoice_total(
        session, actor_id=a.id, card_id=card.id, year=2026, month=8, total_cents=123_456
    )
    assert (inv.closing_on, inv.due_on) == (date(2026, 8, 10), date(2026, 8, 20))
    assert await invoice_total(session, inv.id) == 123_456
    again = await register_invoice_total(  # soma ao que já existe na mesma fatura
        session, actor_id=a.id, card_id=card.id, year=2026, month=8, total_cents=1_000
    )
    assert again.id == inv.id and await invoice_total(session, inv.id) == 124_456


async def test_invoice_total_short_month_closing(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, closing_day=31, due_day=10)
    inv = await register_invoice_total(
        session, actor_id=a.id, card_id=card.id, year=2026, month=2, total_cents=5_000
    )
    assert inv.closing_on == date(2026, 2, 28)  # fecha no último dia do mês curto
```

Run: `cd backend && uv run pytest tests/domain/test_cards_panel.py -q` → FAIL (`register_invoice_total` não existe).

- [ ] **Step 2: Implementação** — em `cards/service.py`, depois de `register_card_purchase`:

```python
async def register_invoice_total(
    session: AsyncSession, *, actor_id: UUID, card_id: UUID, year: int, month: int,
    total_cents: int,
) -> Invoice:  # fmt: skip
    """Fatura pelo total: uma compra "Fatura MM/AAAA" no dia do fechamento (compra no dia do
    fechamento cai na fatura que fecha). `month` = mês de FECHAMENTO."""
    card = await use_card(session, actor_id, card_id)
    dates = invoice_dates_for_month(card.closing_day, card.due_day, year, month)
    txs = await register_card_purchase(
        session, actor_id=actor_id, space_id=card.space_id, card_id=card.id,
        amount_cents=total_cents, occurred_on=dates.closing, description=f"Fatura {month:02d}/{year}",
    )  # fmt: skip
    inv = await session.get(Invoice, txs[0].invoice_id)
    assert inv is not None
    return inv
```

- [ ] **Step 3:** `uv run pytest tests/domain/test_cards_panel.py -q` → PASS. `uv run ruff check . && uv run ruff format . && uv run mypy app` limpos.
- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(cards): register an invoice by its total"`

---

### Task 2: Painel do cartão (domínio)

**Files:** create `backend/app/domain/cards/panel.py`; extend `backend/tests/domain/test_cards_panel.py`.

- [ ] **Step 1: Teste que falha** (acrescente ao arquivo; imports extras: `pytest`, `HTTPException`, `card_panel` de `app.domain.cards.panel`, `category_id` e `make_family` de `tests.factories`)

```python
async def test_panel_limit_categories_history_and_top(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    card = await make_card(session, a, sp, closing_day=10, due_day=20, limit_cents=100_000)
    mercado, lazer = await category_id(session, sp, "Mercado"), await category_id(session, sp, "Lazer")
    for amount, cat, on in ((30_000, mercado, date(2026, 11, 5)), (20_000, lazer, date(2026, 11, 6)),
                            (10_000, mercado, date(2026, 11, 7))):
        await register_card_purchase(
            session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=amount,
            occurred_on=on, category_id=cat, description=f"c{amount}",
        )  # fmt: skip
    for m in range(1, 8):  # 7 faturas antigas para testar o corte em 6
        await register_invoice_total(
            session, actor_id=a.id, card_id=card.id, year=2026, month=m, total_cents=1_000 * m
        )
    p = await card_panel(session, a.id, card.id, today=date(2026, 11, 8))
    assert p["invoice"]["closing_on"] == date(2026, 11, 10)  # a que ainda vai fechar
    assert p["used_cents"] == 60_000 + sum(1_000 * m for m in range(1, 8))
    assert p["available_cents"] == 100_000 - p["used_cents"]
    assert {c["category_id"]: c["total_cents"] for c in p["by_category"]} == {
        mercado: 40_000, lazer: 20_000}  # fmt: skip
    assert [t["amount_cents"] for t in p["top"]] == [30_000, 20_000, 10_000]
    assert len(p["history"]) == 6 and p["history"][-1]["closing_on"] == date(2026, 11, 10)
    assert [h["closing_on"] for h in p["history"]] == sorted(h["closing_on"] for h in p["history"])


async def test_panel_picks_invoice_and_guards_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    other = await make_card(session, a, a.default_space_id, name="Outro")
    inv = await register_invoice_total(
        session, actor_id=a.id, card_id=card.id, year=2026, month=3, total_cents=7_000
    )
    foreign = await register_invoice_total(
        session, actor_id=a.id, card_id=other.id, year=2026, month=3, total_cents=1_000
    )
    p = await card_panel(session, a.id, card.id, today=date(2026, 11, 8), invoice_id=inv.id)
    assert p["invoice"]["id"] == inv.id and p["limit_cents"] is None and p["available_cents"] is None
    for who, cid, iid in ((a, card.id, foreign.id), (b, card.id, None)):
        with pytest.raises(HTTPException) as e:  # fatura de outro cartão / não é membro
            await card_panel(session, who.id, cid, today=date(2026, 11, 8), invoice_id=iid)
        assert e.value.status_code in (403, 404)


async def test_panel_without_invoices(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, limit_cents=50_000)
    p = await card_panel(session, a.id, card.id, today=date(2026, 11, 8))
    assert p["invoice"] is None and p["used_cents"] == 0 and p["available_cents"] == 50_000
    assert p["by_category"] == [] and p["top"] == [] and p["history"] == []
```

Run → FAIL.

- [ ] **Step 2: Implementação** (`cards/panel.py`)

```python
from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import row
from app.domain.cards.models import Invoice
from app.domain.cards.service import invoice_statement, invoice_summary, visible_card


async def card_panel(
    session: AsyncSession, viewer_id: UUID, card_id: UUID, *, today: date,
    invoice_id: UUID | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Resumo e gastos do cartão. Compras de espaços de que o visualizador não é membro entram só
    em `private_total_cents` (nunca por categoria nem na lista de maiores).
    # ponytail: olha as 24 faturas mais recentes (igual à listagem); paginar se alguém passar disso"""
    card = await visible_card(session, viewer_id, card_id)
    invs = list(
        await session.scalars(
            select(Invoice).where(Invoice.card_id == card.id).order_by(Invoice.closing_on.desc()).limit(24)
        )
    )
    sums = {i.id: await invoice_summary(session, i) for i in invs}
    used = sum(s["remaining_cents"] for s in sums.values())
    if invoice_id is not None:
        sel = next((i for i in invs if i.id == invoice_id), None)
        if sel is None:
            raise HTTPException(status_code=404, detail="not_found")
    else:  # a que ainda vai fechar (a mais próxima) ou, sem nenhuma, a mais recente
        sel = next((i for i in reversed(invs) if i.closing_on >= today), invs[0] if invs else None)
    by_cat: dict[UUID | None, int] = defaultdict(int)
    top: list[dict[str, Any]] = []
    private = 0
    if sel is not None:
        stmt = await invoice_statement(session, viewer_id, sel.id)
        private = stmt.private_total_cents
        for it in stmt.items:
            by_cat[it.category_id] += it.amount_cents
        top = [
            {"description": it.description, "merchant": it.merchant,
             "amount_cents": it.amount_cents, "occurred_on": it.occurred_on}
            for it in sorted(stmt.items, key=lambda x: -x.amount_cents)[:5]
        ]  # fmt: skip
    return {
        "invoice": row(sel) | sums[sel.id] if sel else None,
        "limit_cents": card.limit_cents,
        "used_cents": used,
        "available_cents": None if card.limit_cents is None else card.limit_cents - used,
        "by_category": [{"category_id": k, "total_cents": v} for k, v in
                        sorted(by_cat.items(), key=lambda kv: -kv[1])],  # fmt: skip
        "private_total_cents": private,
        "top": top,
        "history": [
            {"invoice_id": i.id, "closing_on": i.closing_on, "due_on": i.due_on,
             "total_cents": sums[i.id]["total_cents"]}
            for i in sorted(invs[:6], key=lambda i: i.closing_on)
        ],  # fmt: skip
    }
```

- [ ] **Step 3:** `uv run pytest tests/domain/test_cards_panel.py -q` → PASS; ruff/format/mypy limpos. Se `test_panel_limit...` divergir no `used_cents` por causa de uma fatura sem `remaining`, confira `invoice_summary` (faturas só com compra ficam abertas, `remaining = total`).
- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(cards): card panel domain"`

---

### Task 3: API

**Files:** modify `backend/app/api/schemas.py`, `backend/app/api/cards.py`; create `backend/tests/api/test_cards_panel_api.py`.

- [ ] **Step 1: Teste que falha**

```python
from tests.factories import auth, make_card, make_user


async def test_panel_and_invoice_total_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    card = await make_card(session, a, a.default_space_id, closing_day=10, due_day=20, limit_cents=50_000)
    r = await client.post(
        f"/cards/{card.id}/invoice-totals", headers=h, json={"month": "2026-08", "total_cents": 12_000}
    )
    assert r.status_code == 201
    assert (r.json()["closing_on"], r.json()["total_cents"]) == ("2026-08-10", 12_000)
    p = (await client.get(f"/cards/{card.id}/panel", headers=h)).json()
    assert p["used_cents"] == 12_000 and p["available_cents"] == 38_000
    assert p["invoice"]["id"] == r.json()["id"] and p["history"][0]["total_cents"] == 12_000
    sel = await client.get(f"/cards/{card.id}/panel?invoice={r.json()['id']}", headers=h)
    assert sel.status_code == 200
    bad = await client.post(f"/cards/{card.id}/invoice-totals", headers=h,
                            json={"month": "2026-13", "total_cents": 1})
    assert bad.status_code == 422
    zero = await client.post(f"/cards/{card.id}/invoice-totals", headers=h,
                             json={"month": "2026-08", "total_cents": 0})
    assert zero.status_code == 422


async def test_panel_requires_membership(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    r = await client.get(f"/cards/{card.id}/panel", headers=auth(b))
    assert r.status_code in (403, 404)
```

Run → FAIL (404/405).

- [ ] **Step 2: Implementação**

`schemas.py` (junto de `InvoiceOut`):

```python
class PanelCategoryOut(Out):
    category_id: UUID | None
    total_cents: int


class PanelPurchaseOut(Out):
    description: str
    merchant: str | None
    amount_cents: int
    occurred_on: date


class PanelInvoiceOut(Out):
    invoice_id: UUID
    closing_on: date
    due_on: date
    total_cents: int


class CardPanelOut(Out):
    invoice: InvoiceOut | None
    limit_cents: int | None
    used_cents: int
    available_cents: int | None
    by_category: list[PanelCategoryOut]
    private_total_cents: int
    top: list[PanelPurchaseOut]
    history: list[PanelInvoiceOut]
```

`api/cards.py` (importe `CardPanelOut`, `re` não é preciso — use `Field(pattern=...)`; `card_panel` de `app.domain.cards.panel`; `register_invoice_total` do service; `local_today` já usado no arquivo):

```python
class InvoiceTotalIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # mês de fechamento, YYYY-MM
    total_cents: Cents


@router.post("/cards/{card_id}/invoice-totals", status_code=201, response_model=InvoiceOut)
async def invoice_total_in(
    card_id: UUID, body: InvoiceTotalIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    year, month = int(body.month[:4]), int(body.month[5:])
    inv = await register_invoice_total(
        session, actor_id=user.id, card_id=card_id, year=year, month=month,
        total_cents=body.total_cents,
    )  # fmt: skip
    return row(inv) | await invoice_summary(session, inv)


@router.get("/cards/{card_id}/panel", response_model=CardPanelOut)
async def panel(
    card_id: UUID, user: CurrentUser, session: Session, invoice: UUID | None = None
) -> dict[str, Any]:
    return await card_panel(
        session, user.id, card_id, today=local_today(user.tz), invoice_id=invoice
    )
```

- [ ] **Step 3:** `uv run pytest tests/api/test_cards_panel_api.py tests/domain/test_cards_panel.py -q` → PASS; depois `uv run ruff check . && uv run ruff format --check . && uv run mypy app`. Confirme que `Cents` rejeita 0 (já usado nas outras rotas; o teste `zero` prova).
- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(cards): panel and invoice total endpoints"`

---

### Task 4: Web — card por cartão

**Files:** modify `web/src/pages/billing.tsx`, `web/src/pages/pages.test.tsx`; regenerate `web/src/api/schema.d.ts`.

- [ ] **Step 1: Tipos** — `cd backend && uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json && cd ../web && npm run gen:api`. Em `api/types.ts` acrescente `export type CardPanel = S['CardPanelOut']`.

- [ ] **Step 2: Testes que falham** (acrescente ao fim de `pages.test.tsx`; os helpers `go`, `routes`, `J`, `calls`, `SP` já existem. A rota `/cards` do mock devolve o cartão `k1` "Visa" fechando dia 5 e vencendo dia 12)

```tsx
const PANEL = {
  invoice: { id: 'i1', card_id: 'k1', closing_on: '2026-12-05', due_on: '2026-12-12', total_cents: 50000, paid_cents: 0, remaining_cents: 50000, status: 'open' },
  limit_cents: 200000, used_cents: 50000, available_cents: 150000,
  by_category: [{ category_id: 'c1', total_cents: 50000 }], private_total_cents: 0,
  top: [{ description: 'Supermercado', merchant: null, amount_cents: 30000, occurred_on: '2026-11-20' }],
  history: [{ invoice_id: 'i1', closing_on: '2026-12-05', due_on: '2026-12-12', total_cents: 50000 }],
}

test('cartões: um card por cartão com resumo e limite', async () => {
  routes['/cards/k1/panel'] = () => J(PANEL)
  routes['/cards/k1/invoices'] = () => J([PANEL.invoice])
  go('/cartoes')
  const card = within((await screen.findByRole('heading', { name: 'Visa' })).closest('section')!)
  expect(await card.findByText(/Disponível R\\$ 1\\.500,00/)).toBeInTheDocument()
  await userEvent.click(card.getByRole('button', { name: 'Ver painel' }))
  expect(await card.findByText(/Mercado/)).toBeInTheDocument()
  expect(card.getByText(/Supermercado/)).toBeInTheDocument()
})

test('cartões: cadastrar fatura pelo total envia mês e valor', async () => {
  routes['/cards/k1/panel'] = () => J(PANEL)
  routes['/cards/k1/invoices'] = () => J([PANEL.invoice])
  routes['/cards/k1/invoice-totals'] = () => J(PANEL.invoice, 201)
  go('/cartoes')
  const card = within((await screen.findByRole('heading', { name: 'Visa' })).closest('section')!)
  await userEvent.click(await card.findByRole('button', { name: 'Cadastrar fatura' }))
  await userEvent.type(card.getByLabelText('Mês de fechamento'), '2026-08')
  await userEvent.type(card.getByLabelText('Valor total (R$)'), '1234,56')
  await userEvent.click(card.getByRole('button', { name: 'Salvar fatura' }))
  const post = calls.find(([u]) => u === '/cards/k1/invoice-totals')!
  expect(JSON.parse(post[1].body as string)).toEqual({ month: '2026-08', total_cents: 123456 })
})

test('cartões: nova compra no cartão', async () => {
  routes['/cards/k1/panel'] = () => J(PANEL)
  routes['/cards/k1/invoices'] = () => J([])
  go('/cartoes')
  const card = within((await screen.findByRole('heading', { name: 'Visa' })).closest('section')!)
  await userEvent.click(await card.findByRole('button', { name: 'Nova compra' }))
  await userEvent.type(card.getByLabelText('Valor (R$)'), '45,00')
  await userEvent.click(card.getByRole('button', { name: 'Registrar compra' }))
  const post = calls.find(([u]) => u === `/spaces/${SP}/card-purchases`)!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ card_id: 'k1', amount_cents: 4500, installments: 1 })
})
```

(Se a rota do mock de compras já existir em `routes` com status 201 e outro corpo, o teste só lê `calls`; basta a rota responder.) Run: `cd web && npm test -- pages` → FAIL.

- [ ] **Step 3: Implementação** — em `billing.tsx`:

Importe `CardPanel` de `../api/types` e `CategorySelect, useCatName` de `../ui`.

Componentes novos (acima de `Cards`):

```tsx
const pctOf = (v: number, max: number) => (max > 0 ? Math.round((v / max) * 100) : 0)

function CardPanelView({ card, invoiceId, onPick }: { card: CardT; invoiceId: string | null; onPick: (id: string) => void }) {
  const p = useGet<CardPanel>(`/cards/${card.id}/panel${invoiceId ? `?invoice=${invoiceId}` : ''}`)
  const catName = useCatName()
  if (!p.data) return <p>Carregando…</p>
  const d = p.data
  const maxCat = Math.max(1, ...d.by_category.map((c) => c.total_cents))
  const maxH = Math.max(1, ...d.history.map((h) => h.total_cents))
  return (
    <div className="mt-2">
      <h3 className="font-semibold">Gastos por categoria{d.invoice ? ` · fatura ${br(d.invoice.closing_on)}` : ''}</h3>
      {d.by_category.length === 0 && <p>Sem compras nesta fatura.</p>}
      <ul>{d.by_category.map((c) => (
        <li key={c.category_id ?? 'none'}>
          <div className="flex justify-between"><span>{catName(c.category_id)}</span><span>{formatBRL(c.total_cents)}</span></div>
          <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${pctOf(c.total_cents, maxCat)}%` }} /></div>
        </li>
      ))}</ul>
      {d.private_total_cents !== 0 && <p>Outros lançamentos (privados): {formatBRL(d.private_total_cents)}</p>}
      <h3 className="mt-3 font-semibold">Últimas faturas</h3>
      <div className="flex items-end gap-2" role="group" aria-label="Últimas faturas">
        {d.history.map((h) => (
          <button key={h.invoice_id} type="button" aria-label={`Fatura ${br(h.closing_on)}: ${formatBRL(h.total_cents)}`} aria-pressed={d.invoice?.id === h.invoice_id}
            className="flex flex-col items-center text-xs" onClick={() => onPick(h.invoice_id)}>
            <span className="w-8 rounded-t bg-primary" style={{ height: `${Math.max(4, pctOf(h.total_cents, maxH) * 0.8)}px` }} />
            <span>{h.closing_on.slice(5, 7)}/{h.closing_on.slice(2, 4)}</span>
          </button>
        ))}
      </div>
      <h3 className="mt-3 font-semibold">Maiores compras</h3>
      <ul>{d.top.map((t, i) => <li key={i} className="flex justify-between"><span>{br(t.occurred_on)} {t.description || t.merchant}</span><span>{formatBRL(t.amount_cents)}</span></li>)}</ul>
    </div>
  )
}

function PurchaseForm({ card, done }: { card: CardT; done: () => void }) {
  const [f, setF] = useState({ amount: '', installments: '1', description: '', category_id: '', occurred_on: today() })
  const cents = parseBRL(f.amount)
  const send = useSend(
    () => api('POST', `/spaces/${card.space_id}/card-purchases`, { card_id: card.id, amount_cents: cents!, installments: Number(f.installments), description: f.description, category_id: f.category_id || null, occurred_on: f.occurred_on } satisfies S['PurchaseIn']),
    done,
  )
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (cents) send.mutate() }}>
      <Field label="Valor (R$)"><input inputMode="decimal" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Parcelas"><input type="number" min={1} max={48} value={f.installments} onChange={(e) => setF({ ...f, installments: e.target.value })} /></Field>
      <Field label="Data"><input type="date" value={f.occurred_on} onChange={(e) => setF({ ...f, occurred_on: e.target.value })} /></Field>
      <Field label="Descrição"><input maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <CategorySelect value={f.category_id} onChange={(v) => setF({ ...f, category_id: v })} />
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !cents}>Registrar compra</Btn>
    </form>
  )
}

function InvoiceTotalForm({ card, done }: { card: CardT; done: () => void }) {
  const [f, setF] = useState({ month: '', total: '' })
  const cents = parseBRL(f.total)
  const send = useSend(() => api('POST', `/cards/${card.id}/invoice-totals`, { month: f.month, total_cents: cents! }), done)
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (cents && f.month) send.mutate() }}>
      <Field label="Mês de fechamento"><input type="month" required value={f.month} onChange={(e) => setF({ ...f, month: e.target.value })} /></Field>
      <Field label="Valor total (R$)"><input inputMode="decimal" required value={f.total} onChange={(e) => setF({ ...f, total: e.target.value })} /></Field>
      <Err e={send.error} />
      <Btn type="submit" disabled={send.isPending || !cents || !f.month}>Salvar fatura</Btn>
    </form>
  )
}

function CardTile({ c, owner }: { c: CardT; owner: boolean }) {
  const [open, setOpen] = useState<'purchase' | 'invoice' | 'panel' | null>(null)
  const [pick, setPick] = useState<string | null>(null)
  const [invId, setInvId] = useState<string | null>(null)
  const sum = useGet<CardPanel>(`/cards/${c.id}/panel`)
  const invoices = useGet<Invoice[]>(`/cards/${c.id}/invoices`)
  const toggle = (k: 'purchase' | 'invoice' | 'panel') => setOpen(open === k ? null : k)
  const cur = sum.data?.invoice
  return (
    <Card title={c.name}>
      <p>Fecha dia {c.closing_day} · vence dia {c.due_day}</p>
      {cur && <p>Fatura atual {formatBRL(cur.total_cents)} · vence {br(cur.due_on)}{cur.status === 'paid' ? ' · paga' : ''}</p>}
      {sum.data?.limit_cents != null && <p>Limite {formatBRL(sum.data.limit_cents)} · usado {formatBRL(sum.data.used_cents)} · Disponível {formatBRL(sum.data.available_cents ?? 0)}</p>}
      <div className="my-2 flex flex-wrap gap-2">
        <Btn type="button" onClick={() => toggle('purchase')}>Nova compra</Btn>
        <Btn type="button" onClick={() => toggle('invoice')}>Cadastrar fatura</Btn>
        <Btn type="button" onClick={() => toggle('panel')} className="bg-muted-foreground hover:bg-muted-foreground/90">{open === 'panel' ? 'Ocultar painel' : 'Ver painel'}</Btn>
      </div>
      {open === 'purchase' && <PurchaseForm card={c} done={() => setOpen(null)} />}
      {open === 'invoice' && <InvoiceTotalForm card={c} done={() => setOpen(null)} />}
      {open === 'panel' && <CardPanelView card={c} invoiceId={pick} onPick={setPick} />}
      {(invoices.data ?? []).map((i) => (
        <div key={i.id} className="border-t border-border py-2">
          <button type="button" className="flex w-full justify-between text-left" aria-expanded={invId === i.id} onClick={() => setInvId(invId === i.id ? null : i.id)}>
            <span>Fatura {br(i.closing_on)} · vence {br(i.due_on)}{i.status === 'paid' && <> · <span>paga</span></>}</span><span>{formatBRL(i.total_cents)}</span>
          </button>
          {invId === i.id && <InvoiceView id={i.id} />}
        </div>
      ))}
      <Err e={invoices.error} />
      <EditBox what="cartão" canEdit={owner} fields={[{ k: 'name', label: 'Nome do cartão (edição)', v: c.name }, { k: 'closing_day', label: 'Dia do fechamento (edição)', v: String(c.closing_day), type: 'number' }, { k: 'due_day', label: 'Dia do vencimento (edição)', v: String(c.due_day), type: 'number' }, { k: 'limit', label: 'Limite (R$, vazio = sem limite)', v: c.limit_cents ? centsText(c.limit_cents) : '' }]}
        save={(v) => { const l = v.limit ? parseBRL(v.limit) : null; return v.limit && !l ? Promise.reject(new ApiError(422, 'invalid_amount')) : api('PATCH', `/cards/${c.id}`, { name: v.name, closing_day: Number(v.closing_day), due_day: Number(v.due_day), limit_cents: l } satisfies S['CardPatch']) }}
        remove={() => api('DELETE', `/cards/${c.id}`)} />
    </Card>
  )
}
```

Substitua o corpo de `Cards()`: remova `sel`, `invId`, `invoices` e o `Card title="Meus cartões"`; mantenha `create`/`f`/`lim` e renderize:

```tsx
      <h1 className="mb-3 text-xl font-bold">Cartões e faturas</h1>
      <Card title="Novo cartão"><CardForm f={f} setF={setF} onSubmit={() => create.mutate()} err={create.error} busy={create.isPending} lim={lim} /></Card>
      {cards.isLoading ? null : mine.length === 0 && <p>Nenhum cartão neste espaço.</p>}
      <div className="grid gap-4 md:grid-cols-2">{mine.map((c) => <CardTile key={c.id} c={c} owner={owner} />)}</div>
```

(O `Card` do `ui.tsx` já tem `mb-4`; o `grid gap-4` só alinha as colunas. Se o `EditBox` exigir `key` para resetar ao trocar de cartão, o `key={c.id}` do `CardTile` já cobre.) Os testes antigos de `/cartoes` (fatura antiga: marcar como paga e desfazer) selecionavam o cartão pelo `<select>`; atualize-os para encontrar o card pelo `heading` "Visa" e abrir a fatura pelo botão `aria-expanded` dentro dele.

- [ ] **Step 4: Rodar** — `cd web && npm run lint && npm run typecheck && npm test && npm run build` → verde. Corrija os testes antigos de cartão que dependiam do `<select>` (Step 3).

- [ ] **Step 5: Commit** — `git add web backend && git commit -m "feat(web): one card per credit card with panel"`

---

### Task 5: Verificação e entrega

- [ ] `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app && bash scripts/migrate_check.sh` (sem migração nova: deve passar sem diferenças).
- [ ] `cd web && npm run lint && npm run typecheck && npm test && npm run build`.
- [ ] Conferir no navegador (ou, sem acesso, dizer explicitamente que não foi visto): card por cartão, painel, nova compra, cadastrar fatura, marcar fatura antiga como paga.
- [ ] Deploy só com confirmação do usuário: backup, `git pull` em `/home/vipsfibra/abby-cash-prod`, nova `ABBY_TAG`, `build api web`, `up -d api worker web` (ver memória `reference-prod-deploy`). **Sem rota nova de prefixo** (`/cards` já está no Nginx), então o conf do host não muda.

## Self-review (spec → tarefas)

- Fatura pelo total (compra única no dia do fechamento, soma à existente, mês curto): Task 1 e 3. Painel (fatura padrão, limite usado/disponível, categorias, 6 faturas, top 5, privacidade, fatura alheia = 404): Task 2 e 3. Card por cartão, resumo, ações, painel expansível, lista de faturas: Task 4. Nova compra reaproveita o endpoint existente: Task 4.
- Nomes consistentes: `register_invoice_total`, `card_panel`, `CardPanelOut`, `CardPanel`, `CardTile`, `CardPanelView`, `PurchaseForm`, `InvoiceTotalForm`.
