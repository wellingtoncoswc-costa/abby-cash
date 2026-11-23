from typing import Annotated

from pydantic import Field

# int estrito: 45.5 e "4500" viram 422 (dinheiro nunca é float nem string)
Cents = Annotated[int, Field(strict=True, gt=0)]
SignedCents = Annotated[int, Field(strict=True)]
