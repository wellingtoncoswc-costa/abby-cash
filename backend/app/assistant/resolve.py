import difflib

from app.assistant.context import CtxCategory, SpaceContext
from app.core.text import fold


def pick_category(ctx: SpaceContext, kind: str, idx: int | None) -> CtxCategory | None:
    """Categoria do nº (base 1) da lista do prompt; None se fora da faixa ou de outro tipo
    (o chamador usa a 'Outros' do tipo)."""
    if idx is None or not 1 <= idx <= len(ctx.categories):
        return None
    cat = ctx.categories[idx - 1]
    return cat if cat.kind == kind else None


def resolve_hint(hint: str | None, names: list[str]) -> str | None:
    """Nome da lista que melhor casa com o texto do usuário (sem acento/caixa; aproximado)."""
    if not hint:
        return None
    by_fold = {fold(n): n for n in names}
    found = difflib.get_close_matches(fold(hint), list(by_fold), n=1, cutoff=0.7)
    return by_fold[found[0]] if found else None
