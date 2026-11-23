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


async def _poll() -> None:
    from app.channels.poll import poll_forever
    from app.channels.registry import telegram_adapter

    adapter = telegram_adapter()
    await adapter.delete_webhook()  # getUpdates não funciona com webhook ativo
    print(f"polling como @{await adapter.bot_username()} (Ctrl+C para sair)")
    await poll_forever(adapter)


async def _set_webhook(url: str | None) -> None:
    from app.channels.registry import telegram_adapter
    from app.core.config import get_settings

    target = url or f"{get_settings().PUBLIC_BASE_URL.rstrip('/')}/webhooks/telegram"
    if not target.startswith("https://"):
        raise SystemExit("the Telegram webhook needs a public https URL (use telegram-poll in dev)")
    await telegram_adapter().set_webhook(target)
    print(f"webhook set: {target}")


def main() -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    sub.add_parser("create-signup-invite")
    sub.add_parser("telegram-poll")
    w = sub.add_parser("telegram-set-webhook")
    w.add_argument("--url", help="default: PUBLIC_BASE_URL/webhooks/telegram")
    args = p.parse_args()
    if args.cmd == "create-admin":
        asyncio.run(_admin(args.email, args.name))
    elif args.cmd == "telegram-poll":
        try:
            asyncio.run(_poll())
        except KeyboardInterrupt:
            pass
    elif args.cmd == "telegram-set-webhook":
        asyncio.run(_set_webhook(args.url))
    else:
        asyncio.run(_invite())


if __name__ == "__main__":
    main()
