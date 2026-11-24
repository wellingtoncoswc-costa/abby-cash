import re
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[3]
CONF = (ROOT / "infra/nginx/abby-cash.conf").read_text()


def _nginx_prefixes() -> set[str]:
    out: set[str] = set()
    for m in re.finditer(r"location\s+(?:=\s+|~\s+)?(\S+)\s*\{", CONF):
        loc = m.group(1)
        if loc.startswith("^/("):
            out |= set(loc[3:].split(")")[0].split("|"))
        elif loc.startswith("^/"):
            out.add(re.match(r"\^/(\w+)", loc).group(1))  # type: ignore[union-attr]
        elif re.fullmatch(r"/\w+/?", loc):
            out.add(loc.strip("/"))
    return out


def test_nginx_proxies_exactly_the_api_top_level_prefixes():
    api = {p.split("/")[1] for p in app.openapi()["paths"]}
    assert _nginx_prefixes() == api


def test_prefixes_that_are_also_spa_routes_fall_back_to_the_spa_for_html():
    router = (ROOT / "web/src/router.tsx").read_text()
    spa = set(re.findall(r"(?:pub|page)\('/(\w+)", router))
    block = re.search(r"location ~ \^/\(([^)]*)\).*?\n    \}", CONF, re.S)
    assert block and "$abby_html" in block.group(0)
    for clash in spa & {p.split("/")[1] for p in app.openapi()["paths"]}:
        assert clash in block.group(1).split("|") or clash in {"auth", "health", "webhooks"}, clash
