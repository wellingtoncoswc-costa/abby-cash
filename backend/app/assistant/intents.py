from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

Intent = Literal[
    "lancar_despesa", "lancar_receita", "lancar_parcelado", "corrigir", "apagar", "pagar_conta",
    "nova_conta_a_pagar", "aporte_meta", "consultar_gastos", "consultar_teto", "consultar_saldo",
    "consultar_faturas", "ajuda", "desconhecido",
]  # fmt: skip
Period = Literal["hoje", "ontem", "semana", "mes", "mes_passado"]


class ParsedIntent(BaseModel):
    """Saída estruturada do LLM. Todo campo opcional é `| None = None` (e `confidence` não tem
    default): o SDK da OpenAI exige esquema estrito e o converte para "todos obrigatórios"."""

    intent: Intent
    confidence: float  # 0..1
    amount_cents: int | None = None  # valor TOTAL em centavos
    description: str | None = None
    merchant: str | None = None
    category_name: str | None = None
    account_hint: str | None = None  # "nubank", "pix", "dinheiro"
    card_hint: str | None = None
    installments: int | None = None
    occurred_on: date | None = None
    private: bool | None = None  # #pessoal
    goal_hint: str | None = None
    period: Period | None = None
    choice: int | None = None  # número escolhido numa lista

    @classmethod
    def of(cls, intent: Intent, **fields: Any) -> "ParsedIntent":
        """Resultado determinístico (atalhos, fallback): confiança máxima, salvo se informada."""
        return cls(intent=intent, **{"confidence": 1.0, **fields})
