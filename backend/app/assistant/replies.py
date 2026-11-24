from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import format_brl
from app.domain.accounts.models import Account
from app.domain.budgets.service import BudgetAlert
from app.domain.cards.billing import split_installments
from app.domain.cards.models import CreditCard
from app.domain.categories.models import Category
from app.domain.transactions.models import Transaction

MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
    "outubro", "novembro", "dezembro",
]  # fmt: skip

NOT_UNDERSTOOD = "Não entendi. Tente: gastei 45 mercado — ou mande 'ajuda'."
HELP = (
    "Eu lanço seus gastos pelo chat. Exemplos:\n"
    "• gastei 45 no mercado\n"
    "• uber 23 ontem\n"
    "• tv 3000 em 10x no nubank\n"
    "• recebi 3000 de salário\n"
    "• #pessoal presente 150 (só você vê)\n"
    "Consultas: saldo · teto · faturas · quanto gastei esse mês\n"
    "Ajustes: corrigir · apagar último\n"
    "Contas: paguei · guardei 500 na viagem\n"
    "Resumo semanal: resumo semanal on · resumo semanal off"
)
DIGEST_ON = "✅ Resumo semanal ligado: domingo às 20h."
DIGEST_OFF = "Resumo semanal desligado."
AI_DOWN = "⚠️ A IA está indisponível agora; lancei do jeito simples (categoria Outros)."
CORRECT_PROMPT = (
    "O que está errado? Responda como: valor 50 · categoria Lazer · descrição cinema · "
    "data ontem. Ou mande 'apagar último'."
)
NO_FAMILY = "Você não tem um espaço familiar. Crie ou entre em um no painel web."
NO_CARD = "Não achei nenhum cartão cadastrado. Cadastre um no painel web (Cartões)."
NO_ACCOUNT = "Não achei nenhuma conta cadastrada. Cadastre uma no painel web (Contas)."
FUTURE_DATE = "Essa data é no futuro. Mande uma data de hoje ou passada."
BAD_DATE = "Essa data não existe. Mande de novo com uma data válida (ex.: 23/11)."
ALREADY = "Já registrei isso."
ALREADY_HANDLED = "Já tratei isso."
ZERO = "O valor precisa ser maior que zero."

_DOMAIN_ERRORS = {
    "amount_must_be_positive": ZERO,
    "amount_too_small": ZERO,
    "amount_too_large": "Esse valor é alto demais.",
    "invalid_date": "Data inválida.",
    "invalid_installments": "Parcelas: de 2 a 48.",
    "invalid_category": "Essa categoria não existe neste espaço.",
    "insufficient_saved": "Não há tanto guardado nessa meta.",
    "invalid_payment_amount": "Esse valor é maior do que falta pagar.",
    "not_editable": "Esse lançamento não pode ser corrigido pelo chat.",
    "installment_group_not_editable": (
        "Compra parcelada: só dá para corrigir categoria ou descrição. "
        "Para mudar valor ou data, apague e lance de novo."
    ),
    "card_date_not_editable": "Para mudar a data de uma compra no cartão, apague e lance de novo.",
}


def domain_error_text(code: str) -> str:
    """Só códigos conhecidos viram texto próprio; o resto é genérico (nunca detalhe interno)."""
    return _DOMAIN_ERRORS.get(code, "Não consegui concluir. Confira os dados e tente de novo.")


def http_error_text(status: int) -> str:
    if status == 403:
        return "Você não tem permissão para isso (conta ou lançamento de outra pessoa)."
    if status == 404:
        return "Não encontrei isso, ou você não tem acesso."
    return "Não consegui concluir."


def month_name(d: date) -> str:
    return MONTHS[d.month - 1]


def when_label(d: date, today: date) -> str:
    if d == today:
        return "hoje"
    return "ontem" if (today - d).days == 1 else f"{d:%d/%m}"


def account_label(type: str, name: str) -> str:
    if type == "wallet":
        return name
    return name if name.lower().startswith("conta") else f"Conta {name}"


def installments_text(total_cents: int, n: int) -> str:
    each = split_installments(total_cents, n)[-1]
    return f"{format_brl(total_cents)} em {n}x de {format_brl(each)}"


def months_list(months: list[date]) -> str:
    names = [MONTHS[m.month - 1][:3] for m in months]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]


def future_impact_text(each_cents: int, months: list[date]) -> str:
    return f"Compromete {format_brl(each_cents)} dos tetos de {months_list(months)}."


def alert_text(alert: BudgetAlert, month: date, category: str | None) -> str:
    spent, limit = format_brl(alert.spent), format_brl(alert.limit)
    scope = month_name(month) if category is None else f"{category} em {month_name(month)}"
    if alert.threshold == 101:
        return f"🚨 Você ultrapassou o teto de {scope}: {spent} de {limit}."
    return f"⚠️ Você atingiu {alert.threshold}% do teto de {scope}: {spent} de {limit}."


def options_text(question: str, labels: list[str]) -> str:
    lines = "\n".join(f"{i}) {x}" for i, x in enumerate(labels, 1))
    return f"{question} Responda com o número:\n{lines}"


async def tx_line(
    session: AsyncSession, tx: Transaction, today: date, *, total_cents: int | None = None,
    installments: int | None = None, private: bool = False, hint: bool = True,
) -> str:  # fmt: skip
    """`✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank` (+ linha de correção)."""
    category = "Sem categoria"
    if tx.category_id is not None:
        category = (
            await session.scalar(select(Category.name).where(Category.id == tx.category_id))
            or category
        )
    payment = "—"
    if tx.card_id is not None:
        name = await session.scalar(select(CreditCard.name).where(CreditCard.id == tx.card_id))
        payment = f"Cartão {name}"
    elif tx.account_id is not None:
        acc = await session.get(Account, tx.account_id)
        if acc is not None:
            payment = account_label(acc.type, acc.name)
    amount = (
        installments_text(total_cents, installments)
        if installments and total_cents
        else format_brl(tx.amount_cents)
    )
    parts = [amount, category]
    if label := (tx.merchant or tx.description):
        parts.append(label)
    parts += [when_label(tx.occurred_on, today), payment]
    if private:
        parts.append("🔒 pessoal")
    return "✅ " + " · ".join(parts) + ('\nResponda "corrigir" se errei.' if hint else "")
