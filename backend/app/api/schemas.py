from typing import Annotated

from pydantic import Field

from app.core.money import MAX_CENTS

# int estrito: 45.5 e "4500" viram 422 (dinheiro nunca é float nem string)
Cents = Annotated[int, Field(strict=True, gt=0, le=MAX_CENTS)]
SignedCents = Annotated[int, Field(strict=True, ge=-MAX_CENTS, le=MAX_CENTS)]
