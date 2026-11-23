import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.assistant.amounts import MAX_TEXT, MONTH_WORDS, extract_amount
from app.core.dates import clamp_day
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
    occurred_on: date | None
    installments: int | None
    private: bool  # #pessoal
    family: bool  # #familia


def resolve_date(text: str, today: date) -> date | None:
    """ "hoje", "ontem", "anteontem", "sexta" (a última), "dia 15", "23/11"; None se não houver."""
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
            return clamp_day(year, month, day)
        found = clamp_day(today.year, month, day)
        return found if found <= today else clamp_day(today.year - 1, month, day)
    if m := _DAY_OF_MONTH.search(s):  # "5 de outubro", "dia 25 de dezembro"
        day, month = int(m.group(1)), _MONTH_NUMBER[m.group(2)]
        if not 1 <= day <= 31:
            return None
        found = clamp_day(today.year, month, day)
        return found if found <= today else clamp_day(today.year - 1, month, day)
    for word, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{word}(?:-feira)?\b", s):
            return today - timedelta(days=(today.weekday() - weekday) % 7 or 7)
    if m := _DAY.search(s):
        day = int(m.group(1))
        if not 1 <= day <= 31:
            return None
        this_month = clamp_day(today.year, today.month, day)
        if this_month <= today:
            return this_month
        last = today.replace(day=1) - timedelta(days=1)
        return clamp_day(last.year, last.month, day)
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
    return Hints(
        amount_cents=amount,
        occurred_on=resolve_date(text, today),
        installments=installments,
        private="#pessoal" in s,
        family="#familia" in s,
    )
