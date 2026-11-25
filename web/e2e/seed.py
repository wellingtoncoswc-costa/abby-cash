"""Cria um admin e N convites de cadastro no banco do ambiente (DATABASE_URL). Uso: uv run python ../web/e2e/seed.py 2"""
import asyncio
import secrets
import sys

from app.core.db import SessionLocal
from app.domain.users.service import create_admin, create_signup_invite


async def main(n: int) -> None:
    async with SessionLocal() as s:
        admin = await create_admin(s, email=f"admin-{secrets.token_hex(3)}@e2e.test", name="Admin", password=secrets.token_urlsafe(16))
        for _ in range(n):
            print((await create_signup_invite(s, created_by=admin.id)).code)


asyncio.run(main(int(sys.argv[1])))
