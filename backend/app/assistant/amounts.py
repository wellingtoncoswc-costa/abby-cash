import re

from app.core.money import parse_brl
from app.core.text import fold

MAX_TEXT = 500  # mensagem de chat: o resto é ignorado (limita o custo dos regex)
_MAX = 10**11  # R$ 1 bi: o mesmo teto de parse_brl
_UNITS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "quatorze": 14, "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
    "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40,
    "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
    "cem": 100, "cento": 100, "duzentos": 200, "trezentos": 300, "quatrocentos": 400,
    "quinhentos": 500, "seiscentos": 600, "setecentos": 700, "oitocentos": 800,
    "novecentos": 900,
}  # fmt: skip
_REAIS = {"real", "reais", "conto", "contos", "pila", "pilas"}
_CENTS = {"centavo", "centavos"}


def parse_amount_words(text: str, *, bare: bool = True) -> int | None:
    """Primeiro valor por extenso, em centavos: "mil e duzentos" -> 120000, "dois mil" -> 200000,
    "quarenta e cinco reais e cinquenta centavos" -> 4550. None se não houver. Com `bare=False` só
    vale com "reais/conto" depois ou com "mil" ("três amigos", "dois pastéis" não são valores)."""
    toks = re.findall(r"[a-z]+", fold(text[:MAX_TEXT]))
    n, i = len(toks), 0
    while i < n:
        if toks[i] not in _UNITS and toks[i] != "mil":
            i += 1
            continue
        total = cur = 0
        j = i
        while j < n:
            t = toks[j]
            if t in _UNITS:
                cur += _UNITS[t]
            elif t == "mil":
                total += (cur or 1) * 1000
                cur = 0
            elif not (t == "e" and j + 1 < n and (toks[j + 1] in _UNITS or toks[j + 1] == "mil")):
                break
            j += 1
        value = total + cur
        nxt = toks[j] if j < n else ""
        if nxt in _REAIS:
            cents, k = 0, j + 1
            if k + 1 < n and toks[k] == "e" and toks[k + 1] in _UNITS:
                k, c = k + 1, 0
                while k < n and toks[k] in _UNITS:
                    c, k = c + _UNITS[toks[k]], k + 1
                cents = c if k < n and toks[k] in _CENTS else 0
            result = value * 100 + cents
        elif value == 1:  # "uma pizza": artigo, não valor
            i = j
            continue
        elif not bare and "mil" not in toks[i:j]:
            i = j
            continue
        else:
            result = value * 100
        return result if 0 < result <= _MAX else None
    return None


_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
MONTH_WORDS = (
    "janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
)
_NOISE = re.compile(
    rf"#\w+|\bdia\s+\d{{1,2}}\b|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b|\b\d{{1,2}}\s+de\s+(?:{MONTH_WORDS})\b"
)
_INSTALL_X = re.compile(r"\b\d{1,2}\s*x\b")
_INSTALL_V = re.compile(r"\b\d{1,2}\s*(?:vezes|parcelas)\b")
_CURRENCY = re.compile(r"r\$|\b(?:reais|real|conto|contos)\b")
# "0", "R$ 0,00", "-10": valor que o chat recusa (e o modelo estruturado nem devolve)
ZERO_OR_NEG = re.compile(r"(?<![\w.,])(?:-\s?\d[\d.,]*|0+(?:[.,]0+)?)(?![\w.,])")


_CANDIDATE = re.compile(rf"(r\$\s*)?({_NUM})(\s*mil\b)?(\s*(?:reais|real|contos?)\b)?")


def amount_candidates(text: str) -> list[tuple[int, bool]]:
    """Todo valor em dígitos da mensagem, em centavos, e se vem marcado (R$, reais, mil). Ignora
    tags (#pessoal), datas ("dia 10", "23/11") e parcelas ("3x", "em 10 vezes")."""
    s = _INSTALL_V.sub(" ", _INSTALL_X.sub(" ", _NOISE.sub(" ", fold(text[:MAX_TEXT]))))
    out = []
    for m in _CANDIDATE.finditer(s):
        if cents := parse_brl(m.group(2)):
            out.append(
                (
                    cents * 1000 if m.group(3) else cents,
                    bool(m.group(1) or m.group(3) or m.group(4)),
                )
            )
    return out


def extract_amount(text: str) -> int | None:
    """Valor da mensagem, em centavos. Regra: o primeiro valor marcado (R$, reais, mil); sem
    marca, o MAIOR ("2 camisetas 100", "uber 2 pessoas 23"). Por extenso só com reais/conto/mil."""
    found = amount_candidates(text)
    if marked := [v for v, ok in found if ok]:
        return marked[0]
    if found:
        return max(v for v, _ in found)
    s = _INSTALL_V.sub(" ", _INSTALL_X.sub(" ", _NOISE.sub(" ", fold(text[:MAX_TEXT]))))
    return parse_amount_words(s, bare=False)


def parse_bare_amount(text: str) -> int | None:
    """Resposta que é SÓ um valor ("45", "R$ 45,50", "quarenta e cinco reais"); qualquer outra
    palavra -> None (a pessoa mudou de assunto)."""
    s = _CURRENCY.sub(" ", fold(text[:MAX_TEXT])).strip()
    if re.fullmatch(r"[\d.,\s]+", s):
        return parse_brl(s.replace(" ", ""))
    words = re.findall(r"[a-z]+", s)
    if words and all(w in _UNITS or w in {"mil", "e"} for w in words):
        return parse_amount_words(s)
    return None
