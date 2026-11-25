from datetime import date

import httpx
import pytest

from app.domain.errors import DomainError
from app.domain.investments.quotes import fetch_quotes, latest_close, range_for, upsert_quotes

BODY = (
    '{"results":[{"symbol":"PETR4","historicalDataPrice":['
    '{"date":1763996400,"close":38.5},{"date":1764082800,"close":null},'
    '{"date":1764169200,"close":38.456}]}]}'
)


def _transport(status=200, body=BODY):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/quote/PETR4" and "token" in req.url.params
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


async def test_fetch_parses_prices_in_cents_and_skips_null():
    qs = await fetch_quotes("PETR4", 30, _transport())
    assert [q.close_cents for q in qs] == [3850, 3846]  # 38,456 -> 3846 (arredonda)


async def test_unknown_or_malformed_ticker():
    with pytest.raises(DomainError, match="unknown_ticker"):
        await fetch_quotes("PETR4", 30, _transport(404, "{}"))
    with pytest.raises(DomainError, match="unknown_ticker"):
        await fetch_quotes("../x", 30, _transport())  # nunca vira caminho de URL


def test_range_for():
    assert (range_for(3), range_for(40), range_for(5000)) == ("5d", "3mo", "max")


async def test_upsert_and_latest_close(session):
    qs = await fetch_quotes("PETR4", 30, _transport())
    await upsert_quotes(session, "PETR4", qs)
    await upsert_quotes(session, "PETR4", qs)  # idempotente
    await session.commit()
    last = await latest_close(session, "PETR4", date(2099, 1, 1))
    assert last is not None and last.close_cents == 3846
    assert await latest_close(session, "PETR4", date(2000, 1, 1)) is None
