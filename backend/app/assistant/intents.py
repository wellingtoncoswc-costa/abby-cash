from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from app.core.text import clean_text

Intent = Literal[
    "lancar_despesa", "lancar_receita", "lancar_parcelado", "corrigir", "apagar", "pagar_conta",
    "nova_conta_a_pagar", "aporte_meta", "consultar_gastos", "consultar_teto", "consultar_saldo",
    "consultar_faturas", "guardar_caixinha", "resgatar_caixinha", "consultar_caixinhas",
    "consultar_financiamentos", "transferir_contas", "ajuda", "desconhecido",
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
    category_index: int | None = None  # nº na lista de categorias do prompt
    account_hint: str | None = None  # "nubank", "pix", "dinheiro"
    to_account_hint: str | None = None  # transferir_contas: DESTINO (a origem é account_hint)
    card_hint: str | None = None
    installments: int | None = None
    occurred_on: date | None = None
    private: bool | None = None  # #pessoal
    goal_hint: str | None = None
    pocket_hint: str | None = None  # nome (ou parte) da caixinha OU do financiamento/consórcio
    period: Period | None = None
    choice: int | None = None  # número escolhido numa lista

    @field_validator("amount_cents")
    @classmethod
    def _amount(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 10**10:
            raise ValueError("amount_cents fora do intervalo")
        return v

    @field_validator("installments")
    @classmethod
    def _installments(cls, v: int | None) -> int | None:
        if v is not None and not (v == 1 or 2 <= v <= 72):
            raise ValueError("installments fora do intervalo")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, v: float) -> float:
        if not 0 <= v <= 1:  # falso também para NaN
            raise ValueError("confidence fora de 0..1")
        return v

    @field_validator("choice")
    @classmethod
    def _choice(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 99:
            raise ValueError("choice fora de 1..99")
        return v

    @field_validator("description", "merchant")
    @classmethod
    def _long_text(cls, v: str | None) -> str | None:
        return None if v is None else clean_text(v, 200)

    @field_validator("account_hint", "to_account_hint", "card_hint", "goal_hint", "pocket_hint")
    @classmethod
    def _hint(cls, v: str | None) -> str | None:
        return None if v is None else clean_text(v, 100)

    @classmethod
    def of(cls, intent: Intent, **fields: Any) -> "ParsedIntent":
        """Resultado determinístico (atalhos, fallback): confiança máxima, salvo se informada."""
        return cls(intent=intent, **{"confidence": 1.0, **fields})
