from sqlalchemy import select

from app.domain.users.models import User


async def test_digest_toggle_command(ana):
    assert "ligado" in await ana.say("Resumo semanal ON")
    await ana.session.refresh(ana.user)
    assert ana.user.weekly_digest is True
    assert "desligado" in await ana.say("resumo semanal off")
    await ana.session.refresh(ana.user)
    assert (
        await ana.session.scalar(select(User.weekly_digest).where(User.id == ana.user.id)) is False
    )
