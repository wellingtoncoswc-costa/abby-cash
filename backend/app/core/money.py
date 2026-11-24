import re
from decimal import Decimal, InvalidOperation

_CHARS = re.compile(r"^[\d.,]+$")
MAX_CENTS = 10**12  # R$ 10 bi: teto de qualquer valor monetário (cabe em BIGINT)
_MAX_PARSED_CENTS = 10**11  # R$ 1 bi: teto de valor digitado no chat
_THOUSANDS = re.compile(r"^[1-9]\d{0,2}(\.\d{3})+$")


def parse_brl(text: str) -> int | None:
    s = text.lower().replace("r$", "").replace("reais", "").replace("real", "").strip()
    s = s.replace(" ", "")
    if not _CHARS.match(s):  # só dígitos, '.' e ','; rejeita 1e30, 1_000, nan, sinal
        return None
    if "," in s:
        whole, _, frac = s.partition(",")
        if not (_THOUSANDS.match(whole) or whole.isdigit()) or not re.fullmatch(r"\d{0,2}", frac):
            return None
        s = f"{whole.replace('.', '')}.{frac}"
    elif _THOUSANDS.match(s):
        s = s.replace(".", "")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if not value.is_finite():  # "nan"/"inf" parse as Decimal
        return None
    scaled = value * 100
    if scaled != scaled.to_integral_value():  # sem arredondamento silencioso
        return None
    cents = int(scaled)
    return cents if 0 < cents <= _MAX_PARSED_CENTS else None


def format_brl(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"
