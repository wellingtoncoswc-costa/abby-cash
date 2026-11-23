import csv
import io
import json
import zipfile
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import row
from app.domain.accounts.models import Account
from app.domain.audit import AuditLog, audit
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


def _csv_safe(v: Any) -> Any:
    """Anti CSV-injection: texto que começa com =+-@ (ou tab/CR) ganha ' na frente."""
    return "'" + v if isinstance(v, str) and v[:1] and v[0] in "=+-@\t\r" else v


async def export_user_data(session: AsyncSession, user: User) -> bytes:
    """Zip com data.json e transactions.csv dos espaços de que o usuário é membro (e só deles).

    Privacidade: lançamentos são filtrados por `space_id`, então itens privados de outros
    espaços numa conta/fatura compartilhada nem entram (equivale ao extrato, que os soma sem
    detalhar; aqui nem o total). Referências a contas/cartões/faturas/contas a pagar de fora
    do export viram null. Sem hash de senha, TOTP, tokens nem dados de outros usuários.
    # ponytail: zip montado em memória; ok até ~100 mil lançamentos (dezenas de MB),
    # acima disso gerar em arquivo temporário/streaming.
    """
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
    budget_ids = [b["id"] for b in data["budgets"]]
    cats = await session.scalars(
        select(BudgetCategory).where(BudgetCategory.budget_id.in_(budget_ids))
    )
    data["budget_categories"] = [row(c) for c in cats]
    members = await session.scalars(select(SpaceMember).where(SpaceMember.space_id.in_(space_ids)))
    # só UUIDs dos outros membros: sem e-mail/nome
    data["space_members"] = [
        row(m) | ({} if m.user_id == user.id else {"default_account_id": None}) for m in members
    ]
    known = {
        "account_id": {a["id"] for a in data["accounts"]},
        "counter_account_id": {a["id"] for a in data["accounts"]},
        "card_id": set(card_ids),
        "invoice_id": {i["id"] for i in data["invoices"]},
        "bill_id": {b["id"] for b in data["bills"]},
    }
    for t in data["transactions"]:
        for col, ids in known.items():
            if t[col] is not None and t[col] not in ids:
                t[col] = None
    audit(session, user.id, "privacy.export", "user", user.id)
    await session.commit()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({k: _csv_safe(v) for k, v in t.items()} for t in data["transactions"])
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
        (SpaceMember, SpaceMember.default_account_id, accs),
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
    # FOR UPDATE: serializa com accept_space_invite (que trava o mesmo espaço)
    owned = list(
        await session.scalars(select(Space.id).where(Space.owner_id == uid).with_for_update())
    )
    for sid in owned:
        others = await session.scalar(
            select(func.count())
            .select_from(SpaceMember)
            .where(SpaceMember.space_id == sid, SpaceMember.user_id != uid)
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
    # Decisão: actor_id é nullable, então as linhas de auditoria do usuário são anonimizadas
    # (actor_id -> NULL); a ação e o entity_id (UUID pseudônimo, sem dados pessoais) ficam.
    await session.execute(update(AuditLog).where(AuditLog.actor_id == uid).values(actor_id=None))
    audit(session, None, "privacy.delete_account", "user", uid)  # só o UUID, sem dados
    await session.commit()
