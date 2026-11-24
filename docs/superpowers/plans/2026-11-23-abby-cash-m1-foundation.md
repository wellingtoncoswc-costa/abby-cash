# Abby Cash M1 — Fundação: Plano detalhado (TDD)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **Use ponytail em tudo** (passe esta instrução a todo subagente). TDD, testes, review e verificação continuam integrais.

**Goal:** monorepo rodando (api, worker, postgres, redis, web), CI verde, dinheiro/datas, auth com cadastro por convite, espaços + categorias padrão + carteira.

**Architecture:** um pacote Python `app` (API e worker, entrypoints distintos). SQLAlchemy 2 async + Alembic. Testes de backend usam Postgres e Redis reais (serviços no CI; `infra/docker-compose.dev.yml` localmente), sem testcontainers (ponytail: menos dependência).

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2 async/asyncpg, Alembic, pydantic-settings, ARQ, redis-py, argon2-cffi, PyJWT, pyotp, pytest, pytest-asyncio, httpx, ruff, mypy · React 18 + Vite + TS, Vitest.

**Interfaces:** exatamente as do plano mestre (`docs/superpowers/plans/2026-11-23-abby-cash-v1.md`), T1.1–T1.4. Nenhuma renomeada.

## Decisões técnicas do marco (registradas)

- **Gerenciador:** `uv` (`backend/uv.lock` versionado). Comandos: `cd backend && uv run pytest`.
- **Schema nos testes:** `Base.metadata.create_all` (fixture de sessão) + truncate por teste. O CI roda também `alembic upgrade head && alembic check` para garantir que a migração bate com os modelos.
- **Models mínimos antecipados:** `Account` (id, space_id, type, name, initial_balance_cents) nasce no T1.4 para criar a carteira; o T2.1 o estende.
- **Rate limit de login:** contador no Redis (`login_fail:{email}`, TTL 15 min), 5 falhas → 429.
- **Refresh token:** string aleatória; no banco só o `sha256`. Reuso de token revogado revoga a família inteira.
- **IDs:** `uuid4` em todas as tabelas. Timestamps `timestamptz` UTC.
- **Cookie `Secure`:** sempre ligado; os testes usam `base_url="https://test"`.

## Estrutura de arquivos do M1

```
backend/pyproject.toml            deps + ruff + mypy + pytest
backend/app/core/{config,db,security,money,dates,redis}.py
backend/app/domain/users/{models,service}.py
backend/app/domain/spaces/{models,service,access}.py
backend/app/domain/categories/{models,defaults}.py
backend/app/domain/accounts/models.py
backend/app/api/{auth,spaces,deps}.py
backend/app/{main,worker,cli}.py
backend/migrations/ (alembic)     backend/tests/{conftest.py,core/,api/,domain/}
web/ (vite react-ts + vitest)     infra/docker-compose.{dev,prod}.yml
.env.example .gitignore .github/workflows/ci.yml README.md CLAUDE.md
```

---

## Task 1 (T1.1): Monorepo, Compose e CI

**Files:** Create `backend/pyproject.toml`, `backend/app/{__init__,main,worker}.py`, `backend/app/core/{__init__,config,db,redis}.py`, `backend/tests/conftest.py`, `backend/tests/api/test_health.py`, `backend/Dockerfile`, `web/*`, `infra/docker-compose.dev.yml`, `infra/docker-compose.prod.yml` (esqueleto: api, worker, postgres, redis), `.env.example`, `.gitignore`, `.github/workflows/ci.yml`, `README.md`, `CLAUDE.md`.

- [ ] **Step 1: Scaffold do backend**

```bash
mkdir -p backend/app/core backend/tests/api && cd backend
cat > pyproject.toml <<'EOF'
[project]
name = "abby-cash"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.30", "sqlalchemy[asyncio]>=2.0", "asyncpg>=0.29",
  "alembic>=1.13", "pydantic-settings>=2.4", "email-validator>=2.2", "arq>=0.26", "redis>=5.0",
  "argon2-cffi>=23.1", "pyjwt>=2.9", "pyotp>=2.9", "httpx>=0.27", "python-multipart>=0.0.9",
]
[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6", "mypy>=1.11"]
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
markers = ["slow: testes lentos (áudio real etc.)"]
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
[tool.mypy]
python_version = "3.12"
strict = true
plugins = []
[[tool.mypy.overrides]]
module = ["arq.*", "pyotp.*"]
ignore_missing_imports = true
EOF
touch app/__init__.py app/core/__init__.py tests/__init__.py tests/api/__init__.py
uv sync
```

- [ ] **Step 2: Config**

`backend/app/core/config.py`:
```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://abby:abby@localhost:5432/abby"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "dev-only-change-me"
    AI_MODEL: str = "gpt-4.1"
    OPENAI_API_KEY: str = ""
    STT_URL: str = "http://stt:8000"
    STT_MODEL: str = "small"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    EVOLUTION_URL: str = ""
    EVOLUTION_API_KEY: str = ""
    EVOLUTION_INSTANCE: str = ""
    EVOLUTION_WEBHOOK_SECRET: str = ""
    STORAGE_DIR: str = "./storage"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    DEFAULT_TZ: str = "America/Sao_Paulo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/core/db.py`:
```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

engine = create_async_engine(get_settings().DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

`backend/app/core/redis.py`:
```python
from redis.asyncio import Redis

from app.core.config import get_settings

redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
```

- [ ] **Step 3: Teste falhando**

`backend/tests/api/test_health.py`:
```python
from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_reports_db_and_redis():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True, "redis": True}
```

- [ ] **Step 4: Subir infra dev e ver falhar**

`infra/docker-compose.dev.yml`:
```yaml
name: abby-cash-dev
services:
  postgres:
    image: postgres:16
    environment: {POSTGRES_USER: abby, POSTGRES_PASSWORD: abby, POSTGRES_DB: abby}
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: {test: ["CMD-SHELL", "pg_isready -U abby"], interval: 3s, retries: 20}
  redis:
    image: redis:7
    ports: ["6379:6379"]
  api:
    build: ../backend
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    env_file: ../.env
    environment:
      DATABASE_URL: postgresql+asyncpg://abby:abby@postgres:5432/abby
      REDIS_URL: redis://redis:6379/0
    ports: ["8000:8000"]
    volumes: [../backend:/app]
    depends_on: {postgres: {condition: service_healthy}, redis: {condition: service_started}}
  worker:
    build: ../backend
    command: arq app.worker.WorkerSettings
    env_file: ../.env
    environment:
      DATABASE_URL: postgresql+asyncpg://abby:abby@postgres:5432/abby
      REDIS_URL: redis://redis:6379/0
    volumes: [../backend:/app]
    depends_on: {postgres: {condition: service_healthy}, redis: {condition: service_started}}
  web:
    image: node:22
    working_dir: /web
    command: sh -c "npm ci && npm run dev -- --host 0.0.0.0"
    ports: ["5173:5173"]
    volumes: [../web:/web]
volumes:
  pgdata:
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Run: `docker compose -f infra/docker-compose.dev.yml up -d postgres redis && cd backend && uv run pytest tests/api/test_health.py -v`
Expected: FAIL (`ModuleNotFoundError: app.main`).

- [ ] **Step 5: Implementar `/health` e worker**

`backend/app/main.py`:
```python
from fastapi import FastAPI
from sqlalchemy import text

from app.core.db import engine
from app.core.redis import redis

app = FastAPI(title="Abby Cash")


@app.get("/health")
async def health() -> dict[str, object]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        db = True
    except Exception:
        db = False
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    return {"status": "ok" if db and redis_ok else "degraded", "db": db, "redis": redis_ok}
```

`backend/app/worker.py`:
```python
from arq.connections import RedisSettings

from app.core.config import get_settings


async def noop(ctx: dict) -> None:  # ponytail: placeholder até o M3 trazer jobs reais
    return None


class WorkerSettings:
    functions = [noop]
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
```

Run: `uv run pytest tests/api/test_health.py -v` → Expected: PASS.

- [ ] **Step 6: Web (Vite + Vitest)**

```bash
cd ~/abby-cash && npm create vite@latest web -- --template react-ts
cd web && npm i && npm i -D vitest jsdom @testing-library/react @testing-library/jest-dom
```
Em `web/vite.config.ts` adicione `test: { environment: "jsdom", globals: true }` (importando `defineConfig` de `vitest/config`). Em `web/package.json` scripts: `"test": "vitest run"`, `"typecheck": "tsc -b --noEmit"`. Teste smoke `web/src/App.test.tsx` renderizando `<App />` e esperando não lançar:
```tsx
import { render } from "@testing-library/react";
import App from "./App";
test("renders", () => { render(<App />); });
```
Run: `npm test && npm run lint && npm run typecheck` → Expected: PASS.

- [ ] **Step 7: `.env.example`, `.gitignore`, prod esqueleto, CI, docs**

`.env.example`: todas as chaves de `Settings` com valores vazios/de exemplo (sem segredos reais). `.gitignore` acrescenta `.env`, `storage/`, `.venv/`, `node_modules/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `web/dist/`. `infra/docker-compose.prod.yml`: `name: abby-cash`, serviços api/worker/postgres/redis com `deploy.resources.limits`, rede `abby-cash-net`, sem `ports` públicos (M8 completa).

`.github/workflows/ci.yml`:
```yaml
name: ci
on: {push: {branches: [main]}, pull_request: {}}
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_USER: abby, POSTGRES_PASSWORD: abby, POSTGRES_DB: abby}
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready -U abby" --health-interval 3s --health-retries 20
      redis:
        image: redis:7
        ports: ["6379:6379"]
    env:
      DATABASE_URL: postgresql+asyncpg://abby:abby@localhost:5432/abby
      REDIS_URL: redis://localhost:6379/0
    defaults: {run: {working-directory: backend}}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run ruff check . && uv run ruff format --check .
      - run: uv run mypy app
      - run: uv run alembic upgrade head && uv run alembic check
      - run: uv run pytest -m "not slow"
  web:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: web}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: 22, cache: npm, cache-dependency-path: web/package-lock.json}
      - run: npm ci && npm run lint && npm run typecheck && npm test
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: gitleaks/gitleaks-action@v2
        env: {GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}"}
```
(O passo `alembic` só passa depois da Task 3 criar a migração; até lá, comente-o e reative na Task 3.)

`CLAUDE.md`: comandos de dev/teste (`docker compose -f infra/docker-compose.dev.yml up -d postgres redis`, `cd backend && uv run pytest`, `uv run ruff check . && uv run mypy app`, `cd web && npm test`) + as "Restrições globais" do plano mestre, copiadas. `README.md`: o que é, como subir o dev.

- [ ] **Step 8: Verificar e commitar**

Run: `cd backend && uv run ruff check . && uv run ruff format . && uv run mypy app && uv run pytest` → tudo verde. `docker compose -f infra/docker-compose.dev.yml up -d --build` → `curl -s localhost:8000/health` retorna `{"status":"ok","db":true,"redis":true}`.
```bash
git add -A && git commit -m "feat: scaffold monorepo, dev compose, health endpoint and CI"
```

---

## Task 2 (T1.2): Dinheiro e datas

**Files:** Create `backend/app/core/money.py`, `backend/app/core/dates.py`, `backend/tests/core/{__init__,test_money,test_dates}.py`.

- [ ] **Step 1: Testes falhando**

`backend/tests/core/test_money.py`:
```python
import pytest

from app.core.money import format_brl, parse_brl


@pytest.mark.parametrize(
    ("text", "cents"),
    [("1.234,56", 123456), ("1234.56", 123456), ("R$45", 4500), ("R$ 45", 4500),
     ("45 reais", 4500), ("45,5", 4550), ("45", 4500), ("1.234", 123400), ("0,99", 99)],
)
def test_parse_brl_valid(text, cents):
    assert parse_brl(text) == cents


@pytest.mark.parametrize("text", ["0", "0,00", "-10", "R$ -5", "abc", "", "1,2,3"])
def test_parse_brl_rejects_non_positive_or_garbage(text):
    assert parse_brl(text) is None


def test_format_brl():
    assert format_brl(123456) == "R$ 1.234,56"
    assert format_brl(4500) == "R$ 45,00"
    assert format_brl(5) == "R$ 0,05"
    assert format_brl(100000000) == "R$ 1.000.000,00"
```
`backend/tests/core/test_dates.py`:
```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.dates import add_months, clamp_day, local_today


def test_clamp_day():
    assert clamp_day(2026, 2, 31) == date(2026, 2, 28)
    assert clamp_day(2028, 2, 31) == date(2028, 2, 29)
    assert clamp_day(2026, 4, 31) == date(2026, 4, 30)
    assert clamp_day(2026, 3, 15) == date(2026, 3, 15)


def test_add_months():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_local_today_uses_timezone(monkeypatch):
    # 23:30 em São Paulo (UTC-3) já é o dia seguinte em UTC
    fixed = datetime(2026, 11, 24, 2, 30, tzinfo=ZoneInfo("UTC"))

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    monkeypatch.setattr("app.core.dates.datetime", FakeDT)
    assert local_today("America/Sao_Paulo") == date(2026, 11, 23)
    assert local_today("UTC") == date(2026, 11, 24)
```
Run: `uv run pytest tests/core -v` → FAIL (módulos inexistentes).

- [ ] **Step 2: Implementar**

`backend/app/core/money.py`:
```python
import re
from decimal import Decimal, InvalidOperation

_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")


def parse_brl(text: str) -> int | None:
    s = text.lower().replace("r$", "").replace("reais", "").replace("real", "").strip()
    s = s.replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif _THOUSANDS.match(s):
        s = s.replace(".", "")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    cents = int((value * 100).to_integral_value())
    return cents if cents > 0 else None


def format_brl(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"
```
`backend/app/core/dates.py`:
```python
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo


def local_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return clamp_day(y, m + 1, d.day)
```
Run: `uv run pytest tests/core -v` → PASS. (Atenção: `"1,2,3"` → `Decimal("1.2.3")` inválido → `None`. `"R$ -5"` → `-5` → `None`.)

- [ ] **Step 3: Qualidade e commit**

`uv run ruff check . && uv run ruff format . && uv run mypy app`
```bash
git add -A && git commit -m "feat(core): add BRL money parsing/formatting and date helpers"
```

---

## Task 3 (T1.3): Banco, usuários, autenticação, convites de cadastro

**Files:** Create `backend/app/core/security.py`, `backend/app/domain/users/{__init__,models,service}.py`, `backend/app/api/{__init__,deps,auth}.py`, `backend/app/cli.py`, `backend/migrations/*` (alembic), `backend/tests/conftest.py` (reescrito), `backend/tests/api/test_auth.py`. Modify `backend/app/main.py` (incluir router).

**Modelos** (`domain/users/models.py`): `User(id, email unique, name, password_hash, tz default 'America/Sao_Paulo', is_admin bool, totp_secret str|None, totp_enabled bool, preferred_channel str|None, default_space_id UUID|None, reminder_time time default 09:00, weekly_digest bool default false, created_at)`; `SignupInvite(id, code unique, created_by FK users, expires_at, used_by FK users|None, used_at)`; `RefreshToken(id, user_id FK, family_id UUID, token_hash unique, expires_at, revoked_at|None)`.

- [ ] **Step 1: Alembic**

```bash
cd backend && uv run alembic init -t async migrations
```
Edite `migrations/env.py`: `from app.core.db import Base`, importe todos os módulos de models (`app.domain.users.models` etc.), `target_metadata = Base.metadata`, e `config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)`.

- [ ] **Step 2: Fixtures de teste**

`backend/tests/conftest.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.domain.spaces.models  # noqa: F401  (registra tabelas)
import app.domain.users.models  # noqa: F401
from app.core.db import Base, SessionLocal, engine
from app.core.redis import redis
from app.main import app


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
async def _clean():
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await redis.flushdb()


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c
```
(O import de `spaces.models` só resolve após a Task 4; até lá comente-o.)

- [ ] **Step 3: Testes falhando**

`backend/tests/api/test_auth.py`:
```python
from datetime import UTC, datetime, timedelta

import pyotp

from app.domain.users.service import create_admin, create_signup_invite

PWD = "correct horse battery"


async def _invite(session) -> str:
    admin = await create_admin(session, email="admin@x.com", name="Admin", password=PWD)
    return (await create_signup_invite(session, created_by=admin.id)).code


async def _register(client, code, email="a@x.com"):
    return await client.post(
        "/auth/register",
        json={"email": email, "name": "A", "password": PWD, "invite_code": code},
    )


async def test_register_requires_valid_invite(client, session):
    assert (await _register(client, "nope")).status_code == 400
    code = await _invite(session)
    assert (await _register(client, code)).status_code == 201


async def test_invite_single_use(client, session):
    code = await _invite(session)
    assert (await _register(client, code, "a@x.com")).status_code == 201
    assert (await _register(client, code, "b@x.com")).status_code == 400


async def test_expired_invite_rejected(client, session):
    admin = await create_admin(session, email="admin@x.com", name="Admin", password=PWD)
    inv = await create_signup_invite(
        session, created_by=admin.id, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert (await _register(client, inv.code)).status_code == 400


async def test_login_rate_limited_after_5_failures(client, session):
    await _register(client, await _invite(session))
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "a@x.com", "password": "bad"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    assert r.status_code == 429


async def test_refresh_rotation_revokes_reused_token(client, session):
    await _register(client, await _invite(session))
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    old = login.cookies["refresh_token"]
    r1 = await client.post("/auth/refresh", cookies={"refresh_token": old})
    assert r1.status_code == 200
    new = r1.cookies["refresh_token"]
    assert new != old
    # reuso do token antigo → 401 e a família inteira é revogada
    assert (await client.post("/auth/refresh", cookies={"refresh_token": old})).status_code == 401
    assert (await client.post("/auth/refresh", cookies={"refresh_token": new})).status_code == 401


async def test_2fa_required_when_enabled(client, session):
    await _register(client, await _invite(session))
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    secret = (await client.post("/auth/2fa/setup", headers=h)).json()["secret"]
    ok = await client.post("/auth/2fa/verify", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    r = await client.post(
        "/auth/login",
        json={"email": "a@x.com", "password": PWD, "totp": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200
```
Run: `uv run pytest tests/api/test_auth.py -v` → FAIL (módulos inexistentes).

- [ ] **Step 4: `security.py`**

```python
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_ph = PasswordHasher()  # Argon2id por padrão


def hash_password(pwd: str) -> str:
    return _ph.hash(pwd)


def verify_password(pwd: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pwd)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: UUID) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=15)
    return jwt.encode({"sub": str(user_id), "exp": exp}, get_settings().JWT_SECRET, "HS256")


def decode_access_token(token: str) -> UUID | None:
    try:
        data = jwt.decode(token, get_settings().JWT_SECRET, algorithms=["HS256"])
        return UUID(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_opaque_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
```

- [ ] **Step 5: Modelos e serviço de usuários**

`domain/users/models.py` com as colunas descritas acima (SQLAlchemy 2 `Mapped[...]`, `mapped_column`, `UUID(as_uuid=True)`, `default=uuid4`, `DateTime(timezone=True)`). `domain/users/service.py` expõe:
- `create_admin(session, *, email, name, password) -> User` (`is_admin=True`)
- `create_signup_invite(session, *, created_by, expires_at=None) -> SignupInvite` (código `secrets.token_urlsafe(8)`, expira em 7 dias por padrão)
- `register_user(session, *, email, name, password, invite_code) -> User` — valida convite (existe, não usado, não expirado) com `SELECT ... FOR UPDATE`, cria usuário, marca `used_by/used_at`; levanta `ValueError("invalid_invite")`.
- `authenticate(session, email, password, totp) -> User` — levanta `AuthError("invalid_credentials" | "totp_required")`.
- `issue_refresh(session, user_id, family_id=None) -> str` e `rotate_refresh(session, raw) -> tuple[User, str]` (token revogado ⇒ revoga família inteira e levanta `AuthError`).

- [ ] **Step 6: API de auth**

`api/deps.py`: `get_current_user` (Bearer → `decode_access_token` → carrega `User`, 401 se inválido). `api/auth.py`:
- `POST /auth/register` (201 `{id,email}`; `ValueError` → 400)
- `POST /auth/login` → verifica rate limit (`redis.get(f"login_fail:{email}") >= 5` → 429 **antes** de checar a senha); falha → `INCR` + `EXPIRE 900` e 401 (`detail` = `invalid_credentials` ou `totp_required`); sucesso → limpa o contador, devolve `{access_token}` e `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Lax; Path=/auth`
- `POST /auth/refresh` (cookie) → rotaciona; novo access + novo cookie
- `POST /auth/2fa/setup` (autenticado) → gera `pyotp.random_base32()`, salva em `totp_secret`, devolve `{secret, uri}`
- `POST /auth/2fa/verify` `{code}` → valida e liga `totp_enabled`

Inclua o router em `main.py`: `app.include_router(auth.router)`.

- [ ] **Step 7: CLI**

`app/cli.py` com `argparse`: `create-admin --email --name` (senha via `getpass`) e `create-signup-invite` (imprime o código). Smoke manual: `uv run python -m app.cli create-signup-invite`.

- [ ] **Step 8: Migração inicial**

```bash
uv run alembic revision --autogenerate -m "users and auth"
uv run alembic upgrade head && uv run alembic check
```
Reative o passo `alembic` no CI.

- [ ] **Step 9: Rodar tudo e commitar**

Run: `uv run pytest tests/api/test_auth.py -v` → 6 PASS; depois `uv run ruff check . && uv run ruff format . && uv run mypy app`.
```bash
git add -A && git commit -m "feat(auth): add users, signup invites, JWT with rotating refresh, TOTP and CLI"
```

---

## Task 4 (T1.4): Espaços, membros, categorias padrão e carteira

**Files:** Create `backend/app/domain/spaces/{__init__,models,service,access}.py`, `backend/app/domain/categories/{__init__,models,defaults}.py`, `backend/app/domain/accounts/{__init__,models}.py`, `backend/app/api/spaces.py`, `backend/tests/domain/{__init__,test_spaces}.py`. Modify `domain/users/service.py` (`register_user` chama `provision_user`), `app/main.py`, `migrations/env.py` (importar novos models), `tests/conftest.py` (descomentar import).

**Modelos:** `Space(id, type 'personal'|'family', name, owner_id)`; `SpaceMember(space_id, user_id, role 'owner'|'member', default_account_id|None; PK composta)`; `SpaceInvite(id, space_id, token unique, created_by, expires_at, used_at|None)`; `Category(id, space_id, kind 'expense'|'income', name, icon, color)`; `Account(id, space_id, type 'checking'|'wallet'|'savings', name, initial_balance_cents BIGINT default 0)`. Índice único parcial: um `family` por owner (`UNIQUE(owner_id) WHERE type='family'`).

- [ ] **Step 1: Testes falhando**

`backend/tests/domain/test_spaces.py`:
```python
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.domain.accounts.models import Account
from app.domain.categories.models import Category
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceMember
from app.domain.spaces.service import (
    accept_space_invite, create_family_space, create_space_invite, remove_member,
)
from app.domain.users.service import create_admin, create_signup_invite, register_user

PWD = "correct horse battery"


async def _user(session, email):
    admin = await create_admin(session, email=f"adm-{email}", name="Adm", password=PWD)
    inv = await create_signup_invite(session, created_by=admin.id)
    return await register_user(
        session, email=email, name=email, password=PWD, invite_code=inv.code
    )


async def test_signup_creates_personal_space_with_defaults_and_wallet(session):
    u = await _user(session, "a@x.com")
    assert u.default_space_id is not None
    space = await session.get(Space, u.default_space_id)
    assert space.type == "personal" and space.owner_id == u.id
    cats = (await session.scalars(select(Category).where(Category.space_id == space.id))).all()
    names = {c.name for c in cats if c.kind == "expense"}
    assert {"Alimentação", "Mercado", "Impostos e taxas", "Outros"} <= names
    assert {c.name for c in cats if c.kind == "income"} == {
        "Salário", "Renda extra", "Reembolso", "Outros"
    }
    wallet = await session.scalar(select(Account).where(Account.space_id == space.id))
    assert wallet.type == "wallet" and wallet.name == "Carteira"


async def test_non_member_gets_404(session):
    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    with pytest.raises(HTTPException) as e:
        await require_member(session, b.id, a.default_space_id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        await require_member(session, a.id, uuid4())


async def test_user_cannot_own_two_family_spaces(session):
    a = await _user(session, "a@x.com")
    await create_family_space(session, owner_id=a.id, name="Casa")
    with pytest.raises(ValueError, match="family_space_exists"):
        await create_family_space(session, owner_id=a.id, name="Outra")


async def test_removed_member_loses_access_immediately(session):
    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    fam = await create_family_space(session, owner_id=a.id, name="Casa")
    inv = await create_space_invite(session, space_id=fam.id, created_by=a.id)
    await accept_space_invite(session, token=inv.token, user_id=b.id)
    assert (await require_member(session, b.id, fam.id)).role == "member"
    await remove_member(session, actor_id=a.id, space_id=fam.id, user_id=b.id)
    with pytest.raises(HTTPException):
        await require_member(session, b.id, fam.id)
    assert await session.get(SpaceMember, (fam.id, a.id)) is not None
```
Run: `uv run pytest tests/domain/test_spaces.py -v` → FAIL.

- [ ] **Step 2: Implementar**

`categories/defaults.py`: `DEFAULT_EXPENSE = ["Alimentação","Mercado","Transporte","Moradia","Contas da casa","Saúde","Educação","Lazer","Compras","Assinaturas","Pets","Impostos e taxas","Outros"]`, `DEFAULT_INCOME = ["Salário","Renda extra","Reembolso","Outros"]`.

`spaces/access.py`:
```python
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.spaces.models import SpaceMember


async def require_member(session: AsyncSession, user_id: UUID, space_id: UUID) -> SpaceMember:
    member = await session.get(SpaceMember, (space_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="not_found")  # 404 não revela existência
    return member
```
`spaces/service.py`: `provision_user(session, user)` (cria espaço personal + owner membership + categorias + carteira, define `default_space_id` e `default_account_id` da carteira), `create_family_space` (checa existência → `ValueError("family_space_exists")`; também protegido pelo índice único), `create_space_invite` (token urlsafe, 7 dias, só owner), `accept_space_invite` (token válido/não usado; cria membership `member`), `remove_member` (só owner; não remove o próprio owner). `register_user` chama `provision_user` antes do commit.

`api/spaces.py` (todas com `get_current_user` + `require_member`): `GET /spaces` (do usuário), `POST /spaces/family`, `POST /spaces/{id}/invites` → `{link: f"{PUBLIC_BASE_URL}/invite/{token}"}`, `POST /spaces/invites/{token}/accept`, `DELETE /spaces/{id}/members/{user_id}`. Inclua o router em `main.py`.

- [ ] **Step 3: Migração e testes**

```bash
uv run alembic revision --autogenerate -m "spaces, categories, accounts"
uv run alembic upgrade head && uv run alembic check
uv run pytest -v
```
Expected: todos PASS (health, core, auth, spaces).

- [ ] **Step 4: Teste de API para o isolamento via HTTP**

Em `backend/tests/api/test_spaces_api.py`: registra A e B, A cria família e B tenta `POST /spaces/{fam}/invites` → 404; A convida, B aceita, A remove B, B acessa `GET /spaces` e não vê a família. Rode e confirme PASS.

- [ ] **Step 5: Qualidade e commit**

`uv run ruff check . && uv run ruff format . && uv run mypy app && uv run pytest`
```bash
git add -A && git commit -m "feat(spaces): add spaces, members, default categories, wallet and invites"
```

---

## Fechamento do marco

- [ ] Revisão por tarefa: o revisor do subagent-driven-development aprova cada task antes da próxima.
- [ ] `superpowers:verification-before-completion`: rode toda a suíte (backend, web, `alembic upgrade head && alembic check`, `docker compose ... up` + `curl /health`) e cole a saída real no PR.
- [ ] `/code-review high` no diff `main...feat/m1-foundation`; corrija, rode os testes de novo; repita até limpar.
- [ ] `git push -u origin feat/m1-foundation` e abra o PR contra `main` (**antes, pedir ao dono para publicar a `main`**); depois `/code-review high --comment <PR>`.
- [ ] Parar e pedir a revisão do PR ao dono.

## Autorrevisão do plano

- Cobertura: T1.1 (health, compose, CI, CLAUDE.md), T1.2 (todos os asserts do plano mestre), T1.3 (5 testes nomeados + `test_expired_invite_rejected`), T1.4 (4 testes nomeados + HTTP). CI com ruff, mypy, pytest, eslint, tsc, vitest e gitleaks.
- Tipos consistentes: `provision_user`, `require_member`, `create_family_space`, `create_space_invite`, `accept_space_invite`, `remove_member` usados com a mesma assinatura em testes e serviço.
- Lacuna conhecida: o `docker-compose.prod.yml` é só esqueleto; o M8 o completa.
