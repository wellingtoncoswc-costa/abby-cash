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
