import contextvars
import ipaddress
import json
import logging
import re
import time
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.core.config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
log = logging.getLogger("app.access")
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por log. Só mensagem já formatada: o código não loga PII/segredos."""

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for k in ("method", "path", "status", "ms"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:  # só o tipo: o texto da exceção pode ter dados do usuário
            out["exc"] = record.exc_info[0].__name__ if record.exc_info[0] else "?"
        return json.dumps(out, ensure_ascii=False)


def configure_logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True  # o access log próprio não leva a query
    logging.getLogger("httpx").setLevel(logging.WARNING)  # URLs levam o token do bot


class RequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _RID_OK.match(incoming) else uuid.uuid4().hex
        tok = request_id_var.set(rid)
        t0 = time.monotonic()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
        finally:
            ms = round((time.monotonic() - t0) * 1000)
            log.info(
                "request",
                extra={"method": request.method, "path": request.url.path, "status": status,
                       "ms": ms},
            )  # fmt: skip
            request_id_var.reset(tok)
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if get_settings().HSTS:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp


def install(app: FastAPI) -> None:
    configure_logging()
    s = urlsplit(get_settings().PUBLIC_BASE_URL)
    app.add_middleware(
        CORSMiddleware, allow_origins=[f"{s.scheme}://{s.netloc}"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )  # fmt: skip
    app.add_middleware(RequestMiddleware)  # por último = mais externo: cobre inclusive o CORS


def client_ip(request: Request) -> str:
    """IP do cliente. X-Forwarded-For só vale se o peer direto está em TRUSTED_PROXIES."""
    peer = request.client.host if request.client else "unknown"
    nets = [n.strip() for n in get_settings().TRUSTED_PROXIES.split(",") if n.strip()]
    xff = request.headers.get("x-forwarded-for")
    if not nets or not xff:
        return peer
    try:
        trusted = [ipaddress.ip_network(n, strict=False) for n in nets]
        hops = [h.strip() for h in xff.split(",")]
        # da direita p/ esquerda: o primeiro salto não confiável é o cliente (o resto é forjável)
        cur = peer
        for hop in [*reversed(hops)]:
            if not any(ipaddress.ip_address(cur) in n for n in trusted):
                break
            cur = str(ipaddress.ip_address(hop))
        return cur
    except ValueError:
        return peer
