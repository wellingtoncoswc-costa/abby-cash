from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from app.core.text import clean_text

Intent = Literal[
    "lancar_despesa", "lancar_receita", "lancar_parcelado", "corrigir", "apagar", "pagar_conta",
    "nova_conta_a_pagar", "aporte_meta", "consultar_gastos", "consultar_teto", "consultar_saldo",
    "consultar_faturas", "guardar_caixinha", "resgatar_caixinha", "consultar_caixinhas",
    "consultar_financiamentos", "transferir_contas", "criar_caixinha", "criar_financiamento",
    "baixar_parcela", "ajuda", "desconhecido",
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
    # criar_caixinha / criar_financiamento (amount_cents = valor da PARCELA) / baixar_parcela
    new_name: str | None = None  # nome da caixinha ou do financiamento a criar
    cdi_bp: int | None = None  # % do CDI x 100 (120% = 12000)
    loan_kind: Literal["financing", "consortium"] | None = None
    loan_installments: int | None = None  # total de parcelas do financiamento (1..480)
    first_due_on: date | None = None  # 1º vencimento
    paid_installments: int | None = None  # parcelas já pagas antes do cadastro (0..480)
    installment_number: int | None = None  # baixar_parcela: nº da parcela (ou até qual)
    through: bool | None = None  # baixar_parcela: "até a 17" (todas de 1 a N)

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

    @field_validator("cdi_bp")
    @classmethod
    def _cdi(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 100_000:
            raise ValueError("cdi_bp fora do intervalo")
        return v

    @field_validator("loan_installments", "installment_number")
    @classmethod
    def _n480(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 480:
            raise ValueError("parcelas fora de 1..480")
        return v

    @field_validator("paid_installments")
    @classmethod
    def _paid(cls, v: int | None) -> int | None:
        if v is not None and not 0 <= v <= 480:
            raise ValueError("paid_installments fora de 0..480")
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

    @field_validator(
        "account_hint", "to_account_hint", "card_hint", "goal_hint", "pocket_hint", "new_name"
    )
    @classmethod
    def _hint(cls, v: str | None) -> str | None:
        return None if v is None else clean_text(v, 100)

    @classmethod
    def of(cls, intent: Intent, **fields: Any) -> "ParsedIntent":
        """Resultado determinístico (atalhos, fallback): confiança máxima, salvo se informada."""
        return cls(intent=intent, **{"confidence": 1.0, **fields})
