import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.assistant.amounts import MAX_TEXT, MONTH_WORDS, amount_candidates, extract_amount
from app.core.money import parse_brl
from app.core.text import fold

_WEEKDAYS = {
    "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6,
}  # fmt: skip
_RELATIVE = {"anteontem": 2, "ontem": 1, "hoje": 0}
_DAY_MONTH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_DAY = re.compile(r"\bdia\s+(\d{1,2})\b")
_DAY_OF_MONTH = re.compile(rf"\b(\d{{1,2}})\s+de\s+({MONTH_WORDS})\b")
_MONTH_NUMBER = {m: i for i, m in enumerate(MONTH_WORDS.split("|"), 1)}
_X_DE = re.compile(r"\b(\d{1,2})\s*x\s*de\s*(?:r\$\s*)?(\d[\d.,]*)")
_X = re.compile(r"\b(\d{1,2})\s*x\b|\b(\d{1,2})\s*(?:vezes|parcelas)\b")


@dataclass(frozen=True)
class Hints:
    """O que dá para tirar da mensagem sem IA. Etiquetas, data e parcelas são determinísticas
    (valem mais que o LLM); o valor só preenche o que o LLM deixou vazio."""

    amount_cents: int | None
    occurred_on: date | None  # data explícita: vale mais que a do modelo
    installments: int | None
    private: bool  # #pessoal
    family: bool  # #familia
    amounts: frozenset[int] = frozenset()  # todos os valores em dígitos da mensagem
    weekday_on: date | None = None  # "na sexta": só dica, nunca sobrescreve a data do modelo
    bad_date: bool = False  # "31/02": perguntar a data


class BadDate(ValueError):
    """Data que não existe (31/02): não se chuta, pergunta-se."""


_WD = "|".join(_WEEKDAYS)
_NOT_ORDINAL = r"(?!\s+(?:via|parcela|vez|parte|serie))"  # "segunda via", "quarta parcela"
# "na sexta", "sexta passada", "sexta-feira"; "terça/sábado/domingo" valem sozinhos
_WEEKDAY = re.compile(
    rf"\b(?:(?:na|no|nessa|nesse|desde|ultima|ultimo|a|o)\s+)({_WD})(?:-feira)?\b{_NOT_ORDINAL}"
    rf"|\b({_WD})(?:-feira|\s+passad[ao])\b|\b(terca|sabado|domingo)\b"
)


def _recent(month: int, day: int, today: date) -> date:
    """O dia/mês mais recente que não seja futuro (este ano ou o anterior)."""
    for year in (today.year, today.year - 1):
        try:
            found = date(year, month, day)
        except ValueError:
            continue
        if found <= today:
            return found
    raise BadDate


def resolve_date(text: str, today: date, *, weekdays: bool = True) -> date | None:
    """ "hoje", "ontem", "anteontem", "dia 15", "23/11" e, com `weekdays`, "na sexta" (a última);
    None se não houver. Levanta BadDate se a data não existe (31/02)."""
    s = fold(text[:MAX_TEXT])
    for word, back in _RELATIVE.items():
        if re.search(rf"\b{word}\b", s):
            return today - timedelta(days=back)
    if m := _DAY_MONTH.search(s):
        day, month = int(m.group(1)), int(m.group(2))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return None
        if m.group(3):
            year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
            try:
                return date(year, month, day)
            except ValueError:
                raise BadDate from None
        return _recent(month, day, today)
    if m := _DAY_OF_MONTH.search(s):  # "5 de outubro", "dia 25 de dezembro"
        day, month = int(m.group(1)), _MONTH_NUMBER[m.group(2)]
        return _recent(month, day, today) if 1 <= day <= 31 else None
    if m := _DAY.search(s):
        day = int(m.group(1))
        if not 1 <= day <= 31:
            return None
        year, month = today.year, today.month
        for _ in range(12):  # "dia 31" em novembro é 31/10
            try:
                found = date(year, month, day)
            except ValueError:
                found = None
            if found and found <= today:
                return found
            year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        raise BadDate
    if weekdays and (m := _WEEKDAY.search(s)):
        weekday = _WEEKDAYS[m.group(1) or m.group(2) or m.group(3)]
        return today - timedelta(days=(today.weekday() - weekday) % 7 or 7)
    return None


def extract_hints(text: str, today: date) -> Hints:
    s = fold(text[:MAX_TEXT])
    amount = extract_amount(text)
    installments: int | None = None
    plain = _DAY_OF_MONTH.sub(" ", _DAY_MONTH.sub(" ", _DAY.sub(" ", s)))  # datas não são parcelas
    if m := _X_DE.search(plain):  # "3x de 500": o valor informado é por parcela
        n, each = int(m.group(1)), parse_brl(m.group(2))
        if each and 2 <= n <= 48:
            installments, amount = n, n * each
    elif m := _X.search(plain):
        n = int(m.group(1) or m.group(2))
        installments = n if 2 <= n <= 48 else None
    occurred = weekday_on = None
    bad_date = False
    try:
        occurred = resolve_date(text, today, weekdays=False)
        weekday_on = None if occurred else resolve_date(text, today)
    except BadDate:
        bad_date = True
    return Hints(
        amount_cents=amount,
        occurred_on=occurred,
        weekday_on=weekday_on,
        bad_date=bad_date,
        amounts=frozenset(v for v, _ in amount_candidates(text)),
        installments=installments,
        private="#pessoal" in s,
        family="#familia" in s,
    )
