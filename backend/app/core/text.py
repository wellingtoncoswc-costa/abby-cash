import unicodedata


def fold(text: str) -> str:
    """minúsculas, sem acentos e sem caracteres de controle/não imprimíveis: base de toda
    comparação de texto livre."""
    s = unicodedata.normalize("NFKD", text.lower())
    return "".join(
        c for c in s if not unicodedata.combining(c) and unicodedata.category(c)[0] != "C"
    )


def clean_text(text: str, limit: int) -> str:
    """Remove caracteres de controle (inclui quebras de linha) e trunca."""
    return "".join(c for c in text if unicodedata.category(c)[0] != "C")[:limit].strip()


def restore_accents(value: str | None, source: str) -> str | None:
    """O modelo às vezes devolve texto livre sem a letra acentuada ("imvel" para "imóvel"). Se um
    trecho acentuado da mensagem original é quase igual ao valor, usa o trecho original. Só
    restaura (nunca reescreve): sem trecho parecido com acento, devolve o valor como veio."""
    import difflib

    if not value or value in source:
        return value
    words, key, n = source.split(), fold(value), len(value.split())
    best, best_r = None, 0.0
    for k in {max(1, n - 1), n, n + 1}:
        for i in range(len(words) - k + 1):
            cand = " ".join(words[i : i + k]).strip(".,;:!?")
            if cand.isascii():
                continue
            r = difflib.SequenceMatcher(None, key, fold(cand)).ratio()
            if r > best_r:
                best, best_r = cand, r
    return best if best is not None and best_r >= 0.85 else value
