# M4 — WhatsApp (Evolution API) + fallback: plano curto

Escopo: T4.1 e T4.2 do plano mestre. Ponytail: o mínimo que cumpre o contrato.

## Decisões
- Canal `whatsapp_evolution`; rota existente `POST /webhooks/whatsapp_evolution` (mesmo `ingest`/limite de corpo 1 MB, JSON inválido -> 400).
- Segredo: header `x-webhook-secret` (configurado via `headers` no `webhook/set`) OU query `?token=`; `hmac.compare_digest`; `EVOLUTION_WEBHOOK_SECRET` vazio = tudo recusado (fail-closed).
- Aceita só `event == "messages.upsert"` (também `MESSAGES_UPSERT`); ignora: `fromMe`, JID que não termina em `@s.whatsapp.net` (grupos `@g.us`, `status@broadcast`, newsletters, `@lid`), tipos sem texto/áudio/imagem. `external_user_id` = dígitos do JID (E.164 sem `+`). `external_message_id` = `key.id`. Payload fora do formato -> `ValueError` -> 400.
- Mídia: `media_ref` = `key.id`; `download_media` chama `chat/getBase64FromMediaMessage` (stub funcional, usado no M6).
- Fixtures JSON escritas à mão no formato Evolution v2 (não capturadas de uma instância real).
- `EvolutionClient` (httpx, MockTransport nos testes, timeout 10 s, `apikey` só em header; erros viram `ChannelError` sem URL/chave): `send_text`, `connection_state`, `set_webhook`, `get_base64`. O adaptador a usa.
- `transactions.origin` VARCHAR(16) -> VARCHAR(32) (migração).
- Vínculo: `Channel = Literal["telegram","whatsapp_evolution"]` na API; o código é enviado por mensagem de WhatsApp (o `unlinked` do processor já aceita código puro); limitador de falhas já é por canal+remetente.
- `outbound_messages(id, user_id FK nullable, channel, status ok|failed, error_kind, created_at)`: sem texto (privacidade). Migração.
- `notify_user(user_id, text, *, prefer=None)` em `channels/sender.py`: ordem = prefer, `users.preferred_channel`, demais vínculos; para no primeiro sucesso; registra cada tentativa; devolve canal usado ou None. Abre sessão própria.
- `notify_members` passa a chamar `notify_user` para cada outro membro.
- Job `check_evolution_connection` (cron ARQ a cada 5 min, `jobs/health.py`): estado != `open` -> se `SET NX evolution:down` (sem TTL), avisa admins pelo Telegram; voltou a `open` -> apaga a chave. Sem EVOLUTION_URL configurado, não faz nada.
- LGPD: `delete_account` apaga `outbound_messages` do usuário (links/inbound já cobertos pelo canal genérico). Nada de texto em log.
- Respostas da conversa seguem pelo adaptador do canal do inbound (`get_adapter(channel)`), sem mudança no pipeline.
- Infra: serviço `evolution` (+ postgres/redis próprios) no compose de prod, imagem fixada, limites, sem porta pública; variante comentada no dev. README: chip dedicado + QR.

## Arquivos
`app/channels/{evolution,sender}.py`, `registry.py`, `app/jobs/health.py`, `worker.py`, `cli.py` (`evolution-set-webhook`), `api/channel_links.py`, `assistant/notify.py`, `domain/channels/models.py` (OutboundMessage), `domain/privacy.py`, 2 migrações, `infra/*`, `README.md`.

## Testes
- `tests/channels/test_evolution.py`: `test_ignores_group_and_from_me`, `test_parses_text_audio_image`, segredo (fail-closed, query), malformado, cliente (apikey fora de erros).
- `tests/channels/test_sender.py`: `test_fallback_to_telegram_on_whatsapp_failure`, só um canal, nenhum canal.
- `tests/jobs/test_health.py`: `test_disconnect_alert_once`, recuperação reabre o incidente.
- API: webhook 401/400, link-code whatsapp. Migração: transação com origin `whatsapp_evolution`. E2E: fixture WhatsApp + parser falso -> lançamento + resposta no canal. LGPD: delete_account limpa `outbound_messages`.
