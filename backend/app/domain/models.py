"""Importa todos os models para registrar as tabelas em Base.metadata (Alembic e testes)."""

import app.domain.accounts.models  # noqa: F401
import app.domain.bills.models  # noqa: F401
import app.domain.budgets.models  # noqa: F401
import app.domain.cards.models  # noqa: F401
import app.domain.categories.models  # noqa: F401
import app.domain.spaces.models  # noqa: F401
import app.domain.transactions.models  # noqa: F401
import app.domain.users.models  # noqa: F401
