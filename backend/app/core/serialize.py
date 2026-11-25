from typing import Any


def row(obj: Any) -> dict[str, Any]:
    """Todas as colunas de um model como dict (valores monetários continuam int)."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
