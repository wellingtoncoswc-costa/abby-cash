from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal


def cdi_factors(rates: dict[date, Decimal], pct_bp: int) -> dict[date, Decimal]:
    """Fator de cada dia com CDI publicado: 1 + CDI diário (%) x % do CDI contratado."""
    return {d: 1 + r / 100 * Decimal(pct_bp) / 10000 for d, r in rates.items()}


def weekday_factors(start: date, end: date, rate_bp: int) -> dict[date, Decimal]:
    """Taxa prefixada a.a.: (1+taxa)^(1/252) por dia útil em (start, end].
    # ponytail: sem calendário de feriados (conta feriado como dia útil); ok p/ valor bruto estimado
    """
    f = (1 + Decimal(rate_bp) / 10000) ** (Decimal(1) / 252)
    days = (start + timedelta(n) for n in range(1, (end - start).days + 1))
    return {d: f for d in days if d.weekday() < 5}


def fixed_value(moves: list[tuple[date, int]], factors: dict[date, Decimal], on: date) -> int:
    """Saldo bruto em `on`, em centavos. `moves`: (data, +aporte/−resgate). O fator de um dia
    rende sobre o saldo do início do dia (movimentos do próprio dia só rendem a partir do seguinte).
    """
    by_day: dict[date, int] = {}
    for d, c in moves:
        by_day[d] = by_day.get(d, 0) + c
    bal = Decimal(0)
    for d in sorted(set(factors) | set(by_day)):
        if d > on:
            break
        bal = bal * factors.get(d, Decimal(1)) + by_day.get(d, 0)
    return int(bal.quantize(Decimal(1), ROUND_HALF_EVEN))
