from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.assistant.flows.query import period_bounds
from app.assistant.intents import ParsedIntent
from app.assistant.links import analises, with_link
from app.assistant.turn import Turn
from app.core.money import format_brl
from app.domain.reports.service import overview
from app.domain.transactions.service import NO_MERCHANT

EMPTY = "Sem lançamentos {label}. Registre um gasto, por exemplo: gastei 45 no mercado."


def pct_change(cur: int, prev: int) -> str:
    """Variação % inteira (meio longe de zero, só inteiros; igual ao web); "—" se prev == 0."""
    if prev == 0:
        return "—"
    n, d = abs((cur - prev) * 100), abs(prev)
    q = (2 * n + d) // (2 * d)
    return f"{'-' if cur < prev else '+'}{q}%" if q else "0%"


async def _overview(
    t: Turn, p: ParsedIntent, space_id: UUID
) -> tuple[dict[str, Any], str, date, date, str]:
    period = p.period or "mes"
    start, end, label = period_bounds(period, t.today)
    ov = await overview(
        t.session, viewer_id=t.user_id, space_id=space_id, start=start, end=end, today=t.today
    )
    return ov, period, start, end, label


async def resumo(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    ov, period, start, end, label = await _overview(t, p, space_id)
    tot, prev = ov["totals"], ov["previous"]
    if tot["tx_count"] == 0:
        return EMPTY.format(label=label)
    lines = [
        f"📊 Resumo {label}",
        f"Receitas {format_brl(tot['income_cents'])} · Despesas {format_brl(tot['expense_cents'])}"
        f" · Saldo {format_brl(tot['net_cents'])}",
        f"Despesas vs período anterior: {pct_change(tot['expense_cents'], prev['expense_cents'])}",
    ]
    if cats := ov["by_category"][:3]:
        lines.append(
            "Maiores categorias: "
            + " · ".join(
                f"{c['name']} {format_brl(c['expense_cents'])} ({c['share_bp'] // 100}%)"
                for c in cats
            )
        )
    if top := next((m for m in ov["by_merchant"] if m["merchant"] != NO_MERCHANT), None):
        lines.append(f"Maior estabelecimento: {top['merchant']} {format_brl(top['expense_cents'])}")
    soon = [u for u in ov["upcoming"] if u["due_on"] <= t.today + timedelta(days=7)]
    due = format_brl(sum(u["amount_cents"] for u in soon))
    lines.append(
        f"Contas nos próximos 7 dias: {len(soon)} ({due})"
        if soon
        else "Nenhuma conta vence nos próximos 7 dias."
    )
    return with_link("\n".join(lines), analises(period, start, end))


async def maiores(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    ov, period, start, end, label = await _overview(t, p, space_id)
    if not ov["largest"]:
        return EMPTY.format(label=label)
    cats = {c.id: c.name for c in (await t.context(space_id)).categories}
    lines = [f"💸 Maiores gastos {label}:"]
    for x in ov["largest"]:
        what = x["merchant"] or x["description"]
        lines.append(
            f"• {x['occurred_on']:%d/%m} · {what} · {format_brl(x['amount_cents'])} · "
            f"{cats.get(x['category_id'], 'Sem categoria')}"
        )
    return with_link("\n".join(lines), analises(period, start, end, expenses=True))
