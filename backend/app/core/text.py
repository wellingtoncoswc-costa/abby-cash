import unicodedata


def fold(text: str) -> str:
    """minúsculas e sem acentos: base de toda comparação de texto livre."""
    s = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in s if not unicodedata.combining(c))
