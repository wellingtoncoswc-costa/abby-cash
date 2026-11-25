from datetime import date
from decimal import Decimal

from app.domain.investments.valuation import cdi_factors, fixed_value, weekday_factors

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)  # seg, ter, qua


def test_cdi_pct_compounds_from_the_day_after_the_buy():
    f = cdi_factors({D2: Decimal("0.05"), D3: Decimal("0.05")}, 10000)  # 100% do CDI
    assert fixed_value([(D1, 100_000)], f, D1) == 100_000  # no dia do aporte não rende
    assert fixed_value([(D1, 100_000)], f, D2) == 100_050
    assert fixed_value([(D1, 100_000)], f, D3) == 100_100  # 100_050 * 1,0005 = 100_100,02


def test_pct_of_cdi_scales_rate():
    f = cdi_factors({D2: Decimal("0.05")}, 11000)  # 110% do CDI
    assert fixed_value([(D1, 100_000)], f, D2) == 100_055


def test_redeem_reduces_balance_and_later_buys_start_late():
    f = cdi_factors({D2: Decimal("0.05"), D3: Decimal("0.05")}, 10000)
    moves = [(D1, 100_000), (D2, -50_050), (D2, 20_000)]
    # D2: 100_000 -> 100_050; resgate -50_050 e aporte +20_000 no mesmo dia => 70_000
    assert fixed_value(moves, f, D2) == 70_000
    assert fixed_value(moves, f, D3) == 70_035


def test_fixed_rate_uses_weekdays_over_252():
    f = weekday_factors(D1, D3, 1250)  # 12,5% a.a.; D2 e D3 são dias úteis
    assert set(f) == {D2, D3}
    v = fixed_value([(D1, 1_000_000)], f, D3)
    assert abs(v - 1_000_000 * 1.125 ** (2 / 252)) < 1
