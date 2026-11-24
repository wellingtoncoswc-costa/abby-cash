import stat
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.ai.models import AiUsage
from app.ai.receipt import ReceiptData, ReceiptError
from app.ai.stt import SttError
from app.core.config import get_settings
from app.domain.attachments import Attachment
from app.domain.channels.models import InboundMessage
from app.domain.privacy import delete_account
from app.domain.transactions.models import Transaction
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import FakeReader, FakeTranscriber, expense
from tests.assistant.test_conversation import nubank_default, txs
from tests.factories import make_inbound

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
FARMACIA = ReceiptData(
    confidence=0.9, amount_cents=8740, merchant="Farmácia São João", occurred_on=date(2026, 11, 22)
)
ASK = 'Lançar R$ 87,40 · Farmácia São João · 22/11? Responda "sim" ou corrija'


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "STORAGE_DIR", str(tmp_path))
    return tmp_path


async def test_audio_message_transcribed_then_parsed(ana, parser, adapter, session):
    await nubank_default(session, ana.user)
    adapter.media, adapter.media_mime = b"OGG", "audio/ogg"
    tr = FakeTranscriber("gastei 45 no mercado", 3.5)
    ana.extra["transcriber"] = tr
    parser.add(expense(4500, "Alimentação", merchant="Mercado"))
    reply = await ana.say("", media_kind="audio")
    assert reply.startswith('🎙️ "gastei 45 no mercado"\n✅ R$ 45,00')
    assert parser.calls[0][0] == "gastei 45 no mercado" and tr.calls == [(3, "audio/ogg")]
    assert len(await txs(session)) == 1
    usage = await session.scalar(select(AiUsage).where(AiUsage.kind == "stt"))
    assert usage is not None and usage.seconds == 3.5


async def test_long_transcript_is_truncated_in_reply(ana, parser, adapter, session):
    await nubank_default(session, ana.user)
    ana.extra["transcriber"] = FakeTranscriber("gastei 45 no mercado " + "bla " * 60)
    parser.add(expense(4500, "Alimentação"))
    first = (await ana.say("", media_kind="audio")).split("\n")[0]
    assert first.endswith('…"') and len(first) <= 130


@pytest.mark.parametrize("fake", [FakeTranscriber(error=SttError("x")), FakeTranscriber("")])
async def test_audio_failure_asks_to_write(ana, parser, session, fake):
    ana.extra["transcriber"] = fake
    assert await ana.say("", media_kind="audio") == "Não consegui ouvir o áudio, pode escrever?"
    assert parser.calls == [] and await txs(session) == []


async def test_unlinked_sender_media_is_never_downloaded(session, adapter):
    iid = await make_inbound(session, None, media_kind="image")
    await process_inbound({"receipt_reader": FakeReader()}, str(iid))
    assert adapter.downloads == [] and "Vincular" in adapter.sent[0][1]


async def test_receipt_requires_confirmation(ana, adapter, session):
    await nubank_default(session, ana.user)
    adapter.media, adapter.media_mime = JPEG, "image/jpeg"
    ana.extra["receipt_reader"] = FakeReader(FARMACIA)
    assert await ana.say("", media_kind="image") == ASK
    assert await txs(session) == []
    assert await ana.say("talvez") != ASK  # outra mensagem: nada é gravado
    assert await txs(session) == []


async def test_receipt_confirm_creates_tx_with_attachment(ana, adapter, session, storage):
    await nubank_default(session, ana.user)
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(FARMACIA)
    await ana.say("", media_kind="image")
    reply = await ana.say("sim")
    assert reply.startswith("✅ R$ 87,40")
    [tx] = await txs(session)
    att = await session.get(Attachment, tx.attachment_id)
    assert att is not None and att.mime == "image/jpeg" and att.space_id == tx.space_id
    f = storage / att.path
    assert f.read_bytes() == JPEG and att.path.startswith(f"{tx.space_id}/")
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert tx.merchant == "Farmácia São João" and tx.occurred_on == date(2026, 11, 22)
    await ana.say("sim")  # estado consumido: não grava de novo
    assert len(await txs(session)) == 1


async def test_receipt_corrections_update_draft_and_ask_again(ana, adapter, session):
    await nubank_default(session, ana.user)
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(FARMACIA)
    await ana.say("", media_kind="image")
    assert await ana.say("é 90") == ASK.replace("87,40", "90,00")
    assert "25/11" not in await ana.say("foi ontem")
    assert await txs(session) == []
    assert (await ana.say("categoria saúde")).startswith("Lançar R$ 90,00")
    assert (await ana.say("sim")).startswith("✅ R$ 90,00 · Saúde")
    [tx] = await txs(session)
    assert tx.occurred_on == date(2026, 11, 24)


async def test_receipt_no_cancels(ana, adapter, session):
    await nubank_default(session, ana.user)
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(FARMACIA)
    await ana.say("", media_kind="image")
    assert await ana.say("não") == "Ok, não lancei."
    assert await txs(session) == []


async def test_receipt_unreadable_asks_amount(ana, adapter, session):
    await nubank_default(session, ana.user)
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(ReceiptError("x"))
    assert "Quanto foi?" in await ana.say("", media_kind="image")
    assert (await ana.say("50")).startswith("Lançar R$ 50,00")  # ainda confirma
    assert await txs(session) == []
    assert (await ana.say("sim")).startswith("✅ R$ 50,00")
    [tx] = await txs(session)
    assert tx.attachment_id is not None


async def test_non_image_and_oversize_are_refused(ana, adapter, session, storage):
    ana.extra["receipt_reader"] = FakeReader()
    adapter.media = b"%PDF-1.4 not an image"
    assert "JPEG, PNG ou WebP" in await ana.say("", media_kind="image")
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 0
    assert not any(storage.iterdir())


async def test_redelivered_image_reuses_attachment(ana, adapter, session):
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(FARMACIA, FARMACIA)
    iid = await make_inbound(session, None, media_kind="image")
    for _ in range(2):  # worker caiu e a mesma mensagem voltou a "received"
        await process_inbound(ana.extra, str(iid))
        await session.execute(update(InboundMessage).values(status="received"))
        await session.commit()
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 1
    assert len(adapter.downloads) == 1


async def test_delete_account_removes_attachment_files(ana, adapter, session, storage):
    await nubank_default(session, ana.user)
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(FARMACIA)
    await ana.say("", media_kind="image")
    await ana.say("sim")
    assert len([p for p in Path(storage).rglob("*") if p.is_file()]) == 1
    await delete_account(session, ana.user)
    assert [p for p in Path(storage).rglob("*") if p.is_file()] == []
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 0
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0


async def _draft(ana, adapter, session):
    await nubank_default(session, ana.user)
    adapter.media = JPEG
    ana.extra["receipt_reader"] = FakeReader(FARMACIA)
    await ana.say("", media_kind="image")


async def test_abandoned_receipt_draft_deletes_image(ana, adapter, session, storage):
    await _draft(ana, adapter, session)
    assert len([f for f in storage.rglob("*") if f.is_file()]) == 1
    await ana.say("não")
    assert not [f for f in storage.rglob("*") if f.is_file()]
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 0


async def test_delete_transaction_deletes_attachment(ana, adapter, session, storage):
    from app.domain.transactions.service import delete_transaction

    await _draft(ana, adapter, session)
    await ana.say("sim")
    [tx] = await txs(session)
    await delete_transaction(session, actor_id=ana.user.id, tx_id=tx.id)
    assert not [f for f in storage.rglob("*") if f.is_file()]
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 0


async def test_purge_orphan_attachments_keeps_linked_and_recent(ana, adapter, session, storage):
    from datetime import UTC, datetime, timedelta

    from app.domain.attachments import purge_orphan_attachments, save_image

    await _draft(ana, adapter, session)
    await ana.say("sim")  # anexo ligado a lançamento
    sp = ana.user.default_space_id
    old = await save_image(session, space_id=sp, origin="t", source_message_id="o", data=JPEG)
    await save_image(session, space_id=sp, origin="t", source_message_id="n", data=JPEG)
    await session.execute(
        update(Attachment)
        .where(Attachment.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=25))
    )
    await session.commit()
    assert await purge_orphan_attachments(session) == 1
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 2
