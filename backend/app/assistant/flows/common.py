from app.assistant.state import set_state
from app.assistant.turn import Draft, Turn


async def ask(t: Turn, d: Draft, kind: str, text: str) -> str:
    """Guarda a ação em andamento e devolve a pergunta; a próxima mensagem retoma (30 min)."""
    await set_state(
        t.session, t.user_id, t.channel, kind, {"draft": d.model_dump(mode="json")}, t.now
    )
    return text
