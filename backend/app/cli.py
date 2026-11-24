import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.domain.users.models import User
from app.domain.users.service import create_admin, create_signup_invite


async def _admin(email: str, name: str) -> None:
    pwd = getpass("Password: ")
    if pwd != getpass("Confirm password: "):
        raise SystemExit("passwords do not match")
    async with SessionLocal() as s:
        try:
            await create_admin(s, email=email, name=name, password=pwd)
        except IntegrityError:
            raise SystemExit(f"email already registered: {email}") from None
    print("admin created")


async def _invite() -> None:
    async with SessionLocal() as s:
        admin = (await s.execute(select(User).where(User.is_admin).limit(1))).scalar_one_or_none()
        if admin is None:
            raise SystemExit("create an admin first")
        print((await create_signup_invite(s, created_by=admin.id)).code)


def main() -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    sub.add_parser("create-signup-invite")
    args = p.parse_args()
    asyncio.run(_admin(args.email, args.name) if args.cmd == "create-admin" else _invite())


if __name__ == "__main__":
    main()
