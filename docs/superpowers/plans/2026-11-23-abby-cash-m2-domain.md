# Abby Cash M2 — Domínio financeiro: Plano detalhado (TDD)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **Use ponytail em tudo** (passe esta instrução a todo subagente). TDD, testes, review e verificação continuam integrais.

**Goal:** contas, lançamentos, visibilidade em contas compartilhadas, cartões/faturas/parcelas, contas a pagar e pagamentos, teto de gastos, metas e auditoria/LGPD, tudo com API REST e testes. Nenhuma IA, canal ou web neste marco.

**Architecture:** continua o pacote Python `app` do M1. Cada área vive em `app/domain/<área>/` (models + service) e é exposta por um router em `app/api/`. Serviços de domínio recebem `session` como primeiro argumento, validam acesso com `require_member`/`use_account`/`use_card`, **commitam no fim** (como `create_family_space` do M1) e levantam `DomainError` (regra de negócio, vira 422 na API) ou `HTTPException` (404/403 de acesso). Testes usam Postgres e Redis reais (mesma infra do M1).

**Tech Stack:** a do M1; **nenhuma dependência nova** (zipfile, csv, json e dataclasses são stdlib).

**Interfaces:** exatamente as do plano mestre (`docs/superpowers/plans/2026-11-23-abby-cash-v1.md`), T2.1–T2.7. Nenhuma renomeada. Extensões permitidas e usadas aqui: (a) funções com acesso a banco recebem `session` como 1º parâmetro (o plano mestre omite por brevidade, ex.: `invoice_total(session, invoice_id)`); (b) parâmetros opcionais com default (`today=`, `commit`-free); (c) helpers extras listados em cada tarefa.

## Decisões técnicas do marco (registradas)

- **Escopo da API de lançamentos:** M2 cria e lista lançamentos. **Editar/apagar lançamento** não está na lista de interfaces do plano mestre; entra no M3 (corrigir/apagar pelo chat) e no M7 (edição na web), reutilizando `sync_invoice_bill` (T2.3) para manter a conta espelho da fatura correta.
- **Erros:** `DomainError(ValueError)` em `app/domain/errors.py`, com o código no texto (`str(e)` = `"amount_must_be_positive"`). `main.py` registra um handler que devolve `422 {"detail": "<código>"}`. Acesso: 404 para quem não é membro (via `require_member`), 403 ao usar conta/cartão de espaço de que o autor não é membro.
- **Valores:** `amount_cents` (e todo `*_cents`) é `int` estrito no JSON (`Annotated[int, Field(strict=True)]`): `45.5` e `"4500"` dão 422. Coluna `BIGINT`; `CHECK (amount_cents > 0)` nos lançamentos.
- **Serialização:** `app/core/serialize.py::row(obj)` converte qualquer model em `dict` com todas as colunas (UUID/date/datetime saem como string via FastAPI). Assim, colunas novas aparecem na API sem editar schemas de resposta.
- **Schema por tarefa:** cada tarefa com tabela nova gera sua migração Alembic (`autogenerate`), revisa o arquivo e valida com `scripts/migrate_check.sh` (banco descartável: `upgrade head && alembic check`). Os testes continuam usando `Base.metadata.create_all`.
- **Agregador de models:** `app/domain/models.py` importa todos os models; `tests/conftest.py` e `migrations/env.py` importam só ele. Cada tarefa acrescenta sua linha e roda `uv run ruff check --fix .` para ordenar.
- **Conta compartilhada (spec 14.1):** `use_account(session, actor_id, account_id)` exige que o autor seja membro do espaço **dono da conta** (`accounts.space_id`); senão 403. O lançamento pertence a `transactions.space_id` (qualquer espaço de que o autor seja membro). Cartão idem (`use_card`).
- **Sinal por conta (`signed`)**: para uma conta, receita = +, despesa = −, transferência: − na origem (`account_id`), + no destino (`counter_account_id`). Saldo e extrato usam a mesma função (`transactions/rules.py::signed`), então "o total fecha".
- **Pagamento de fatura:** `transfer` com `account_id` (origem), `card_id`, `invoice_id` e `bill_id` (conta espelho). O lançamento pertence ao espaço da **conta de origem** (não revela a conta pessoal a outros membros do espaço do cartão). **Pagamento de conta a pagar:** `expense` no espaço da conta a pagar, `bill_id` preenchido, categoria da conta.
- **Metas:** `contribute` = `transfer` com `account_id` (origem) e `goal_id`; `withdraw` = `transfer` com `account_id=None`, `counter_account_id` (destino) e `goal_id`. Guardado = aportes − retiradas. `Goal.account_id` é informativo (onde o dinheiro mora); não altera saldos.
- **Ordem real das dependências:** a fatura precisa da conta espelho (`Bill`) já no T2.3; por isso o model `Bill` e a coluna `transactions.bill_id` nascem no T2.3 (junto com cartões). O T2.4 só adiciona serviço, recorrência, pagamentos e API (sem migração). O teste `test_goal_contribution_not_counted` (T2.5 no plano mestre) depende de metas e é escrito no T2.6.
- **Concorrência:** pagamentos usam `SELECT ... FOR UPDATE` na conta a pagar; criação de fatura confia na restrição única `(card_id, closing_on)` (ponytail: corrida rarísssima, o chamador repete).
- **Deixado para o M3 (anotado):** `delete_account` precisa apagar também `channel_links` quando a tabela existir.

## Estrutura de arquivos do M2

```
backend/scripts/migrate_check.sh
backend/app/core/{dates.py (+to_local_date), serialize.py}
backend/app/domain/{errors,models,audit,privacy}.py
backend/app/domain/accounts/{access,service,statement}.py
backend/app/domain/transactions/{models,rules,service}.py
backend/app/domain/cards/{models,billing,service}.py
backend/app/domain/bills/{models,status,recurrence,service}.py   backend/app/domain/payments.py
backend/app/domain/budgets/{models,service}.py
backend/app/domain/goals/{models,service}.py
backend/app/api/{schemas,accounts,transactions,cards,bills,budgets,goals,privacy}.py
backend/tests/factories.py
backend/tests/domain/{test_transactions,test_statement,test_cards,test_bills,test_budgets,test_goals,test_audit}.py
backend/tests/api/{test_accounts_transactions_api,test_cards_api,test_bills_api,test_budgets_api,test_goals_api,test_privacy_api}.py
```

## Rotas REST do marco (todas com `get_current_user`; acesso por `require_member`; não membro = 404)

| Tarefa | Rotas |
|---|---|
| T2.1 | `POST /spaces/{id}/accounts`, `GET /accounts`, `GET /accounts/{id}` (com `balance_cents`), `PUT /spaces/{id}/default-account`, `POST /spaces/{id}/transactions`, `GET /spaces/{id}/transactions` |
| T2.2 | `GET /accounts/{id}/statement?start&end` |
| T2.3 | `POST /spaces/{id}/cards`, `GET /cards`, `POST /spaces/{id}/card-purchases`, `GET /cards/{id}/invoices`, `GET /invoices/{id}` |
| T2.4 | `POST /spaces/{id}/bills`, `GET /spaces/{id}/bills`, `POST /bills/{id}/payments`, `POST /invoices/{id}/payments` |
| T2.5 | `PUT\|GET /spaces/{id}/budgets/{YYYY-MM}` |
| T2.6 | `POST\|GET /spaces/{id}/goals`, `GET /goals/{id}`, `POST /goals/{id}/contributions`, `POST /goals/{id}/withdrawals` |
| T2.7 | `GET /privacy/export`, `DELETE /privacy/account` |

**Lacuna conhecida do M1, resolvida no T2.1:** `create_family_space` não cria contas (só categorias), então um espaço familiar nasce sem nenhuma conta. O T2.1 acrescenta `POST /spaces/{id}/accounts` (qualquer membro cria conta no espaço) e `create_account` no serviço; não se altera `create_family_space`.

---

## Task 1 (T2.1): Contas e lançamentos

**Files:** Create `backend/scripts/migrate_check.sh`, `backend/app/core/serialize.py`, `backend/app/domain/{errors,models}.py`, `backend/app/domain/accounts/{access,service}.py`, `backend/app/domain/transactions/{__init__,models,rules,service}.py`, `backend/app/api/{schemas,accounts,transactions}.py`, `backend/tests/factories.py`, `backend/tests/domain/test_transactions.py`, `backend/tests/api/test_accounts_transactions_api.py`. Modify `backend/app/core/dates.py`, `backend/tests/core/test_dates.py`, `backend/app/domain/spaces/access.py`, `backend/app/main.py`, `backend/tests/conftest.py`, `backend/migrations/env.py`.

- [ ] **Step 1: Infra de teste (script de migração, factories, agregador, datas)**

`backend/scripts/migrate_check.sh` (valida as migrações num banco descartável):
```bash
#!/usr/bin/env bash
# Aplica todas as migrações num banco novo e roda `alembic check` (modelos == migrações).
set -euo pipefail
cd "$(dirname "$0")/.."
DB="abby_scratch_$$"
PSQL=(docker compose -f ../infra/docker-compose.dev.yml exec -T postgres psql -U abby -d postgres -v ON_ERROR_STOP=1)
"${PSQL[@]}" -c "CREATE DATABASE $DB"
trap '"${PSQL[@]}" -c "DROP DATABASE IF EXISTS $DB"' EXIT
export DATABASE_URL="postgresql+asyncpg://abby:abby@localhost:5432/$DB"
uv run alembic upgrade head
uv run alembic check
```

`backend/app/domain/errors.py`:
```python
class DomainError(ValueError):
    """Violação de regra de negócio. O texto é o código estável (ex.: "invalid_category")."""
```

`backend/app/core/serialize.py`:
```python
from typing import Any


def row(obj: Any) -> dict[str, Any]:
    """Todas as colunas de um model como dict (valores monetários continuam int)."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
```

`backend/app/domain/models.py` (agregador; cada tarefa acrescenta sua linha):
```python
"""Importa todos os models para registrar as tabelas em Base.metadata (Alembic e testes)."""

import app.domain.accounts.models  # noqa: F401
import app.domain.categories.models  # noqa: F401
import app.domain.spaces.models  # noqa: F401
import app.domain.transactions.models  # noqa: F401
import app.domain.users.models  # noqa: F401
```

Em `backend/tests/conftest.py` troque as quatro linhas
```python
import app.domain.accounts.models  # noqa: F401
import app.domain.categories.models  # noqa: F401
import app.domain.spaces.models  # noqa: F401
import app.domain.users.models  # noqa: F401
```
por
```python
import app.domain.models  # noqa: F401
```
e faça a mesma troca das mesmas quatro linhas em `backend/migrations/env.py`.

Em `backend/app/core/dates.py`, troque o import e `local_today` por:
```python
import calendar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def to_local_date(moment: datetime, tz: str) -> date:
    """Dia civil de um instante no fuso do usuário (23:30 em São Paulo ainda é o mesmo dia)."""
    return moment.astimezone(ZoneInfo(tz)).date()


def local_today(tz: str) -> date:
    return to_local_date(datetime.now(UTC), tz)
```
(mantenha `clamp_day` e `add_months` como estão). Acrescente a `backend/tests/core/test_dates.py`:
```python
def test_to_local_date_uses_local_calendar_day():
    from datetime import UTC, date, datetime

    from app.core.dates import to_local_date

    late = datetime(2026, 3, 11, 2, 30, tzinfo=UTC)  # 23:30 de 10/03 em São Paulo
    assert to_local_date(late, "America/Sao_Paulo") == date(2026, 3, 10)
    assert to_local_date(late, "UTC") == date(2026, 3, 11)
```

Em `backend/app/domain/spaces/access.py` acrescente ao final:
```python
async def is_member(session: AsyncSession, user_id: UUID, space_id: UUID) -> bool:
    return await session.get(SpaceMember, (space_id, user_id), populate_existing=True) is not None
```

`backend/tests/factories.py`:
```python
from uuid import UUID

from sqlalchemy import select

from app.core.security import create_access_token
from app.domain.accounts.models import Account
from app.domain.categories.models import Category
from app.domain.spaces.models import Space
from app.domain.spaces.service import (
    accept_space_invite,
    create_family_space,
    create_space_invite,
)
from app.domain.users.models import User
from app.domain.users.service import create_admin, create_signup_invite, register_user

PWD = "correct horse battery"


async def make_user(session, email: str) -> User:
    admin = await create_admin(session, email=f"adm-{email}", name="Adm", password=PWD)
    inv = await create_signup_invite(session, created_by=admin.id)
    return await register_user(session, email=email, name=email, password=PWD, invite_code=inv.code)


async def make_family(session, owner: User, *members: User) -> Space:
    fam = await create_family_space(session, owner_id=owner.id, name="Casa")
    for m in members:
        inv = await create_space_invite(session, space_id=fam.id, created_by=owner.id)
        await accept_space_invite(session, token=inv.token, user_id=m.id)
    return fam


async def make_account(
    session, space_id: UUID, *, name: str = "Conta", type: str = "checking", initial: int = 0
) -> Account:
    acc = Account(space_id=space_id, type=type, name=name, initial_balance_cents=initial)
    session.add(acc)
    await session.commit()
    return acc


async def category_id(session, space_id: UUID, name: str = "Mercado", kind: str = "expense") -> UUID:
    cid = await session.scalar(
        select(Category.id).where(
            Category.space_id == space_id, Category.name == name, Category.kind == kind
        )
    )
    assert cid is not None
    return cid


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
```

```bash
chmod +x backend/scripts/migrate_check.sh
```

- [ ] **Step 2: Testes de domínio falhando**

`backend/tests/domain/test_transactions.py`:
```python
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.domain.errors import DomainError
from app.domain.transactions.service import (
    account_balance,
    create_transaction,
    list_transactions,
    normalize_merchant,
)
from tests.factories import category_id, make_account, make_family, make_user

D = date(2026, 11, 10)


async def _tx(session, user, acc, amount, *, type="expense", on=D, cat=None, space=None,
              counter=None, description="x"):  # fmt: skip
    return await create_transaction(
        session, actor_id=user.id, space_id=space or user.default_space_id, type=type,
        amount_cents=amount, occurred_on=on, description=description, category_id=cat,
        account_id=acc.id, counter_account_id=counter.id if counter else None,
    )  # fmt: skip


async def test_balance_formula_with_transfers(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    one = await make_account(session, sp, name="Um", initial=100_000)
    two = await make_account(session, sp, name="Dois")
    await _tx(session, a, one, 50_000, type="income")
    await _tx(session, a, one, 20_000)
    await _tx(session, a, one, 30_000, type="transfer", counter=two)
    await _tx(session, a, two, 10_000, type="transfer", counter=one)
    assert await account_balance(session, one.id) == 100_000 + 50_000 - 20_000 - 30_000 + 10_000
    assert await account_balance(session, two.id) == 30_000 - 10_000


async def test_cannot_use_account_from_space_user_is_not_member(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    theirs = await make_account(session, a.default_space_id)
    mine = await make_account(session, b.default_space_id)
    with pytest.raises(HTTPException) as e:
        await _tx(session, b, theirs, 1_000)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:  # destino de transferência também conta
        await _tx(session, b, mine, 1_000, type="transfer", counter=theirs)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await create_transaction(
            session, actor_id=b.id, space_id=b.default_space_id, type="expense",
            amount_cents=1, occurred_on=D, account_id=uuid4(),
        )  # fmt: skip
    assert e.value.status_code == 404


async def test_member_can_use_shared_account_in_own_personal_space(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    shared = await make_account(session, fam.id, name="Conjunta")
    tx = await _tx(session, h, shared, 1_000)  # lançamento no espaço pessoal do h
    assert tx.space_id == h.default_space_id and tx.account_id == shared.id
    assert await account_balance(session, shared.id) == -1_000


async def test_non_member_cannot_create_or_list_in_space(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, b.default_space_id)
    with pytest.raises(HTTPException) as e:
        await _tx(session, b, acc, 1_000, space=a.default_space_id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await list_transactions(session, viewer_id=b.id, space_id=a.default_space_id)
    assert e.value.status_code == 404


async def test_amount_must_be_positive(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    for bad in (0, -5):
        with pytest.raises(DomainError, match="amount_must_be_positive"):
            await _tx(session, a, acc, bad)
    assert await list_transactions(session, viewer_id=a.id, space_id=a.default_space_id) == []


async def test_category_must_belong_to_space_and_match_kind(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id)
    foreign = await category_id(session, b.default_space_id)
    with pytest.raises(DomainError, match="invalid_category"):
        await _tx(session, a, acc, 1_000, cat=foreign)
    salary = await category_id(session, a.default_space_id, "Salário", "income")
    with pytest.raises(DomainError, match="invalid_category"):
        await _tx(session, a, acc, 1_000, cat=salary)  # despesa com categoria de receita
    await _tx(session, a, acc, 1_000, type="income", cat=salary)


async def test_transfer_shape_rules(session):
    a = await make_user(session, "a@x.com")
    one = await make_account(session, a.default_space_id, name="Um")
    two = await make_account(session, a.default_space_id, name="Dois")
    with pytest.raises(DomainError, match="invalid_transfer"):
        await _tx(session, a, one, 100, type="transfer")  # sem destino
    with pytest.raises(DomainError, match="invalid_transfer"):
        await _tx(session, a, one, 100, type="transfer", counter=one)  # mesma conta
    with pytest.raises(DomainError, match="invalid_transfer"):
        await _tx(session, a, one, 100, type="expense", counter=two)  # destino em despesa
    with pytest.raises(DomainError, match="invalid_type"):
        await _tx(session, a, one, 100, type="goal_contribution")


async def test_list_transactions_filters_by_period_category_account(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    one = await make_account(session, sp, name="Um")
    two = await make_account(session, sp, name="Dois")
    mercado, transporte = await category_id(session, sp), await category_id(session, sp, "Transporte")
    t1 = await _tx(session, a, one, 1_000, on=date(2026, 11, 1), cat=mercado)
    t2 = await _tx(session, a, one, 2_000, on=date(2026, 11, 15), cat=transporte)
    t3 = await _tx(session, a, two, 3_000, on=date(2026, 12, 2), cat=mercado)

    async def ids(**kw):
        return [t.id for t in await list_transactions(session, viewer_id=a.id, space_id=sp, **kw)]

    assert await ids() == [t3.id, t2.id, t1.id]  # mais recente primeiro
    assert await ids(start=date(2026, 11, 10), end=date(2026, 11, 30)) == [t2.id]
    assert await ids(category_id=mercado) == [t3.id, t1.id]
    assert await ids(account_id=one.id) == [t2.id, t1.id]
    assert await ids(account_id=two.id, category_id=transporte) == []
    assert await ids(limit=1, offset=1) == [t2.id]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mercado Extra Loja 123", "mercado extra"),
        ("PADARIA SÃO JOÃO #45", "padaria sao joao"),
        ("Uber *Trip 8821", "uber trip"),
        ("  Farmácia   Pague Menos  ", "farmacia pague menos"),
        ("Posto Shell Nº 7", "posto shell"),
        ("Açaí do Zé", "acai do ze"),
    ],
)
def test_normalize_merchant(raw, expected):
    assert normalize_merchant(raw) == expected
```
- [ ] **Step 3: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_transactions.py -v`
Expected: FAIL na coleta (`ModuleNotFoundError: No module named 'app.domain.transactions'`).

- [ ] **Step 4: Implementar models, regras e serviço**

`backend/app/domain/transactions/__init__.py`: arquivo vazio. Idem `backend/app/domain/accounts/__init__.py` já existe.

`backend/app/domain/transactions/models.py`:
```python
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
        Index("ix_transactions_space_date", "space_id", "occurred_on"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    type: Mapped[str] = mapped_column(String(16))  # expense | income | transfer
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(500), default="")
    merchant: Mapped[str | None] = mapped_column(String(200))
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    counter_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    # NULL = "Usuário removido"
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    origin: Mapped[str] = mapped_column(String(16), default="web")  # web | telegram | whatsapp_*
    source_message_id: Mapped[str | None] = mapped_column(String(128))
    attachment_id: Mapped[UUID | None] = mapped_column()  # tabela de anexos chega no M6
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/app/domain/accounts/access.py`:
```python
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.models import Account
from app.domain.spaces.access import is_member, require_member


async def use_account(session: AsyncSession, actor_id: UUID, account_id: UUID) -> Account:
    """Conta que o autor pode usar: precisa ser membro do espaço DONO da conta (spec 14.1)."""
    acc = await session.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    if not await is_member(session, actor_id, acc.space_id):
        raise HTTPException(status_code=403, detail="account_forbidden")
    return acc


async def visible_account(session: AsyncSession, viewer_id: UUID, account_id: UUID) -> Account:
    """Conta que o usuário pode ver (GET): não membro = 404, sem revelar existência."""
    acc = await session.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, acc.space_id)
    return acc
```

`backend/app/domain/accounts/service.py`:
```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.accounts.models import Account
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member

ACCOUNT_TYPES = {"checking", "wallet", "savings"}


async def create_account(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, name: str,
    initial_balance_cents: int = 0,
) -> Account:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if type not in ACCOUNT_TYPES:
        raise DomainError("invalid_account_type")
    acc = Account(
        space_id=space_id, type=type, name=name, initial_balance_cents=initial_balance_cents
    )
    session.add(acc)
    await session.commit()
    return acc


async def set_default_account(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, account_id: UUID
) -> None:
    member = await require_member(session, actor_id, space_id)
    await use_account(session, actor_id, account_id)  # pode ser conta de outro espaço seu
    member.default_account_id = account_id
    await session.commit()
```

`backend/app/domain/transactions/rules.py`:
```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.categories.models import Category
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction


async def check_common(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, amount_cents: int,
    category_id: UUID | None,
) -> None:  # fmt: skip
    """Valor > 0, autor membro do espaço, categoria do mesmo espaço e do tipo certo."""
    if amount_cents <= 0:
        raise DomainError("amount_must_be_positive")
    await require_member(session, actor_id, space_id)
    if category_id is not None:
        cat = await session.get(Category, category_id)
        wanted = "income" if type == "income" else "expense"
        if cat is None or cat.space_id != space_id or (type != "transfer" and cat.kind != wanted):
            raise DomainError("invalid_category")


def signed(tx: Transaction, account_id: UUID) -> int:
    """Efeito do lançamento no saldo da conta: receita +, despesa −, transferência −/+."""
    if tx.type == "transfer":
        if tx.account_id == account_id:
            return -tx.amount_cents
        return tx.amount_cents if tx.counter_account_id == account_id else 0
    if tx.account_id != account_id:
        return 0
    return tx.amount_cents if tx.type == "income" else -tx.amount_cents
```

`backend/app/domain/transactions/service.py`:
```python
import re
import unicodedata
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.accounts.models import Account
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common, signed

TYPES = {"expense", "income", "transfer"}
_STORE_NO = re.compile(r"\b(?:n[oº°]?|loja|filial|unid(?:ade)?)\.?\s*\d+\b")


def normalize_merchant(text: str) -> str:
    """minúsculas, sem acento, sem número de loja/dígitos/símbolos, espaços colapsados."""
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _STORE_NO.sub(" ", s)
    return " ".join(re.sub(r"[^a-z\s]", " ", s).split())


async def create_transaction(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, amount_cents: int,
    occurred_on: date, description: str = "", merchant: str | None = None,
    category_id: UUID | None = None, account_id: UUID | None = None,
    counter_account_id: UUID | None = None, origin: str = "web",
    source_message_id: str | None = None, attachment_id: UUID | None = None,
) -> Transaction:  # fmt: skip
    if type not in TYPES:
        raise DomainError("invalid_type")
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type=type, amount_cents=amount_cents,
        category_id=category_id,
    )  # fmt: skip
    if account_id is None:
        raise DomainError("account_required")
    await use_account(session, actor_id, account_id)
    if type == "transfer":
        if counter_account_id is None or counter_account_id == account_id:
            raise DomainError("invalid_transfer")
        await use_account(session, actor_id, counter_account_id)
    elif counter_account_id is not None:
        raise DomainError("invalid_transfer")
    tx = Transaction(
        space_id=space_id, type=type, amount_cents=amount_cents, occurred_on=occurred_on,
        description=description, merchant=merchant, category_id=category_id,
        account_id=account_id, counter_account_id=counter_account_id, created_by=actor_id,
        origin=origin, source_message_id=source_message_id, attachment_id=attachment_id,
    )  # fmt: skip
    session.add(tx)
    await session.commit()
    return tx


async def account_balance(session: AsyncSession, account_id: UUID) -> int:
    """saldo inicial + receitas − despesas à vista − transferências de saída + de entrada."""
    acc = await session.get(Account, account_id)
    if acc is None:
        raise DomainError("account_not_found")
    rows = await session.scalars(
        select(Transaction).where(
            or_(Transaction.account_id == account_id, Transaction.counter_account_id == account_id)
        )
    )
    # ponytail: soma em Python; usar SUM(CASE ...) no SQL se passar de ~10k lançamentos
    return acc.initial_balance_cents + sum(signed(t, account_id) for t in rows)


async def list_transactions(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, start: date | None = None,
    end: date | None = None, category_id: UUID | None = None, account_id: UUID | None = None,
    limit: int = 100, offset: int = 0,
) -> list[Transaction]:  # fmt: skip
    await require_member(session, viewer_id, space_id)
    q = select(Transaction).where(Transaction.space_id == space_id)
    if start is not None:
        q = q.where(Transaction.occurred_on >= start)
    if end is not None:
        q = q.where(Transaction.occurred_on <= end)
    if category_id is not None:
        q = q.where(Transaction.category_id == category_id)
    if account_id is not None:
        q = q.where(
            or_(Transaction.account_id == account_id, Transaction.counter_account_id == account_id)
        )
    q = q.order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
    return list(await session.scalars(q.limit(limit).offset(offset)))
```

- [ ] **Step 5: Migração (autogenerate) e validação em banco descartável**

```bash
cd ~/abby-cash/backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "transactions"
```
Abra o arquivo novo em `migrations/versions/` e confira: cria `transactions` com `ck_transactions_amount_positive`, `ix_transactions_space_date`, FKs para `spaces/categories/accounts/users` e nenhum `drop_*` inesperado. Depois:
```bash
bash scripts/migrate_check.sh
```
Expected: `upgrade` até a nova revisão e `alembic check` com `No new upgrade operations detected.`

- [ ] **Step 6: Rodar testes de domínio**

Run: `uv run pytest tests/domain/test_transactions.py tests/core/test_dates.py -v`
Expected: todos PASS.

- [ ] **Step 7: Testes de API falhando**

`backend/tests/api/test_accounts_transactions_api.py`:
```python
from tests.factories import auth, category_id, make_account, make_family, make_user


async def _personal(client, headers) -> str:
    spaces = (await client.get("/spaces", headers=headers)).json()
    return next(s["id"] for s in spaces if s["type"] == "personal")


async def test_create_account_in_space_and_list(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    sp = await _personal(client, h)
    r = await client.post(
        f"/spaces/{sp}/accounts",
        json={"type": "checking", "name": "Nubank", "initial_balance_cents": 10_000},
        headers=h,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["initial_balance_cents"] == 10_000 and isinstance(body["initial_balance_cents"], int)
    names = [x["name"] for x in (await client.get("/accounts", headers=h)).json()]
    assert names == ["Carteira", "Nubank"]
    bad = await client.post(f"/spaces/{sp}/accounts", json={"type": "pix", "name": "x"}, headers=h)
    assert bad.status_code == 422


async def test_family_space_gets_accounts_via_api(client, session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    r = await client.post(
        f"/spaces/{fam.id}/accounts", json={"type": "checking", "name": "Conjunta"},
        headers=auth(h),
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["space_id"] == str(fam.id)
    assert "Conjunta" in [x["name"] for x in (await client.get("/accounts", headers=auth(w))).json()]


async def test_transaction_roundtrip_amount_is_int_and_balance(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    sp = str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    cat = await category_id(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{sp}/transactions",
        json={"type": "expense", "amount_cents": 4_500, "occurred_on": "2026-11-10",
              "description": "feira", "category_id": str(cat), "account_id": str(acc.id)},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201
    assert r.json()["amount_cents"] == 4_500 and isinstance(r.json()["amount_cents"], int)
    listed = (await client.get(f"/spaces/{sp}/transactions?start=2026-11-01&end=2026-11-30",
                               headers=h)).json()  # fmt: skip
    assert [t["description"] for t in listed] == ["feira"]
    bal = (await client.get(f"/accounts/{acc.id}", headers=h)).json()
    assert bal["balance_cents"] == 95_500


async def test_amount_never_float_or_string(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    for bad in (45.5, "4500", 0, -1):
        r = await client.post(
            f"/spaces/{a.default_space_id}/transactions",
            json={"type": "expense", "amount_cents": bad, "account_id": str(acc.id)},
            headers=auth(a),
        )
        assert r.status_code == 422, bad


async def test_domain_error_is_422_with_code(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{a.default_space_id}/transactions",
        json={"type": "transfer", "amount_cents": 100, "account_id": str(acc.id)},
        headers=auth(a),
    )
    assert r.status_code == 422 and r.json() == {"detail": "invalid_transfer"}


async def test_default_occurred_on_is_user_local_today(client, session):
    from app.core.dates import local_today

    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{a.default_space_id}/transactions",
        json={"type": "income", "amount_cents": 100, "account_id": str(acc.id)},
        headers=auth(a),
    )
    assert r.json()["occurred_on"] == local_today(a.tz).isoformat()


async def test_shared_account_403_and_non_member_404_over_http(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    theirs = await make_account(session, a.default_space_id)
    mine = await make_account(session, b.default_space_id)
    hb = auth(b)
    r = await client.post(
        f"/spaces/{b.default_space_id}/transactions",
        json={"type": "expense", "amount_cents": 100, "account_id": str(theirs.id)}, headers=hb,
    )  # fmt: skip
    assert r.status_code == 403
    sp_a = a.default_space_id
    assert (await client.post(f"/spaces/{sp_a}/accounts", json={"type": "wallet", "name": "x"},
                              headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/accounts/{theirs.id}", headers=hb)).status_code == 404
    assert (await client.get(f"/spaces/{sp_a}/transactions", headers=hb)).status_code == 404
    assert (await client.post(
        f"/spaces/{sp_a}/transactions",
        json={"type": "expense", "amount_cents": 100, "account_id": str(mine.id)}, headers=hb,
    )).status_code == 404  # fmt: skip
    r = await client.put(
        f"/spaces/{sp_a}/default-account", json={"account_id": str(mine.id)}, headers=hb
    )
    assert r.status_code == 404
    assert (await client.get("/accounts")).status_code == 401


async def test_set_default_account(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, name="Itaú")
    r = await client.put(
        f"/spaces/{a.default_space_id}/default-account", json={"account_id": str(acc.id)},
        headers=auth(a),
    )  # fmt: skip
    assert r.status_code == 204
    from app.domain.spaces.access import require_member

    assert (await require_member(session, a.id, a.default_space_id)).default_account_id == acc.id
```

- [ ] **Step 8: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_accounts_transactions_api.py -v`
Expected: FAIL (404 nas rotas novas / `ImportError` de `app.api.accounts`).

- [ ] **Step 9: API**

`backend/app/api/schemas.py`:
```python
from typing import Annotated

from pydantic import Field

# int estrito: 45.5 e "4500" viram 422 (dinheiro nunca é float nem string)
Cents = Annotated[int, Field(strict=True, gt=0)]
SignedCents = Annotated[int, Field(strict=True)]
```

`backend/app/api/accounts.py`:
```python
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import SignedCents
from app.core.serialize import row
from app.domain.accounts.access import visible_account
from app.domain.accounts.models import Account
from app.domain.accounts.service import create_account, set_default_account
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.service import account_balance

router = APIRouter(tags=["accounts"])


class AccountIn(BaseModel):
    type: Literal["checking", "wallet", "savings"]
    name: str = Field(min_length=1, max_length=100)
    initial_balance_cents: SignedCents = 0


class DefaultAccountIn(BaseModel):
    account_id: UUID


@router.post("/spaces/{space_id}/accounts", status_code=201)
async def create(
    space_id: UUID, body: AccountIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    acc = await create_account(
        session, actor_id=user.id, space_id=space_id, type=body.type, name=body.name,
        initial_balance_cents=body.initial_balance_cents,
    )  # fmt: skip
    return row(acc)


@router.get("/accounts")
async def list_accounts(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    """Contas de todos os espaços de que o usuário é membro (inclui as compartilháveis)."""
    rows = await session.scalars(
        select(Account)
        .join(SpaceMember, SpaceMember.space_id == Account.space_id)
        .where(SpaceMember.user_id == user.id)
        .order_by(Account.name)
    )
    return [row(a) for a in rows]


@router.get("/accounts/{account_id}")
async def get_account(account_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    acc = await visible_account(session, user.id, account_id)
    return row(acc) | {"balance_cents": await account_balance(session, acc.id)}


@router.put("/spaces/{space_id}/default-account", status_code=204)
async def default_account(
    space_id: UUID, body: DefaultAccountIn, user: CurrentUser, session: Session
) -> None:
    await set_default_account(
        session, actor_id=user.id, space_id=space_id, account_id=body.account_id
    )
```

`backend/app/api/transactions.py`:
```python
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.transactions.service import create_transaction, list_transactions

router = APIRouter(tags=["transactions"])


class TransactionIn(BaseModel):
    type: Literal["expense", "income", "transfer"]
    amount_cents: Cents
    occurred_on: date | None = None  # padrão: hoje no fuso do usuário
    description: str = Field(default="", max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    category_id: UUID | None = None
    account_id: UUID
    counter_account_id: UUID | None = None


@router.post("/spaces/{space_id}/transactions", status_code=201)
async def create(
    space_id: UUID, body: TransactionIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await create_transaction(
        session, actor_id=user.id, space_id=space_id, type=body.type,
        amount_cents=body.amount_cents, occurred_on=body.occurred_on or local_today(user.tz),
        description=body.description, merchant=body.merchant, category_id=body.category_id,
        account_id=body.account_id, counter_account_id=body.counter_account_id, origin="web",
    )  # fmt: skip
    return row(tx)


@router.get("/spaces/{space_id}/transactions")
async def list_(
    space_id: UUID, user: CurrentUser, session: Session,
    start: date | None = None, end: date | None = None, category_id: UUID | None = None,
    account_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:  # fmt: skip
    txs = await list_transactions(
        session, viewer_id=user.id, space_id=space_id, start=start, end=end,
        category_id=category_id, account_id=account_id, limit=limit, offset=offset,
    )  # fmt: skip
    return [row(t) for t in txs]
```

`backend/app/main.py`: troque o bloco inicial (imports + criação do app + routers) por:
```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import accounts, auth, spaces, transactions
from app.core.db import engine
from app.core.redis import redis
from app.domain.errors import DomainError

app = FastAPI(title="Abby Cash")
app.include_router(auth.router)
app.include_router(spaces.router)
app.include_router(accounts.router)
app.include_router(transactions.router)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})
```
(o `/health` permanece abaixo, intacto).

- [ ] **Step 10: Rodar tudo, qualidade e commit**

Run: `uv run pytest -v` → todos PASS (M1 + M2 até aqui); depois:
```bash
uv run ruff format . && uv run ruff check --fix . && uv run mypy app
cd .. && git add -A && git commit -m "feat(transactions): add accounts API, transactions, balance and shared-account rule"
```

---

## Task 2 (T2.2): Visibilidade em contas compartilhadas

**Files:** Create `backend/app/domain/accounts/statement.py`, `backend/tests/domain/test_statement.py`. Modify `backend/app/api/accounts.py`, `backend/tests/api/test_accounts_transactions_api.py`. **Sem tabela nova: nenhuma migração** (rode `bash scripts/migrate_check.sh` mesmo assim; deve continuar limpo).

Regra (spec 14.1): quem é membro do espaço dono da conta vê o extrato. Itens cujo `transactions.space_id` é um espaço de que o **visualizador** também é membro aparecem um a um; os demais entram só em `private_total_cents` (ex.: "Outros lançamentos (privados) — R$ X"), para o total fechar sem revelar detalhes. Valores do extrato têm o **sinal da conta** (`signed`): saída negativa. A associação é consultada a cada chamada (sem cache): membro removido perde o acesso na hora.

- [ ] **Step 1: Testes falhando**

`backend/tests/domain/test_statement.py`:
```python
from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.accounts.statement import account_statement
from app.domain.spaces.service import remove_member
from app.domain.transactions.service import account_balance, create_transaction
from tests.factories import category_id, make_account, make_family, make_user

D = date(2026, 11, 10)
RANGE = (date(2026, 11, 1), date(2026, 11, 30))


async def _setup(session):
    """w e h na família; conta conjunta da família; w lança um item da família e um pessoal."""
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    acc = await make_account(session, fam.id, name="Conjunta", initial=50_000)
    shared = await create_transaction(
        session, actor_id=w.id, space_id=fam.id, type="expense", amount_cents=10_000,
        occurred_on=D, description="mercado", account_id=acc.id,
        category_id=await category_id(session, fam.id),
    )  # fmt: skip
    secret = await create_transaction(
        session, actor_id=w.id, space_id=w.default_space_id, type="expense", amount_cents=4_000,
        occurred_on=D, description="presente", account_id=acc.id,
        category_id=await category_id(session, w.default_space_id),
    )  # fmt: skip
    return w, h, fam, acc, shared, secret


async def test_private_items_aggregated_for_non_member_viewer(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    st = await account_statement(session, h.id, acc.id, *RANGE)
    assert [i.id for i in st.items] == [shared.id]  # só o item da família aparece
    assert st.items[0].amount_cents == -10_000
    assert st.private_total_cents == -4_000  # o pessoal da w vira agregado
    assert st.total_cents == -14_000  # o total fecha
    assert secret.id not in [i.id for i in st.items]
    assert await account_balance(session, acc.id) == 50_000 + st.total_cents


async def test_owner_sees_all_items(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    st = await account_statement(session, w.id, acc.id, *RANGE)
    assert {i.id for i in st.items} == {shared.id, secret.id}
    assert st.private_total_cents == 0 and st.total_cents == -14_000


async def test_statement_respects_period(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    st = await account_statement(session, w.id, acc.id, date(2026, 12, 1), date(2026, 12, 31))
    assert st.items == [] and st.private_total_cents == 0 and st.total_cents == 0


async def test_removed_member_loses_statement_access(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    await account_statement(session, h.id, acc.id, *RANGE)
    await remove_member(session, actor_id=w.id, space_id=fam.id, user_id=h.id)
    with pytest.raises(HTTPException) as e:
        await account_statement(session, h.id, acc.id, *RANGE)
    assert e.value.status_code == 404


async def test_statement_of_unrelated_account_is_404(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    other = await make_user(session, "z@x.com")
    with pytest.raises(HTTPException) as e:
        await account_statement(session, other.id, acc.id, *RANGE)
    assert e.value.status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_statement.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.domain.accounts.statement'`).

- [ ] **Step 3: Implementar**

`backend/app/domain/accounts/statement.py`:
```python
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import visible_account
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import signed


@dataclass(frozen=True)
class TransactionView:
    id: UUID
    space_id: UUID
    type: str
    amount_cents: int  # com o sinal da conta
    occurred_on: date
    description: str
    merchant: str | None
    category_id: UUID | None
    created_by: UUID | None


@dataclass(frozen=True)
class Statement:
    items: list[TransactionView]
    private_total_cents: int  # soma dos itens de espaços de que o visualizador NÃO é membro
    total_cents: int  # itens + privados


async def build_statement(
    session: AsyncSession, viewer_id: UUID, rows: Sequence[tuple[Transaction, int]]
) -> Statement:
    """Itens de espaços do visualizador viram itens; o resto é só somado."""
    mine = set(
        await session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == viewer_id))
    )
    items: list[TransactionView] = []
    private = 0
    for tx, amount in rows:
        if tx.space_id in mine:
            items.append(
                TransactionView(
                    tx.id, tx.space_id, tx.type, amount, tx.occurred_on, tx.description,
                    tx.merchant, tx.category_id, tx.created_by,
                )  # fmt: skip
            )
        else:
            private += amount
    return Statement(items, private, sum(i.amount_cents for i in items) + private)


async def account_statement(
    session: AsyncSession, viewer_id: UUID, account_id: UUID, start: date, end: date
) -> Statement:
    acc = await visible_account(session, viewer_id, account_id)  # 404 se não for membro do dono
    txs = await session.scalars(
        select(Transaction)
        .where(
            or_(Transaction.account_id == acc.id, Transaction.counter_account_id == acc.id),
            Transaction.occurred_on >= start,
            Transaction.occurred_on <= end,
        )
        .order_by(Transaction.occurred_on, Transaction.created_at)
    )
    return await build_statement(session, viewer_id, [(t, signed(t, acc.id)) for t in txs])
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/domain/test_statement.py -v` → 5 PASS. `bash scripts/migrate_check.sh` → limpo.

- [ ] **Step 5: Teste de API falhando**

Acrescente a `backend/tests/api/test_accounts_transactions_api.py`:
```python
async def test_statement_over_http_aggregates_private(client, session):
    from datetime import date

    from app.domain.transactions.service import create_transaction

    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    acc = await make_account(session, fam.id, name="Conjunta")
    for space, amount, desc in ((fam.id, 10_000, "mercado"), (w.default_space_id, 4_000, "segredo")):
        await create_transaction(
            session, actor_id=w.id, space_id=space, type="expense", amount_cents=amount,
            occurred_on=date(2026, 11, 10), description=desc, account_id=acc.id,
        )  # fmt: skip
    url = f"/accounts/{acc.id}/statement?start=2026-11-01&end=2026-11-30"
    r = await client.get(url, headers=auth(h))
    assert r.status_code == 200
    body = r.json()
    assert [i["description"] for i in body["items"]] == ["mercado"]
    assert body["private_total_cents"] == -4_000 and body["total_cents"] == -14_000
    assert "segredo" not in r.text
    full = (await client.get(url, headers=auth(w))).json()
    assert len(full["items"]) == 2 and full["private_total_cents"] == 0
    stranger = await make_user(session, "z@x.com")
    assert (await client.get(url, headers=auth(stranger))).status_code == 404
```

- [ ] **Step 6: Rodar e ver falhar; implementar a rota**

Run: `uv run pytest tests/api/test_accounts_transactions_api.py::test_statement_over_http_aggregates_private -v` → FAIL (404 na rota).

Em `backend/app/api/accounts.py` acrescente aos imports `from dataclasses import asdict` e `from datetime import date` (antes de `from typing ...`), `from app.domain.accounts.statement import account_statement` (junto dos imports `app.domain.accounts...`), e ao final do arquivo:
```python
@router.get("/accounts/{account_id}/statement")
async def statement(
    account_id: UUID, start: date, end: date, user: CurrentUser, session: Session
) -> dict[str, Any]:
    return asdict(await account_statement(session, user.id, account_id, start, end))
```

- [ ] **Step 7: Rodar tudo e commitar**

Run: `uv run pytest -v` → PASS; `uv run ruff format . && uv run ruff check --fix . && uv run mypy app`
```bash
cd .. && git add -A && git commit -m "feat(accounts): add shared-account statement with private aggregation"
```

---

## Task 3 (T2.3): Cartões, faturas e parcelas

**Files:** Create `backend/app/domain/cards/{__init__,models,billing,service}.py`, `backend/app/domain/bills/{__init__,models,status}.py`, `backend/app/api/cards.py`, `backend/tests/domain/test_cards.py`, `backend/tests/api/test_cards_api.py`. Modify `backend/app/domain/transactions/{models,service}.py`, `backend/app/domain/models.py`, `backend/app/main.py`, `backend/tests/factories.py`.

Regras (plano mestre T2.3): compra com data **local** `≤` fechamento do mês cai na fatura que fecha neste mês; **após**, na seguinte. Vencimento = primeiro `due_day` **depois** do fechamento. Dias inexistentes usam `clamp_day`. Parcela `i` cai na `i`-ésima fatura depois da primeira (cada mês com o fechamento recalculado, então dia 31 vira 28/29/30 conforme o mês). Cada fatura tem uma `Bill` espelho (`kind="invoice"`, mesmo espaço do cartão) cujo valor acompanha `invoice_total`.

- [ ] **Step 1: Testes de domínio falhando**

Acrescente ao final de `backend/tests/factories.py` (e `from app.domain.cards.service import create_card` junto dos imports):
```python
async def make_card(
    session, actor: User, space_id: UUID, *, name: str = "Visa", closing_day: int = 10,
    due_day: int = 20, limit_cents: int | None = None, payment_account_id: UUID | None = None,
):  # fmt: skip
    return await create_card(
        session, actor_id=actor.id, space_id=space_id, name=name, closing_day=closing_day,
        due_day=due_day, limit_cents=limit_cents, payment_account_id=payment_account_id,
    )  # fmt: skip
```

`backend/tests/domain/test_cards.py`:
```python
from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.dates import to_local_date
from app.domain.bills.models import Bill
from app.domain.cards.billing import InvoiceDates, invoice_dates_for_purchase, split_installments
from app.domain.cards.models import Invoice
from app.domain.cards.service import (
    invoice_statement,
    invoice_total,
    register_card_purchase,
    use_card,
    visible_invoice,
)
from app.domain.errors import DomainError
from app.domain.spaces.service import remove_member
from app.domain.transactions.service import create_transaction
from tests.factories import make_account, make_card, make_family, make_user


def _inv(closing, due):
    return InvoiceDates(closing, due)


# ---- datas de fechamento (puras) ----
def test_purchase_on_closing_day_goes_to_current_invoice():
    expected = _inv(date(2026, 3, 10), date(2026, 3, 20))
    assert invoice_dates_for_purchase(10, 20, date(2026, 3, 10)) == expected
    assert invoice_dates_for_purchase(10, 20, date(2026, 3, 1)) == expected


def test_purchase_after_closing_goes_to_next():
    assert invoice_dates_for_purchase(10, 20, date(2026, 3, 11)) == _inv(
        date(2026, 4, 10), date(2026, 4, 20)
    )
    # vencimento "antes" do fechamento no calendário: 1º due_day depois do fechamento
    assert invoice_dates_for_purchase(25, 5, date(2026, 12, 26)) == _inv(
        date(2027, 1, 25), date(2027, 2, 5)
    )
    assert invoice_dates_for_purchase(25, 5, date(2026, 12, 25)) == _inv(
        date(2026, 12, 25), date(2027, 1, 5)
    )


def test_closing_day_31_in_february():
    assert invoice_dates_for_purchase(31, 10, date(2026, 2, 28)) == _inv(
        date(2026, 2, 28), date(2026, 3, 10)
    )  # fevereiro fecha no dia 28 (último dia do mês)
    assert invoice_dates_for_purchase(31, 10, date(2026, 3, 1)) == _inv(
        date(2026, 3, 31), date(2026, 4, 10)
    )
    assert invoice_dates_for_purchase(31, 10, date(2028, 2, 29)) == _inv(
        date(2028, 2, 29), date(2028, 3, 10)
    )  # ano bissexto


def test_closing_day_31_in_april():
    assert invoice_dates_for_purchase(31, 10, date(2026, 4, 30)) == _inv(
        date(2026, 4, 30), date(2026, 5, 10)
    )
    assert invoice_dates_for_purchase(31, 10, date(2026, 5, 1)) == _inv(
        date(2026, 5, 31), date(2026, 6, 10)
    )


def test_due_day_31_is_clamped_to_month_end():
    assert invoice_dates_for_purchase(10, 31, date(2026, 2, 5)) == _inv(
        date(2026, 2, 10), date(2026, 2, 28)
    )


def test_purchase_2330_local_uses_local_date():
    instant = datetime(2026, 3, 11, 2, 30, tzinfo=UTC)  # 23:30 de 10/03 em São Paulo
    local = to_local_date(instant, "America/Sao_Paulo")
    assert invoice_dates_for_purchase(10, 20, local).closing == date(2026, 3, 10)
    # usar o dia UTC jogaria a compra na fatura seguinte (o bug que o teste previne)
    assert invoice_dates_for_purchase(10, 20, instant.date()).closing == date(2026, 4, 10)


def test_split_600_in_3():
    assert split_installments(600, 3) == [200, 200, 200]


def test_split_1000_in_3():
    assert split_installments(1000, 3) == [334, 333, 333]


def test_split_edge_cases():
    assert split_installments(999, 1) == [999]
    with pytest.raises(DomainError, match="invalid_installments"):
        split_installments(1000, 0)
    with pytest.raises(DomainError, match="amount_too_small"):
        split_installments(2, 3)


# ---- faturas e parcelas (banco) ----
async def _buy(session, user, card, amount, on, *, n=1, space=None, desc="compra"):
    return await register_card_purchase(
        session, actor_id=user.id, space_id=space or user.default_space_id, card_id=card.id,
        amount_cents=amount, occurred_on=on, installments=n, description=desc,
    )  # fmt: skip


async def _invoices(session, txs):
    return [await session.get(Invoice, t.invoice_id) for t in txs]


async def test_installments_land_on_consecutive_invoices(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)  # fecha 10, vence 20
    txs = await _buy(session, a, card, 30_000, date(2026, 11, 5), n=3)
    invs = await _invoices(session, txs)
    assert [(i.closing_on, i.due_on) for i in invs] == [
        (date(2026, 11, 10), date(2026, 11, 20)),
        (date(2026, 12, 10), date(2026, 12, 20)),
        (date(2027, 1, 10), date(2027, 1, 20)),
    ]
    assert [t.amount_cents for t in txs] == [10_000] * 3
    assert [(t.installment_number, t.installment_total) for t in txs] == [(1, 3), (2, 3), (3, 3)]
    assert len({t.installment_group_id for t in txs}) == 1 and txs[0].installment_group_id
    assert all(
        t.card_id == card.id and t.account_id is None and t.type == "expense"
        and t.occurred_on == date(2026, 11, 5)
        for t in txs
    )  # fmt: skip


async def test_installment_remainder_goes_to_first(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    txs = await _buy(session, a, card, 1_000, date(2026, 11, 5), n=3)
    assert [t.amount_cents for t in txs] == [334, 333, 333]


async def test_installments_with_closing_day_31_clamp_each_month(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, closing_day=31, due_day=10)
    txs = await _buy(session, a, card, 30_000, date(2026, 1, 31), n=3)
    invs = await _invoices(session, txs)
    assert [(i.closing_on, i.due_on) for i in invs] == [
        (date(2026, 1, 31), date(2026, 2, 10)),
        (date(2026, 2, 28), date(2026, 3, 10)),
        (date(2026, 3, 31), date(2026, 4, 10)),
    ]


async def test_single_purchase_has_no_installment_fields(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    (tx,) = await _buy(session, a, card, 5_000, date(2026, 11, 5))
    assert tx.installment_group_id is None and tx.installment_number is None


async def test_invoice_has_mirror_bill_that_tracks_total(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    t1 = (await _buy(session, a, card, 10_000, date(2026, 11, 1)))[0]
    t2 = (await _buy(session, a, card, 5_000, date(2026, 11, 9)))[0]
    assert t1.invoice_id == t2.invoice_id
    assert await invoice_total(session, t1.invoice_id) == 15_000
    bills = (await session.scalars(select(Bill))).all()
    assert len(bills) == 1
    bill = bills[0]
    assert (bill.kind, bill.amount_cents, bill.due_on, bill.status) == (
        "invoice", 15_000, date(2026, 11, 20), "open",
    )  # fmt: skip
    assert bill.space_id == card.space_id and bill.invoice_id == t1.invoice_id


async def test_invalid_installments_and_amounts(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    for n in (0, 49):
        with pytest.raises(DomainError, match="invalid_installments"):
            await _buy(session, a, card, 1_000, date(2026, 11, 5), n=n)
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await _buy(session, a, card, 0, date(2026, 11, 5))
    with pytest.raises(DomainError, match="amount_too_small"):
        await _buy(session, a, card, 2, date(2026, 11, 5), n=3)
    assert (await session.scalars(select(Invoice))).all() == []  # nada pela metade


async def test_card_of_foreign_space_is_403(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    with pytest.raises(HTTPException) as e:
        await _buy(session, b, card, 1_000, date(2026, 11, 5))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await use_card(session, b.id, card.id)
    assert e.value.status_code == 403


async def test_create_transaction_with_card_id_registers_purchase(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    tx = await create_transaction(
        session, actor_id=a.id, space_id=a.default_space_id, type="expense", amount_cents=2_500,
        occurred_on=date(2026, 11, 5), card_id=card.id,
    )  # fmt: skip
    assert tx.invoice_id is not None and tx.card_id == card.id
    with pytest.raises(DomainError, match="invalid_card_purchase"):
        await create_transaction(
            session, actor_id=a.id, space_id=a.default_space_id, type="income",
            amount_cents=2_500, occurred_on=date(2026, 11, 5), card_id=card.id,
        )  # fmt: skip


async def test_shared_card_statement_aggregates_private_items(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id, name="Cartão da família")
    await _buy(session, w, card, 10_000, date(2026, 11, 2), space=fam.id, desc="mercado")
    (secret,) = await _buy(session, w, card, 4_000, date(2026, 11, 3), desc="presente")  # #pessoal
    inv_id = secret.invoice_id
    st_h = await invoice_statement(session, h.id, inv_id)
    assert [i.description for i in st_h.items] == ["mercado"]
    assert st_h.private_total_cents == 4_000
    assert st_h.total_cents == 14_000 == await invoice_total(session, inv_id)  # total fecha
    st_w = await invoice_statement(session, w.id, inv_id)
    assert sorted(i.description for i in st_w.items) == ["mercado", "presente"]
    assert st_w.private_total_cents == 0 and st_w.total_cents == 14_000


async def test_removed_member_loses_card_and_invoice_access(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id)
    (tx,) = await _buy(session, h, card, 3_000, date(2026, 11, 2), space=fam.id)
    await visible_invoice(session, h.id, tx.invoice_id)
    await remove_member(session, actor_id=w.id, space_id=fam.id, user_id=h.id)
    with pytest.raises(HTTPException) as e:
        await visible_invoice(session, h.id, tx.invoice_id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await _buy(session, h, card, 1_000, date(2026, 11, 3))
    assert e.value.status_code == 403
    st_w = await invoice_statement(session, w.id, tx.invoice_id)
    assert [i.amount_cents for i in st_w.items] == [3_000]  # o histórico (espaço família) fica
```


- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_cards.py -v`
Expected: FAIL na coleta (`ModuleNotFoundError: No module named 'app.domain.cards'`).

- [ ] **Step 3: Models (cartão, fatura, conta a pagar) e colunas novas do lançamento**

`backend/app/domain/cards/__init__.py` e `backend/app/domain/bills/__init__.py`: arquivos vazios.

`backend/app/domain/cards/models.py`:
```python
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCard(Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        CheckConstraint(
            "closing_day BETWEEN 1 AND 31 AND due_day BETWEEN 1 AND 31", name="ck_credit_cards_days"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    closing_day: Mapped[int] = mapped_column(Integer)
    due_day: Mapped[int] = mapped_column(Integer)
    limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    payment_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("card_id", "closing_on", name="uq_invoices_card_closing"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    card_id: Mapped[UUID] = mapped_column(ForeignKey("credit_cards.id"))
    closing_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date, index=True)
```
`backend/app/domain/bills/models.py`:
```python
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (CheckConstraint("amount_cents >= 0", name="ck_bills_amount_nonneg"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # manual | invoice
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    due_on: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"))
    responsible_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | paid | partial
    recurrence_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/app/domain/bills/status.py` (usado pela fatura agora e pelos pagamentos no T2.4):
```python
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bills.models import Bill
from app.domain.transactions.models import Transaction


async def bill_paid_cents(session: AsyncSession, bill_id: UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.bill_id == bill_id
        )
    )
    return int(total or 0)


async def refresh_status(session: AsyncSession, bill: Bill) -> None:
    paid = await bill_paid_cents(session, bill.id)
    bill.status = "open" if paid <= 0 else "paid" if paid >= bill.amount_cents else "partial"
```

Em `backend/app/domain/transactions/models.py`: troque o import de `sqlalchemy` por
```python
from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, func,
)
```
e acrescente, logo depois de `counter_account_id`, as colunas:
```python
    card_id: Mapped[UUID | None] = mapped_column(ForeignKey("credit_cards.id"), index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    bill_id: Mapped[UUID | None] = mapped_column(ForeignKey("bills.id"), index=True)
    installment_group_id: Mapped[UUID | None] = mapped_column(index=True)
    installment_number: Mapped[int | None] = mapped_column(Integer)
    installment_total: Mapped[int | None] = mapped_column(Integer)
```

Em `backend/app/domain/models.py` acrescente (a ordem alfabética é aplicada pelo `ruff --fix`):
```python
import app.domain.bills.models  # noqa: F401
import app.domain.cards.models  # noqa: F401
```

- [ ] **Step 4: Regras de fatura e serviço de cartões**

`backend/app/domain/cards/billing.py`:
```python
from dataclasses import dataclass
from datetime import date

from app.core.dates import add_months, clamp_day
from app.domain.errors import DomainError


@dataclass(frozen=True)
class InvoiceDates:
    closing: date
    due: date


def invoice_dates_for_month(closing_day: int, due_day: int, year: int, month: int) -> InvoiceDates:
    """Fatura que FECHA em (year, month). Vencimento = primeiro `due_day` depois do fechamento."""
    closing = clamp_day(year, month, closing_day)
    due = clamp_day(year, month, due_day)
    if due <= closing:
        nxt = add_months(date(year, month, 1), 1)
        due = clamp_day(nxt.year, nxt.month, due_day)
    return InvoiceDates(closing, due)


def invoice_dates_for_purchase(closing_day: int, due_day: int, purchase_date: date) -> InvoiceDates:
    """`purchase_date` = dia LOCAL do usuário. <= fechamento: esta fatura; senão, a seguinte."""
    this = invoice_dates_for_month(closing_day, due_day, purchase_date.year, purchase_date.month)
    if purchase_date <= this.closing:
        return this
    nxt = add_months(date(purchase_date.year, purchase_date.month, 1), 1)
    return invoice_dates_for_month(closing_day, due_day, nxt.year, nxt.month)


def split_installments(total_cents: int, n: int) -> list[int]:
    """O resto dos centavos vai na 1ª parcela: 1000/3 -> [334, 333, 333]."""
    if n < 1:
        raise DomainError("invalid_installments")
    if total_cents < n:
        raise DomainError("amount_too_small")
    base, rest = divmod(total_cents, n)
    return [base + rest] + [base] * (n - 1)
```

`backend/app/domain/cards/service.py`:
```python
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.accounts.access import use_account
from app.domain.accounts.statement import Statement, build_statement
from app.domain.bills.models import Bill
from app.domain.bills.status import refresh_status
from app.domain.cards.billing import (
    InvoiceDates,
    invoice_dates_for_month,
    invoice_dates_for_purchase,
    split_installments,
)
from app.domain.cards.models import CreditCard, Invoice
from app.domain.errors import DomainError
from app.domain.spaces.access import is_member, require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common

MAX_INSTALLMENTS = 48


async def create_card(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, name: str, closing_day: int,
    due_day: int, limit_cents: int | None = None, payment_account_id: UUID | None = None,
) -> CreditCard:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if not (1 <= closing_day <= 31 and 1 <= due_day <= 31):
        raise DomainError("invalid_day")
    if limit_cents is not None and limit_cents <= 0:
        raise DomainError("amount_must_be_positive")
    if payment_account_id is not None:
        await use_account(session, actor_id, payment_account_id)
    card = CreditCard(
        space_id=space_id, name=name, closing_day=closing_day, due_day=due_day,
        limit_cents=limit_cents, payment_account_id=payment_account_id,
    )  # fmt: skip
    session.add(card)
    await session.commit()
    return card


async def use_card(session: AsyncSession, actor_id: UUID, card_id: UUID) -> CreditCard:
    """Cartão que o autor pode usar: membro do espaço dono do cartão (spec 14.1), senão 403."""
    card = await session.get(CreditCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card_not_found")
    if not await is_member(session, actor_id, card.space_id):
        raise HTTPException(status_code=403, detail="card_forbidden")
    return card


async def visible_card(session: AsyncSession, viewer_id: UUID, card_id: UUID) -> CreditCard:
    card = await session.get(CreditCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, card.space_id)
    return card


async def visible_invoice(
    session: AsyncSession, viewer_id: UUID, invoice_id: UUID
) -> tuple[Invoice, CreditCard]:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="not_found")
    card = await visible_card(session, viewer_id, inv.card_id)
    return inv, card


async def invoice_total(session: AsyncSession, invoice_id: UUID) -> int:
    """Soma das compras da fatura (inclui as de espaços privados para quem vê)."""
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.invoice_id == invoice_id, Transaction.type == "expense"
        )
    )
    return int(total or 0)


async def invoice_paid(session: AsyncSession, invoice_id: UUID) -> int:
    paid = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.invoice_id == invoice_id, Transaction.type == "transfer"
        )
    )
    return int(paid or 0)


async def invoice_remaining(session: AsyncSession, invoice_id: UUID) -> int:
    return await invoice_total(session, invoice_id) - await invoice_paid(session, invoice_id)


async def invoice_summary(session: AsyncSession, invoice: Invoice) -> dict[str, Any]:
    total = await invoice_total(session, invoice.id)
    paid = await invoice_paid(session, invoice.id)
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == invoice.id))
    return {
        "total_cents": total, "paid_cents": paid, "remaining_cents": total - paid,
        "status": bill.status if bill else "open",
    }  # fmt: skip


async def get_or_create_invoice(
    session: AsyncSession, card: CreditCard, dates: InvoiceDates
) -> Invoice:
    inv = await session.scalar(
        select(Invoice).where(Invoice.card_id == card.id, Invoice.closing_on == dates.closing)
    )
    if inv is None:
        # ponytail: sem lock; a restrição única (card_id, closing_on) barra a corrida
        inv = Invoice(card_id=card.id, closing_on=dates.closing, due_on=dates.due)
        session.add(inv)
        await session.flush()
        session.add(
            Bill(
                space_id=card.space_id, kind="invoice", amount_cents=0, due_on=dates.due,
                description=f"Fatura {card.name} {dates.closing:%m/%Y}", invoice_id=inv.id,
            )  # fmt: skip
        )
    return inv


async def sync_invoice_bill(session: AsyncSession, invoice: Invoice) -> None:
    """Mantém a conta espelho = total da fatura (chamar após gravar/alterar compras)."""
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == invoice.id))
    assert bill is not None
    bill.amount_cents = await invoice_total(session, invoice.id)
    bill.due_on = invoice.due_on
    await refresh_status(session, bill)


async def register_card_purchase(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, card_id: UUID, amount_cents: int,
    occurred_on: date, installments: int = 1, description: str = "", merchant: str | None = None,
    category_id: UUID | None = None, origin: str = "web", source_message_id: str | None = None,
    attachment_id: UUID | None = None,
) -> list[Transaction]:  # fmt: skip
    """`occurred_on` é o dia local do usuário. Cada parcela vai para a sua fatura."""
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=amount_cents,
        category_id=category_id,
    )  # fmt: skip
    if not 1 <= installments <= MAX_INSTALLMENTS:
        raise DomainError("invalid_installments")
    card = await use_card(session, actor_id, card_id)
    parts = split_installments(amount_cents, installments)
    first = invoice_dates_for_purchase(card.closing_day, card.due_day, occurred_on)
    group = uuid4() if installments > 1 else None
    txs: list[Transaction] = []
    invoices: dict[UUID, Invoice] = {}
    for i, part in enumerate(parts):
        month = add_months(first.closing.replace(day=1), i)
        dates = invoice_dates_for_month(card.closing_day, card.due_day, month.year, month.month)
        inv = await get_or_create_invoice(session, card, dates)
        invoices[inv.id] = inv
        tx = Transaction(
            space_id=space_id, type="expense", amount_cents=part, occurred_on=occurred_on,
            description=description, merchant=merchant, category_id=category_id,
            card_id=card.id, invoice_id=inv.id, installment_group_id=group,
            installment_number=i + 1 if group else None,
            installment_total=installments if group else None,
            created_by=actor_id, origin=origin, source_message_id=source_message_id,
            attachment_id=attachment_id,
        )  # fmt: skip
        session.add(tx)
        txs.append(tx)
    await session.flush()
    for inv in invoices.values():
        await sync_invoice_bill(session, inv)
    await session.commit()
    return txs


async def invoice_statement(session: AsyncSession, viewer_id: UUID, invoice_id: UUID) -> Statement:
    """Compras da fatura; as de espaços de que o visualizador não é membro viram agregado."""
    inv, _ = await visible_invoice(session, viewer_id, invoice_id)
    txs = await session.scalars(
        select(Transaction)
        .where(Transaction.invoice_id == inv.id, Transaction.type == "expense")
        .order_by(Transaction.occurred_on, Transaction.created_at)
    )
    return await build_statement(session, viewer_id, [(t, t.amount_cents) for t in txs])
```
Em `backend/app/domain/transactions/service.py`, acrescente o parâmetro `card_id` e a delegação. Troque
```python
    counter_account_id: UUID | None = None, origin: str = "web",
    source_message_id: str | None = None, attachment_id: UUID | None = None,
) -> Transaction:  # fmt: skip
    if type not in TYPES:
        raise DomainError("invalid_type")
```
por
```python
    counter_account_id: UUID | None = None, card_id: UUID | None = None, origin: str = "web",
    source_message_id: str | None = None, attachment_id: UUID | None = None,
) -> Transaction:  # fmt: skip
    if type not in TYPES:
        raise DomainError("invalid_type")
    if card_id is not None:  # compra no cartão: fatura e parcelas ficam no serviço de cartões
        if type != "expense" or account_id is not None or counter_account_id is not None:
            raise DomainError("invalid_card_purchase")
        from app.domain.cards.service import register_card_purchase  # evita import circular

        purchase = await register_card_purchase(
            session, actor_id=actor_id, space_id=space_id, card_id=card_id,
            amount_cents=amount_cents, occurred_on=occurred_on, description=description,
            merchant=merchant, category_id=category_id, origin=origin,
            source_message_id=source_message_id, attachment_id=attachment_id,
        )  # fmt: skip
        return purchase[0]
```

- [ ] **Step 5: Migração (autogenerate) e validação em banco descartável**

```bash
cd ~/abby-cash/backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "cards, invoices, bills and transaction links"
```
Confira no arquivo gerado: `create_table` de `credit_cards`, `invoices` (com `uq_invoices_card_closing`) e `bills` (com `ck_bills_amount_nonneg`, `JSONB`, unique em `invoice_id`), e `add_column` + FKs em `transactions` (`card_id, invoice_id, bill_id, installment_*`). Depois:
```bash
bash scripts/migrate_check.sh
```
Expected: `No new upgrade operations detected.`

- [ ] **Step 6: Rodar testes de domínio**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run pytest tests/domain -v`
Expected: todos PASS (incluindo T2.1 e T2.2).

- [ ] **Step 7: Testes de API falhando**

`backend/tests/api/test_cards_api.py`:
```python
from datetime import UTC, datetime

from app.core.dates import to_local_date
from tests.factories import auth, make_card, make_family, make_user


async def _new_card(client, headers, space, **kw):
    body = {"name": "Visa", "closing_day": 10, "due_day": 20} | kw
    r = await client.post(f"/spaces/{space}/cards", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_card_purchase_installments_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    card = await _new_card(client, h, sp, limit_cents=500_000)
    assert card["limit_cents"] == 500_000
    r = await client.post(
        f"/spaces/{sp}/card-purchases",
        json={"card_id": card["id"], "amount_cents": 1_000, "installments": 3,
              "occurred_on": "2026-11-05", "description": "tv"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201
    txs = r.json()
    assert [t["amount_cents"] for t in txs] == [334, 333, 333]
    assert all(isinstance(t["amount_cents"], int) for t in txs)
    invs = (await client.get(f"/cards/{card['id']}/invoices", headers=h)).json()
    assert [i["due_on"] for i in invs] == ["2027-01-20", "2026-12-20", "2026-11-20"]
    assert [i["total_cents"] for i in invs] == [333, 333, 334]
    detail = (await client.get(f"/invoices/{txs[0]['invoice_id']}", headers=h)).json()
    assert detail["total_cents"] == 334 and detail["paid_cents"] == 0
    assert detail["remaining_cents"] == 334 and detail["status"] == "open"
    assert [i["amount_cents"] for i in detail["statement"]["items"]] == [334]
    assert detail["statement"]["private_total_cents"] == 0
    assert [c["id"] for c in (await client.get("/cards", headers=h)).json()] == [card["id"]]


async def test_card_and_purchase_validation_422(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    for bad in ({"closing_day": 0}, {"closing_day": 32}, {"due_day": "10"}, {"limit_cents": 9.5}):
        r = await client.post(
            f"/spaces/{sp}/cards", json={"name": "V", "closing_day": 10, "due_day": 20} | bad,
            headers=h,
        )  # fmt: skip
        assert r.status_code == 422, bad
    card = await _new_card(client, h, sp)
    base = {"card_id": card["id"], "amount_cents": 1_000, "occurred_on": "2026-11-05"}
    for bad in ({"installments": 0}, {"installments": 49}, {"amount_cents": 10.5}):
        r = await client.post(f"/spaces/{sp}/card-purchases", json=base | bad, headers=h)
        assert r.status_code == 422, bad
    r = await client.post(
        f"/spaces/{sp}/card-purchases", json=base | {"amount_cents": 2, "installments": 3},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 422 and r.json() == {"detail": "amount_too_small"}


async def test_purchase_without_date_uses_user_local_date(client, session, monkeypatch):
    # 02:30 UTC de 11/03 = 23:30 de 10/03 em São Paulo (dia do fechamento)
    instant = datetime(2026, 3, 11, 2, 30, tzinfo=UTC)
    monkeypatch.setattr("app.api.cards.local_today", lambda tz: to_local_date(instant, tz))
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    card = await _new_card(client, h, sp)
    r = await client.post(
        f"/spaces/{sp}/card-purchases", json={"card_id": card["id"], "amount_cents": 1_000},
        headers=h,
    )  # fmt: skip
    tx = r.json()[0]
    assert tx["occurred_on"] == "2026-03-10"
    inv = (await client.get(f"/invoices/{tx['invoice_id']}", headers=h)).json()
    assert inv["closing_on"] == "2026-03-10" and inv["due_on"] == "2026-03-20"


async def test_cards_routes_404_for_non_member_and_403_for_foreign_card(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    ha, hb = auth(a), auth(b)
    sp_a = str(a.default_space_id)
    r = await client.post(
        f"/spaces/{sp_a}/card-purchases",
        json={"card_id": str(card.id), "amount_cents": 1_000, "occurred_on": "2026-11-05"},
        headers=ha,
    )  # fmt: skip
    inv_id = r.json()[0]["invoice_id"]
    assert (await client.post(f"/spaces/{sp_a}/cards", json={"name": "V", "closing_day": 1,
                              "due_day": 2}, headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/cards/{card.id}/invoices", headers=hb)).status_code == 404
    assert (await client.get(f"/invoices/{inv_id}", headers=hb)).status_code == 404
    assert (await client.get("/cards", headers=hb)).json() == []
    r = await client.post(
        f"/spaces/{b.default_space_id}/card-purchases",
        json={"card_id": str(card.id), "amount_cents": 1_000, "occurred_on": "2026-11-05"},
        headers=hb,
    )  # fmt: skip
    assert r.status_code == 403
    assert (await client.get("/cards")).status_code == 401


async def test_shared_invoice_hides_private_items_over_http(client, session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id)
    body = {"card_id": str(card.id), "occurred_on": "2026-11-05"}
    await client.post(f"/spaces/{fam.id}/card-purchases",
                      json=body | {"amount_cents": 10_000, "description": "mercado"},
                      headers=auth(w))  # fmt: skip
    r = await client.post(f"/spaces/{w.default_space_id}/card-purchases",
                          json=body | {"amount_cents": 4_000, "description": "segredo"},
                          headers=auth(w))  # fmt: skip
    inv_id = r.json()[0]["invoice_id"]
    seen = await client.get(f"/invoices/{inv_id}", headers=auth(h))
    assert "segredo" not in seen.text
    st = seen.json()["statement"]
    assert [i["description"] for i in st["items"]] == ["mercado"]
    assert st["private_total_cents"] == 4_000 and st["total_cents"] == 14_000
    assert seen.json()["total_cents"] == 14_000
```

- [ ] **Step 8: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_cards_api.py -v`
Expected: FAIL (404 nas rotas novas).

- [ ] **Step 9: API de cartões**

`backend/app/api/cards.py`:
```python
from dataclasses import asdict
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.cards.models import CreditCard, Invoice
from app.domain.cards.service import (
    create_card,
    invoice_statement,
    invoice_summary,
    register_card_purchase,
    visible_card,
    visible_invoice,
)
from app.domain.spaces.models import SpaceMember

router = APIRouter(tags=["cards"])
Day = Annotated[int, Field(strict=True, ge=1, le=31)]


class CardIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    closing_day: Day
    due_day: Day
    limit_cents: Cents | None = None
    payment_account_id: UUID | None = None


class PurchaseIn(BaseModel):
    card_id: UUID
    amount_cents: Cents
    installments: Annotated[int, Field(strict=True, ge=1, le=48)] = 1
    occurred_on: date | None = None  # padrão: hoje no fuso do usuário
    description: str = Field(default="", max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    category_id: UUID | None = None


@router.post("/spaces/{space_id}/cards", status_code=201)
async def create(
    space_id: UUID, body: CardIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    card = await create_card(
        session, actor_id=user.id, space_id=space_id, name=body.name,
        closing_day=body.closing_day, due_day=body.due_day, limit_cents=body.limit_cents,
        payment_account_id=body.payment_account_id,
    )  # fmt: skip
    return row(card)


@router.get("/cards")
async def list_cards(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(CreditCard)
        .join(SpaceMember, SpaceMember.space_id == CreditCard.space_id)
        .where(SpaceMember.user_id == user.id)
        .order_by(CreditCard.name)
    )
    return [row(c) for c in rows]


@router.post("/spaces/{space_id}/card-purchases", status_code=201)
async def purchase(
    space_id: UUID, body: PurchaseIn, user: CurrentUser, session: Session
) -> list[dict[str, Any]]:
    txs = await register_card_purchase(
        session, actor_id=user.id, space_id=space_id, card_id=body.card_id,
        amount_cents=body.amount_cents, occurred_on=body.occurred_on or local_today(user.tz),
        installments=body.installments, description=body.description, merchant=body.merchant,
        category_id=body.category_id, origin="web",
    )  # fmt: skip
    return [row(t) for t in txs]


@router.get("/cards/{card_id}/invoices")
async def list_invoices(
    card_id: UUID, user: CurrentUser, session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> list[dict[str, Any]]:  # fmt: skip
    card = await visible_card(session, user.id, card_id)
    invs = await session.scalars(
        select(Invoice).where(Invoice.card_id == card.id).order_by(Invoice.closing_on.desc()).limit(limit)
    )
    return [row(i) | await invoice_summary(session, i) for i in invs]


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    inv, _ = await visible_invoice(session, user.id, invoice_id)
    stmt = await invoice_statement(session, user.id, invoice_id)
    return row(inv) | await invoice_summary(session, inv) | {"statement": asdict(stmt)}
```

Em `backend/app/main.py`: troque `from app.api import accounts, auth, spaces, transactions` por `from app.api import accounts, auth, cards, spaces, transactions` e acrescente `app.include_router(cards.router)` depois do router de transações.

- [ ] **Step 10: Rodar tudo, qualidade e commit**

Run: `uv run pytest -v` → todos PASS; `uv run ruff format . && uv run ruff check --fix . && uv run mypy app`
```bash
cd .. && git add -A && git commit -m "feat(cards): add credit cards, invoices, installments and mirror bills"
```

---

## Task 4 (T2.4): Contas a pagar, recorrência e pagamentos

**Files:** Create `backend/app/domain/bills/{recurrence,service}.py`, `backend/app/domain/payments.py`, `backend/app/api/bills.py`, `backend/tests/domain/test_bills.py`, `backend/tests/api/test_bills_api.py`. Modify `backend/app/main.py`. **Sem tabela nova** (o model `Bill`, `transactions.bill_id` e `bills/status.py` já nasceram no T2.3): nenhuma migração; `scripts/migrate_check.sh` deve continuar limpo.

Regras (spec 14.6): pagar **conta a pagar** = `expense` na conta escolhida (categoria da conta, data do pagamento, espaço da conta a pagar, `bill_id`); pagar **fatura** = `transfer` conta→cartão (não conta no teto), parcial permitido; **a conta de origem é sempre obrigatória** (pode ser `wallet`); todo pagamento gera lançamento.

- [ ] **Step 1: Testes de domínio falhando**

`backend/tests/domain/test_bills.py`:
```python
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.domain.accounts.models import Account
from app.domain.bills.recurrence import (
    Recurrence,
    every_n_months,
    generate_occurrences,
    monthly,
    yearly,
)
from app.domain.bills.service import create_bill, list_bills
from app.domain.cards.service import invoice_remaining, register_card_purchase
from app.domain.errors import DomainError
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance, list_transactions
from tests.factories import category_id, make_account, make_card, make_family, make_user

DUE = date(2026, 11, 20)


async def _bill(session, user, amount=12_000, **kw):
    return await create_bill(
        session, actor_id=user.id, space_id=user.default_space_id, description="Luz",
        amount_cents=amount, due_on=DUE, **kw,
    )  # fmt: skip


async def _tx_count(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(Transaction)))


# ---- recorrência (pura) ----
def test_monthly_recurrence_day_31():
    assert generate_occurrences(monthly(31), date(2026, 1, 31)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
    ]  # fmt: skip
    assert generate_occurrences(monthly(31), date(2026, 1, 15)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
    ]  # fmt: skip
    assert date(2028, 2, 29) in generate_occurrences(monthly(31), date(2028, 1, 31))  # bissexto


def test_yearly_and_every_n_months():
    assert generate_occurrences(yearly(2, 29), date(2026, 1, 1), horizon_months=14) == [
        date(2026, 2, 28), date(2027, 2, 28),
    ]  # fmt: skip
    assert generate_occurrences(every_n_months(2, 15), date(2026, 1, 20), horizon_months=6) == [
        date(2026, 3, 15), date(2026, 5, 15), date(2026, 7, 15),
    ]  # fmt: skip


def test_invalid_recurrence_rules():
    for make in (
        lambda: monthly(0), lambda: monthly(32), lambda: every_n_months(0, 5),
        lambda: yearly(13, 1), lambda: yearly(0, 1),
    ):  # fmt: skip
        with pytest.raises(DomainError, match="invalid_recurrence"):
            make()


def test_recurrence_json_roundtrip():
    rule = yearly(3, 10)
    assert Recurrence.from_json(rule.to_json()) == rule
    assert monthly(5).to_json() == {"kind": "monthly", "day": 5, "month": None, "n": 1}


# ---- contas a pagar ----
async def test_create_bill_validates_and_stores_recurrence(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = a.default_space_id
    cat = await category_id(session, sp, "Contas da casa")
    bill = await _bill(session, a, category_id=cat, recurrence=monthly(31), responsible_user_id=a.id)
    assert (bill.kind, bill.status, bill.amount_cents) == ("manual", "open", 12_000)
    assert bill.recurrence_rule == {"kind": "monthly", "day": 31, "month": None, "n": 1}
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await _bill(session, a, amount=0)
    with pytest.raises(DomainError, match="invalid_category"):
        await _bill(session, a, category_id=await category_id(session, b.default_space_id))
    with pytest.raises(DomainError, match="invalid_responsible"):
        await _bill(session, a, responsible_user_id=b.id)
    with pytest.raises(HTTPException) as e:
        await create_bill(
            session, actor_id=b.id, space_id=sp, description="x", amount_cents=1, due_on=DUE
        )  # fmt: skip
    assert e.value.status_code == 404
    assert [x.id for x in await list_bills(session, viewer_id=a.id, space_id=sp)] == [bill.id]
    assert await list_bills(session, viewer_id=a.id, space_id=sp, status="paid") == []


async def test_pay_bill_creates_expense_on_account(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    cat = await category_id(session, a.default_space_id, "Contas da casa")
    bill = await _bill(session, a, category_id=cat)
    tx = await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=date(2026, 11, 18)
    )  # fmt: skip
    assert (tx.type, tx.amount_cents, tx.account_id) == ("expense", 12_000, acc.id)
    assert (tx.category_id, tx.space_id, tx.bill_id) == (cat, bill.space_id, bill.id)
    assert tx.occurred_on == date(2026, 11, 18) and tx.created_by == a.id
    await session.refresh(bill)
    assert bill.status == "paid"
    assert await account_balance(session, acc.id) == 88_000


async def test_pay_bill_from_wallet(session):
    a = await make_user(session, "a@x.com")
    wallet = await session.scalar(
        select(Account).where(Account.space_id == a.default_space_id, Account.type == "wallet")
    )
    bill = await _bill(session, a)
    tx = await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=wallet.id, paid_on=DUE
    )  # fmt: skip
    assert tx.account_id == wallet.id
    assert await account_balance(session, wallet.id) == -12_000


async def test_paying_requires_source_account(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=5_000, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    bill = await _bill(session, a)
    with pytest.raises(DomainError, match="source_account_required"):
        await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=None, paid_on=DUE)
    with pytest.raises(DomainError, match="source_account_required"):
        await pay_invoice(
            session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=None, paid_on=DUE,
            amount_cents=5_000,
        )  # fmt: skip
    assert await _tx_count(session) == 1  # só a compra; nenhum pagamento sem origem


async def test_partial_bill_payment_and_invalid_amounts(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    bill = await _bill(session, a)
    await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE, amount_cents=5_000
    )  # fmt: skip
    await session.refresh(bill)
    assert bill.status == "partial"
    for bad in (0, 7_001):
        with pytest.raises(DomainError, match="invalid_payment_amount"):
            await pay_bill(
                session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE,
                amount_cents=bad,
            )  # fmt: skip
    rest = await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE)
    assert rest.amount_cents == 7_000  # sem valor: quita o que falta
    await session.refresh(bill)
    assert bill.status == "paid"
    with pytest.raises(DomainError, match="invalid_payment_amount"):  # já quitada
        await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE)


async def test_pay_bill_access_rules(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    mine = await make_account(session, a.default_space_id)
    theirs = await make_account(session, b.default_space_id)
    bill = await _bill(session, a)
    with pytest.raises(HTTPException) as e:  # b não é membro do espaço da conta a pagar
        await pay_bill(session, actor_id=b.id, bill_id=bill.id, account_id=theirs.id, paid_on=DUE)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:  # a não pode debitar de conta do b
        await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=theirs.id, paid_on=DUE)
    assert e.value.status_code == 403
    await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=mine.id, paid_on=DUE)


async def _invoice_setup(session, amount=30_000):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=amount, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    return a, acc, card, buy.invoice_id


async def test_pay_invoice_is_transfer_not_expense(session):
    a, acc, card, inv_id = await _invoice_setup(session)
    pay = await pay_invoice(
        session, actor_id=a.id, invoice_id=inv_id, account_id=acc.id, paid_on=date(2026, 11, 18),
        amount_cents=30_000,
    )  # fmt: skip
    assert pay.type == "transfer"
    assert (pay.account_id, pay.card_id, pay.invoice_id) == (acc.id, card.id, inv_id)
    assert pay.counter_account_id is None and pay.bill_id is not None
    assert await account_balance(session, acc.id) == 70_000
    assert await invoice_remaining(session, inv_id) == 0


async def test_partial_invoice_payment_leaves_remaining(session):
    from app.domain.bills.models import Bill

    a, acc, card, inv_id = await _invoice_setup(session)
    pay = lambda amount: pay_invoice(  # noqa: E731
        session, actor_id=a.id, invoice_id=inv_id, account_id=acc.id, paid_on=DUE,
        amount_cents=amount,
    )  # fmt: skip
    await pay(10_000)
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == inv_id))
    assert await invoice_remaining(session, inv_id) == 20_000 and bill.status == "partial"
    for bad in (0, 20_001):
        with pytest.raises(DomainError, match="invalid_payment_amount"):
            await pay(bad)
    await pay(20_000)
    await session.refresh(bill)
    assert await invoice_remaining(session, inv_id) == 0 and bill.status == "paid"
    with pytest.raises(DomainError, match="invalid_payment_amount"):
        await pay(1)


async def test_purchase_after_payment_reopens_invoice(session):
    from app.domain.bills.models import Bill

    a, acc, card, inv_id = await _invoice_setup(session)
    await pay_invoice(
        session, actor_id=a.id, invoice_id=inv_id, account_id=acc.id, paid_on=DUE,
        amount_cents=30_000,
    )  # fmt: skip
    await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=5_000, occurred_on=date(2026, 11, 8),
    )  # fmt: skip
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == inv_id))
    await session.refresh(bill)
    assert (bill.amount_cents, bill.status) == (35_000, "partial")
    assert await invoice_remaining(session, inv_id) == 5_000


async def test_invoice_paid_from_personal_account_stays_in_payer_space(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id)
    mine = await make_account(session, w.default_space_id, name="Itaú pessoal", initial=50_000)
    (buy,) = await register_card_purchase(
        session, actor_id=w.id, space_id=fam.id, card_id=card.id, amount_cents=8_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    pay = await pay_invoice(
        session, actor_id=w.id, invoice_id=buy.invoice_id, account_id=mine.id, paid_on=DUE,
        amount_cents=8_000,
    )  # fmt: skip
    assert pay.space_id == w.default_space_id  # a conta pessoal não aparece para a família
    seen_by_h = await list_transactions(session, viewer_id=h.id, space_id=fam.id)
    assert pay.id not in [t.id for t in seen_by_h]
    assert await invoice_remaining(session, buy.invoice_id) == 0
    with pytest.raises(HTTPException) as e:  # h não pode debitar da conta pessoal da w
        await pay_invoice(
            session, actor_id=h.id, invoice_id=buy.invoice_id, account_id=mine.id, paid_on=DUE,
            amount_cents=1,
        )  # fmt: skip
    assert e.value.status_code == 403


async def test_pay_invoice_by_non_member_is_404(session):
    a, acc, card, inv_id = await _invoice_setup(session)
    b = await make_user(session, "b@x.com")
    theirs = await make_account(session, b.default_space_id)
    with pytest.raises(HTTPException) as e:
        await pay_invoice(
            session, actor_id=b.id, invoice_id=inv_id, account_id=theirs.id, paid_on=DUE,
            amount_cents=100,
        )  # fmt: skip
    assert e.value.status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_bills.py -v`
Expected: FAIL na coleta (`ModuleNotFoundError: No module named 'app.domain.bills.recurrence'`).

- [ ] **Step 3: Implementar recorrência, serviço de contas e pagamentos**

`backend/app/domain/bills/recurrence.py`:
```python
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from app.core.dates import add_months, clamp_day
from app.domain.errors import DomainError


@dataclass(frozen=True)
class Recurrence:
    kind: Literal["monthly", "yearly", "every_n_months"]
    day: int
    month: int | None = None  # só yearly
    n: int = 1  # só every_n_months

    def __post_init__(self) -> None:
        yearly_ok = self.kind != "yearly" or (self.month is not None and 1 <= self.month <= 12)
        if not (
            self.kind in ("monthly", "yearly", "every_n_months")
            and 1 <= self.day <= 31 and self.n >= 1 and yearly_ok
        ):  # fmt: skip
            raise DomainError("invalid_recurrence")

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Recurrence":
        return cls(**data)


def monthly(day: int) -> Recurrence:
    return Recurrence("monthly", day)


def yearly(month: int, day: int) -> Recurrence:
    return Recurrence("yearly", day, month=month)


def every_n_months(n: int, day: int) -> Recurrence:
    return Recurrence("every_n_months", day, n=n)


def generate_occurrences(rule: Recurrence, start: date, horizon_months: int = 3) -> list[date]:
    """Datas de `start` até `start + horizon_months`; dia inexistente vira o último do mês."""
    end = add_months(start, horizon_months)
    step = {"monthly": 1, "every_n_months": rule.n, "yearly": 12}[rule.kind]
    first = date(start.year, rule.month or start.month, 1)
    out: list[date] = []
    k = 0
    while True:
        m = add_months(first, k * step)
        d = clamp_day(m.year, m.month, rule.day)
        k += 1
        if d > end:
            return out
        if d >= start:
            out.append(d)
```

`backend/app/domain/bills/service.py`:
```python
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bills.models import Bill
from app.domain.bills.recurrence import Recurrence
from app.domain.errors import DomainError
from app.domain.spaces.access import is_member, require_member
from app.domain.transactions.rules import check_common


async def create_bill(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, description: str, amount_cents: int,
    due_on: date, category_id: UUID | None = None, responsible_user_id: UUID | None = None,
    recurrence: Recurrence | None = None,
) -> Bill:  # fmt: skip
    """Conta a pagar avulsa ou recorrente. A próxima ocorrência é gerada pelo job do M5."""
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=amount_cents,
        category_id=category_id,
    )  # fmt: skip
    if responsible_user_id is not None and not await is_member(session, responsible_user_id, space_id):
        raise DomainError("invalid_responsible")
    bill = Bill(
        space_id=space_id, kind="manual", description=description, amount_cents=amount_cents,
        due_on=due_on, category_id=category_id, responsible_user_id=responsible_user_id,
        recurrence_rule=recurrence.to_json() if recurrence else None,
    )  # fmt: skip
    session.add(bill)
    await session.commit()
    return bill


async def list_bills(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, status: str | None = None,
    start: date | None = None, end: date | None = None,
) -> list[Bill]:  # fmt: skip
    await require_member(session, viewer_id, space_id)
    q = select(Bill).where(Bill.space_id == space_id)
    if status is not None:
        q = q.where(Bill.status == status)
    if start is not None:
        q = q.where(Bill.due_on >= start)
    if end is not None:
        q = q.where(Bill.due_on <= end)
    return list(await session.scalars(q.order_by(Bill.due_on, Bill.created_at)))
```

`backend/app/domain/payments.py`:
```python
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.bills.models import Bill
from app.domain.bills.status import bill_paid_cents, refresh_status
from app.domain.cards.service import invoice_remaining, visible_invoice
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction


async def pay_bill(
    session: AsyncSession, *, actor_id: UUID, bill_id: UUID, account_id: UUID | None,
    paid_on: date, amount_cents: int | None = None,
) -> Transaction:  # fmt: skip
    """Quita (ou paga parte de) uma conta a pagar: despesa na conta de origem, que é obrigatória."""
    if account_id is None:
        raise DomainError("source_account_required")
    bill = await session.get(Bill, bill_id, with_for_update=True, populate_existing=True)
    if bill is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, actor_id, bill.space_id)
    if bill.kind != "manual":
        raise DomainError("use_pay_invoice")
    await use_account(session, actor_id, account_id)
    remaining = bill.amount_cents - await bill_paid_cents(session, bill.id)
    amount = remaining if amount_cents is None else amount_cents
    if amount <= 0 or amount > remaining:
        raise DomainError("invalid_payment_amount")
    tx = Transaction(
        space_id=bill.space_id, type="expense", amount_cents=amount, occurred_on=paid_on,
        description=bill.description, category_id=bill.category_id, account_id=account_id,
        bill_id=bill.id, created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    await refresh_status(session, bill)
    await session.commit()
    return tx


async def pay_invoice(
    session: AsyncSession, *, actor_id: UUID, invoice_id: UUID, account_id: UUID | None,
    paid_on: date, amount_cents: int,
) -> Transaction:  # fmt: skip
    """Transferência conta -> cartão (não é despesa). Parcial permitido; o resto fica em aberto."""
    if account_id is None:
        raise DomainError("source_account_required")
    inv, card = await visible_invoice(session, actor_id, invoice_id)  # 404 se não for membro
    acc = await use_account(session, actor_id, account_id)
    bill = await session.scalar(
        select(Bill).where(Bill.invoice_id == inv.id).with_for_update()
    )  # trava contra pagamento duplo
    assert bill is not None
    remaining = await invoice_remaining(session, inv.id)
    if amount_cents <= 0 or amount_cents > remaining:
        raise DomainError("invalid_payment_amount")
    tx = Transaction(
        space_id=acc.space_id,  # espaço da conta de origem: não expõe a conta a outros membros
        type="transfer", amount_cents=amount_cents, occurred_on=paid_on,
        description=f"Pagamento da fatura {card.name}", account_id=acc.id, card_id=card.id,
        invoice_id=inv.id, bill_id=bill.id, created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    await refresh_status(session, bill)
    await session.commit()
    return tx
```

- [ ] **Step 4: Rodar testes de domínio**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run pytest tests/domain -v` → todos PASS. `bash scripts/migrate_check.sh` → limpo (sem migração nova).

- [ ] **Step 5: Testes de API falhando**

`backend/tests/api/test_bills_api.py`:
```python
from datetime import date

from app.domain.cards.service import register_card_purchase
from tests.factories import auth, category_id, make_account, make_card, make_user


async def _bill(client, headers, space, **kw):
    body = {"description": "Luz", "amount_cents": 12_000, "due_on": "2026-11-20"} | kw
    r = await client.post(f"/spaces/{space}/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_bill_with_recurrence_and_payment_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=50_000)
    cat = str(await category_id(session, a.default_space_id, "Contas da casa"))
    bill = await _bill(
        client, h, sp, category_id=cat, recurrence={"kind": "monthly", "day": 31},
        responsible_user_id=str(a.id),
    )  # fmt: skip
    assert bill["amount_cents"] == 12_000 and isinstance(bill["amount_cents"], int)
    assert bill["recurrence_rule"]["day"] == 31 and bill["status"] == "open"
    no_acc = await client.post(f"/bills/{bill['id']}/payments", json={}, headers=h)
    assert no_acc.status_code == 422  # conta de origem obrigatória (corpo)
    r = await client.post(
        f"/bills/{bill['id']}/payments",
        json={"account_id": str(acc.id), "amount_cents": 5_000, "paid_on": "2026-11-18"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201
    tx = r.json()
    assert (tx["type"], tx["amount_cents"], tx["bill_id"]) == ("expense", 5_000, bill["id"])
    listed = (await client.get(f"/spaces/{sp}/bills?status=partial", headers=h)).json()
    assert [b["id"] for b in listed] == [bill["id"]]
    bal = (await client.get(f"/accounts/{acc.id}", headers=h)).json()["balance_cents"]
    assert bal == 45_000


async def test_invoice_payment_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=30_000, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    url = f"/invoices/{buy.invoice_id}/payments"
    r = await client.post(
        url, json={"account_id": str(acc.id), "amount_cents": 10_000, "paid_on": "2026-11-18"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["type"] == "transfer"
    inv = (await client.get(f"/invoices/{buy.invoice_id}", headers=h)).json()
    assert (inv["total_cents"], inv["paid_cents"], inv["remaining_cents"]) == (30_000, 10_000, 20_000)
    assert inv["status"] == "partial"
    over = await client.post(url, json={"account_id": str(acc.id), "amount_cents": 20_001}, headers=h)
    assert over.status_code == 422 and over.json() == {"detail": "invalid_payment_amount"}
    missing = await client.post(url, json={"amount_cents": 100}, headers=h)
    assert missing.status_code == 422
    manual_bill = await client.post(
        f"/bills/{inv['id']}/payments", json={"account_id": str(acc.id)}, headers=h
    )  # id de fatura não é conta
    assert manual_bill.status_code == 404


async def test_bill_validation_422(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    base = {"description": "Luz", "amount_cents": 100, "due_on": "2026-11-20"}
    for bad in (
        {"amount_cents": 10.5}, {"amount_cents": 0}, {"recurrence": {"kind": "monthly", "day": 32}},
        {"recurrence": {"kind": "yearly", "day": 5}}, {"recurrence": {"kind": "weekly", "day": 5}},
    ):  # fmt: skip
        r = await client.post(f"/spaces/{sp}/bills", json=base | bad, headers=h)
        assert r.status_code == 422, bad


async def test_bills_routes_404_for_non_member_and_403_for_foreign_account(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb = auth(a), auth(b)
    sp_a = str(a.default_space_id)
    bill = await _bill(client, ha, sp_a)
    mine = await make_account(session, b.default_space_id)
    theirs = await make_account(session, a.default_space_id)
    body = {"description": "x", "amount_cents": 1, "due_on": "2026-11-20"}
    assert (await client.post(f"/spaces/{sp_a}/bills", json=body, headers=hb)).status_code == 404
    assert (await client.get(f"/spaces/{sp_a}/bills", headers=hb)).status_code == 404
    pay = await client.post(
        f"/bills/{bill['id']}/payments", json={"account_id": str(mine.id)}, headers=hb
    )
    assert pay.status_code == 404
    pay = await client.post(
        f"/bills/{bill['id']}/payments", json={"account_id": str(theirs.id)}, headers=hb
    )
    assert pay.status_code == 404  # b nem enxerga a conta a pagar: 404 vem antes do 403
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id, amount_cents=100,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    pay = await client.post(
        f"/invoices/{buy.invoice_id}/payments",
        json={"account_id": str(mine.id), "amount_cents": 1}, headers=hb,
    )  # fmt: skip
    assert pay.status_code == 404
    # a tenta pagar com a conta do b: 403
    pay = await client.post(
        f"/bills/{bill['id']}/payments", json={"account_id": str(mine.id)}, headers=ha
    )
    assert pay.status_code == 403
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_bills_api.py -v`
Expected: FAIL (404 nas rotas novas).

- [ ] **Step 7: API**

`backend/app/api/bills.py`:
```python
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.bills.recurrence import Recurrence
from app.domain.bills.service import create_bill, list_bills
from app.domain.payments import pay_bill, pay_invoice

router = APIRouter(tags=["bills"])


class RecurrenceIn(BaseModel):
    kind: Literal["monthly", "yearly", "every_n_months"]
    day: Annotated[int, Field(strict=True, ge=1, le=31)]
    month: Annotated[int, Field(strict=True, ge=1, le=12)] | None = None
    n: Annotated[int, Field(strict=True, ge=1)] = 1


class BillIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_cents: Cents
    due_on: date
    category_id: UUID | None = None
    responsible_user_id: UUID | None = None
    recurrence: RecurrenceIn | None = None


class PayBillIn(BaseModel):
    account_id: UUID  # obrigatório: todo pagamento tem conta de origem (pode ser a carteira)
    amount_cents: Cents | None = None  # padrão: o que falta
    paid_on: date | None = None


class PayInvoiceIn(BaseModel):
    account_id: UUID
    amount_cents: Cents
    paid_on: date | None = None


@router.post("/spaces/{space_id}/bills", status_code=201)
async def create(
    space_id: UUID, body: BillIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    bill = await create_bill(
        session, actor_id=user.id, space_id=space_id, description=body.description,
        amount_cents=body.amount_cents, due_on=body.due_on, category_id=body.category_id,
        responsible_user_id=body.responsible_user_id,
        recurrence=Recurrence(**body.recurrence.model_dump()) if body.recurrence else None,
    )  # fmt: skip
    return row(bill)


@router.get("/spaces/{space_id}/bills")
async def list_(
    space_id: UUID, user: CurrentUser, session: Session, status: str | None = None,
    start: date | None = None, end: date | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    bills = await list_bills(
        session, viewer_id=user.id, space_id=space_id, status=status, start=start, end=end
    )
    return [row(b) for b in bills]


@router.post("/bills/{bill_id}/payments", status_code=201)
async def pay(
    bill_id: UUID, body: PayBillIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await pay_bill(
        session, actor_id=user.id, bill_id=bill_id, account_id=body.account_id,
        paid_on=body.paid_on or local_today(user.tz), amount_cents=body.amount_cents,
    )  # fmt: skip
    return row(tx)


@router.post("/invoices/{invoice_id}/payments", status_code=201)
async def pay_inv(
    invoice_id: UUID, body: PayInvoiceIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await pay_invoice(
        session, actor_id=user.id, invoice_id=invoice_id, account_id=body.account_id,
        paid_on=body.paid_on or local_today(user.tz), amount_cents=body.amount_cents,
    )  # fmt: skip
    return row(tx)
```
Em `backend/app/main.py`: acrescente `bills` ao import (`from app.api import accounts, auth, bills, cards, spaces, transactions`) e `app.include_router(bills.router)`.

- [ ] **Step 8: Rodar tudo, qualidade e commit**

Run: `uv run pytest -v` → todos PASS; `uv run ruff format . && uv run ruff check --fix . && uv run mypy app`
```bash
cd .. && git add -A && git commit -m "feat(bills): add bills, recurrence rules and bill/invoice payments"
```

---

## Task 5 (T2.5): Teto de gastos

**Files:** Create `backend/app/domain/budgets/{__init__,models,service}.py`, `backend/app/api/budgets.py`, `backend/tests/domain/test_budgets.py`, `backend/tests/api/test_budgets_api.py`. Modify `backend/app/domain/models.py`, `backend/app/main.py`.

Regras (spec 8.6, 13): gasto do mês de um espaço = despesas **fora do cartão** com `occurred_on` no mês (inclui pagamento de conta a pagar, pela data do pagamento) **+** compras de cartão (à vista ou parcelas) cuja **fatura vence** no mês. **Pagamento de fatura e aportes em metas são transferências e nunca contam.** Só entram lançamentos do próprio espaço (`transactions.space_id`): o `#pessoal` de alguém numa conta/cartão da família não entra no teto da família. Alertas em 80%, 100% e >100%: uma vez por limiar/escopo/mês; se o gasto pula vários limiares de uma vez, todos são registrados e **só o mais alto** é devolvido (uma mensagem, não três).

- [ ] **Step 1: Testes de domínio falhando**

`backend/tests/domain/test_budgets.py`:
```python
from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.bills.service import create_bill
from app.domain.budgets.service import (
    BudgetAlert,
    evaluate_thresholds,
    future_impact,
    month_spending,
    set_budget,
)
from app.domain.cards.service import register_card_purchase
from app.domain.errors import DomainError
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.service import create_transaction
from tests.factories import category_id, make_account, make_card, make_family, make_user

NOV, DEC, JAN = date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)


async def _spend(session, user, acc, amount, *, on=date(2026, 11, 10), cat=None, space=None):
    return await create_transaction(
        session, actor_id=user.id, space_id=space or user.default_space_id, type="expense",
        amount_cents=amount, occurred_on=on, account_id=acc.id, category_id=cat,
    )  # fmt: skip


async def _buy(session, user, card, amount, on, *, n=1, space=None):
    return await register_card_purchase(
        session, actor_id=user.id, space_id=space or user.default_space_id, card_id=card.id,
        amount_cents=amount, occurred_on=on, installments=n,
    )  # fmt: skip


async def test_card_installments_count_in_due_month(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    card = await make_card(session, a, sp)  # fecha 10, vence 20
    await _buy(session, a, card, 30_000, date(2026, 11, 5), n=3)  # 10.000 em nov, dez e jan
    await _buy(session, a, card, 5_000, date(2026, 11, 15))  # depois do fechamento: fatura de dez
    await _spend(session, a, acc, 2_000, on=date(2026, 11, 3))  # à vista: mês da data
    await _spend(session, a, acc, 700, on=date(2026, 10, 31))
    assert await month_spending(session, sp, NOV) == 12_000
    assert await month_spending(session, sp, date(2026, 11, 17)) == 12_000  # qualquer dia do mês
    assert await month_spending(session, sp, DEC) == 15_000
    assert await month_spending(session, sp, JAN) == 10_000
    assert await month_spending(session, sp, date(2027, 2, 1)) == 0
    assert await month_spending(session, sp, date(2026, 10, 1)) == 700


async def test_invoice_payment_not_counted(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    card = await make_card(session, a, sp)
    (buy,) = await _buy(session, a, card, 30_000, date(2026, 11, 5))
    assert await month_spending(session, sp, NOV) == 30_000  # a compra conta (fatura vence em nov)
    await pay_invoice(
        session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=acc.id,
        paid_on=date(2026, 11, 18), amount_cents=30_000,
    )  # fmt: skip
    assert await month_spending(session, sp, NOV) == 30_000  # o pagamento NÃO conta de novo


async def test_bill_payment_counts_on_payment_date(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    bill = await create_bill(
        session, actor_id=a.id, space_id=sp, description="Luz", amount_cents=9_000,
        due_on=date(2026, 11, 28),
    )  # fmt: skip
    await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=date(2026, 12, 2)
    )  # fmt: skip
    assert await month_spending(session, sp, NOV) == 0
    assert await month_spending(session, sp, DEC) == 9_000


async def test_category_filter_in_month_spending(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    mercado, lazer = await category_id(session, sp), await category_id(session, sp, "Lazer")
    await _spend(session, a, acc, 4_000, cat=mercado)
    await _spend(session, a, acc, 1_000, cat=lazer)
    assert await month_spending(session, sp, NOV) == 5_000
    assert await month_spending(session, sp, NOV, mercado) == 4_000


async def test_set_budget_validates_and_replaces_categories(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = a.default_space_id
    mercado = await category_id(session, sp)
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=0)
    with pytest.raises(DomainError, match="invalid_category"):
        await set_budget(
            session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=100,
            categories={await category_id(session, b.default_space_id): 50},
        )  # fmt: skip
    with pytest.raises(HTTPException) as e:
        await set_budget(session, actor_id=b.id, space_id=sp, month=NOV, limit_cents=100)
    assert e.value.status_code == 404
    first = await set_budget(
        session, actor_id=a.id, space_id=sp, month=date(2026, 11, 17), limit_cents=100_000,
        categories={mercado: 40_000},
    )  # fmt: skip
    assert first.month == NOV  # normalizado para o dia 1
    again = await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=90_000)
    assert again.id == first.id and again.limit_cents == 90_000  # mesmo mês: atualiza


async def test_alerts_fire_once_per_threshold(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=100_000)
    await _spend(session, a, acc, 79_999)
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 1)  # 80.000 = 80%
    assert await evaluate_thresholds(session, sp, NOV) == [
        BudgetAlert("general", None, 80, 80_000, 100_000)
    ]
    assert await evaluate_thresholds(session, sp, NOV) == []  # não repete
    await _spend(session, a, acc, 20_000)  # 100.000 = 100%
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [100]
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 1)  # acima do teto
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [101]
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 5_000)
    assert await evaluate_thresholds(session, sp, NOV) == []  # "acima" só uma vez no mês


async def test_alert_jump_reports_only_highest_threshold(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=100_000)
    await _spend(session, a, acc, 130_000)
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [101]
    assert await evaluate_thresholds(session, sp, NOV) == []  # 80 e 100 também ficaram registrados


async def test_alerts_are_per_month_and_need_a_budget(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    assert await evaluate_thresholds(session, sp, NOV) == []  # sem teto, sem alerta
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=1_000)
    await set_budget(session, actor_id=a.id, space_id=sp, month=DEC, limit_cents=1_000)
    await _spend(session, a, acc, 900, on=date(2026, 11, 10))
    await _spend(session, a, acc, 900, on=date(2026, 12, 10))
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [80]
    assert [x.threshold for x in await evaluate_thresholds(session, sp, DEC)] == [80]


async def test_category_budget_alert(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    mercado, transporte = await category_id(session, sp), await category_id(session, sp, "Transporte")
    await set_budget(
        session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=1_000_000,
        categories={mercado: 10_000},
    )  # fmt: skip
    await _spend(session, a, acc, 50_000, cat=transporte)  # sem teto de categoria: nada
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 8_000, cat=mercado)
    assert await evaluate_thresholds(session, sp, NOV) == [
        BudgetAlert("category", mercado, 80, 8_000, 10_000)
    ]
    assert await evaluate_thresholds(session, sp, NOV) == []


async def test_personal_tx_not_in_family_budget(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    acc = await make_account(session, fam.id, name="Conjunta")
    card = await make_card(session, w, fam.id)
    await _spend(session, w, acc, 30_000, space=fam.id)
    await _spend(session, w, acc, 20_000)  # #pessoal da w, na conta da família
    await _buy(session, w, card, 7_000, date(2026, 11, 5), space=fam.id)
    await _buy(session, w, card, 3_000, date(2026, 11, 6))  # #pessoal no cartão da família
    assert await month_spending(session, fam.id, NOV) == 37_000
    assert await month_spending(session, w.default_space_id, NOV) == 23_000
    assert await month_spending(session, h.default_space_id, NOV) == 0


async def test_future_impact_lists_due_months_with_limits(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    card = await make_card(session, a, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=50_000)
    await set_budget(session, actor_id=a.id, space_id=sp, month=DEC, limit_cents=40_000)
    txs = await _buy(session, a, card, 30_000, date(2026, 11, 5), n=3)
    assert await future_impact(session, sp, txs) == [
        (NOV, 10_000, 50_000), (DEC, 10_000, 40_000), (JAN, 10_000, None),
    ]  # fmt: skip
    assert await future_impact(session, sp, []) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_budgets.py -v`
Expected: FAIL na coleta (`ModuleNotFoundError: No module named 'app.domain.budgets'`).

- [ ] **Step 3: Models e serviço**

`backend/app/domain/budgets/__init__.py`: arquivo vazio.

`backend/app/domain/budgets/models.py`:
```python
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("space_id", "month", name="uq_budgets_space_month"),
        CheckConstraint("limit_cents > 0", name="ck_budgets_limit_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    month: Mapped[date] = mapped_column(Date)  # sempre o dia 1
    limit_cents: Mapped[int] = mapped_column(BigInteger)


class BudgetCategory(Base):
    __tablename__ = "budget_categories"
    __table_args__ = (CheckConstraint("limit_cents > 0", name="ck_budget_categories_positive"),)

    budget_id: Mapped[UUID] = mapped_column(ForeignKey("budgets.id"), primary_key=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id"), primary_key=True)
    limit_cents: Mapped[int] = mapped_column(BigInteger)


class BudgetAlertSent(Base):
    __tablename__ = "budget_alerts_sent"
    __table_args__ = (
        UniqueConstraint("space_id", "month", "scope_key", "threshold", name="uq_budget_alert_once"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    month: Mapped[date] = mapped_column(Date)
    scope_key: Mapped[str] = mapped_column(String(40))  # "general" ou o id da categoria
    threshold: Mapped[int] = mapped_column(Integer)  # 80 | 100 | 101 (101 = acima do teto)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Em `backend/app/domain/models.py` acrescente `import app.domain.budgets.models  # noqa: F401`.

`backend/app/domain/budgets/service.py`:
```python
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, NamedTuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.budgets.models import Budget, BudgetAlertSent, BudgetCategory
from app.domain.cards.models import Invoice
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common


@dataclass(frozen=True)
class BudgetAlert:
    scope: Literal["general", "category"]
    category_id: UUID | None
    threshold: int  # 80 | 100 | 101 (101 = acima do teto)
    spent: int
    limit: int


class FutureImpact(NamedTuple):
    month: date
    spent: int
    limit: int | None  # None: o mês ainda não tem teto


def _bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    return start, add_months(start, 1)


async def month_spending(
    session: AsyncSession, space_id: UUID, month: date, category_id: UUID | None = None
) -> int:
    """Despesas fora do cartão (data no mês) + compras de cartão cuja fatura vence no mês.

    Transferências (pagamento de fatura, aportes em metas) não são `expense`: nunca entram."""
    start, end = _bounds(month)
    t = Transaction
    by_cat = [] if category_id is None else [t.category_id == category_id]
    total = func.coalesce(func.sum(t.amount_cents), 0)
    cash = await session.scalar(
        select(total).where(
            t.space_id == space_id, t.type == "expense", t.card_id.is_(None),
            t.occurred_on >= start, t.occurred_on < end, *by_cat,
        )
    )  # fmt: skip
    card = await session.scalar(
        select(total)
        .select_from(t)
        .join(Invoice, Invoice.id == t.invoice_id)
        .where(
            t.space_id == space_id, t.type == "expense", t.card_id.is_not(None),
            Invoice.due_on >= start, Invoice.due_on < end, *by_cat,
        )
    )  # fmt: skip
    return int(cash or 0) + int(card or 0)


async def set_budget(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, month: date, limit_cents: int,
    categories: dict[UUID, int] | None = None,
) -> Budget:  # fmt: skip
    """Cria/atualiza o teto do mês (geral + por categoria; as categorias são substituídas)."""
    await require_member(session, actor_id, space_id)
    for cid, limit in (categories or {}).items():
        await check_common(
            session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=limit,
            category_id=cid,
        )  # fmt: skip
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=limit_cents,
        category_id=None,
    )  # fmt: skip
    start = month.replace(day=1)
    budget = await session.scalar(
        select(Budget).where(Budget.space_id == space_id, Budget.month == start)
    )
    if budget is None:
        budget = Budget(space_id=space_id, month=start, limit_cents=limit_cents)
        session.add(budget)
        await session.flush()
    else:
        # ponytail: alertas já enviados não são zerados ao mudar o teto; resetar se o dono pedir
        budget.limit_cents = limit_cents
    await session.execute(delete(BudgetCategory).where(BudgetCategory.budget_id == budget.id))
    for cid, limit in (categories or {}).items():
        session.add(BudgetCategory(budget_id=budget.id, category_id=cid, limit_cents=limit))
    await session.commit()
    return budget


async def budget_overview(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, month: date
) -> dict[str, Any]:
    await require_member(session, viewer_id, space_id)
    start = month.replace(day=1)
    budget = await session.scalar(
        select(Budget).where(Budget.space_id == space_id, Budget.month == start)
    )
    if budget is None:
        raise HTTPException(status_code=404, detail="budget_not_found")
    cats = await session.scalars(
        select(BudgetCategory).where(BudgetCategory.budget_id == budget.id)
    )
    return {
        "month": start,
        "limit_cents": budget.limit_cents,
        "spent_cents": await month_spending(session, space_id, start),
        "categories": [
            {
                "category_id": c.category_id,
                "limit_cents": c.limit_cents,
                "spent_cents": await month_spending(session, space_id, start, c.category_id),
            }
            for c in cats
        ],
    }


def _crossed(spent: int, limit: int) -> list[int]:
    hits = ((80, spent * 100 >= limit * 80), (100, spent >= limit), (101, spent > limit))
    return [threshold for threshold, hit in hits if hit]


async def evaluate_thresholds(
    session: AsyncSession, space_id: UUID, month: date
) -> list[BudgetAlert]:
    """Limiares novos: registra todos e devolve só o mais alto por escopo."""
    start = month.replace(day=1)
    budget = await session.scalar(
        select(Budget).where(Budget.space_id == space_id, Budget.month == start)
    )
    if budget is None:
        return []
    cats = await session.scalars(
        select(BudgetCategory).where(BudgetCategory.budget_id == budget.id)
    )
    scopes: list[tuple[UUID | None, int]] = [(None, budget.limit_cents)]
    scopes += [(c.category_id, c.limit_cents) for c in cats]
    alerts: list[BudgetAlert] = []
    for cat_id, limit in scopes:
        key = "general" if cat_id is None else str(cat_id)
        spent = await month_spending(session, space_id, start, cat_id)
        done = set(
            await session.scalars(
                select(BudgetAlertSent.threshold).where(
                    BudgetAlertSent.space_id == space_id,
                    BudgetAlertSent.month == start,
                    BudgetAlertSent.scope_key == key,
                )
            )
        )
        new = [t for t in _crossed(spent, limit) if t not in done]
        # ponytail: duas avaliações simultâneas estouram a restrição única; o chamador repete
        session.add_all(
            [BudgetAlertSent(space_id=space_id, month=start, scope_key=key, threshold=t) for t in new]
        )
        if new:
            scope: Literal["general", "category"] = "general" if cat_id is None else "category"
            alerts.append(BudgetAlert(scope, cat_id, max(new), spent, limit))
    await session.commit()
    return alerts


async def future_impact(
    session: AsyncSession, space_id: UUID, transactions: Sequence[Transaction]
) -> list[FutureImpact]:
    """Por mês de vencimento das compras de cartão dadas: gasto atual e teto (se houver)."""
    ids = {t.invoice_id for t in transactions if t.invoice_id is not None}
    if not ids:
        return []
    dues = await session.scalars(select(Invoice.due_on).where(Invoice.id.in_(ids)))
    out: list[FutureImpact] = []
    for month in sorted({d.replace(day=1) for d in dues}):
        limit = await session.scalar(
            select(Budget.limit_cents).where(Budget.space_id == space_id, Budget.month == month)
        )
        out.append(FutureImpact(month, await month_spending(session, space_id, month), limit))
    return out
```

- [ ] **Step 4: Migração (autogenerate) e validação em banco descartável**

```bash
cd ~/abby-cash/backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "budgets"
```
Confira: `budgets` (`uq_budgets_space_month`, `ck_budgets_limit_positive`), `budget_categories` (PK composta) e `budget_alerts_sent` (`uq_budget_alert_once`). Depois `bash scripts/migrate_check.sh` → `No new upgrade operations detected.`

- [ ] **Step 5: Rodar testes de domínio**

Run: `uv run ruff format . && uv run ruff check --fix . && uv run pytest tests/domain/test_budgets.py -v` → todos PASS. (`test_goal_contribution_not_counted` do plano mestre depende de metas e é acrescentado a este arquivo no T2.6, Step 5.)

- [ ] **Step 6: Testes de API falhando**

`backend/tests/api/test_budgets_api.py`:
```python
from datetime import date

from app.domain.transactions.service import create_transaction
from tests.factories import auth, category_id, make_account, make_user


async def test_budget_roundtrip_and_replace(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    mercado = await category_id(session, a.default_space_id)
    acc = await make_account(session, a.default_space_id)
    await create_transaction(
        session, actor_id=a.id, space_id=a.default_space_id, type="expense", amount_cents=20_000,
        occurred_on=date(2026, 11, 8), account_id=acc.id, category_id=mercado,
    )  # fmt: skip
    url = f"/spaces/{sp}/budgets/2026-11"
    body = {
        "limit_cents": 300_000,
        "categories": [{"category_id": str(mercado), "limit_cents": 80_000}],
    }
    put = await client.put(url, json=body, headers=h)
    assert put.status_code == 200
    expected = {
        "month": "2026-11-01", "limit_cents": 300_000, "spent_cents": 20_000,
        "categories": [{"category_id": str(mercado), "limit_cents": 80_000, "spent_cents": 20_000}],
    }  # fmt: skip
    assert put.json() == expected
    assert (await client.get(url, headers=h)).json() == expected
    again = await client.put(url, json={"limit_cents": 250_000}, headers=h)
    assert again.json()["categories"] == [] and again.json()["limit_cents"] == 250_000


async def test_budget_errors(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    assert (await client.get(f"/spaces/{sp}/budgets/2026-12", headers=ha)).status_code == 404
    for month in ("2026-13", "nov", "2026-11-01"):
        r = await client.get(f"/spaces/{sp}/budgets/{month}", headers=ha)
        assert r.status_code == 422, month
    for bad in (10.5, 0, "100"):
        r = await client.put(f"/spaces/{sp}/budgets/2026-11", json={"limit_cents": bad}, headers=ha)
        assert r.status_code == 422, bad
    assert (await client.put(f"/spaces/{sp}/budgets/2026-11", json={"limit_cents": 100},
                             headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/spaces/{sp}/budgets/2026-11", headers=hb)).status_code == 404
    other_cat = str(await category_id(session, b.default_space_id))
    r = await client.put(
        f"/spaces/{sp}/budgets/2026-11", headers=ha,
        json={"limit_cents": 100, "categories": [{"category_id": other_cat, "limit_cents": 10}]},
    )  # fmt: skip
    assert r.status_code == 422 and r.json() == {"detail": "invalid_category"}
```

- [ ] **Step 7: Rodar e ver falhar; implementar a API**

Run: `uv run pytest tests/api/test_budgets_api.py -v` → FAIL (404 nas rotas).

`backend/app/api/budgets.py`:
```python
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.domain.budgets.service import budget_overview, set_budget

router = APIRouter(tags=["budgets"])


class CategoryLimitIn(BaseModel):
    category_id: UUID
    limit_cents: Cents


class BudgetIn(BaseModel):
    limit_cents: Cents
    categories: list[CategoryLimitIn] = []


def _month(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_month") from None


@router.put("/spaces/{space_id}/budgets/{month}")
async def put_budget(
    space_id: UUID, month: str, body: BudgetIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    m = _month(month)
    await set_budget(
        session, actor_id=user.id, space_id=space_id, month=m, limit_cents=body.limit_cents,
        categories={c.category_id: c.limit_cents for c in body.categories},
    )  # fmt: skip
    return await budget_overview(session, viewer_id=user.id, space_id=space_id, month=m)


@router.get("/spaces/{space_id}/budgets/{month}")
async def get_budget(
    space_id: UUID, month: str, user: CurrentUser, session: Session
) -> dict[str, Any]:
    return await budget_overview(
        session, viewer_id=user.id, space_id=space_id, month=_month(month)
    )
```
Em `backend/app/main.py`: acrescente `budgets` ao import (`from app.api import accounts, auth, bills, budgets, cards, spaces, transactions`) e `app.include_router(budgets.router)`.

Nota: `GET .../budgets/2026-11-01` dá 422 (`%Y-%m` não aceita o dia) e `GET` de não membro com mês inválido dá 422 antes do 404 (a validação do mês vem primeiro; aceitável, não revela existência).

- [ ] **Step 8: Rodar tudo, qualidade e commit**

Run: `uv run pytest -v` → PASS; `uv run ruff format . && uv run ruff check --fix . && uv run mypy app`
```bash
cd .. && git add -A && git commit -m "feat(budgets): add monthly budgets, spending rules and one-shot threshold alerts"
```

---

## Task 6 (T2.6): Metas de economia

**Files:** Create `backend/app/domain/goals/{__init__,models,service}.py`, `backend/app/api/goals.py`, `backend/tests/domain/test_goals.py`, `backend/tests/api/test_goals_api.py`. Modify `backend/app/domain/transactions/models.py` (coluna `goal_id`), `backend/app/domain/models.py`, `backend/app/main.py`, `backend/tests/domain/test_budgets.py`.

Regras (spec 13, 8.7): aporte = **transferência** da conta de origem para a meta (reduz o saldo da conta, não conta no teto); retirada = transferência inversa. Aporte: `account_id` = origem, `goal_id`. Retirada: `account_id=None`, `counter_account_id` = destino, `goal_id`. Guardado = aportes − retiradas. O lançamento pertence ao espaço da meta; a conta de origem segue a regra de conta compartilhada. `behind`: guardado < esperado por um ritmo linear entre `created_on` e o prazo.

- [ ] **Step 1: Testes de domínio falhando**

`backend/tests/domain/test_goals.py`:
```python
from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.errors import DomainError
from app.domain.goals.service import (
    contribute,
    create_goal,
    goal_progress,
    visible_goal,
    withdraw,
)
from app.domain.transactions.service import account_balance
from tests.factories import make_account, make_family, make_user

D = date(2026, 1, 15)


async def _goal(session, user, *, target=120_000, deadline=None, created_on=D, space=None):
    return await create_goal(
        session, actor_id=user.id, space_id=space or user.default_space_id, name="Viagem",
        target_cents=target, deadline=deadline, account_id=None, created_on=created_on,
    )  # fmt: skip


async def test_contribution_reduces_source_balance(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    goal = await _goal(session, a)
    tx = await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=25_000, on=D
    )  # fmt: skip
    assert tx.type == "transfer" and tx.goal_id == goal.id
    assert tx.account_id == acc.id and tx.counter_account_id is None
    assert tx.space_id == goal.space_id and tx.created_by == a.id
    assert await account_balance(session, acc.id) == 75_000
    assert (await goal_progress(session, goal.id, today=D)).saved == 25_000

    back = await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=5_000, on=D
    )  # fmt: skip
    assert back.account_id is None and back.counter_account_id == acc.id
    assert await account_balance(session, acc.id) == 80_000  # retirada devolve à conta
    assert (await goal_progress(session, goal.id, today=D)).saved == 20_000
    with pytest.raises(DomainError, match="insufficient_saved"):
        await withdraw(
            session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=20_001,
            on=D,
        )  # fmt: skip


async def test_monthly_needed(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    g = await _goal(session, a, target=120_000, deadline=date(2026, 7, 15))
    p = await goal_progress(session, g.id, today=D)
    assert (p.saved, p.target, p.monthly_needed) == (0, 120_000, 20_000)  # 6 meses
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=30_000, on=D
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=D)).monthly_needed == 15_000
    g2 = await _goal(session, a, target=100_000, deadline=date(2026, 4, 15))
    # arredonda para cima: 100000 / 3 meses
    assert (await goal_progress(session, g2.id, today=D)).monthly_needed == 33_334
    g3 = await _goal(session, a, target=1_000, deadline=date(2026, 1, 10))
    assert (await goal_progress(session, g3.id, today=D)).monthly_needed == 1_000  # prazo vencido
    g4 = await _goal(session, a, target=1_000)
    p4 = await goal_progress(session, g4.id, today=D)
    assert p4.monthly_needed is None and p4.behind is False  # sem prazo


async def test_behind_flag(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    g = await _goal(
        session, a, target=30_000, created_on=date(2026, 1, 1), deadline=date(2026, 1, 31)
    )  # 30 dias; no dia 16 esperado = 15.000
    mid = date(2026, 1, 16)
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=10_000, on=mid
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=mid)).behind is True
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=5_000, on=mid
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=mid)).behind is False  # 15.000 não é < 15.000
    assert (await goal_progress(session, g.id, today=date(2026, 2, 5))).behind is True  # vencida
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=15_000, on=mid
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=date(2026, 2, 5))).behind is False  # concluída


async def test_goal_access_and_validation(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    mine = await make_account(session, a.default_space_id, initial=10_000)
    theirs = await make_account(session, b.default_space_id, initial=10_000)
    g = await _goal(session, a)
    with pytest.raises(HTTPException) as e:  # b não é membro do espaço da meta
        await contribute(
            session, actor_id=b.id, goal_id=g.id, from_account_id=theirs.id, amount_cents=100, on=D
        )  # fmt: skip
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await visible_goal(session, b.id, g.id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:  # a debita de conta do b: 403
        await contribute(
            session, actor_id=a.id, goal_id=g.id, from_account_id=theirs.id, amount_cents=100, on=D
        )  # fmt: skip
    assert e.value.status_code == 403
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await contribute(
            session, actor_id=a.id, goal_id=g.id, from_account_id=mine.id, amount_cents=0, on=D
        )  # fmt: skip
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await _goal(session, a, target=0)


async def test_family_goal_funded_from_personal_account(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    mine = await make_account(session, h.default_space_id, name="Do h", initial=50_000)
    g = await _goal(session, w, space=fam.id)
    tx = await contribute(
        session, actor_id=h.id, goal_id=g.id, from_account_id=mine.id, amount_cents=10_000, on=D
    )  # fmt: skip
    assert tx.space_id == fam.id and await account_balance(session, mine.id) == 40_000
    assert (await goal_progress(session, g.id, today=D)).saved == 10_000
```
- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_goals.py -v`
Expected: FAIL na coleta (`ModuleNotFoundError: No module named 'app.domain.goals'`).

- [ ] **Step 3: Model, coluna `goal_id` e serviço**

`backend/app/domain/goals/__init__.py`: arquivo vazio.

`backend/app/domain/goals/models.py`:
```python
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (CheckConstraint("target_cents > 0", name="ck_goals_target_positive"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_cents: Mapped[int] = mapped_column(BigInteger)
    deadline: Mapped[date | None] = mapped_column(Date)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))  # informativo
    created_on: Mapped[date] = mapped_column(Date)  # dia local de criação: base do ritmo linear
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Em `backend/app/domain/transactions/models.py` acrescente, depois de `bill_id`:
```python
    goal_id: Mapped[UUID | None] = mapped_column(ForeignKey("goals.id"), index=True)
```
Em `backend/app/domain/models.py` acrescente `import app.domain.goals.models  # noqa: F401`.

`backend/app/domain/goals/service.py`:
```python
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dates import local_today
from app.domain.accounts.access import use_account
from app.domain.errors import DomainError
from app.domain.goals.models import Goal
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction


@dataclass(frozen=True)
class GoalProgress:
    saved: int
    target: int
    monthly_needed: int | None  # None: meta sem prazo
    behind: bool


async def create_goal(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, name: str, target_cents: int,
    created_on: date, deadline: date | None = None, account_id: UUID | None = None,
) -> Goal:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if target_cents <= 0:
        raise DomainError("amount_must_be_positive")
    if account_id is not None:
        await use_account(session, actor_id, account_id)
    goal = Goal(
        space_id=space_id, name=name, target_cents=target_cents, deadline=deadline,
        account_id=account_id, created_on=created_on,
    )  # fmt: skip
    session.add(goal)
    await session.commit()
    return goal


async def visible_goal(session: AsyncSession, viewer_id: UUID, goal_id: UUID) -> Goal:
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, goal.space_id)
    return goal


async def goal_saved(session: AsyncSession, goal_id: UUID) -> int:
    """Aportes (account_id preenchido) menos retiradas (account_id nulo)."""
    delta = case(
        (Transaction.account_id.is_not(None), Transaction.amount_cents),
        else_=-Transaction.amount_cents,
    )
    total = await session.scalar(
        select(func.coalesce(func.sum(delta), 0)).where(Transaction.goal_id == goal_id)
    )
    return int(total or 0)


async def contribute(
    session: AsyncSession, *, actor_id: UUID, goal_id: UUID, from_account_id: UUID,
    amount_cents: int, on: date,
) -> Transaction:  # fmt: skip
    goal = await visible_goal(session, actor_id, goal_id)
    if amount_cents <= 0:
        raise DomainError("amount_must_be_positive")
    await use_account(session, actor_id, from_account_id)
    tx = Transaction(
        space_id=goal.space_id, type="transfer", amount_cents=amount_cents, occurred_on=on,
        description=f"Aporte: {goal.name}", account_id=from_account_id, goal_id=goal.id,
        created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.commit()
    return tx


async def withdraw(
    session: AsyncSession, *, actor_id: UUID, goal_id: UUID, to_account_id: UUID,
    amount_cents: int, on: date,
) -> Transaction:  # fmt: skip
    """Transferência inversa: da meta para a conta de destino."""
    goal = await visible_goal(session, actor_id, goal_id)
    if amount_cents <= 0:
        raise DomainError("amount_must_be_positive")
    await use_account(session, actor_id, to_account_id)
    if amount_cents > await goal_saved(session, goal.id):
        raise DomainError("insufficient_saved")
    tx = Transaction(
        space_id=goal.space_id, type="transfer", amount_cents=amount_cents, occurred_on=on,
        description=f"Retirada: {goal.name}", account_id=None, counter_account_id=to_account_id,
        goal_id=goal.id, created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.commit()
    return tx


async def goal_progress(
    session: AsyncSession, goal_id: UUID, *, today: date | None = None
) -> GoalProgress:
    """`monthly_needed` = falta / meses até o prazo (mín. 1, arredondado p/ cima).
    `behind` = guardado < esperado por um ritmo linear de `created_on` até o prazo."""
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="not_found")
    today = today or local_today(get_settings().DEFAULT_TZ)
    saved = await goal_saved(session, goal.id)
    if goal.deadline is None:
        return GoalProgress(saved, goal.target_cents, None, False)
    remaining = max(0, goal.target_cents - saved)
    months_left = max(1, (goal.deadline.year - today.year) * 12 + goal.deadline.month - today.month)
    total_days = (goal.deadline - goal.created_on).days
    if total_days <= 0:
        expected = goal.target_cents if today >= goal.deadline else 0
    else:
        elapsed = min(max((today - goal.created_on).days, 0), total_days)
        expected = goal.target_cents * elapsed // total_days
    return GoalProgress(saved, goal.target_cents, -(-remaining // months_left), saved < expected)
```

- [ ] **Step 4: Migração (autogenerate) e validação em banco descartável**

```bash
cd ~/abby-cash/backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "goals"
```
Confira: `create_table goals` (`ck_goals_target_positive`) e `add_column transactions.goal_id` com FK e índice. Depois `bash scripts/migrate_check.sh` → `No new upgrade operations detected.`

- [ ] **Step 5: Teste do teto que depende de metas, e testes de domínio**

Acrescente a `backend/tests/domain/test_budgets.py` o import `from app.domain.goals.service import contribute, create_goal, withdraw` (junto dos demais; o `ruff --fix` ordena) e o teste do plano mestre:
```python
async def test_goal_contribution_not_counted(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=50_000,
        created_on=date(2026, 11, 1),
    )  # fmt: skip
    await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=20_000,
        on=date(2026, 11, 12),
    )  # fmt: skip
    await _spend(session, a, acc, 3_000)
    assert await month_spending(session, sp, NOV) == 3_000  # o aporte não conta
    await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=5_000,
        on=date(2026, 11, 20),
    )  # fmt: skip
    assert await month_spending(session, sp, NOV) == 3_000  # a retirada também não
```
Run: `uv run ruff format . && uv run ruff check --fix . && uv run pytest tests/domain -v` → todos PASS.

- [ ] **Step 6: Testes de API falhando**

`backend/tests/api/test_goals_api.py`:
```python
from app.core.dates import local_today
from tests.factories import auth, make_account, make_user


async def test_goal_flow_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    r = await client.post(
        f"/spaces/{sp}/goals", headers=h,
        json={"name": "Viagem", "target_cents": 120_000, "deadline": "2099-07-15",
              "account_id": str(acc.id)},
    )  # fmt: skip
    assert r.status_code == 201
    goal = r.json()
    assert goal["target_cents"] == 120_000 and goal["created_on"] == local_today(a.tz).isoformat()
    c = await client.post(
        f"/goals/{goal['id']}/contributions", headers=h,
        json={"from_account_id": str(acc.id), "amount_cents": 25_000, "occurred_on": "2026-11-12"},
    )  # fmt: skip
    assert c.status_code == 201
    assert (c.json()["type"], c.json()["goal_id"]) == ("transfer", goal["id"])
    got = (await client.get(f"/goals/{goal['id']}", headers=h)).json()
    assert (got["saved_cents"], got["target_cents"]) == (25_000, 120_000)
    assert isinstance(got["monthly_needed_cents"], int) and got["behind"] is False
    assert (await client.get(f"/accounts/{acc.id}", headers=h)).json()["balance_cents"] == 75_000
    w = await client.post(
        f"/goals/{goal['id']}/withdrawals", headers=h,
        json={"to_account_id": str(acc.id), "amount_cents": 5_000},
    )  # fmt: skip
    assert w.status_code == 201 and w.json()["counter_account_id"] == str(acc.id)
    listed = (await client.get(f"/spaces/{sp}/goals", headers=h)).json()
    assert [(g["id"], g["saved_cents"]) for g in listed] == [(goal["id"], 20_000)]
    over = await client.post(
        f"/goals/{goal['id']}/withdrawals", headers=h,
        json={"to_account_id": str(acc.id), "amount_cents": 20_001},
    )  # fmt: skip
    assert over.status_code == 422 and over.json() == {"detail": "insufficient_saved"}


async def test_goal_validation_and_access_over_http(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    mine = await make_account(session, a.default_space_id)
    theirs = await make_account(session, b.default_space_id)
    for bad in (10.5, 0, "100"):
        r = await client.post(
            f"/spaces/{sp}/goals", json={"name": "x", "target_cents": bad}, headers=ha
        )
        assert r.status_code == 422, bad
    goal = (await client.post(f"/spaces/{sp}/goals", json={"name": "x", "target_cents": 1_000},
                              headers=ha)).json()  # fmt: skip
    assert (await client.post(f"/spaces/{sp}/goals", json={"name": "x", "target_cents": 100},
                              headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/spaces/{sp}/goals", headers=hb)).status_code == 404
    assert (await client.get(f"/goals/{goal['id']}", headers=hb)).status_code == 404
    url = f"/goals/{goal['id']}/contributions"
    body = {"from_account_id": str(mine.id), "amount_cents": 100}
    assert (await client.post(url, json=body, headers=hb)).status_code == 404
    foreign = {"from_account_id": str(theirs.id), "amount_cents": 100}
    assert (await client.post(url, json=foreign, headers=ha)).status_code == 403
    floaty = {**body, "amount_cents": 10.5}
    assert (await client.post(url, json=floaty, headers=ha)).status_code == 422
```

- [ ] **Step 7: Rodar e ver falhar; implementar a API**

Run: `uv run pytest tests/api/test_goals_api.py -v` → FAIL (404 nas rotas).

`backend/app/api/goals.py`:
```python
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.goals.models import Goal
from app.domain.goals.service import (
    GoalProgress,
    contribute,
    create_goal,
    goal_progress,
    visible_goal,
    withdraw,
)
from app.domain.spaces.access import require_member

router = APIRouter(tags=["goals"])


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_cents: Cents
    deadline: date | None = None
    account_id: UUID | None = None


class ContributionIn(BaseModel):
    from_account_id: UUID
    amount_cents: Cents
    occurred_on: date | None = None


class WithdrawalIn(BaseModel):
    to_account_id: UUID
    amount_cents: Cents
    occurred_on: date | None = None


def _progress(p: GoalProgress) -> dict[str, Any]:
    return {
        "saved_cents": p.saved, "target_cents": p.target,
        "monthly_needed_cents": p.monthly_needed, "behind": p.behind,
    }  # fmt: skip


@router.post("/spaces/{space_id}/goals", status_code=201)
async def create(
    space_id: UUID, body: GoalIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    goal = await create_goal(
        session, actor_id=user.id, space_id=space_id, name=body.name,
        target_cents=body.target_cents, deadline=body.deadline, account_id=body.account_id,
        created_on=local_today(user.tz),
    )  # fmt: skip
    return row(goal)


@router.get("/spaces/{space_id}/goals")
async def list_goals(space_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    await require_member(session, user.id, space_id)
    goals = await session.scalars(
        select(Goal).where(Goal.space_id == space_id).order_by(Goal.created_at)
    )
    return [row(g) | _progress(await goal_progress(session, g.id, today=local_today(user.tz)))
            for g in goals]  # fmt: skip


@router.get("/goals/{goal_id}")
async def get_goal(goal_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    goal = await visible_goal(session, user.id, goal_id)
    return row(goal) | _progress(await goal_progress(session, goal.id, today=local_today(user.tz)))


@router.post("/goals/{goal_id}/contributions", status_code=201)
async def add_contribution(
    goal_id: UUID, body: ContributionIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await contribute(
        session, actor_id=user.id, goal_id=goal_id, from_account_id=body.from_account_id,
        amount_cents=body.amount_cents, on=body.occurred_on or local_today(user.tz),
    )  # fmt: skip
    return row(tx)


@router.post("/goals/{goal_id}/withdrawals", status_code=201)
async def add_withdrawal(
    goal_id: UUID, body: WithdrawalIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await withdraw(
        session, actor_id=user.id, goal_id=goal_id, to_account_id=body.to_account_id,
        amount_cents=body.amount_cents, on=body.occurred_on or local_today(user.tz),
    )  # fmt: skip
    return row(tx)
```
Em `backend/app/main.py`: acrescente `goals` ao import (`from app.api import accounts, auth, bills, budgets, cards, goals, spaces, transactions`) e `app.include_router(goals.router)`.

- [ ] **Step 8: Rodar tudo, qualidade e commit**

Run: `uv run pytest -v` → PASS; `uv run ruff format . && uv run ruff check --fix . && uv run mypy app`
```bash
cd .. && git add -A && git commit -m "feat(goals): add savings goals with contributions, withdrawals and pace"
```

---

## Task 7 (T2.7): Auditoria, exportação e exclusão (LGPD)

**Files:** Create `backend/app/domain/audit.py`, `backend/app/domain/privacy.py`, `backend/app/api/privacy.py`, `backend/tests/domain/test_audit.py`, `backend/tests/api/test_privacy_api.py`. Modify `backend/app/domain/models.py`, `backend/app/main.py` e os serviços listados no Step 5.

Regras (plano mestre T2.7, spec 9 e 14): `audit()` registra quem fez o quê em dados financeiros (sem FK para `users`: o registro sobrevive à exclusão da conta, só com o UUID). `GET /privacy/export` devolve um zip (`data.json` + `transactions.csv`) só com os espaços **de que o usuário é membro** (nada de espaços alheios; e-mails de outros membros não entram). `DELETE /privacy/account` exige a senha, apaga o espaço pessoal inteiro (e famílias de que é dono **sozinho**), tira o usuário dos demais espaços e **anonimiza** os lançamentos que ele deixou em espaços familiares (`created_by = NULL`, que a web mostra como "Usuário removido"). Dono de família **com outros membros** não pode se excluir (422 `owns_family_with_members`): transferir a posse é decisão futura. Limite conhecido: lançamentos de família feitos numa conta/cartão pessoal que será apagado perdem o vínculo (`account_id`/`card_id`/`invoice_id`/`bill_id` viram NULL) e a compra parcelada passa a contar no teto pela data do gasto; o M3 também precisa apagar `channel_links` aqui.

- [ ] **Step 1: Testes falhando (auditoria)**

`backend/tests/domain/test_audit.py`:
```python
from datetime import date

from sqlalchemy import select

from app.domain.accounts.service import create_account
from app.domain.audit import AuditLog, audit
from app.domain.bills.service import create_bill
from app.domain.budgets.service import set_budget
from app.domain.cards.service import register_card_purchase
from app.domain.goals.service import contribute, create_goal, withdraw
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.service import create_transaction
from tests.factories import make_card, make_user

D = date(2026, 11, 10)


async def test_audit_helper_adds_a_row(session):
    a = await make_user(session, "a@x.com")
    audit(session, a.id, "x.did", "thing", a.id, {"k": 1})
    await session.commit()
    row = await session.scalar(select(AuditLog))
    assert (row.actor_id, row.action, row.entity, row.entity_id) == (a.id, "x.did", "thing", a.id)
    assert row.data == {"k": 1} and row.created_at is not None


async def test_services_write_audit_rows(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await create_account(
        session, actor_id=a.id, space_id=sp, type="checking", name="Itaú",
        initial_balance_cents=100_000,
    )  # fmt: skip
    tx = await create_transaction(
        session, actor_id=a.id, space_id=sp, type="expense", amount_cents=1_000, occurred_on=D,
        account_id=acc.id,
    )  # fmt: skip
    card = await make_card(session, a, sp)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=5_000, occurred_on=D
    )  # fmt: skip
    bill = await create_bill(
        session, actor_id=a.id, space_id=sp, description="Luz", amount_cents=2_000, due_on=D
    )  # fmt: skip
    await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=D)
    await pay_invoice(
        session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=acc.id, paid_on=D,
        amount_cents=5_000,
    )  # fmt: skip
    await set_budget(session, actor_id=a.id, space_id=sp, month=D, limit_cents=10_000)
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=9_000, created_on=D
    )  # fmt: skip
    await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=500, on=D
    )  # fmt: skip
    await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=100, on=D
    )  # fmt: skip
    rows = (await session.scalars(select(AuditLog))).all()
    assert {r.action for r in rows} >= {
        "account.create", "transaction.create", "card.create", "card.purchase", "bill.create",
        "bill.pay", "invoice.pay", "budget.set", "goal.create", "goal.contribute",
        "goal.withdraw",
    }  # fmt: skip
    assert all(r.actor_id == a.id for r in rows)
    created = next(r for r in rows if r.action == "transaction.create")
    assert created.entity_id == tx.id and created.data["amount_cents"] == 1_000
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_audit.py -v`
Expected: FAIL na coleta (`ModuleNotFoundError: No module named 'app.domain.audit'`).

- [ ] **Step 3: Model e `audit()`**

`backend/app/domain/audit.py`:
```python
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(index=True)  # sem FK: sobrevive à exclusão
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[UUID] = mapped_column(index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # sem dados sensíveis
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def audit(
    session: AsyncSession, actor_id: UUID | None, action: str, entity: str, entity_id: UUID,
    data: dict[str, Any] | None = None,
) -> None:  # fmt: skip
    """Só adiciona à sessão: grava junto com o commit do serviço que chamou."""
    session.add(
        AuditLog(actor_id=actor_id, action=action, entity=entity, entity_id=entity_id, data=data or {})
    )
```
Em `backend/app/domain/models.py` acrescente `import app.domain.audit  # noqa: F401`.

- [ ] **Step 4: Migração (autogenerate) e validação em banco descartável**

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "audit log"
bash scripts/migrate_check.sh
```
Confira: só `create_table audit_log` (com índices em `actor_id` e `entity_id`). Expected: `No new upgrade operations detected.`

- [ ] **Step 5: Chamar `audit()` nos serviços que gravam**

Em cada função abaixo, **imediatamente antes do `await session.commit()` final**, insira o bloco indicado (importe `from app.domain.audit import audit` no topo do arquivo). Onde o bloco começa com `await session.flush()`, ele é necessário para o `id` já existir (UUIDs são gerados no flush).

| Arquivo · função | Bloco a inserir |
|---|---|
| `accounts/service.py` · `create_account` | `await session.flush()` + `audit(session, actor_id, "account.create", "account", acc.id, {"space_id": str(space_id), "type": type})` |
| `transactions/service.py` · `create_transaction` (o `commit` do caminho normal, não o do cartão) | `await session.flush()` + `audit(session, actor_id, "transaction.create", "transaction", tx.id, {"space_id": str(space_id), "type": type, "amount_cents": amount_cents})` |
| `cards/service.py` · `create_card` | `await session.flush()` + `audit(session, actor_id, "card.create", "card", card.id, {"space_id": str(space_id)})` |
| `cards/service.py` · `register_card_purchase` | `audit(session, actor_id, "card.purchase", "card", card.id, {"space_id": str(space_id), "amount_cents": amount_cents, "installments": installments})` |
| `bills/service.py` · `create_bill` | `await session.flush()` + `audit(session, actor_id, "bill.create", "bill", bill.id, {"space_id": str(space_id), "amount_cents": amount_cents})` |
| `payments.py` · `pay_bill` | `audit(session, actor_id, "bill.pay", "bill", bill.id, {"transaction_id": str(tx.id), "account_id": str(account_id), "amount_cents": amount})` |
| `payments.py` · `pay_invoice` | `audit(session, actor_id, "invoice.pay", "invoice", inv.id, {"transaction_id": str(tx.id), "account_id": str(acc.id), "amount_cents": amount_cents})` |
| `budgets/service.py` · `set_budget` | `audit(session, actor_id, "budget.set", "budget", budget.id, {"space_id": str(space_id), "month": start.isoformat(), "limit_cents": limit_cents})` |
| `goals/service.py` · `create_goal` | `await session.flush()` + `audit(session, actor_id, "goal.create", "goal", goal.id, {"space_id": str(space_id), "target_cents": target_cents})` |
| `goals/service.py` · `contribute` | `await session.flush()` + `audit(session, actor_id, "goal.contribute", "goal", goal.id, {"transaction_id": str(tx.id), "amount_cents": amount_cents})` |
| `goals/service.py` · `withdraw` | `await session.flush()` + `audit(session, actor_id, "goal.withdraw", "goal", goal.id, {"transaction_id": str(tx.id), "amount_cents": amount_cents})` |

Quebre as chamadas em várias linhas (`audit(\n session, ..., \n {...},\n)`) para respeitar as 100 colunas; `ruff format` ajusta.

Run: `uv run ruff format . && uv run ruff check --fix . && uv run pytest tests/domain -v` → todos PASS (incluindo `test_audit.py` e toda a suíte anterior: nenhuma regressão).

- [ ] **Step 6: Testes de API falhando (exportação e exclusão)**

`backend/tests/api/test_privacy_api.py`:
```python
import csv
import io
import json
import zipfile
from datetime import date

from sqlalchemy import func, select

from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.bills.service import create_bill
from app.domain.budgets.models import Budget, BudgetAlertSent
from app.domain.budgets.service import evaluate_thresholds, set_budget
from app.domain.cards.models import CreditCard, Invoice
from app.domain.cards.service import register_card_purchase
from app.domain.categories.models import Category
from app.domain.goals.models import Goal
from app.domain.goals.service import contribute, create_goal
from app.domain.payments import pay_bill
from app.domain.spaces.models import Space, SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import create_transaction, list_transactions
from app.domain.users.models import User
from tests.factories import PWD, auth, make_account, make_card, make_family, make_user

D = date(2026, 11, 10)


async def _tx(session, user, space, acc, amount, desc):
    return await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=D, description=desc, account_id=acc.id,
    )  # fmt: skip


async def _delete(client, user, password=PWD):
    return await client.request(
        "DELETE", "/privacy/account", json={"password": password}, headers=auth(user)
    )


async def test_export_contains_only_user_spaces(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    acc_a = await make_account(session, a.default_space_id, name="Itaú")
    acc_b = await make_account(session, b.default_space_id, name="Nubank do b")
    acc_f = await make_account(session, fam.id, name="Conjunta")
    await _tx(session, a, a.default_space_id, acc_a, 1_000, "meu-gasto")
    await _tx(session, b, fam.id, acc_f, 2_000, "gasto-familia")
    await _tx(session, b, b.default_space_id, acc_b, 3_000, "gasto-do-b")
    r = await client.get("/privacy/export", headers=auth(a))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["data.json", "transactions.csv"]
    raw = z.read("data.json").decode()
    data = json.loads(raw)
    assert {t["description"] for t in data["transactions"]} == {"meu-gasto", "gasto-familia"}
    assert {s["id"] for s in data["spaces"]} == {str(a.default_space_id), str(fam.id)}
    assert all(isinstance(t["amount_cents"], int) for t in data["transactions"])
    assert data["user"]["email"] == "a@x.com"
    assert "gasto-do-b" not in raw and "Nubank do b" not in raw and "b@x.com" not in raw
    rows = list(csv.DictReader(io.StringIO(z.read("transactions.csv").decode())))
    assert sorted(x["description"] for x in rows) == ["gasto-familia", "meu-gasto"]
    assert {x["amount_cents"] for x in rows} == {"1000", "2000"}


async def test_export_and_delete_require_auth(client):
    assert (await client.get("/privacy/export")).status_code == 401
    r = await client.request("DELETE", "/privacy/account", json={"password": PWD})
    assert r.status_code == 401


async def test_delete_account_requires_password(client, session):
    a = await make_user(session, "a@x.com")
    r = await _delete(client, a, "senha errada aqui")
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}
    assert await session.scalar(select(func.count()).select_from(User).where(User.id == a.id)) == 1


async def test_delete_account_anonymizes_family_transactions(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    a_id, b_id, pa = a.id, b.id, a.default_space_id
    fam = await make_family(session, b, a)  # b é dono; a é membro
    fam_id = fam.id
    acc_a = await make_account(session, pa, name="Itaú", initial=100_000)
    acc_f = await make_account(session, fam_id, name="Conjunta")
    card = await make_card(session, a, pa)
    await register_card_purchase(
        session, actor_id=a_id, space_id=pa, card_id=card.id, amount_cents=6_000, occurred_on=D
    )  # fmt: skip
    goal = await create_goal(
        session, actor_id=a_id, space_id=pa, name="Viagem", target_cents=9_000, created_on=D
    )  # fmt: skip
    await contribute(
        session, actor_id=a_id, goal_id=goal.id, from_account_id=acc_a.id, amount_cents=1_000, on=D
    )  # fmt: skip
    bill = await create_bill(
        session, actor_id=a_id, space_id=pa, description="Luz", amount_cents=2_000, due_on=D
    )  # fmt: skip
    await pay_bill(session, actor_id=a_id, bill_id=bill.id, account_id=acc_a.id, paid_on=D)
    await set_budget(session, actor_id=a_id, space_id=pa, month=D, limit_cents=5_000)
    assert await evaluate_thresholds(session, pa, D)  # grava alertas enviados
    await _tx(session, a, fam_id, acc_f, 3_000, "gasto-familia")
    await _tx(session, a, fam_id, acc_a, 700, "pelo-pessoal")  # família, mas na conta pessoal do a
    await _tx(session, b, fam_id, acc_f, 900, "gasto-do-b")

    ha = auth(a)  # antes do expire_all: depois disso `a.id` não pode mais ser lido
    r = await _delete(client, a)
    assert r.status_code == 204

    session.expire_all()  # o servidor usou outra sessão
    count = lambda model, *where: session.scalar(  # noqa: E731
        select(func.count()).select_from(model).where(*where)
    )
    assert await count(User, User.id == a_id) == 0
    assert await count(Space, Space.id == pa) == 0
    for model in (Account, Category, CreditCard, Bill, Goal, Budget, BudgetAlertSent, Transaction):
        assert await count(model, model.space_id == pa) == 0, model.__name__
    assert await count(Invoice) == 0  # as faturas do cartão pessoal foram junto
    assert await count(SpaceMember, SpaceMember.user_id == a_id) == 0
    assert await count(Space, Space.id == fam_id) == 1  # a família continua com o b
    txs = {t.description: t for t in await list_transactions(session, viewer_id=b_id, space_id=fam_id)}
    assert set(txs) == {"gasto-familia", "pelo-pessoal", "gasto-do-b"}
    assert txs["gasto-familia"].created_by is None and txs["gasto-familia"].amount_cents == 3_000
    assert txs["pelo-pessoal"].created_by is None and txs["pelo-pessoal"].account_id is None
    assert txs["gasto-do-b"].created_by == b_id
    assert (await client.get("/spaces", headers=ha)).status_code == 401  # o token morreu junto


async def test_delete_refused_when_owning_family_with_members(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    r = await _delete(client, a)
    assert r.status_code == 422 and r.json() == {"detail": "owns_family_with_members"}
    assert await session.scalar(select(func.count()).select_from(User).where(User.id == a.id)) == 1
    assert await session.scalar(select(func.count()).select_from(Space).where(Space.id == fam.id)) == 1


async def test_delete_removes_solo_family_owned_by_user(client, session):
    a = await make_user(session, "a@x.com")
    a_id = a.id
    from app.domain.spaces.service import create_family_space

    fam = await create_family_space(session, owner_id=a_id, name="Só eu")
    fam_id = fam.id
    acc = await make_account(session, fam_id)
    await _tx(session, a, fam_id, acc, 500, "solo")
    assert (await _delete(client, a)).status_code == 204
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(Space).where(Space.id == fam_id)) == 0
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
```

- [ ] **Step 7: Rodar e ver falhar; implementar exportação/exclusão e rotas**

Run: `uv run pytest tests/api/test_privacy_api.py -v` → FAIL (404 nas rotas).

`backend/app/domain/privacy.py`:
```python
import csv
import io
import json
import zipfile
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import row
from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.budgets.models import Budget, BudgetAlertSent, BudgetCategory
from app.domain.cards.models import CreditCard, Invoice
from app.domain.categories.models import Category
from app.domain.errors import DomainError
from app.domain.goals.models import Goal
from app.domain.spaces.models import Space, SpaceInvite, SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.users.models import RefreshToken, SignupInvite, User

EXPORT_MODELS: dict[str, Any] = {
    "accounts": Account, "categories": Category, "cards": CreditCard,
    "transactions": Transaction, "bills": Bill, "goals": Goal, "budgets": Budget,
}  # fmt: skip
CSV_COLUMNS = [
    "id", "space_id", "type", "amount_cents", "occurred_on", "description", "merchant",
    "category_id", "account_id", "counter_account_id", "card_id", "created_by",
]  # fmt: skip


async def export_user_data(session: AsyncSession, user: User) -> bytes:
    """Zip com data.json e transactions.csv dos espaços de que o usuário é membro (e só deles)."""
    space_ids = list(
        await session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == user.id))
    )
    spaces = await session.scalars(select(Space).where(Space.id.in_(space_ids)))
    data: dict[str, Any] = {
        "user": {"id": str(user.id), "name": user.name, "email": user.email, "tz": user.tz},
        "spaces": [row(s) for s in spaces],
    }
    for key, model in EXPORT_MODELS.items():
        found = await session.scalars(select(model).where(model.space_id.in_(space_ids)))
        data[key] = [row(r) for r in found]
    card_ids = [c["id"] for c in data["cards"]]
    invoices = await session.scalars(select(Invoice).where(Invoice.card_id.in_(card_ids)))
    data["invoices"] = [row(i) for i in invoices]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(data["transactions"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(data, default=str, ensure_ascii=False, indent=2))
        z.writestr("transactions.csv", buf.getvalue())
    return out.getvalue()


async def _purge_space(session: AsyncSession, space_id: Any) -> None:
    """Apaga o espaço e tudo que é dele, na ordem das chaves estrangeiras."""
    accs = select(Account.id).where(Account.space_id == space_id)
    cards = select(CreditCard.id).where(CreditCard.space_id == space_id)
    bills = select(Bill.id).where(Bill.space_id == space_id)
    invoices = select(Invoice.id).where(Invoice.card_id.in_(cards))
    # referências de OUTROS espaços (ex.: despesa da família em conta pessoal) perdem o vínculo
    refs: list[tuple[Any, Any, Any]] = [
        (Transaction, Transaction.account_id, accs),
        (Transaction, Transaction.counter_account_id, accs),
        (Transaction, Transaction.card_id, cards),
        (Transaction, Transaction.invoice_id, invoices),
        (Transaction, Transaction.bill_id, bills),
        (Goal, Goal.account_id, accs),
        (CreditCard, CreditCard.payment_account_id, accs),
    ]
    for model, col, sub in refs:
        await session.execute(
            update(model).where(model.space_id != space_id, col.in_(sub)).values({col.key: None})
        )
    await session.execute(delete(Transaction).where(Transaction.space_id == space_id))
    await session.execute(delete(SpaceMember).where(SpaceMember.space_id == space_id))
    await session.execute(delete(BudgetAlertSent).where(BudgetAlertSent.space_id == space_id))
    budgets = select(Budget.id).where(Budget.space_id == space_id)
    await session.execute(delete(BudgetCategory).where(BudgetCategory.budget_id.in_(budgets)))
    await session.execute(delete(Budget).where(Budget.space_id == space_id))
    await session.execute(delete(Goal).where(Goal.space_id == space_id))
    await session.execute(delete(Bill).where(Bill.space_id == space_id))
    await session.execute(delete(Invoice).where(Invoice.card_id.in_(cards)))
    await session.execute(delete(CreditCard).where(CreditCard.space_id == space_id))
    await session.execute(delete(Account).where(Account.space_id == space_id))
    await session.execute(delete(Category).where(Category.space_id == space_id))
    await session.execute(delete(SpaceInvite).where(SpaceInvite.space_id == space_id))
    await session.execute(delete(Space).where(Space.id == space_id))


async def delete_account(session: AsyncSession, user: User) -> None:
    """Exclusão LGPD. A senha já foi conferida pela API."""
    uid = user.id
    owned = list(await session.scalars(select(Space.id).where(Space.owner_id == uid)))
    for sid in owned:
        others = await session.scalar(
            select(func.count()).select_from(SpaceMember).where(
                SpaceMember.space_id == sid, SpaceMember.user_id != uid
            )
        )
        if others:
            raise DomainError("owns_family_with_members")
    await session.execute(
        update(User)
        .where(or_(User.id == uid, User.default_space_id.in_(owned)))
        .values(default_space_id=None)
    )
    for sid in owned:
        await _purge_space(session, sid)
    # espaços de que é só membro: os lançamentos ficam, sem autor ("Usuário removido")
    await session.execute(
        update(Transaction).where(Transaction.created_by == uid).values(created_by=None)
    )
    await session.execute(
        update(Bill).where(Bill.responsible_user_id == uid).values(responsible_user_id=None)
    )
    await session.execute(delete(SpaceMember).where(SpaceMember.user_id == uid))
    await session.execute(delete(SpaceInvite).where(SpaceInvite.created_by == uid))
    await session.execute(
        update(SignupInvite).where(SignupInvite.used_by == uid).values(used_by=None)
    )
    await session.execute(delete(SignupInvite).where(SignupInvite.created_by == uid))
    await session.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
    await session.execute(delete(User).where(User.id == uid))
    await session.commit()
```

`backend/app/api/privacy.py`:
```python
import asyncio

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.auth import MAX_FAILS, _hit
from app.api.deps import CurrentUser, Session
from app.core.redis import redis
from app.core.security import verify_password
from app.domain.privacy import delete_account, export_user_data

router = APIRouter(prefix="/privacy", tags=["privacy"])


class DeleteIn(BaseModel):
    password: str = Field(max_length=128)


@router.get("/export")
async def export(user: CurrentUser, session: Session) -> Response:
    return Response(
        content=await export_user_data(session, user),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="abby-cash-export.zip"'},
    )


@router.delete("/account", status_code=204)
async def delete(body: DeleteIn, user: CurrentUser, session: Session) -> None:
    key = f"delete_pw:{user.id}"
    await _hit(key, MAX_FAILS)  # re-autenticação também é alvo de força bruta
    if not await asyncio.to_thread(verify_password, body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    await redis.delete(key)
    await delete_account(session, user)
```
Em `backend/app/main.py`: acrescente `privacy` ao import (`from app.api import accounts, auth, bills, budgets, cards, goals, privacy, spaces, transactions`) e `app.include_router(privacy.router)`.

- [ ] **Step 8: Rodar tudo, qualidade e commit**

Run: `uv run pytest -v` → todos PASS; `uv run ruff format . && uv run ruff check --fix . && uv run mypy app`; `bash scripts/migrate_check.sh`.
```bash
cd .. && git add -A && git commit -m "feat(privacy): add audit log, data export and account deletion"
```

---

## Fechamento do marco

- [ ] Revisão por tarefa: o revisor do subagent-driven-development aprova cada task antes da próxima (foco: acesso cruzado entre espaços, dinheiro sempre `int`, regra de datas de fechamento, privacidade do extrato).
- [ ] Atualize o `CLAUDE.md` (seção nova "Domínio financeiro (M2)") com: serviços em `app/domain/<área>/service.py` recebem `session` primeiro e commitam no fim; `DomainError` = 422 (`detail` com o código) e `HTTPException` para acesso; conta/cartão de outro espaço só via `use_account`/`use_card` (403) e leitura via `visible_*` (404); extrato compartilhado via `build_statement`; gasto do teto só por `month_spending`; migrações novas validadas com `bash backend/scripts/migrate_check.sh`. Commit: `docs: document M2 domain conventions`.
- [ ] `superpowers:verification-before-completion`: rode a suíte completa e cole a saída real no PR:
  ```bash
  cd ~/abby-cash/backend && uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy app
  bash scripts/migrate_check.sh
  uv run python -c "from app.main import app; print(sorted({r.path for r in app.routes if r.path.startswith(('/spaces','/accounts','/cards','/invoices','/bills','/goals','/privacy'))}))"
  ```
  Confira que a lista de rotas bate com a tabela "Rotas REST do marco".
- [ ] Verificação manual rápida de privacidade e de centavos (opcional, com `docker compose ... up`): criar a conta de uma família por `POST /spaces/{id}/accounts`, lançar `#pessoal` com a esposa e ver o extrato com o marido (`private_total_cents`).
- [ ] `/code-review high` no diff `main...feat/m2-domain`; corrija, rode os testes de novo; repita até limpar.
- [ ] `git push -u origin feat/m2-domain` e abra o PR contra `main` (**antes, confirme que a `main` do remoto contém o M1**; se não, pedir ao dono para publicá-la); depois `/code-review high --comment <PR>`.
- [ ] Parar e pedir a revisão do PR ao dono.

## Autorrevisão do plano

- **Ensaio real:** todo o código e os testes deste plano foram aplicados numa cópia do repositório (M1 + M2): 171 testes PASS, `ruff` e `mypy app` limpos, e `alembic revision --autogenerate` + `upgrade head` + `alembic check` sem diferenças (o executor ainda roda cada passo na ordem, com a falha esperada antes de cada implementação).
- **Cobertura do plano mestre:** T2.1 (4 testes nomeados: `test_balance_formula_with_transfers`, `test_cannot_use_account_from_space_user_is_not_member`, `test_amount_must_be_positive`, `test_list_transactions_filters_by_period_category_account`), T2.2 (`test_private_items_aggregated_for_non_member_viewer`, `test_owner_sees_all_items`), T2.3 (7 testes nomeados, incluindo `test_split_1000_in_3` = `[334, 333, 333]`), T2.4 (6 testes nomeados), T2.5 (6 testes nomeados; `test_goal_contribution_not_counted` fica no T2.6, Step 5, por depender de metas), T2.6 (3 testes nomeados), T2.7 (`test_export_contains_only_user_spaces`, `test_delete_account_anonymizes_family_transactions`).
- **Extras pedidos:** fechamento no dia, dia 31 em fevereiro/abril/bissexto, 23:30 São Paulo (puro e pela API com `local_today` simulado), 1000/3, agregação privada em extrato e fatura (domínio e HTTP), membro removido perde acesso (T2.2 e T2.3), regras de contagem do teto (parcela pelo mês de vencimento; pagamento de fatura, aportes e retiradas fora; conta a pagar pela data do pagamento; espaço próprio), alertas uma vez por limiar (e salto), pagamento sempre com origem e gerando lançamento (conta, carteira, fatura), pagamento parcial de fatura, recorrência mensal dia 31 (+ anual e a cada N meses).
- **Foco de revisão 1 e 4 do plano mestre:** datas de fechamento (T2.3) e privacidade em cartão compartilhado + membro removido (T2.2/T2.3).
- **Lacuna do M1:** `POST /spaces/{id}/accounts` (T2.1) cobre o espaço familiar sem contas.
- **Consistência de nomes:** `use_account`/`use_card` (403, escrita) vs `visible_account`/`visible_card`/`visible_invoice`/`visible_goal` (404, leitura); `build_statement` compartilhado por extrato de conta e de fatura; `signed` único para saldo e extrato; `refresh_status` e `bill_paid_cents` em `bills/status.py` usados por faturas (T2.3) e pagamentos (T2.4).
- **Divergências deliberadas e declaradas:** `session` como 1º parâmetro; `create_transaction(card_id=...)` delega para `register_card_purchase` (1 parcela) e **não** aceita `goal_id` (metas usam `contribute`/`withdraw`); `Bill` e `transactions.bill_id` nascem no T2.3; editar/apagar lançamento fica para M3/M7.
- **Limites conhecidos (ponytail):** saldo calculado em Python (trocar por SUM no SQL acima de ~10k lançamentos); criação de fatura e avaliação de limiar sem lock (restrições únicas protegem; o chamador repete); alertas enviados não são zerados ao alterar o teto; dono de família com membros não pode excluir a conta.
