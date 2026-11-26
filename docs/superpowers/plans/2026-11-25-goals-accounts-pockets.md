# Metas com contas e caixinhas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O progresso de uma meta soma contas e caixinhas ligadas pelo usuário, cada conta/caixinha em no máximo uma meta.

**Architecture:** Duas tabelas de ligação (`goal_accounts`, `goal_pockets`) com `account_id`/`pocket_id` como PK (exclusividade). `goal_progress` passa a usar `goal_total` = aportes diretos + saldo das contas ligadas + saldo das caixinhas ligadas cuja conta não está ligada. `Goal.account_id` é migrado e removido.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest (backend); React + TS + vitest (web).

Spec: `docs/superpowers/specs/2026-11-25-goals-accounts-pockets-design.md`.
Pré-requisito: `docker compose -f infra/docker-compose.dev.yml up -d postgres redis`. Trabalhe numa branch nova a partir da `main` (`git switch -c feat/goals-accounts-pockets main`).

## File Structure

- Modify `backend/app/domain/goals/models.py`: remove `Goal.account_id`; add `GoalAccount`, `GoalPocket`.
- Create `backend/migrations/versions/d0e1f2a3b4c5_goal_links.py`.
- Modify `backend/app/domain/goals/service.py`: `goal_links`, `_set_links`, `goal_total`; `create_goal`, `update_goal`, `goal_progress`.
- Modify `backend/app/domain/accounts/service.py:98` and `backend/app/domain/privacy.py:132`: troca/remoção das referências a `Goal.account_id`.
- Modify `backend/app/domain/pockets/service.py` (`delete_pocket`): desliga a caixinha da meta.
- Modify `backend/app/api/goals.py`, `backend/app/api/schemas.py`: `account_ids`/`pocket_ids`.
- Modify `backend/tests/domain/test_goals.py`, `backend/tests/api/test_goals_api.py`.
- Modify `web/src/pages/plan.tsx`, `web/src/pages/pages.test.tsx`, `web/src/api/schema.d.ts` (gerado).

---

### Task 1: Modelo e migração

**Files:**
- Modify: `backend/app/domain/goals/models.py`
- Create: `backend/migrations/versions/d0e1f2a3b4c5_goal_links.py`
- Modify: `backend/app/domain/accounts/service.py` (import + linha 98), `backend/app/domain/privacy.py` (linha 132), `backend/tests/domain/test_goals.py` (`_goal`)

- [ ] **Step 1: Models**

Em `goals/models.py`, apague a linha `account_id: ... # informativo` do `Goal` e acrescente ao final do arquivo:

```python
class GoalAccount(Base):
    """Conta ligada à meta. PK em `account_id`: cada conta fica em no máximo uma meta."""

    __tablename__ = "goal_accounts"

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)


class GoalPocket(Base):
    __tablename__ = "goal_pockets"

    pocket_id: Mapped[UUID] = mapped_column(
        ForeignKey("pockets.id", ondelete="CASCADE"), primary_key=True
    )
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
```

- [ ] **Step 2: Migração** (`d0e1f2a3b4c5_goal_links.py`)

```python
"""goal links to accounts and pockets

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goal_accounts",
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_goal_accounts_goal_id", "goal_accounts", ["goal_id"])
    op.create_table(
        "goal_pockets",
        sa.Column("pocket_id", sa.Uuid(), sa.ForeignKey("pockets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_goal_pockets_goal_id", "goal_pockets", ["goal_id"])
    # o campo antigo era informativo e podia repetir: a meta mais antiga fica com a conta
    op.execute(
        "INSERT INTO goal_accounts (account_id, goal_id) "
        "SELECT DISTINCT ON (account_id) account_id, id FROM goals "
        "WHERE account_id IS NOT NULL ORDER BY account_id, created_at"
    )
    op.drop_column("goals", "account_id")


def downgrade() -> None:
    op.add_column("goals", sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id")))
    op.execute(
        "UPDATE goals g SET account_id = (SELECT min(a.account_id::text)::uuid "
        "FROM goal_accounts a WHERE a.goal_id = g.id)"
    )
    op.drop_table("goal_pockets")
    op.drop_table("goal_accounts")
```

- [ ] **Step 3: Referências antigas**

- `accounts/service.py`: troque `from app.domain.goals.models import Goal` por `GoalAccount` (confira o import existente) e a linha `| exists().where(Goal.account_id == acc.id)` por `| exists().where(GoalAccount.account_id == acc.id)`.
- `privacy.py`: apague a linha `(Goal, Goal.account_id, accs),` (as ligações somem por `ON DELETE CASCADE`).
- `tests/domain/test_goals.py::_goal`: remova `account_id=None,` da chamada.

- [ ] **Step 4: Verificar migração**

Run: `cd backend && bash scripts/migrate_check.sh`
Expected: termina sem erro (upgrade head + `alembic check` sem diferenças). Se `alembic check` acusar diferença de índice/nome, ajuste a migração ao model.

- [ ] **Step 5: Commit** (os testes de domínio só voltam a passar na Task 2, pois `create_goal` ainda recebe `account_id`)

```bash
git add backend && git commit -m "feat(goals): link tables for accounts and pockets, drop goals.account_id"
```

---

### Task 2: Domínio (ligações e progresso)

**Files:**
- Modify: `backend/app/domain/goals/service.py`
- Modify: `backend/app/domain/pockets/service.py` (`delete_pocket`)
- Test: `backend/tests/domain/test_goals.py`

- [ ] **Step 1: Testes que falham** (acrescente ao fim de `tests/domain/test_goals.py`; ajuste os imports no topo: `from app.domain.errors import DomainError`, `from app.domain.pockets.service import create_pocket, deposit`, `update_goal`, `pytest` — confira o que já existe)

```python
async def _pocket(session, user, acc, name="Reserva"):
    return await create_pocket(
        session, actor_id=user.id, space_id=acc.space_id, account_id=acc.id, name=name, cdi_bp=10000
    )


async def test_progress_sums_linked_account_and_pocket(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc1 = await make_account(session, sp, initial=50_000)
    acc2 = await make_account(session, sp, initial=100_000)
    pk = await _pocket(session, a, acc2)
    await deposit(session, actor_id=a.id, pocket_id=pk.id, amount_cents=30_000, on=D)
    goal = await _goal(session, a)
    await update_goal(
        session, actor_id=a.id, goal_id=goal.id,
        fields={"account_ids": [acc1.id], "pocket_ids": [pk.id]},
    )  # fmt: skip
    # acc1 inteira (50_000) + só a caixinha de acc2 (30_000); o resto de acc2 não conta
    assert (await goal_progress(session, goal.id, today=D)).saved == 80_000


async def test_pocket_of_linked_account_not_counted_twice(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    pk = await _pocket(session, a, acc)
    await deposit(session, actor_id=a.id, pocket_id=pk.id, amount_cents=30_000, on=D)
    goal = await _goal(session, a)
    await update_goal(
        session, actor_id=a.id, goal_id=goal.id,
        fields={"account_ids": [acc.id], "pocket_ids": [pk.id]},
    )  # fmt: skip
    assert (await goal_progress(session, goal.id, today=D)).saved == 100_000


async def test_account_and_pocket_belong_to_one_goal(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=1_000)
    other = await make_account(session, a.default_space_id, initial=1_000)
    pk = await _pocket(session, a, acc)
    g1, g2 = await _goal(session, a), await _goal(session, a)
    await update_goal(session, actor_id=a.id, goal_id=g1.id, fields={"account_ids": [acc.id]})
    with pytest.raises(DomainError, match="already_linked"):  # mesma conta
        await update_goal(session, actor_id=a.id, goal_id=g2.id, fields={"account_ids": [acc.id]})
    with pytest.raises(DomainError, match="already_linked"):  # caixinha de conta de outra meta
        await update_goal(session, actor_id=a.id, goal_id=g2.id, fields={"pocket_ids": [pk.id]})
    pk2 = await _pocket(session, a, other)
    await update_goal(session, actor_id=a.id, goal_id=g2.id, fields={"pocket_ids": [pk2.id]})
    g3 = await _goal(session, a)
    with pytest.raises(DomainError, match="already_linked"):  # conta cuja caixinha está em outra meta
        await update_goal(session, actor_id=a.id, goal_id=g3.id, fields={"account_ids": [other.id]})
```

(Confira se `pytest`, `HTTPException`, `goal_links` e `update_goal` estão importados no topo do arquivo.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && uv run pytest tests/domain/test_goals.py -q`
Expected: FAIL (`goal_links`/`account_ids` não existem).

- [ ] **Step 3: Implementação** em `goals/service.py`

Imports novos: `delete` (sqlalchemy), `IntegrityError` (`sqlalchemy.exc`), `Pocket` (`app.domain.pockets.models`), `GoalAccount`, `GoalPocket` (`goals.models`), `pocket_stats`, `visible_pocket` (`app.domain.pockets.service`), `account_balance` (`app.domain.transactions.service`). Remova o parâmetro `account_id` e o bloco `if account_id is not None` de `create_goal`, e acrescente `account_ids: list[UUID] = (), pocket_ids: list[UUID] = ()` à assinatura.

```python
async def goal_links(session: AsyncSession, goal_id: UUID) -> tuple[list[UUID], list[UUID]]:
    accs = await session.scalars(select(GoalAccount.account_id).where(GoalAccount.goal_id == goal_id))
    pks = await session.scalars(select(GoalPocket.pocket_id).where(GoalPocket.goal_id == goal_id))
    return sorted(accs), sorted(pks)


async def _set_links(
    session: AsyncSession, actor_id: UUID, goal: Goal,
    account_ids: list[UUID] | None, pocket_ids: list[UUID] | None,
) -> None:  # fmt: skip
    """Substitui as ligações enviadas (None mantém). Conta/caixinha: uma meta só, inclusive
    cruzado (conta de uma meta + caixinha dessa conta em outra contaria o dinheiro duas vezes)."""
    cur_a, cur_p = await goal_links(session, goal.id)
    accs = set(cur_a if account_ids is None else account_ids)
    pids = set(cur_p if pocket_ids is None else pocket_ids)
    for aid in accs:
        await use_account(session, actor_id, aid)
    pockets = [await visible_pocket(session, actor_id, pid) for pid in pids]
    other_accs = set(
        await session.scalars(select(GoalAccount.account_id).where(GoalAccount.goal_id != goal.id))
    )
    other_pk = (
        await session.execute(
            select(GoalPocket.pocket_id, Pocket.account_id)
            .join(Pocket, Pocket.id == GoalPocket.pocket_id)
            .where(GoalPocket.goal_id != goal.id)
        )
    ).all()
    if accs & ({r[1] for r in other_pk} | other_accs) or any(
        p.id in {r[0] for r in other_pk} or p.account_id in other_accs for p in pockets
    ):
        raise DomainError("already_linked")
    await session.execute(delete(GoalAccount).where(GoalAccount.goal_id == goal.id))
    await session.execute(delete(GoalPocket).where(GoalPocket.goal_id == goal.id))
    session.add_all(GoalAccount(goal_id=goal.id, account_id=a) for a in accs)
    session.add_all(GoalPocket(goal_id=goal.id, pocket_id=p) for p in pids)
    try:
        await session.flush()
    except IntegrityError:  # corrida: outra meta pegou a mesma conta/caixinha
        await session.rollback()
        raise DomainError("already_linked") from None


async def goal_total(session: AsyncSession, goal_id: UUID, today: date) -> int:
    """Aportes diretos + saldo das contas ligadas + caixinhas ligadas (a caixinha de uma conta
    já ligada é ignorada: o saldo da conta já a inclui)."""
    accs, pids = await goal_links(session, goal_id)
    total = await goal_saved(session, goal_id)
    for a in accs:
        total += await account_balance(session, a)
    covered = set(await session.scalars(select(Pocket.id).where(Pocket.account_id.in_(accs))))
    for p in set(pids) - covered:
        total += (await pocket_stats(session, p, today)).balance
    return total
```

Em `create_goal`, depois de `await session.flush()` e antes do `audit`: `await _set_links(session, actor_id, goal, list(account_ids), list(pocket_ids))`.

Em `goal_progress`, troque `saved = await goal_saved(session, goal.id)` por `saved = await goal_total(session, goal.id, today)`.

Em `update_goal`, **antes** de `before = snap(goal, fields)` (o `snap` e o `setattr` só aceitam colunas), extraia os ids para o `snap`/`setattr` não os verem:

```python
    ids = {k: fields.pop(k) for k in ("account_ids", "pocket_ids") if k in fields}
    if ids:
        await _set_links(session, actor_id, goal, ids.get("account_ids"), ids.get("pocket_ids"))
```


Em `pockets/service.py::delete_pocket`, antes do `audit`: `await session.execute(delete(GoalPocket).where(GoalPocket.pocket_id == pocket.id))` (imports: `delete` de sqlalchemy, `GoalPocket` de `app.domain.goals.models`).

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && uv run pytest tests/domain -q`
Expected: PASS (inclui `test_goals.py`, `test_accounts`/privacidade que usavam `Goal.account_id`).

- [ ] **Step 5: Commit**

```bash
git add backend && git commit -m "feat(goals): progress includes linked accounts and pockets"
```

---

### Task 3: API

**Files:**
- Modify: `backend/app/api/goals.py`, `backend/app/api/schemas.py` (`GoalOut`)
- Test: `backend/tests/api/test_goals_api.py`

- [ ] **Step 1: Teste que falha** — em `test_goal_flow_over_http`, troque `"account_id": str(acc.id)` por `"account_ids": [str(acc.id)]` e, depois da criação, acrescente:

```python
    assert goal["account_ids"] == [str(acc.id)] and goal["pocket_ids"] == []
```

Ajuste os asserts seguintes: com a conta ligada (100_000) o `saved_cents` passa a ser o saldo da conta mais os aportes (a contribuição de 25_000 sai da conta e entra na meta, total constante). Troque `(got["saved_cents"], got["target_cents"]) == (25_000, 120_000)` por `(100_000, 120_000)`; após a retirada de 5_000 (volta à conta) o total segue 100_000; no `listed` espere `100_000`; o `insufficient_saved` continua valendo (retirada limitada ao aporte direto, 20_000). Acrescente um teste novo:

```python
async def test_goal_links_conflict_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id)
    g1 = (await client.post(f"/spaces/{sp}/goals", headers=h,
          json={"name": "A", "target_cents": 1000, "account_ids": [str(acc.id)]})).json()
    r = await client.post(f"/spaces/{sp}/goals", headers=h,
                          json={"name": "B", "target_cents": 1000, "account_ids": [str(acc.id)]})
    assert r.status_code == 422 and r.json() == {"detail": "already_linked"}
    p = await client.patch(f"/goals/{g1['id']}", headers=h, json={"account_ids": []})
    assert p.status_code == 200 and p.json()["account_ids"] == []
```

Run: `cd backend && uv run pytest tests/api/test_goals_api.py -q` — Expected: FAIL.

- [ ] **Step 2: Implementação**

`schemas.py::GoalOut`: troque `account_id: UUID | None` por `account_ids: list[UUID]` e `pocket_ids: list[UUID]`.

`api/goals.py`:
- `GoalIn`: troque `account_id` por `account_ids: list[UUID] = Field(default_factory=list)` e `pocket_ids: list[UUID] = Field(default_factory=list)`.
- `GoalPatch`: acrescente `account_ids: list[UUID] | None = None` e `pocket_ids: list[UUID] | None = None`; no `patch`, estenda o loop que descarta `None` para `("name", "target_cents", "account_ids", "pocket_ids")`.
- Helper e uso (importe `goal_links`):

```python
async def _links(session: Session, goal_id: UUID) -> dict[str, Any]:
    accs, pks = await goal_links(session, goal_id)
    return {"account_ids": accs, "pocket_ids": pks}
```

  `create`: `create_goal(..., account_ids=body.account_ids, pocket_ids=body.pocket_ids, created_on=...)` e retorno `row(goal) | await _links(session, goal.id)`. Em `list_goals`, `get_goal` e `patch`, some `await _links(session, g.id)` ao dict devolvido (`row(g) | await _links(...) | _progress(...)`; na compreensão de lista use um laço `for` simples, já que há `await` em duas posições).
  Atenção: `row(goal)` não tem mais `account_id`; `GoalOut` exige as duas listas em todos os retornos.

- [ ] **Step 3: Rodar**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: tudo verde.

- [ ] **Step 4: Commit**

```bash
git add backend && git commit -m "feat(goals): account_ids and pocket_ids in the goals API"
```

---

### Task 4: Web

**Files:**
- Modify: `web/src/api/schema.d.ts` (gerado), `web/src/pages/plan.tsx`, `web/src/pages/pages.test.tsx`

- [ ] **Step 1: Regerar tipos**

```bash
cd backend && uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json
cd ../web && npm run gen:api
```

Expected: `schema.d.ts` agora tem `account_ids`/`pocket_ids` em `GoalIn`, `GoalPatch`, `GoalOut`.

- [ ] **Step 2: Teste que falha** — acrescente em `pages.test.tsx` (padrão dos testes vizinhos):

```tsx
test('metas: conta já ligada a outra meta fica desabilitada', async () => {
  routes[`/spaces/${SP}/goals`] = () => J([
    { id: 'g1', name: 'Viagem', saved_cents: 0, target_cents: 100000, deadline: null, monthly_needed_cents: null, behind: false, account_ids: ['a1'], pocket_ids: [] },
    { id: 'g2', name: 'Carro', saved_cents: 0, target_cents: 100000, deadline: null, monthly_needed_cents: null, behind: false, account_ids: [], pocket_ids: [] },
  ])
  routes[`/spaces/${SP}/pockets`] = () => J([])
  go('/metas')
  const carro = (await screen.findByText('Carro')).closest('section')!
  const box = within(carro).getByLabelText(/Nubank/)
  expect(box).toBeDisabled()
  expect(within(carro).getByText(/Viagem/, { selector: 'small' })).toBeInTheDocument()
  routes[`/spaces/${SP}/goals`] = () => J([])
})
```

(Confira a rota real das metas em `router.tsx` — troque `/metas` se for outra — e o elemento que `Card` renderiza; ajuste `closest('section')` ao wrapper real.)

Run: `cd web && npm test -- pages` — Expected: FAIL.

- [ ] **Step 3: Implementação** em `plan.tsx`

Componente (acima de `Goals`; importe `Pocket` de `../api/types`):

```tsx
type Links = { accounts: string[]; pockets: string[] }

/** Quem já está em OUTRA meta (direto ou via caixinha/conta) fica indisponível, com o nome da meta. */
function takenBy(goals: Goal[], self: string | undefined, pockets: Pocket[]) {
  const acc = new Map<string, string>(), pk = new Map<string, string>()
  const pocketAcc = new Map(pockets.map((p) => [p.id, p.account_id]))
  for (const g of goals.filter((x) => x.id !== self)) {
    for (const a of g.account_ids) {
      acc.set(a, g.name)
      pockets.filter((p) => p.account_id === a).forEach((p) => pk.set(p.id, g.name))
    }
    for (const p of g.pocket_ids) {
      pk.set(p, g.name)
      const a = pocketAcc.get(p)
      if (a) acc.set(a, g.name)
    }
  }
  return { acc, pk }
}

function GoalLinks({ goals, self, value, onChange }: { goals: Goal[]; self?: string; value: Links; onChange: (v: Links) => void }) {
  const accounts = useAccounts()
  const { spaceId } = useSpace()
  const pockets = useGet<Pocket[]>(`/spaces/${spaceId}/pockets`).data ?? []
  const taken = takenBy(goals, self, pockets)
  const toggle = (k: keyof Links, id: string) =>
    onChange({ ...value, [k]: value[k].includes(id) ? value[k].filter((x) => x !== id) : [...value[k], id] })
  const row = (k: keyof Links, id: string, label: string, by?: string) => (
    <label key={id} className="flex items-center gap-2">
      <input type="checkbox" checked={value[k].includes(id)} disabled={!!by} onChange={() => toggle(k, id)} />
      {label}{by && <small> · já na meta {by}</small>}
    </label>
  )
  return (
    <fieldset>
      <legend>Contas e caixinhas da meta</legend>
      {accounts.data.map((a) => row('accounts', a.id, a.name, taken.acc.get(a.id)))}
      {pockets.map((p) => row('pockets', p.id, `Caixinha ${p.name}`, taken.pk.get(p.id)))}
    </fieldset>
  )
}
```

Na criação (`Goals`): estado `const [links, setLinks] = useState<Links>({ accounts: [], pockets: [] })`; renderize `<GoalLinks goals={goals.data ?? []} value={links} onChange={setLinks} />` no formulário "Nova meta" e envie `account_ids: links.accounts, pocket_ids: links.pockets` no POST (`satisfies S['GoalIn']`), zerando `links` no `onSuccess`.

Edição: dentro do `Card` de cada meta, um componente `GoalLinksEditor({ g, goals, canEdit })` com estado inicial `{ accounts: g.account_ids, pockets: g.pocket_ids }`, o `GoalLinks` com `self={g.id}` e, só se `canEdit`, um botão "Salvar vínculos" que faz `api('PATCH', `/goals/${g.id}`, { account_ids, pocket_ids } satisfies S['GoalPatch'])` via `useSend` (mostrando `<Err e={send.error} />`). Sem `canEdit`, renderize só a lista de nomes ligados.

- [ ] **Step 4: Rodar**

Run: `cd web && npm run lint && npm run typecheck && npm test`
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git add web && git commit -m "feat(web): link accounts and pockets to goals"
```

---

### Task 5: Verificação final

- [ ] Backend: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app && bash scripts/migrate_check.sh`
- [ ] Web: `cd web && npm run lint && npm run typecheck && npm test && npm run build`
- [ ] Confirmar no navegador (`run` skill ou dev server): criar meta ligando conta e caixinha, ver o progresso somar, tentar ligar a mesma conta a uma segunda meta.
- [ ] Abrir PR para a `main` (`gh pr create`), sem merge/deploy sem confirmação do usuário (a migração `d0e1f2a3b4c5` roda no deploy).

## Self-review (spec → tarefas)

- Tabelas e exclusividade, migração do `account_id`: Task 1. Conflito cruzado, permissão, substituição: Task 2. Soma sem duplicar e `monthly_needed`/`behind`/selo (via `goal_progress`): Task 2. API `account_ids`/`pocket_ids` e `already_linked`: Task 3. Formulário com itens desabilitados e nome da meta: Task 4.
- Nomes consistentes: `goal_links`, `_set_links`, `goal_total`, `GoalAccount`, `GoalPocket`, `account_ids`, `pocket_ids`.
