# M6 — Áudio e comprovante (plano curto)

Base: plano mestre T6.1/T6.2, spec 8.3/9/14.2.

## T6.1 STT
- `stt/` (FastAPI + faster-whisper CPU int8, `STT_MODEL`=small, pt, ffmpeg na imagem). `POST /transcribe`
  multipart -> `{text, duration_s}`; recusa > 10 MB (413) e > 180 s (413). Só rede interna; limites de CPU/mem no Compose
  (prod e dev, dev sob profile `stt`). Modelo baixa no 1º start (volume `stt_models`); nenhum teste baixa modelo.
- `app/ai/stt.py`: `Transcriber` Protocol (`transcribe(audio, mime) -> Transcript(text, duration_s)`; desvio do
  plano: devolve a duração para registrar `ai_usage.seconds`), `HttpWhisperTranscriber` (httpx, timeouts,
  erro -> `SttError` sem corpo/URL).
- Pipeline (`assistant/media.py`): vinculado -> baixa (teto 10 MB; Telegram checa `file_size` do getFile antes;
  Evolution só depois, o endpoint é base64) -> transcreve -> processa como texto. Resposta começa com
  `🎙️ "<120 chars>"`. Texto da transcrição nunca é logado. Falha: "Não consegui ouvir o áudio, pode escrever?".
  Uso por espaço (`ai_usage` kind `stt`, segundos). Remetente não vinculado: mídia nunca é baixada.

## T6.2 Comprovante
- `ai/receipt.py`: `ReceiptData` (limites como ParsedIntent), `ReceiptReader` Protocol, `OpenAIReceiptReader`
  (`chat.completions.parse` + `image_url` data URL; docs openai-python conferidas via context7; `AI_MODEL`
  padrão gpt-4.1 aceita visão). Só imagem + prompt mínimo; erros -> `ReceiptError` (`from None`); sem log de conteúdo.
- `domain/attachments.py` + tabela `attachments` (migração; `unique(origin, source_message_id)` = idempotência
  da mensagem): magic bytes jpeg/png/webp, <= 10 MB, nome `STORAGE_DIR/<space_id>/<uuid4>` sem extensão,
  diretórios 0700 / arquivo 0600. `transactions.attachment_id` ganha FK (SET NULL). `delete_account` apaga
  arquivos e linhas.
- `assistant/flows/receipt.py`: rascunho `Draft(action="launch", attachment_id)` em `conversation_state`
  kind `receipt`; SEMPRE pergunta `Lançar R$ 87,40 · Farmácia São João · 22/11? Responda "sim" ou corrija`.
  `sim` -> `launch.run` (grava com anexo; conta/espaço/categoria como no texto); correção ("é 90", "foi ontem",
  "categoria saúde") atualiza e pergunta de novo; ilegível -> pergunta o valor e depois confirma; "não" descarta.
- Serializado por usuário (lock existente) e idempotente (anexo por mensagem + unicidade do lançamento).

## Notas / lacunas
- Anexo sem confirmação (rascunho abandonado) fica órfão em disco: limpar com job de retenção (futuro).
- Sem rota autenticada para baixar o anexo: o web (M7.4 "anexo visível") precisa dela.
- Retenção: anexos vivem até excluir o espaço/conta.
