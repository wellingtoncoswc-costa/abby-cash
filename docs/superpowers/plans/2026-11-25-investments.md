# Investimentos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seção "Investimentos": cadastrar ativos (ações, FIIs, CDB, LCI, LCA), aportar/resgatar a partir de uma conta, buscar o preço do dia pelo ticker e acompanhar rentabilidade e evolução num dashboard.

**Architecture:** `investments` + `investment_movements` + `price_quotes` (fechamento diário). Ações/FIIs: cotação da brapi.dev (job diário + busca sob demanda), valor = quantidade × último fechamento. Renda fixa: valor calculado dia a dia, bruto, com o CDI já baixado (`cdi_rates`) ou taxa prefixada (dias úteis/252). Aporte/resgate geram transferência (sai/entra na conta), como `goals.contribute`.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, ARQ, httpx, pydantic, pytest; React + TS + vitest.

Spec: `docs/superpowers/specs/2026-11-25-investments-design.md`.
Pré-requisitos: infra de testes de pé (`docker compose -f infra/docker-compose.dev.yml up -d postgres redis`); branch nova a partir da `main` (`git switch -c feat/investments main`). **Rode o pytest uma vez por vez** (compartilha o banco de teste).

**Desvios deliberados da spec (YAGNI):** sem `closed_at`, sem `origin`/`source_message_id` nos movimentos (chat fora do escopo), sem apagar movimento (corrige-se com resgate). `DELETE` do ativo só sem movimentos. Escala de taxa: `rate_bp` = % × 100 (110% do CDI = `11000`; 12,5% a.a. = `1250`).

## File Structure

- `backend/app/core/config.py` (+`BRAPI_TOKEN`), `.env.example`, `infra/docker-compose.*.yml` (repassar a env, se o `OPENAI_API_KEY` estiver lá).
- `backend/app/domain/investments/__init__.py`, `models.py`, `quotes.py` (cliente brapi + cache de fechamentos), `valuation.py` (funções puras da renda fixa), `service.py` (cadastro, aporte, resgate, dashboard).
- `backend/migrations/versions/f7a8b9c0d1e2_investments.py`; registrar em `backend/app/domain/models.py`.
- `backend/app/jobs/investments.py` + cron em `backend/app/worker.py`.
- `backend/app/api/investments.py` + `include_router` em `backend/app/main.py`.
- Testes: `backend/tests/domain/test_investments_*.py`, `backend/tests/api/test_investments_api.py`, `backend/tests/jobs/test_investments_job.py`.
- Web: `web/src/pages/investments.tsx`, `web/src/pages/investments.test.tsx`, `router.tsx`, `layout.tsx`, `api/types.ts`, `api/schema.d.ts` (gerado).

---

### Task 1: Config, modelos e migração

**Files:** modify `config.py`, `.env.example`, `domain/models.py`; create `investments/__init__.py` (vazio), `investments/models.py`, migração.

- [ ] **Step 1: Config** — em `Settings` (ao lado de `OPENAI_API_KEY`): `BRAPI_TOKEN: str = ""`. Em `.env.example`: `BRAPI_TOKEN=`. Se `infra/docker-compose.prod.yml` lista `OPENAI_API_KEY` explicitamente, adicione `BRAPI_TOKEN` igual (`grep -rn OPENAI_API_KEY infra`).

- [ ] **Step 2: Models** (`investments/models.py`)

```python
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Investment(Base):
    __tablename__ = "investments"
    __table_args__ = (
        CheckConstraint("kind IN ('stock', 'fii', 'cdb', 'lci', 'lca')", name="ck_investments_kind"),
        CheckConstraint(
            "rate_type IS NULL OR rate_type IN ('cdi_pct', 'fixed')", name="ck_investments_rate_type"
        ),
        CheckConstraint("rate_bp IS NULL OR rate_bp > 0", name="ck_investments_rate_bp"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # stock | fii | cdb | lci | lca
    name: Mapped[str] = mapped_column(String(100))
    ticker: Mapped[str | None] = mapped_column(String(12))  # só stock/fii
    rate_type: Mapped[str | None] = mapped_column(String(8))  # cdi_pct | fixed (renda fixa)
    rate_bp: Mapped[int | None] = mapped_column(Integer)  # % x 100: 110% CDI = 11000; 12,5% a.a. = 1250
    maturity_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestmentMovement(Base):
    __tablename__ = "investment_movements"
    __table_args__ = (
        CheckConstraint("kind IN ('buy', 'redeem')", name="ck_investment_movements_kind"),
        CheckConstraint("amount_cents > 0", name="ck_investment_movements_amount_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    investment_id: Mapped[UUID] = mapped_column(ForeignKey("investments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    occurred_on: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))  # só stock/fii
    unit_price_cents: Mapped[int | None] = mapped_column(BigInteger)  # preço da data, guardado
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceQuote(Base):
    """Fechamento diário de um ticker (base da evolução e das comparações)."""

    __tablename__ = "price_quotes"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    on_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close_cents: Mapped[int] = mapped_column(BigInteger)
```

Em `domain/models.py`, junto dos outros imports: `import app.domain.investments.models  # noqa: F401`.

- [ ] **Step 3: Migração** `migrations/versions/f7a8b9c0d1e2_investments.py` (`down_revision = "d0e1f2a3b4c5"` se a Parte A já foi mergeada; senão `"c9d0e1f2a3b4"` — confira com `ls migrations/versions` e `grep -rn "down_revision" migrations/versions | grep <head>` para não criar duas heads). Crie as 3 tabelas espelhando os models (mesmos nomes de constraint, `sa.Uuid()`, `sa.Numeric(18, 6)`, `sa.BigInteger()`, `server_default=sa.func.now()` em `created_at`, índices `ix_investments_space_id` e `ix_investment_movements_investment_id`; PK composta `(ticker, on_date)` em `price_quotes`) e `downgrade` com `drop_table` na ordem inversa.

- [ ] **Step 4: Verificar** — `cd backend && bash scripts/migrate_check.sh` → termina sem diferenças ("No new upgrade operations detected"). Se acusar diferença, ajuste a migração ao model.

- [ ] **Step 5: Commit** — `git add backend .env.example infra && git commit -m "feat(investments): models and migration"`

---

### Task 2: Cliente de cotação (brapi)

**Files:** create `investments/quotes.py`, `backend/tests/domain/test_investments_quotes.py`.

- [ ] **Step 1: Teste que falha**

```python
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.domain.errors import DomainError
from app.domain.investments.quotes import fetch_quotes, latest_close, range_for, upsert_quotes

BODY = '{"results":[{"symbol":"PETR4","historicalDataPrice":[' \
       '{"date":1763996400,"close":38.5},{"date":1764082800,"close":null},' \
       '{"date":1764169200,"close":38.456}]}]}'


def _transport(status=200, body=BODY):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/quote/PETR4" and "token" in req.url.params
        return httpx.Response(status, text=body)
    return httpx.MockTransport(handler)


async def test_fetch_parses_prices_in_cents_and_skips_null():
    qs = await fetch_quotes("PETR4", 30, _transport())
    assert [q.close_cents for q in qs] == [3850, 3846]  # 38,456 -> 3846 (arredonda)


async def test_unknown_or_malformed_ticker():
    with pytest.raises(DomainError, match="unknown_ticker"):
        await fetch_quotes("PETR4", 30, _transport(404, "{}"))
    with pytest.raises(DomainError, match="unknown_ticker"):
        await fetch_quotes("../x", 30, _transport())  # nunca vira caminho de URL


def test_range_for():
    assert (range_for(3), range_for(40), range_for(5000)) == ("5d", "3mo", "max")


async def test_upsert_and_latest_close(session):
    qs = await fetch_quotes("PETR4", 30, _transport())
    await upsert_quotes(session, "PETR4", qs)
    await upsert_quotes(session, "PETR4", qs)  # idempotente
    await session.commit()
    last = await latest_close(session, "PETR4", date(2099, 1, 1))
    assert last is not None and last.close_cents == 3846
    assert await latest_close(session, "PETR4", date(2000, 1, 1)) is None
```

Run: `cd backend && uv run pytest tests/domain/test_investments_quotes.py -q` → FAIL (módulo não existe).

- [ ] **Step 2: Implementação** (`investments/quotes.py`)

```python
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.errors import DomainError
from app.domain.investments.models import PriceQuote

URL = "https://brapi.dev/api/quote/{ticker}"
TICKER = re.compile(r"[A-Z0-9]{4,12}")
RANGES = [(5, "5d"), (30, "1mo"), (90, "3mo"), (180, "6mo"), (365, "1y"), (730, "2y"),
          (1825, "5y"), (3650, "10y")]  # fmt: skip


class _Bar(BaseModel):
    date: int  # epoch em segundos
    close: Decimal | None = None


class _Result(BaseModel):
    historicalDataPrice: list[_Bar] = []  # noqa: N815 (nome do campo da brapi)


class _Resp(BaseModel):
    results: list[_Result] = []


@dataclass(frozen=True)
class Quote:
    on_date: date
    close_cents: int


def range_for(days: int) -> str:
    return next((r for d, r in RANGES if days <= d), "max")


async def fetch_quotes(
    ticker: str, days: int, transport: httpx.AsyncBaseTransport | None = None
) -> list[Quote]:
    """Fechamentos diários dos últimos `days` dias (brapi.dev). Sem redirect; formato inválido falha."""
    if not TICKER.fullmatch(ticker):
        raise DomainError("unknown_ticker")
    s = get_settings()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport) as c:
        r = await c.get(
            URL.format(ticker=ticker),
            params={"range": range_for(days), "interval": "1d", "token": s.BRAPI_TOKEN},
        )
    if r.status_code == 404:
        raise DomainError("unknown_ticker")
    r.raise_for_status()
    data = _Resp.model_validate(json.loads(r.text, parse_float=Decimal))
    if not data.results:
        raise DomainError("unknown_ticker")
    tz = ZoneInfo(s.DEFAULT_TZ)
    return [
        Quote(
            datetime.fromtimestamp(b.date, tz).date(),
            int((b.close * 100).quantize(Decimal(1), ROUND_HALF_EVEN)),
        )
        for b in data.results[0].historicalDataPrice
        if b.close is not None
    ]


async def upsert_quotes(session: AsyncSession, ticker: str, quotes: list[Quote]) -> None:
    """Não faz commit."""
    for q in quotes:
        await session.execute(
            insert(PriceQuote)
            .values(ticker=ticker, on_date=q.on_date, close_cents=q.close_cents)
            .on_conflict_do_update(
                index_elements=["ticker", "on_date"], set_={"close_cents": q.close_cents}
            )
        )


async def latest_close(session: AsyncSession, ticker: str, on: date) -> PriceQuote | None:
    return (
        await session.scalars(
            select(PriceQuote)
            .where(PriceQuote.ticker == ticker, PriceQuote.on_date <= on)
            .order_by(PriceQuote.on_date.desc())
            .limit(1)
        )
    ).first()
```

- [ ] **Step 3:** `uv run pytest tests/domain/test_investments_quotes.py -q` → PASS. (Os epochs de teste caem em dias distintos em `America/Sao_Paulo`; se algum cair no mesmo dia, ajuste os valores.)

- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(investments): brapi quotes client"`

---

### Task 3: Valor da renda fixa (funções puras)

**Files:** create `investments/valuation.py`, `backend/tests/domain/test_investments_valuation.py`.

- [ ] **Step 1: Teste que falha**

```python
from datetime import date
from decimal import Decimal

from app.domain.investments.valuation import cdi_factors, fixed_value, weekday_factors

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)  # seg, ter, qua


def test_cdi_pct_compounds_from_the_day_after_the_buy():
    # CDI 0,05%/dia; 100% do CDI; aporte de R$ 1.000,00 em D1
    f = cdi_factors({D2: Decimal("0.05"), D3: Decimal("0.05")}, 10000)
    assert fixed_value([(D1, 100_000)], f, D1) == 100_000  # no dia do aporte não rende
    assert fixed_value([(D1, 100_000)], f, D2) == 100_050
    assert fixed_value([(D1, 100_000)], f, D3) == 100_100  # 100_050 * 1,0005 = 100_100,02


def test_pct_of_cdi_scales_rate():
    f = cdi_factors({D2: Decimal("0.05")}, 11000)  # 110% do CDI
    assert fixed_value([(D1, 100_000)], f, D2) == 100_055


def test_redeem_reduces_balance_and_later_buys_start_late():
    f = cdi_factors({D2: Decimal("0.05"), D3: Decimal("0.05")}, 10000)
    moves = [(D1, 100_000), (D2, -50_050), (D2, 20_000)]
    # D2: 100_000 -> 100_050; resgate -50_050 e aporte +20_000 no mesmo dia => 70_000
    assert fixed_value(moves, f, D2) == 70_000
    assert fixed_value(moves, f, D3) == 70_035


def test_fixed_rate_uses_weekdays_over_252():
    f = weekday_factors(D1, D3, 1250)  # 12,5% a.a.; D2 e D3 são dias úteis
    assert set(f) == {D2, D3}
    v = fixed_value([(D1, 1_000_000)], f, D3)
    assert 1_000_000 * 1.125 ** (2 / 252) - 1 < v < 1_000_000 * 1.125 ** (2 / 252) + 1
```

Run → FAIL.

- [ ] **Step 2: Implementação** (`investments/valuation.py`)

```python
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal


def cdi_factors(rates: dict[date, Decimal], pct_bp: int) -> dict[date, Decimal]:
    """Fator de cada dia com CDI publicado: 1 + CDI diário (%) x % do CDI contratado."""
    return {d: 1 + r / 100 * Decimal(pct_bp) / 10000 for d, r in rates.items()}


def weekday_factors(start: date, end: date, rate_bp: int) -> dict[date, Decimal]:
    """Taxa prefixada a.a.: (1+taxa)^(1/252) por dia útil em (start, end].
    # ponytail: sem calendário de feriados (conta feriado como dia útil); ok p/ valor bruto estimado"""
    f = (1 + Decimal(rate_bp) / 10000) ** (Decimal(1) / 252)
    days = (start + timedelta(n) for n in range(1, (end - start).days + 1))
    return {d: f for d in days if d.weekday() < 5}


def fixed_value(
    moves: list[tuple[date, int]], factors: dict[date, Decimal], on: date
) -> int:
    """Saldo bruto em `on`, em centavos. `moves`: (data, +aporte/−resgate). O fator de um dia
    rende sobre o saldo do início do dia (movimentos do próprio dia só rendem a partir do seguinte)."""
    by_day: dict[date, int] = {}
    for d, c in moves:
        by_day[d] = by_day.get(d, 0) + c
    bal = Decimal(0)
    for d in sorted(set(factors) | set(by_day)):
        if d > on:
            break
        bal = bal * factors.get(d, 1) + by_day.get(d, 0)
    return int(bal.quantize(Decimal(1), ROUND_HALF_EVEN))
```

- [ ] **Step 3:** `uv run pytest tests/domain/test_investments_valuation.py -q` → PASS. Se `test_redeem...` divergir em 1 centavo por arredondamento, recalcule o valor esperado à mão (100_050 − 50_050 + 20_000 = 70_000; ×1,0005 = 70_035) e confirme que a lógica, não o teste, está certa.

- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(investments): fixed income valuation"`

---

### Task 4: Serviço — cadastro, aporte, resgate

**Files:** create `investments/service.py`, `backend/tests/domain/test_investments_service.py`.

- [ ] **Step 1: Teste que falha** (cotação via `monkeypatch` em `service.fetch_quotes`)

```python
from datetime import date
from decimal import Decimal

import pytest

from app.domain.errors import DomainError
from app.domain.investments import service as svc
from app.domain.investments.quotes import Quote
from app.domain.transactions.service import account_balance
from tests.factories import make_account, make_user

D = date(2026, 1, 15)


@pytest.fixture
def quotes(monkeypatch):
    async def fake(ticker, days, transport=None):
        if ticker == "NOPE3":
            raise DomainError("unknown_ticker")
        return [Quote(date(2026, 1, 14), 3800), Quote(D, 3850)]
    monkeypatch.setattr(svc, "fetch_quotes", fake)


async def _stock(session, user):
    return await svc.create_investment(
        session, actor_id=user.id, space_id=user.default_space_id, kind="stock", name="Petrobras",
        ticker="petr4", today=D,
    )  # fmt: skip


async def test_create_validates_kind_fields_and_ticker(session, quotes):
    a = await make_user(session, "a@x.com")
    inv = await _stock(session, a)
    assert inv.ticker == "PETR4"
    sp = a.default_space_id
    with pytest.raises(DomainError, match="unknown_ticker"):
        await svc.create_investment(session, actor_id=a.id, space_id=sp, kind="stock",
                                    name="x", ticker="NOPE3", today=D)  # fmt: skip
    with pytest.raises(DomainError, match="invalid_investment"):  # CDB sem taxa
        await svc.create_investment(session, actor_id=a.id, space_id=sp, kind="cdb",
                                    name="CDB", today=D)  # fmt: skip
    with pytest.raises(DomainError, match="invalid_investment"):  # ação sem ticker
        await svc.create_investment(session, actor_id=a.id, space_id=sp, kind="fii",
                                    name="x", today=D)  # fmt: skip


async def test_buy_stock_uses_dated_price_and_moves_money(session, quotes):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    inv = await _stock(session, a)
    m = await svc.buy(session, actor_id=a.id, investment_id=inv.id, account_id=acc.id,
                      on=D, quantity=Decimal("10"), today=D)  # fmt: skip
    assert (m.unit_price_cents, m.amount_cents) == (3850, 38_500)  # preço do dia, guardado
    assert await account_balance(session, acc.id) == 61_500
    edited = await svc.buy(session, actor_id=a.id, investment_id=inv.id, account_id=acc.id,
                           on=D, quantity=Decimal("1"), unit_price_cents=4000, today=D)  # fmt: skip
    assert edited.amount_cents == 4000  # preço editável (preço médio da corretora)


async def test_redeem_limits_and_returns_money(session, quotes):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    inv = await _stock(session, a)
    await svc.buy(session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
                  quantity=Decimal("10"), today=D)  # fmt: skip
    with pytest.raises(DomainError, match="insufficient_position"):
        await svc.redeem(session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
                         quantity=Decimal("10.5"), today=D)  # fmt: skip
    await svc.redeem(session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
                     quantity=Decimal("4"), today=D)  # fmt: skip
    assert await account_balance(session, acc.id) == 61_500 + 15_400


async def test_fixed_income_buy_redeem_and_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    cdb = await svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="cdb", name="CDB 110%",
        rate_type="cdi_pct", rate_bp=11000, today=D,
    )  # fmt: skip
    await svc.buy(session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
                  amount_cents=50_000, today=D)  # fmt: skip
    with pytest.raises(DomainError, match="insufficient_position"):
        await svc.redeem(session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
                         amount_cents=50_001, today=D)  # fmt: skip
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:  # outro usuário não acessa
        await svc.buy(session, actor_id=b.id, investment_id=cdb.id, account_id=acc.id, on=D,
                      amount_cents=1, today=D)  # fmt: skip
    assert e.value.status_code in (403, 404)
```

Run → FAIL.

- [ ] **Step 2: Implementação** (`investments/service.py`). Imports: `Decimal, ROUND_HALF_EVEN`, `UUID`, `HTTPException`, `select`, `AsyncSession`, `use_account` (`app.domain.accounts.access`), `audit`, `DomainError`, `require_member` (`app.domain.spaces.access`), `Transaction`, `check_common` (`transactions.rules`), `CdiRate` (`pockets.models`), e do próprio pacote `Investment, InvestmentMovement`, `fetch_quotes, latest_close, upsert_quotes`, `cdi_factors, fixed_value, weekday_factors`.

```python
VARIABLE, FIXED = ("stock", "fii"), ("cdb", "lci", "lca")


async def visible_investment(
    session: AsyncSession, viewer_id: UUID, investment_id: UUID, *, lock: bool = False
) -> Investment:
    inv = await session.get(Investment, investment_id, with_for_update=lock)
    if inv is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, inv.space_id)
    return inv


async def create_investment(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, kind: str, name: str, today: date,
    ticker: str | None = None, rate_type: str | None = None, rate_bp: int | None = None,
    maturity_on: date | None = None, transport: Any = None,
) -> Investment:  # fmt: skip
    await require_member(session, actor_id, space_id)
    variable = kind in VARIABLE
    ticker = ticker.strip().upper() if ticker else None
    ok = (
        (variable and ticker and rate_type is None and rate_bp is None)
        or (kind in FIXED and not ticker and rate_type in ("cdi_pct", "fixed") and rate_bp)
    )  # fmt: skip
    if not ok:
        raise DomainError("invalid_investment")
    if variable:  # valida o ticker e já guarda o histórico recente
        assert ticker is not None
        await upsert_quotes(session, ticker, await fetch_quotes(ticker, 30, transport))
    inv = Investment(
        space_id=space_id, kind=kind, name=name, ticker=ticker, rate_type=rate_type,
        rate_bp=rate_bp, maturity_on=maturity_on,
    )  # fmt: skip
    session.add(inv)
    await session.flush()
    audit(session, actor_id, "investment.create", "investment", inv.id,
          {"space_id": str(space_id), "kind": kind})  # fmt: skip
    await session.commit()
    return inv


async def movements(session: AsyncSession, investment_id: UUID) -> list[InvestmentMovement]:
    rows = await session.scalars(
        select(InvestmentMovement)
        .where(InvestmentMovement.investment_id == investment_id)
        .order_by(InvestmentMovement.occurred_on, InvestmentMovement.created_at)
    )
    return list(rows)


def position_qty(movs: list[InvestmentMovement], on: date | None = None) -> Decimal:
    return sum(
        ((m.quantity or Decimal(0)) * (1 if m.kind == "buy" else -1)
         for m in movs if on is None or m.occurred_on <= on),
        Decimal(0),
    )  # fmt: skip


async def fixed_factors(
    session: AsyncSession, inv: Investment, start: date, end: date
) -> dict[date, Decimal]:
    assert inv.rate_bp is not None
    if inv.rate_type == "fixed":
        return weekday_factors(start, end, inv.rate_bp)
    rows = await session.execute(
        select(CdiRate.on_date, CdiRate.daily_pct).where(CdiRate.on_date > start, CdiRate.on_date <= end)
    )
    return cdi_factors({d: p for d, p in rows}, inv.rate_bp)


def fixed_pairs(movs: list[InvestmentMovement]) -> list[tuple[date, int]]:
    return [(m.occurred_on, m.amount_cents if m.kind == "buy" else -m.amount_cents) for m in movs]


async def fixed_value_on(
    session: AsyncSession, inv: Investment, movs: list[InvestmentMovement], on: date
) -> int:
    pairs = [p for p in fixed_pairs(movs) if p[0] <= on]
    if not pairs:
        return 0
    start = min(d for d, _ in pairs)
    return fixed_value(pairs, await fixed_factors(session, inv, start, on), on)


async def _price_on(
    session: AsyncSession, inv: Investment, on: date, today: date, transport: Any
) -> int:
    assert inv.ticker is not None
    q = await latest_close(session, inv.ticker, on)
    if q is None:  # data anterior ao histórico guardado: busca sob demanda
        await upsert_quotes(
            session, inv.ticker, await fetch_quotes(inv.ticker, (today - on).days + 5, transport)
        )
        q = await latest_close(session, inv.ticker, on)
    if q is None:
        raise DomainError("no_quote")
    return q.close_cents


async def _move(
    session: AsyncSession, *, actor_id: UUID, investment_id: UUID, account_id: UUID, on: date,
    kind: str, amount_cents: int | None, quantity: Decimal | None,
    unit_price_cents: int | None, today: date, transport: Any,
) -> InvestmentMovement:  # fmt: skip
    inv = await visible_investment(session, actor_id, investment_id, lock=kind == "redeem")
    await use_account(session, actor_id, account_id)
    movs = await movements(session, inv.id)
    if inv.kind in VARIABLE:
        if quantity is None or quantity <= 0:
            raise DomainError("invalid_quantity")
        if kind == "redeem" and quantity > position_qty(movs):
            raise DomainError("insufficient_position")
        price = unit_price_cents or await _price_on(session, inv, on, today, transport)
        amount = int((quantity * price).quantize(Decimal(1), ROUND_HALF_EVEN))
    else:
        quantity = unit_price_cents = None
        if amount_cents is None:
            raise DomainError("invalid_amount")
        amount, price = amount_cents, None
        if kind == "redeem" and amount > await fixed_value_on(session, inv, movs, on):
            raise DomainError("insufficient_position")
    await check_common(
        session, actor_id=actor_id, space_id=inv.space_id, type="transfer", amount_cents=amount,
        category_id=None, occurred_on=on,
    )  # fmt: skip
    buy = kind == "buy"
    tx = Transaction(
        space_id=inv.space_id, type="transfer", amount_cents=amount, occurred_on=on,
        description=f"{'Aporte' if buy else 'Resgate'}: {inv.name}",
        account_id=account_id if buy else None, counter_account_id=None if buy else account_id,
        created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    mv = InvestmentMovement(
        investment_id=inv.id, kind=kind, occurred_on=on, quantity=quantity,
        unit_price_cents=price, amount_cents=amount, account_id=account_id, transaction_id=tx.id,
    )  # fmt: skip
    session.add(mv)
    await session.flush()
    audit(session, actor_id, f"investment.{kind}", "investment", inv.id,
          {"amount_cents": amount, "transaction_id": str(tx.id)})  # fmt: skip
    await session.commit()
    return mv


async def buy(session: AsyncSession, *, today: date, transport: Any = None, **kw: Any) -> InvestmentMovement:
    return await _move(session, kind="buy", today=today, transport=transport,
                       **{"amount_cents": None, "quantity": None, "unit_price_cents": None, **kw})  # fmt: skip


async def redeem(session: AsyncSession, *, today: date, transport: Any = None, **kw: Any) -> InvestmentMovement:
    return await _move(session, kind="redeem", today=today, transport=transport,
                       **{"amount_cents": None, "quantity": None, "unit_price_cents": None, **kw})  # fmt: skip
```

(Imports extras: `date`, `Any`. `buy`/`redeem` aceitam os kwargs `investment_id, account_id, on, amount_cents, quantity, unit_price_cents` + `actor_id`; o dict de defaults evita repetir a assinatura.)

- [ ] **Step 3:** `uv run pytest tests/domain/test_investments_service.py -q` → PASS; `uv run ruff check . && uv run ruff format . && uv run mypy app` limpos (ajuste tipos dos `**kw` se o mypy reclamar, ex.: assinaturas explícitas).

- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(investments): create, buy and redeem"`

---

### Task 5: Dashboard (serviço)

**Files:** modify `investments/service.py`; create `backend/tests/domain/test_investments_dashboard.py`.

- [ ] **Step 1: Teste que falha**

```python
from datetime import date
from decimal import Decimal

from app.domain.investments import service as svc
from app.domain.investments.models import PriceQuote
from tests.factories import make_account, make_user
from tests.domain.test_investments_service import quotes  # noqa: F401  (fixture)

D, TODAY = date(2026, 1, 14), date(2026, 1, 16)


async def test_dashboard_profit_series_and_allocation(session, quotes):  # noqa: F811
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=1_000_000)
    inv = await svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="stock", name="Petrobras",
        ticker="PETR4", today=TODAY,
    )  # fmt: skip
    await svc.buy(session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
                  quantity=Decimal("10"), today=TODAY)  # compra a 38,00 (fechamento do dia 14)
    cdb = await svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="cdb", name="CDB",
        rate_type="fixed", rate_bp=1250, today=TODAY,
    )  # fmt: skip
    await svc.buy(session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
                  amount_cents=100_000, today=TODAY)  # fmt: skip
    d = await svc.dashboard(session, viewer_id=a.id, space_id=a.default_space_id, today=TODAY)
    stock = next(x for x in d["assets"] if x["ticker"] == "PETR4")
    assert stock["quantity"] == "10" and stock["avg_price_cents"] == 3800
    assert (stock["price_cents"], stock["value_cents"]) == (3850, 38_500)  # último fechamento
    assert stock["profit_cents"] == 500 and stock["day_change_bp"] == 131  # 38,50 vs 38,00
    assert d["contributed_cents"] == 138_000
    assert d["current_cents"] == sum(x["value_cents"] for x in d["assets"])
    assert d["profit_cents"] == d["current_cents"] - 138_000
    assert {k["kind"] for k in d["by_kind"]} == {"stock", "cdb"}
    assert d["series"][0]["on"] == D and d["series"][-1]["on"] == TODAY
    assert d["series"][0]["contributed_cents"] == 138_000


async def test_dashboard_empty(session):
    a = await make_user(session, "a@x.com")
    d = await svc.dashboard(session, viewer_id=a.id, space_id=a.default_space_id, today=TODAY)
    assert d["assets"] == [] and d["series"] == [] and d["profit_bp"] is None
```

(`quotes` fake devolve 38,00 em 14/01 e 38,50 em 15/01; sem cotação em 16/01 o último fechamento é o de 15/01. `day_change_bp` = (3850−3800)×10000//3800 = 131.)

Run → FAIL.

- [ ] **Step 2: Implementação** — acrescente a `service.py` (imports: `bisect`, `timedelta`, `PriceQuote`):

```python
def _bp(num: int, den: int) -> int | None:
    return num * 10000 // den if den > 0 else None


async def dashboard(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, today: date, days: int = 365
) -> dict[str, Any]:
    """Posição atual por ativo, totais, alocação por tipo e série diária (valor x aportado).
    # ponytail: série recalculada a cada chamada (O(dias x ativos)); cachear se passar de ~50 ativos."""
    await require_member(session, viewer_id, space_id)
    invs = list(await session.scalars(select(Investment).where(Investment.space_id == space_id)))
    data = {i.id: await movements(session, i.id) for i in invs}
    firsts = [m[0].occurred_on for m in data.values() if m]
    if not firsts:
        return {"assets": [], "by_kind": [], "series": [], "contributed_cents": 0,
                "current_cents": 0, "profit_cents": 0, "profit_bp": None}  # fmt: skip
    start = max(min(firsts), today - timedelta(days=days))
    value_on: dict[UUID, Any] = {}
    assets: list[dict[str, Any]] = []
    for i in invs:
        movs = data[i.id]
        buys = [m for m in movs if m.kind == "buy"]
        contributed = sum(m.amount_cents if m.kind == "buy" else -m.amount_cents for m in movs)
        a: dict[str, Any] = {
            "id": i.id, "name": i.name, "kind": i.kind, "ticker": i.ticker, "quantity": None,
            "avg_price_cents": None, "price_cents": None, "quote_date": None,
            "day_change_bp": None, "contributed_cents": contributed,
        }  # fmt: skip
        if i.kind in VARIABLE:
            assert i.ticker is not None
            qs = list(await session.scalars(
                select(PriceQuote).where(PriceQuote.ticker == i.ticker, PriceQuote.on_date <= today)
                .order_by(PriceQuote.on_date)
            ))  # fmt: skip
            dates = [q.on_date for q in qs]

            def vv(day: date, qs: Any = qs, dates: Any = dates, movs: Any = movs) -> int:
                k = bisect.bisect_right(dates, day) - 1
                return int(position_qty(movs, day) * qs[k].close_cents) if k >= 0 else 0

            qty = position_qty(movs)
            bought = sum((m.quantity or Decimal(0) for m in buys), Decimal(0))
            a["quantity"] = format(qty.normalize(), "f")
            a["avg_price_cents"] = (
                int(sum(m.amount_cents for m in buys) / bought) if bought else None
            )
            if qs:
                a["price_cents"], a["quote_date"] = qs[-1].close_cents, qs[-1].on_date
                if len(qs) > 1 and qs[-2].close_cents:
                    a["day_change_bp"] = _bp(qs[-1].close_cents - qs[-2].close_cents, qs[-2].close_cents)
            a["value_cents"] = vv(today)
        else:
            pairs = fixed_pairs(movs)
            factors = await fixed_factors(session, i, min(d for d, _ in pairs), today)

            def vv(day: date, pairs: Any = pairs, factors: Any = factors) -> int:
                return fixed_value([p for p in pairs if p[0] <= day], factors, day)

            a["value_cents"] = vv(today)
        value_on[i.id] = vv
        a["profit_cents"] = a["value_cents"] - contributed
        a["profit_bp"] = _bp(a["profit_cents"], contributed)
        assets.append(a)
    series = []
    for n in range((today - start).days + 1):
        day = start + timedelta(n)
        series.append({
            "on": day,
            "value_cents": sum(value_on[i.id](day) for i in invs),
            "contributed_cents": sum(
                m.amount_cents if m.kind == "buy" else -m.amount_cents
                for i in invs for m in data[i.id] if m.occurred_on <= day
            ),
        })  # fmt: skip
    by_kind: dict[str, int] = {}
    for a in assets:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + a["value_cents"]
    contributed = sum(a["contributed_cents"] for a in assets)
    current = sum(a["value_cents"] for a in assets)
    return {
        "assets": assets, "by_kind": [{"kind": k, "value_cents": v} for k, v in by_kind.items()],
        "series": series, "contributed_cents": contributed, "current_cents": current,
        "profit_cents": current - contributed, "profit_bp": _bp(current - contributed, contributed),
    }  # fmt: skip
```

Notas: `value_cents` por variável usa `int(qty × close)` — confira que 10 × 3850 = 38500; para frações, troque por `.quantize(Decimal(1), ROUND_HALF_EVEN)` se necessário. O teste espera `stock["profit_cents"] == 500` (38.500 − 38.000 de custo).

- [ ] **Step 3:** `uv run pytest tests/domain/test_investments_dashboard.py -q` → PASS (se a ordem dos ativos ou uma data diferir, ajuste o teste ao comportamento definido acima, não a lógica). Ruff, format e mypy limpos.

- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(investments): dashboard aggregation"`

---

### Task 6: Job diário de cotações

**Files:** create `backend/app/jobs/investments.py`, `backend/tests/jobs/test_investments_job.py`; modify `backend/app/worker.py`.

- [ ] **Step 1: Teste que falha**

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domain.investments import service as svc
from app.domain.investments.models import PriceQuote
from app.domain.investments.quotes import Quote
from app.jobs import investments as job
from tests.factories import make_user


async def test_sync_quotes_is_idempotent_and_survives_one_failure(session, monkeypatch):
    a = await make_user(session, "a@x.com")

    async def ok(ticker, days, transport=None):
        return [Quote(date(2026, 1, 15), 3850)]

    async def flaky(ticker, days, transport=None):
        if ticker == "BAD3":
            raise RuntimeError("brapi fora")
        return await ok(ticker, days)

    monkeypatch.setattr(svc, "fetch_quotes", ok)  # cadastro dos dois ativos
    for t in ("BAD3", "PETR4"):
        await svc.create_investment(
            session, actor_id=a.id, space_id=a.default_space_id, kind="stock", name=t,
            ticker=t, today=date(2026, 1, 15),
        )  # fmt: skip
    monkeypatch.setattr(job, "fetch_quotes", flaky)  # no job o BAD3 falha, o PETR4 segue
    await job.sync_quotes_job(today=date(2026, 1, 15))
    await job.sync_quotes_job(today=date(2026, 1, 15))
    async with SessionLocal() as s:
        rows = list(await s.scalars(select(PriceQuote).where(PriceQuote.ticker == "PETR4")))
    assert [(r.on_date, r.close_cents) for r in rows] == [(date(2026, 1, 15), 3850)]
```

Run → FAIL.

- [ ] **Step 2: Implementação** (`jobs/investments.py`)

```python
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.dates import local_today
from app.core.db import SessionLocal
from app.domain.investments.models import Investment, PriceQuote
from app.domain.investments.quotes import fetch_quotes, upsert_quotes

log = logging.getLogger(__name__)


async def sync_quotes_job(
    ctx: dict[str, Any] | None = None, *, today: date | None = None, transport: Any = None
) -> None:
    """Fechamento de cada ticker em carteira (idempotente). Falha de um ticker não para os outros."""
    today = today or local_today(get_settings().DEFAULT_TZ)
    async with SessionLocal() as s:
        tickers = list(await s.scalars(
            select(Investment.ticker).where(Investment.ticker.is_not(None)).distinct()
        ))  # fmt: skip
    for t in tickers:
        try:
            async with SessionLocal() as s:
                last = await s.scalar(select(func.max(PriceQuote.on_date)).where(PriceQuote.ticker == t))
                days = (today - last).days + 5 if last else 30
                await upsert_quotes(s, t, await fetch_quotes(t, days, transport))
                await s.commit()
        except Exception:  # noqa: BLE001 - um ticker ruim não derruba os demais
            log.warning("quote sync failed", extra={"ticker": t})
```

Em `worker.py`: `from app.jobs.investments import sync_quotes_job` e, em `cron_jobs`, `cron(sync_quotes_job, hour=21, minute=30),  # 18:30 em SP, após o fechamento da B3`. Se `worker.py` também lista funções em `functions`, siga o mesmo padrão do `sync_cdi_job`.

- [ ] **Step 3:** `uv run pytest tests/jobs/test_investments_job.py -q` → PASS.

- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(investments): daily quote sync job"`

---

### Task 7: API

**Files:** create `backend/app/api/investments.py`, `backend/tests/api/test_investments_api.py`; modify `backend/app/main.py`.

- [ ] **Step 1: Teste que falha**

```python
from datetime import date

from app.domain.investments import service as svc
from app.domain.investments.quotes import Quote
from tests.factories import auth, make_account, make_user


async def test_investment_flow_over_http(client, session, monkeypatch):
    async def fake(ticker, days, transport=None):
        return [Quote(date(2026, 1, 15), 3850)]
    monkeypatch.setattr(svc, "fetch_quotes", fake)
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    r = await client.post(f"/spaces/{sp}/investments", headers=h,
                          json={"kind": "stock", "name": "Petrobras", "ticker": "petr4"})
    assert r.status_code == 201 and r.json()["ticker"] == "PETR4"
    inv = r.json()
    b = await client.post(f"/investments/{inv['id']}/buys", headers=h,
                          json={"account_id": str(acc.id), "quantity": "10", "occurred_on": "2026-01-15"})
    assert b.status_code == 201 and b.json()["amount_cents"] == 38_500
    assert (await client.get(f"/accounts/{acc.id}", headers=h)).json()["balance_cents"] == 61_500
    d = (await client.get(f"/spaces/{sp}/investments/dashboard", headers=h)).json()
    assert d["contributed_cents"] == 38_500 and d["assets"][0]["ticker"] == "PETR4"
    over = await client.post(f"/investments/{inv['id']}/redeems", headers=h,
                             json={"account_id": str(acc.id), "quantity": "11", "occurred_on": "2026-01-15"})
    assert over.status_code == 422 and over.json() == {"detail": "insufficient_position"}


async def test_validation_and_access(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = str(a.default_space_id)
    bad = await client.post(f"/spaces/{sp}/investments", headers=auth(a),
                            json={"kind": "cdb", "name": "x"})
    assert bad.status_code == 422 and bad.json() == {"detail": "invalid_investment"}
    assert (await client.get(f"/spaces/{sp}/investments/dashboard", headers=auth(b))).status_code in (403, 404)
```

Run → FAIL (404 nas rotas).

- [ ] **Step 2: Implementação** (`api/investments.py`). Siga `api/goals.py`/`api/pockets.py` (mesmos `CurrentUser`, `Session`, `Cents`, `row`, `local_today`).

```python
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import exists, select

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.errors import DomainError
from app.domain.investments import service as svc
from app.domain.investments.models import InvestmentMovement
from app.domain.spaces.access import require_owner

MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 12, 31)
router = APIRouter(tags=["investments"])


class InvestmentIn(BaseModel):
    kind: Literal["stock", "fii", "cdb", "lci", "lca"]
    name: str = Field(min_length=1, max_length=100)
    ticker: str | None = Field(default=None, max_length=12)
    rate_type: Literal["cdi_pct", "fixed"] | None = None
    rate_bp: int | None = Field(default=None, strict=True, ge=1, le=100_000)
    maturity_on: date | None = None


class MoveIn(BaseModel):
    account_id: UUID
    occurred_on: date | None = Field(default=None, ge=MIN_DATE, le=MAX_DATE)
    amount_cents: Cents | None = None  # renda fixa
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    unit_price_cents: Cents | None = None  # opcional: vence o preço do dia


class InvestmentOut(BaseModel):
    id: UUID
    space_id: UUID
    kind: str
    name: str
    ticker: str | None
    rate_type: str | None
    rate_bp: int | None
    maturity_on: date | None


class MovementOut(BaseModel):
    id: UUID
    investment_id: UUID
    kind: str
    occurred_on: date
    quantity: Decimal | None
    unit_price_cents: int | None
    amount_cents: int
    transaction_id: UUID


@router.post("/spaces/{space_id}/investments", status_code=201, response_model=InvestmentOut)
async def create(space_id: UUID, body: InvestmentIn, user: CurrentUser, session: Session) -> dict[str, Any]:
    inv = await svc.create_investment(
        session, actor_id=user.id, space_id=space_id, today=local_today(user.tz),
        **body.model_dump(),
    )  # fmt: skip
    return row(inv)


@router.get("/spaces/{space_id}/investments/dashboard")
async def dashboard(space_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await svc.dashboard(session, viewer_id=user.id, space_id=space_id, today=local_today(user.tz))


async def _move(fn: Any, investment_id: UUID, body: MoveIn, user: Any, session: Any) -> dict[str, Any]:
    today = local_today(user.tz)
    mv = await fn(
        session, actor_id=user.id, investment_id=investment_id, account_id=body.account_id,
        on=body.occurred_on or today, amount_cents=body.amount_cents, quantity=body.quantity,
        unit_price_cents=body.unit_price_cents, today=today,
    )  # fmt: skip
    return row(mv)


@router.post("/investments/{investment_id}/buys", status_code=201, response_model=MovementOut)
async def add_buy(investment_id: UUID, body: MoveIn, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await _move(svc.buy, investment_id, body, user, session)


@router.post("/investments/{investment_id}/redeems", status_code=201, response_model=MovementOut)
async def add_redeem(investment_id: UUID, body: MoveIn, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await _move(svc.redeem, investment_id, body, user, session)


@router.delete("/investments/{investment_id}", status_code=204)
async def delete(investment_id: UUID, user: CurrentUser, session: Session) -> None:
    inv = await svc.visible_investment(session, user.id, investment_id, lock=True)
    await require_owner(session, user.id, inv.space_id)
    if await session.scalar(select(exists().where(InvestmentMovement.investment_id == inv.id))):
        raise DomainError("investment_has_history")
    await session.delete(inv)
    await session.commit()
```

Em `main.py`: importe `investments` junto dos outros routers e `app.include_router(investments.router)`.

Pontos de atenção: confira que `DomainError` vira 422 `{"detail": "<código>"}` via o handler global (já usado em goals); `quantity` chega do JSON como string ou número e o pydantic converte para `Decimal` (o teste usa string). `row(mv)` devolve `Decimal` em `quantity`, serializado como string no JSON.

- [ ] **Step 3:** `uv run pytest tests/api/test_investments_api.py -q` → PASS; depois `uv run ruff check . && uv run ruff format . && uv run mypy app` limpos.

- [ ] **Step 4: Commit** — `git add backend && git commit -m "feat(investments): API"`

---

### Task 8: Web — seção Investimentos

Antes de escrever os gráficos, carregue o skill `dataviz` (paleta/semântica dos gráficos) e siga o padrão visual de `pages/dashboard.tsx` (`COLORS`, `Card`, `Bar`).

**Files:** modify `web/src/router.tsx`, `web/src/layout.tsx`, `web/src/api/types.ts`; create `web/src/pages/investments.tsx`, `web/src/pages/investments.test.tsx`; regenerate `web/src/api/schema.d.ts`.

- [ ] **Step 1: Tipos** — `cd backend && uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json && cd ../web && npm run gen:api`. Em `api/types.ts`, o dashboard não tem modelo no OpenAPI (retorna `dict`), então declare à mão, ao lado de `Statement`:

```ts
export type InvAsset = { id: string; name: string; kind: 'stock' | 'fii' | 'cdb' | 'lci' | 'lca'; ticker: string | null; quantity: string | null; avg_price_cents: number | null; price_cents: number | null; quote_date: string | null; day_change_bp: number | null; contributed_cents: number; value_cents: number; profit_cents: number; profit_bp: number | null }
export type InvDashboard = { assets: InvAsset[]; by_kind: { kind: string; value_cents: number }[]; series: { on: string; value_cents: number; contributed_cents: number }[]; contributed_cents: number; current_cents: number; profit_cents: number; profit_bp: number | null }
```

- [ ] **Step 2: Teste que falha** (`investments.test.tsx`; reaproveite o mock de `fetch`/`go` de `pages.test.tsx` — se ele não estiver exportado, exporte `go`, `routes`, `J` de lá ou replique o helper no novo arquivo)

```tsx
test('investimentos: mostra totais, rentabilidade e ativos', async () => {
  routes[`/spaces/${SP}/investments/dashboard`] = () => J({
    assets: [{ id: 'i1', name: 'Petrobras', kind: 'stock', ticker: 'PETR4', quantity: '10', avg_price_cents: 3800, price_cents: 3850, quote_date: '2026-01-15', day_change_bp: 131, contributed_cents: 38000, value_cents: 38500, profit_cents: 500, profit_bp: 131 }],
    by_kind: [{ kind: 'stock', value_cents: 38500 }],
    series: [{ on: '2026-01-14', value_cents: 38000, contributed_cents: 38000 }, { on: '2026-01-15', value_cents: 38500, contributed_cents: 38000 }],
    contributed_cents: 38000, current_cents: 38500, profit_cents: 500, profit_bp: 131,
  })
  go('/investimentos')
  expect(await screen.findByText('PETR4', { exact: false })).toBeInTheDocument()
  expect(screen.getAllByText('R$ 385,00').length).toBeGreaterThan(0)
  expect(screen.getByText('+1,31%')).toBeInTheDocument()
})

test('investimentos: aportar em ação envia quantidade e conta', async () => {
  go('/investimentos')
  await userEvent.click(await screen.findByRole('button', { name: 'Aportar em PETR4' }))
  await userEvent.selectOptions(screen.getByLabelText('Conta'), 'a1')
  await userEvent.type(screen.getByLabelText('Quantidade'), '10')
  await userEvent.click(screen.getByRole('button', { name: 'Confirmar aporte' }))
  const post = calls.find(([u]) => u === '/investments/i1/buys')!
  expect(JSON.parse(post[1].body as string)).toMatchObject({ account_id: 'a1', quantity: '10' })
})
```

Run: `cd web && npm test -- investments` → FAIL.

- [ ] **Step 3: Implementação** (`pages/investments.tsx`) — componentes, na ordem:
  1. `Investments()` (exportada): `useGet<InvDashboard>(`/spaces/${spaceId}/investments/dashboard`)`. Estado vazio: texto "Você ainda não tem investimentos. Cadastre o primeiro ativo." Renderiza `Resumo`, `Evolucao`, `Alocacao`, `Ativos`, `NovoAtivo`.
  2. `Resumo`: três `Card`s/linhas — Investido (`contributed_cents`), Valor atual (`current_cents`), Rentabilidade (`profit_cents` com sinal e `profit_bp` como `+1,31%`; `fmtBp = (bp) => `${bp >= 0 ? '+' : ''}${(bp / 100).toFixed(2).replace('.', ',')}%``). Valores com `formatBRL`; cor semântica verde/vermelha só no número de rentabilidade (não só pela cor: o sinal +/− vai no texto).
  3. `Evolucao`: SVG `viewBox` responsivo com duas `polyline`s (valor da carteira e aportado) escaladas pelo máximo da série, `role="img"` e `aria-label` descritivo; legenda de texto. Sem biblioteca.
  4. `Alocacao`: rosca em SVG (`circle` com `stroke-dasharray`) por `by_kind`, com legenda "Ações 45%"; rótulos pt-BR: `{stock:'Ações', fii:'Fundos imobiliários', cdb:'CDB', lci:'LCI', lca:'LCA'}`.
  5. `Ativos`: lista (cartão por ativo no mobile, `table` no desktop se o padrão do app permitir) com nome/ticker, quantidade, preço médio, preço atual (+ data da cotação se ≠ hoje), variação do dia, valor, rentabilidade; botões `Aportar em {ticker ?? nome}` e `Resgatar de …` que abrem `MovimentoForm`.
  6. `MovimentoForm({ a, kind })`: `Field`s "Conta" (`AccountSelect`, `useAccounts`), "Data" (`input type=date`, padrão `today()`), e, para ações/FIIs, "Quantidade" (+ "Preço unitário (R$) — opcional, vazio usa o fechamento do dia"), para renda fixa "Valor (R$)". Envia `POST /investments/${a.id}/${kind === 'buy' ? 'buys' : 'redeems'}` com `{ account_id, occurred_on, quantity }` (string) ou `{ …, amount_cents }`; `unit_price_cents` só se preenchido (`parseBRL`). Botão "Confirmar aporte"/"Confirmar resgate"; `<Err>` mostra o código (`insufficient_position`, `no_quote`).
  7. `NovoAtivo`: `Card title="Novo ativo"` com select de tipo; para ação/FII: "Nome" + "Ticker (ex.: PETR4)"; para CDB/LCI/LCA: "Nome", "Rentabilidade" (select "% do CDI" / "Prefixada a.a.") e "Taxa (%)" convertida para `rate_bp` (`Math.round(parseFloat(v.replace(',', '.')) * 100)`), "Vencimento (opcional)". `POST /spaces/${spaceId}/investments`.
  Reaproveite `Card, Field, Btn, Err, AccountSelect, Bar, useGet, useSend, useAccounts, today` de `../ui` e `formatBRL, parseBRL` de `../lib/money`, como em `plan.tsx`.

  Registro: `router.tsx` — `import { Investments } from './pages/investments'` e `page('/investimentos', Investments)`; `layout.tsx` — `['/investimentos', 'Investimentos', TrendingUp]` em `PRINCIPAL` (importe `TrendingUp` de `lucide-react`, junto dos outros ícones).

- [ ] **Step 4: Rodar** — `cd web && npm run lint && npm run typecheck && npm test && npm run build` → tudo verde.

- [ ] **Step 5: Commit** — `git add web && git commit -m "feat(web): investments section and dashboard"`

---

### Task 9: Verificação final e entrega

- [ ] Backend: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app && bash scripts/migrate_check.sh` (pytest uma vez, sem rodar outro em paralelo).
- [ ] Web: `cd web && npm run lint && npm run typecheck && npm test && npm run build`.
- [ ] **Verificação real da brapi (precisa do `BRAPI_TOKEN`, peça ao usuário):** `curl -s "https://brapi.dev/api/quote/PETR4?range=1mo&interval=1d&token=$BRAPI_TOKEN" | head -c 600` e confirme que `results[0].historicalDataPrice[]` tem `date` (epoch) e `close`. Se o formato ou o limite do plano gratuito diferir do que `quotes.py` assume (campos, 1 ticker por chamada, ranges aceitos), ajuste `quotes.py` e seu teste antes do PR. O código não foi validado contra a API real até este passo.
- [ ] Conferir no navegador: cadastrar PETR4, aportar, ver preço/rentabilidade; cadastrar um CDB 110% CDI, aportar e ver o valor crescer depois do CDI do dia.
- [ ] Deploy (só com confirmação do usuário): definir `BRAPI_TOKEN` no `.env` de produção e recriar `api`/`worker`/`web`; a migração `f7a8b9c0d1e2` roda no deploy.
- [ ] Abrir PR para a `main` (`gh pr create`).

## Self-review (spec → tarefas)

- Modelo (`investments`, `investment_movements`, `price_quotes`): Task 1. brapi, job diário, busca sob demanda, falha sem quebrar, `unknown_ticker`: Tasks 2, 4, 6. Renda fixa % CDI/prefixada, bruta: Task 3. Aporte/resgate como transferência com conta de origem e limite da posição: Task 4. Preço da data guardado (`unit_price_cents`) e editável: Task 4. Dashboard (cards, evolução, alocação, tabela por ativo, % em bp): Tasks 5 e 8. API: Task 7. Web e menu: Task 8.
- Nomes consistentes: `create_investment`, `buy`, `redeem`, `dashboard`, `fetch_quotes`, `upsert_quotes`, `latest_close`, `fixed_value`, `cdi_factors`, `weekday_factors`, `position_qty`, `fixed_factors`.
