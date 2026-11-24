from datetime import date
from urllib.parse import urlencode

from app.core.config import get_settings


def _url(path: str, **query: str) -> str:
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    return f"{base}{path}" + (f"?{urlencode(query)}" if query else "")


def with_link(text: str, url: str) -> str:
    """Resposta + linha final com a URL pura (o web exige login: o link só abre o app)."""
    return f"{text}\nDetalhes no painel:\n{url}"


def caixinhas() -> str:
    return _url("/caixinhas")


def financiamentos() -> str:
    return _url("/financiamentos")


def lancamentos() -> str:
    return _url("/lancamentos")


def analises(period: str, start: date, end: date, *, expenses: bool = False) -> str:
    """/analises com a janela equivalente (`per` do web: mes = padrão, anterior; resto = custom)."""
    q = {"per": "anterior"} if period == "mes_passado" else {}
    if period not in ("mes", "mes_passado"):
        q = {"per": "custom", "start": start.isoformat(), "end": end.isoformat()}
    if expenses:
        q["type"] = "expense"
    return _url("/analises", **q)
