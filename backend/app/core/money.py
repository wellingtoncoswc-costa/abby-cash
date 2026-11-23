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
    if not value.is_finite():  # "nan"/"inf" parse as Decimal
        return None
    cents = int((value * 100).to_integral_value())
    return cents if cents > 0 else None


def format_brl(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"
