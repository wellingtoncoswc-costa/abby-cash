# Abby Cash M3 — Assistente no Telegram: Plano detalhado (TDD)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **Use ponytail em tudo** (passe esta instrução a todo subagente). TDD, testes, review e verificação continuam integrais.

**Goal:** conversar com o Abby Cash pelo Telegram (somente texto): vincular o chat à conta, lançar despesas/receitas/parcelados em linguagem natural (OpenAI), perguntar o que faltar, confirmar, corrigir/apagar o último lançamento, aprender categorias, consultar gastos/saldo/teto/faturas, quitar contas, aportar em metas e receber alertas de teto. Sem áudio, foto, WhatsApp ou web neste marco.

**Architecture:** continua o pacote Python `app`. O canal é um adaptador (`app/channels/`) atrás de uma interface única; **webhook e polling usam a mesma porta de entrada** (`ingest`: grava `inbound_messages` com UNIQUE e enfileira). O worker ARQ executa `process_inbound`: vínculo → atalhos sem IA → interpretador (OpenAI, atrás de `IntentParser`) → pistas determinísticas (valor, data, parcelas, `#pessoal`) → fluxos (`app/assistant/flows/`) que chamam **os serviços de domínio do M2** (`create_transaction`, `register_card_purchase`, `pay_bill`, `pay_invoice`, `contribute`, `create_bill`, `evaluate_thresholds`) → resposta. Perguntas pendentes ficam em `conversation_state` (30 min). Editar/apagar lançamento nasce **no domínio** (`update_transaction`/`delete_transaction`), que o M2 deixou para este marco.

**Tech Stack:** a do M1/M2 + `openai` (SDK oficial, `AsyncOpenAI`), `httpx` (já presente, Telegram) e, só em desenvolvimento, `pyyaml`/`types-pyyaml` (conjunto de avaliação).

**Interfaces:** exatamente as do plano mestre (`docs/superpowers/plans/2026-11-23-abby-cash-v1.md`), T3.1–T3.4. Nenhuma renomeada. Extensões usadas aqui: (a) funções com banco recebem `session` primeiro (como no M2); (b) `InboundMessage` (dataclass do canal) e `InboundMessage` (model) têm o mesmo nome em módulos diferentes (`app.channels.base` × `app.domain.channels.models`), o model é importado com alias onde convive; (c) `ParsedIntent` ganha `choice` (número escolhido numa lista) e `ParsedIntent.of(...)`; (d) `TelegramAdapter` tem métodos extras além do protocolo (`parse_update`, `get_updates`, `set_webhook`, `delete_webhook`, `bot_username`).

## Decisões do dono (2026-11-23, respondidas durante a execução; prevalecem sobre o texto abaixo)

1. **"apagar último" PEDE confirmação** antes de apagar ("Apagar R$ 45,00 · Mercado? Responda sim ou não"; estado em `conversation_state`, expira em 30 min; só "sim" apaga). Onde o plano diz que apaga direto, implemente a confirmação e ajuste os testes.
2. **"gastos"/consultas somam pela data da compra** (`occurred_on`) também no cartão; o teto continua pelo mês de vencimento da fatura.
3. **Alertas de teto vão a todos os membros do espaço** pelo canal de cada um.
4. **`paguei`, aporte em meta e nova conta a pagar saem em versão mínima no M3**; ambiguidade com lista numerada e lembretes chegam no M5.
5. Enviar texto da mensagem e nomes de categorias/contas/cartões/metas do espaço à OpenAI foi aceito pelo dono ao escolher o provedor.


## Decisões técnicas do marco (registradas)

- **Provedor de IA: OpenAI (não Anthropic).** `OpenAIIntentParser` usa o SDK oficial `openai` (`AsyncOpenAI`), modelo de `settings.AI_MODEL` (padrão `gpt-4.1`), chave `OPENAI_API_KEY`, timeout `AI_TIMEOUT_S` (20 s) e `max_retries=1`. Saída estruturada pelo modelo Pydantic `ParsedIntent` via `client.chat.completions.parse(..., response_format=ParsedIntent)`.
- **API verificada (context7 `/openai/openai-python`, `helpers.md`, + o próprio SDK instalado, `openai` 3.57):** `chat.completions.parse(model, messages, response_format=<Pydantic>)` devolve `ParsedChatCompletion`; o resultado está em `choices[0].message.parsed` e, se o modelo recusar, `parsed is None` e `message.refusal` traz o texto; `completion.usage` é `CompletionUsage | None` com `prompt_tokens`/`completion_tokens`; o cliente aceita `timeout` e `max_retries` (padrão 2, repete conexão/408/409/429/5xx) e os erros herdam de `openai.APIError`. A doc também mostra `responses.parse`; ficamos no Chat Completions por ser o que o plano mestre prevê e por servir igual à visão (M6). **Conferência no SDK instalado (Task 3.3, Step 6):** `type_to_response_format_param(ParsedIntent)` gera esquema estrito (`strict: true`, todos os campos em `required`, opcionais como `anyOf [..., null]`, `additionalProperties: false`, `format: date`) — por isso nenhum campo de `ParsedIntent` tem default diferente de `None` e `confidence` é obrigatório.
- **Modelo (ponto de atenção honesto):** a documentação consultada não traz a matriz "modelo × Structured Outputs × visão". A busca na web (WebSearch; context7 não lista modelos) não achou declaração oficial; achou um tópico de comunidade cuja resposta inicial ("gpt-4.1 não suporta") foi corrigida (suporta Structured Outputs) e a doc da Azure confirmando visão na série GPT-4.1. Por isso **a Task 3.3 termina rodando `scripts/run_eval.py` com a chave real** (manual, nunca no CI): se a API recusar o modelo/`response_format`, troca-se `AI_MODEL` no `.env` — sem mudar código. `temperature=0` é enviado; modelos de raciocínio não aceitam, então ao trocar `AI_MODEL` para um deles remova esse argumento.
- **Avaliação real (T3.3, Step 10):** `gpt-4.1` aceitou Structured Outputs; 47/52 (90%) e, após ajuste do prompt, 49/52 (94%). As falhas restantes são quase todas `category_name` com o acento corrompido pelo modelo (ex. `Sa\x00ade`, estocástico no modo estrito): a T3.4 deve casar a categoria por `fold` e, sem casar, cair em "Outros". Há também timeouts raros (`APITimeoutError`) tratados pelo fallback.
- **Testes de unidade nunca vão à rede:** o interpretador é um `FakeParser`; o cliente OpenAI é um objeto falso; o Telegram usa `httpx.MockTransport`; o webhook usa o `FakeAdapter`. Só `scripts/run_eval.py` fala com o modelo real.
- **Fixtures do Telegram:** JSON no formato oficial da Bot API (`tests/fixtures/telegram/*.json`). Foram escritas à mão a partir da documentação (não capturadas); trocar por capturas reais é um ponto do dono (ver "Pontos que dependem do dono").
- **Telegram só 1:1, só texto/mídia de pessoas.** `parse_update` ignora grupos, `edited_message`, bots e mensagens sem texto nem mídia. `external_message_id = "<chat_id>:<message_id>"` (o `message_id` só é único dentro do chat). `external_user_id = chat_id`.
- **Dev sem HTTPS público:** `python -m app.cli telegram-poll` (long polling com `getUpdates`, apaga o webhook antes) alimenta o **mesmo** `ingest`; `python -m app.cli telegram-set-webhook [--url]` registra o webhook em produção (exige `https://`, envia o segredo em `secret_token`). O `@` do bot vem de `TELEGRAM_BOT_USERNAME` (opcional) ou de `getMe` em tempo de execução; nunca fica no código. Erros do cliente Telegram **não vazam o token** (a URL contém o token): `ChannelError` só carrega o nome do método e o tipo do erro.
- **Idempotência em três camadas:** (1) `UNIQUE(channel, external_message_id)` + `INSERT ... ON CONFLICT DO NOTHING RETURNING id` (cobre reenvio e entrega simultânea); (2) `_job_id = inbound_id` no ARQ; (3) `claim` atômico `received → processing` no worker (uma reentrega do mesmo job não reexecuta). Se enfileirar falhar, a linha é apagada e o erro sobe (500): o reenvio do Telegram entra de novo, sem mensagem perdida. O teste obrigatório `test_duplicate_webhook_creates_single_transaction` fica na Task 3.4 (precisa do pipeline); a Task 3.2 cobre a ingestão única.
- **Vínculo:** código de 6 dígitos no Redis (`linkcode:<código>` → `<user_id>:<canal>`, TTL 10 min, uso único via `DEL`), no máximo **5 tentativas por remetente** por janela de 10 min (`link_attempts:<canal>:<id>`; acima disso nem o código certo passa). Código vale só para o canal em que foi criado. Um chat só se vincula a um usuário (`already_linked`); religar troca o `external_user_id`. `POST /channels/link-code` limita a 5 códigos por janela (`_hit` do auth) e devolve o `deep_link` `https://t.me/<bot>?start=<código>` (ou `null` se o `getMe` falhar). Remetente não vinculado recebe **só** a instrução fixa; nada é gravado no domínio.
- **Interpretação — o que é de quem:** o LLM decide a intenção e sugere categoria/estabelecimento/forma de pagamento; o determinístico (`hints.py`) decide **etiquetas (`#pessoal`/`#familia`), data, parcelas** (valem mais que o LLM) e **preenche o valor** que o LLM deixou vazio. Com parcelas explícitas ("3x de 500", "em 10 vezes"), o valor total da mensagem manda (o LLM costuma errar o total). Espaço: `#pessoal` → espaço pessoal; `#familia` → espaço familiar; senão `users.default_space_id`. Datas relativas são calculadas sobre o **dia local da hora da mensagem** (`received_at` no fuso do usuário), o que torna o teste determinístico.
- **Valor por extenso:** `parse_amount_words` ("mil e duzentos" → 120000, "quarenta e cinco" → 4500, "dois mil" → 200000; reais/centavos, "contos"/"pilas"); `extract_amount` (dígitos ou extenso, ignora `#tags`, "dia 10", "23/11", "5 de outubro", "3x", "em 10 vezes"); `parse_bare_amount` (resposta que é **só** um valor: qualquer outra palavra = mudou de assunto, e a pergunta pendente é descartada em vez de gravar o valor errado). Zero ou negativo nunca lança: pergunta de novo.
- **Perguntas pendentes (`conversation_state`, 30 min, relativo à hora da mensagem):** `amount` (falta o valor), `confirm` (confiança < 0,6), `payment` (qual conta/cartão; lista numerada), `pick_bill` (qual conta a pagar; lista numerada), `correct` (o que corrigir). A ação inteira vai em JSON (`Draft`). Resposta que não é resposta ("saldo") descarta o estado e vira mensagem nova; "cancelar" limpa.
- **Conta/cartão:** dica da mensagem → padrão do espaço (`space_members.default_account_id`) → pergunta. Parcelado exige cartão (dica ou único cartão; vários = pergunta; nenhum = explica). "no dinheiro" → carteira; "no pix"/"no débito" não saem da carteira. Dica que não casa com nada pergunta, não cai em silêncio na conta padrão. Contas e cartões oferecidos são os de **qualquer espaço de que o usuário é membro** (spec 14.1); o lançamento fica no espaço-alvo.
- **Categoria:** regra aprendida (`category_rules`: `merchant_norm` → categoria) > categoria sugerida (existente no espaço, do tipo certo) > "Outros". Corrigir a categoria grava/atualiza a regra (`ON CONFLICT DO UPDATE`).
- **Editar/apagar no domínio (T3.4, Parte 1):** `update_transaction` e `delete_transaction` exigem ser **o autor ou o dono do espaço** (membro comum: 403; não membro: 404), validam como `create_transaction` (`check_common`), gravam `audit()` e fazem o reajuste: compra de cartão reajusta a conta espelho (`sync_invoice_bill`); apagar pagamento de fatura/conta **reabre** a conta; **apagar compra parcelada apaga o grupo inteiro**. Só despesa/receita sem `bill_id`/`goal_id` é editável (pagamentos e aportes só podem ser apagados); parcelado só aceita categoria/descrição/estabelecimento (valor e data: apague e lance de novo); data de compra no cartão não muda (mudaria a fatura). Sem rotas REST aqui: a edição na web é do M7.
- **"corrigir"/"apagar último" são escopados:** o "último" é o último lançamento **do próprio usuário** com `origin == <canal>`. Pagamentos e aportes feitos pelo chat recebem a origem do canal (`tag_origin`), então também podem ser desfeitos. "Apagar último" não pede confirmação (é um comando explícito) e responde dizendo o que apagou.
- **Teto:** após **qualquer despesa** (inclusive cartão) roda `evaluate_thresholds` nos meses afetados (mês da data para dinheiro; mês de vencimento de cada fatura para cartão, via `future_impact`) e os alertas entram na resposta; os **outros membros do espaço** são avisados pelos canais vinculados (`notify_members`: o teto é do espaço e o alerta é registrado uma única vez em `budget_alerts_sent`, então quem cruza o limiar não pode ser o único a saber). Parcelado: frase "Compromete R$ 200,00 dos tetos de dez, jan e fev." só com os meses que têm teto. O M4 troca `notify_members` por `notify_user` (com fallback de canal) e o M5 reaproveita `alert_text`.
- **Consultas e privacidade:** toda consulta parte do espaço-alvo (já checado com `require_member`) ou dos espaços de que o usuário é membro. `gastos`/`teto` usam só o espaço-alvo (o `#pessoal` de outra pessoa nunca está nele); `saldo` lista contas dos espaços do usuário; `faturas` usa `invoice_statement` e mostra "inclui R$ X de lançamentos privados" só como **total agregado** (spec 14.1). "gastos" soma despesas por **data da compra** (inclui cartão); o teto continua pelo mês de vencimento da fatura (`month_spending`).
- **LLM fora do ar (spec 9):** timeout/erro/recusa → `fallback_launch`: `extract_amount` + o resto como descrição, categoria "Outros", intenção despesa (ou receita se começar com "recebi/ganhei/caiu"), com aviso `⚠️`. Sem valor: "Não entendi. Tente: gastei 45 mercado". Consultas e demais intenções dependem do LLM (atalhos como `saldo` não).
- **Pagar contas e metas no M3 (escopo mínimo do T3.4):** `paguei` lista as contas em aberto dos espaços do usuário (0 → "Não encontrei contas em aberto."; 1 → quita; várias → lista numerada), usa `pay_bill`/`pay_invoice`, valor = o que falta (ou o informado) e conta de origem por dica/padrão/pergunta. `aporte_meta` usa `contribute`; `nova_conta_a_pagar` usa `create_bill`. O contexto de lembrete (`last_reminded_bill_id`), a retirada de meta e os testes `test_paguei_*` do plano mestre ficam no M5 (T5.2).
- **Segurança/robustez:** o webhook é autenticado (header `X-Telegram-Bot-Api-Secret-Token`, comparação em tempo constante, falha fechado sem segredo configurado). Mídia (áudio/foto) recebe "ainda não entendo áudio nem foto" e nada é gravado (M6). Erros de domínio viram mensagens educadas (`domain_error_text`); erro inesperado marca a mensagem `failed` e pede nova tentativa. `max_tries = 1` no ARQ (sem retry automático; ponytail).
- **Rollback expira objetos:** o `Turn` guarda só escalares do usuário e o processador relê a linha `inbound_messages` depois de qualquer rollback (caveat do M2: depois de um `withdraw` recusado a sessão volta ao estado limpo e objetos ORM expiram).
- **LGPD:** `delete_account` passa a apagar `channel_links`, `inbound_messages` (têm texto de lançamentos), `conversation_state` e, por espaço, `category_rules` e `ai_usage`. (Mensagens recebidas não entram no export do M2; ponytail.)
- **Pendência herdada para o M4:** `transactions.origin` é `VARCHAR(16)` e `"whatsapp_evolution"` tem 18 caracteres: o M4 precisa alargar a coluna (migração) antes de gravar lançamentos vindos do WhatsApp.
- **Migrações por tarefa:** cada tarefa com tabela nova gera sua migração (`alembic revision --autogenerate`), revisa o arquivo e valida com `bash scripts/migrate_check.sh`. Depois de gerar, rode **`ruff format` antes de `ruff check --fix`** (o arquivo gerado tem linhas longas). Os testes continuam usando `Base.metadata.create_all`.
- **Commits:** Conventional Commits em inglês, um por tarefa (e um por parte do T3.4); `git add` sempre com caminhos explícitos, nunca `git add -A`; o executor acrescenta o trailer de coautoria exigido pelo ambiente. **Nunca ler, imprimir ou versionar `.env` ou `docs/api_keys/`.**

## Estrutura de arquivos do M3

```
backend/app/channels/{base,telegram,meta_cloud,registry,ingest,poll}.py
backend/app/core/text.py                                  fold(): minúsculas sem acento
backend/app/domain/channels/{models,linking}.py           InboundMessage, ChannelLink, códigos de vínculo
backend/app/domain/categories/models.py                   (+ CategoryRule)
backend/app/domain/transactions/service.py                (+ update_transaction, delete_transaction)
backend/app/ai/{models,usage,llm,openai_parser}.py        AiUsage, record_ai_usage, IntentParser, OpenAIIntentParser
backend/app/assistant/{intents,context,shortcuts,amounts,hints,models,state,turn,notify,replies,processor}.py
backend/app/assistant/flows/{common,payment,launch,edit,query,pay,extras}.py
backend/app/jobs/{queue,inbound}.py                       enqueue_inbound, process_inbound
backend/app/api/{webhooks,channel_links}.py
backend/app/{cli,worker,main}.py                          (alterados)
backend/scripts/run_eval.py                               avaliação contra o modelo real (manual)
backend/migrations/versions/*  inbound_messages · channel_links · ai_usage+category_rules · conversation_state
backend/tests/fixtures/telegram/{text,start_code,voice,photo,group,edited,sticker}.json
backend/tests/factories.py                                (+ TS, make_link, make_inbound)
backend/tests/channels/{test_telegram,test_poll}.py
backend/tests/api/{test_webhooks,test_channel_links_api}.py   (+ casos em test_privacy_api.py)
backend/tests/domain/{test_channel_linking,test_transaction_edit}.py
backend/tests/ai/test_openai_parser.py
backend/tests/jobs/test_worker.py
backend/tests/assistant/{fakes,conftest,evalset}.py  eval_cases.yaml
backend/tests/assistant/{test_inbound_flow,test_shortcuts,test_eval_cases,test_context,test_amounts_hints,test_conversation,test_queries}.py
```

## Rotas, jobs e CLI do marco

| Tarefa | Itens |
|---|---|
| T3.1 | `POST /webhooks/{channel}` (só `telegram`; 404 outro canal, 401 segredo errado, 400 payload inválido) · `python -m app.cli telegram-poll` · `python -m app.cli telegram-set-webhook [--url]` · fila ARQ: `enqueue_inbound` |
| T3.2 | `POST /channels/link-code` · `GET /channels` · `DELETE /channels/{channel}` · job `process_inbound` (vínculo e instruções) |
| T3.3 | (sem rotas) `OpenAIIntentParser`, atalhos, `scripts/run_eval.py` |
| T3.4 | `process_inbound` completo (conversa) · `update_transaction`/`delete_transaction` (domínio) |

## Pré-requisitos (ambiente do executor)

- Branch `feat/m3-telegram` já criada e em checkout (`git branch --show-current`); **sem push** até o fechamento. Todos os comandos começam com `cd ~/abby-cash`.
- Infra dos testes no ar: `docker compose -f infra/docker-compose.dev.yml up -d postgres redis`.
- O `.env` local já tem `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` e `OPENAI_API_KEY` (não imprimir). Os testes automáticos **não dependem** deles (usam segredos fictícios e fakes).

---

## Task 1 (T3.1): Interface de canais, adaptador do Telegram, webhook e polling

**Files:** Create `backend/app/channels/{__init__,base,telegram,meta_cloud,registry,ingest,poll}.py`, `backend/app/domain/channels/{__init__,models}.py`, `backend/app/jobs/{__init__,queue}.py`, `backend/app/api/webhooks.py`, `backend/tests/fixtures/telegram/*.json`, `backend/tests/channels/{__init__,test_telegram,test_poll}.py`, `backend/tests/api/test_webhooks.py`, migração `*_inbound_messages.py`. Modify `backend/app/core/config.py`, `.env.example`, `backend/app/cli.py`, `backend/app/main.py`, `backend/app/domain/models.py`, `backend/tests/core/test_config.py`.

- [ ] **Step 1: Baseline**

```bash
cd ~/abby-cash && git branch --show-current          # feat/m3-telegram
cd ~/abby-cash && docker compose -f infra/docker-compose.dev.yml up -d postgres redis
cd ~/abby-cash/backend && uv run pytest -q           # baseline do M2: 198 passed
```

- [ ] **Step 2: Configuração (teste falhando → implementação)**

Acrescente a `backend/tests/core/test_config.py`:
```python


def test_m3_settings_defaults(tmp_path: Path):
    s = Settings(_env_file=tmp_path / "missing")  # type: ignore[call-arg]
    assert s.TELEGRAM_BOT_USERNAME == ""
    assert s.AI_TIMEOUT_S == 20.0
```
Run: `cd ~/abby-cash/backend && uv run pytest tests/core/test_config.py -q` → **FAIL** (`AttributeError: 'Settings' object has no attribute 'TELEGRAM_BOT_USERNAME'`).

Em `backend/app/core/config.py`, na classe `Settings`, acrescente depois de `OPENAI_API_KEY` e depois de `TELEGRAM_WEBHOOK_SECRET`:
```python
    AI_TIMEOUT_S: float = 20.0
```
```python
    TELEGRAM_BOT_USERNAME: str = ""  # opcional: vazio = descobre com getMe
```
No `.env.example` acrescente as linhas `AI_TIMEOUT_S=20` (depois de `OPENAI_API_KEY=`) e `TELEGRAM_BOT_USERNAME=` (depois de `TELEGRAM_WEBHOOK_SECRET=`).
Run: `uv run pytest tests/core/test_config.py -q` → PASS.

- [ ] **Step 3: Fixtures do Telegram e testes do adaptador (falhando)**

```bash
cd ~/abby-cash/backend && mkdir -p app/channels app/domain/channels app/jobs tests/channels tests/fixtures/telegram
touch app/channels/__init__.py app/domain/channels/__init__.py app/jobs/__init__.py tests/channels/__init__.py
```

Fixtures (formato oficial da Bot API; `date` 1795618800 = 2026-11-25 15:00 UTC = 12:00 em São Paulo):

`backend/tests/fixtures/telegram/text.json`:
```json
{
  "update_id": 900001,
  "message": {
    "message_id": 10,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana", "language_code": "pt-br"},
    "chat": {"id": 111, "first_name": "Ana", "type": "private"},
    "date": 1795618800,
    "text": "gastei 45 no mercado"
  }
}
```
`backend/tests/fixtures/telegram/start_code.json`:
```json
{
  "update_id": 900002,
  "message": {
    "message_id": 11,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana", "language_code": "pt-br"},
    "chat": {"id": 111, "first_name": "Ana", "type": "private"},
    "date": 1795618800,
    "text": "/start 123456",
    "entities": [{"offset": 0, "length": 6, "type": "bot_command"}]
  }
}
```
`backend/tests/fixtures/telegram/voice.json`:
```json
{
  "update_id": 900003,
  "message": {
    "message_id": 12,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana"},
    "chat": {"id": 111, "first_name": "Ana", "type": "private"},
    "date": 1795618800,
    "voice": {"duration": 3, "mime_type": "audio/ogg", "file_id": "AwACAgQAAxkBAAIB", "file_unique_id": "AgADxx", "file_size": 9000}
  }
}
```
`backend/tests/fixtures/telegram/photo.json`:
```json
{
  "update_id": 900004,
  "message": {
    "message_id": 13,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana"},
    "chat": {"id": 111, "first_name": "Ana", "type": "private"},
    "date": 1795618800,
    "photo": [
      {"file_id": "small", "file_unique_id": "a", "width": 90, "height": 90, "file_size": 1200},
      {"file_id": "large", "file_unique_id": "b", "width": 800, "height": 800, "file_size": 90000}
    ],
    "caption": "farmácia 87,40"
  }
}
```
`backend/tests/fixtures/telegram/group.json`:
```json
{
  "update_id": 900005,
  "message": {
    "message_id": 14,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana"},
    "chat": {"id": -100123, "title": "Casa", "type": "group"},
    "date": 1795618800,
    "text": "gastei 10"
  }
}
```
`backend/tests/fixtures/telegram/edited.json`:
```json
{
  "update_id": 900006,
  "edited_message": {
    "message_id": 10,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana"},
    "chat": {"id": 111, "first_name": "Ana", "type": "private"},
    "date": 1795618800,
    "edit_date": 1795618900,
    "text": "gastei 450 no mercado"
  }
}
```
`backend/tests/fixtures/telegram/sticker.json`:
```json
{
  "update_id": 900007,
  "message": {
    "message_id": 15,
    "from": {"id": 111, "is_bot": false, "first_name": "Ana"},
    "chat": {"id": 111, "first_name": "Ana", "type": "private"},
    "date": 1795618800,
    "sticker": {"file_id": "stk", "file_unique_id": "s", "width": 512, "height": 512, "emoji": "👍"}
  }
}
```

`backend/tests/channels/test_telegram.py`:
```python
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from app.channels.base import InboundMessage
from app.channels.telegram import ChannelError, TelegramAdapter

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "telegram"


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def adapter(handler) -> TelegramAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TelegramAdapter("T0KEN", "s3cret", client=client)


def req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def test_parse_text_update():
    msg = TelegramAdapter("T", "s").parse_update(fixture("text"))
    assert msg == InboundMessage(
        channel="telegram",
        external_message_id="111:10",  # message_id só é único dentro do chat
        external_user_id="111",
        text="gastei 45 no mercado",
        media_kind=None,
        media_ref=None,
        received_at=datetime(2026, 11, 25, 15, 0, tzinfo=UTC),
    )


def test_parse_start_voice_photo():
    a = TelegramAdapter("T", "s")
    start = a.parse_update(fixture("start_code"))
    assert start is not None and start.text == "/start 123456"
    voice = a.parse_update(fixture("voice"))
    assert voice is not None
    assert (voice.media_kind, voice.media_ref, voice.text) == ("audio", "AwACAgQAAxkBAAIB", None)
    photo = a.parse_update(fixture("photo"))
    assert photo is not None
    assert (photo.media_kind, photo.media_ref, photo.text) == ("image", "large", "farmácia 87,40")


@pytest.mark.parametrize("name", ["group", "edited", "sticker"])
def test_parse_ignores_groups_edits_and_unsupported(name):
    assert TelegramAdapter("T", "s").parse_update(fixture(name)) is None


def test_parse_ignores_bot_senders():
    update = fixture("text")
    update["message"]["from"]["is_bot"] = True
    assert TelegramAdapter("T", "s").parse_update(update) is None


async def test_parse_webhook_reads_request_body():
    body = json.dumps(fixture("text")).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "headers": []}, receive)
    msgs = await TelegramAdapter("T", "s").parse_webhook(request)
    assert [m.text for m in msgs] == ["gastei 45 no mercado"]


def test_verify_secret_header():
    a = TelegramAdapter("T", "s3cret")
    assert a.verify(req({"X-Telegram-Bot-Api-Secret-Token": "s3cret"}))
    assert not a.verify(req({"X-Telegram-Bot-Api-Secret-Token": "outro"}))
    assert not a.verify(req({}))
    assert not a.verify(req({"X-Telegram-Bot-Api-Secret-Token": "ação"}))  # não ASCII: sem 500


def test_verify_fails_closed_without_configured_secret():
    assert not TelegramAdapter("T", "").verify(req({"X-Telegram-Bot-Api-Secret-Token": ""}))


async def test_send_text_posts_to_bot_api():
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    await adapter(handler).send_text("111", "oi")
    assert str(seen[0].url) == "https://api.telegram.org/botT0KEN/sendMessage"
    assert json.loads(seen[0].content) == {"chat_id": 111, "text": "oi"}


async def test_send_error_does_not_leak_token():
    a = adapter(lambda r: httpx.Response(500, json={"ok": False}))
    with pytest.raises(ChannelError) as e:
        await a.send_text("111", "oi")
    assert "T0KEN" not in str(e.value) and "T0KEN" not in repr(e.value)


async def test_download_media_resolves_file_path_and_mime():
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/getFile"):
            assert json.loads(r.content) == {"file_id": "AwAC"}
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/f1.oga"}})
        assert r.url.path == "/file/botT0KEN/voice/f1.oga"
        return httpx.Response(200, content=b"AUDIO")

    assert await adapter(handler).download_media("AwAC") == (b"AUDIO", "audio/ogg")


async def test_bot_username_uses_env_then_get_me(monkeypatch):
    from app.core.config import get_settings

    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r.url.path)
        return httpx.Response(200, json={"ok": True, "result": {"username": "abby_bot"}})

    a = adapter(handler)
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "")
    assert await a.bot_username() == "abby_bot"
    assert await a.bot_username() == "abby_bot"
    assert calls == ["/botT0KEN/getMe"]  # cache: uma chamada só
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "do_env")
    assert await adapter(handler).bot_username() == "do_env"


async def test_set_and_delete_webhook_payloads():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append((r.url.path.rsplit("/", 1)[1], json.loads(r.content)))
        return httpx.Response(200, json={"ok": True, "result": True})

    a = adapter(handler)
    await a.set_webhook("https://x.com/webhooks/telegram")
    await a.delete_webhook()
    assert seen == [
        (
            "setWebhook",
            {
                "url": "https://x.com/webhooks/telegram",
                "secret_token": "s3cret",
                "allowed_updates": ["message"],
            },
        ),
        ("deleteWebhook", {}),
    ]
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/channels -q` → **FAIL** na coleta: `ModuleNotFoundError: No module named 'app.channels.base'`.

- [ ] **Step 5: Implementar a interface, o adaptador e o registro**

`backend/app/channels/base.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from starlette.requests import Request


@dataclass
class InboundMessage:
    channel: str  # "telegram" | "whatsapp_evolution" | "whatsapp_cloud"
    external_message_id: str  # único por canal: base da idempotência
    external_user_id: str  # chat_id / telefone E.164
    text: str | None
    media_kind: Literal["audio", "image"] | None
    media_ref: str | None
    received_at: datetime


class ChannelAdapter(Protocol):
    name: str

    async def parse_webhook(self, request: Request) -> list[InboundMessage]: ...

    def verify(self, request: Request) -> bool: ...

    async def send_text(self, external_user_id: str, text: str) -> None: ...

    async def download_media(self, media_ref: str) -> tuple[bytes, str]: ...  # (bytes, mime)
```
`backend/app/channels/telegram.py`:
```python
import hmac
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from starlette.requests import Request

from app.channels.base import InboundMessage
from app.core.config import get_settings

API = "https://api.telegram.org"
_MIME = {
    ".oga": "audio/ogg", ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
}  # fmt: skip


class ChannelError(Exception):
    """Falha de envio/recebimento. A mensagem nunca carrega a URL (que contém o token)."""


class TelegramAdapter:
    name = "telegram"

    def __init__(self, token: str, secret: str, client: httpx.AsyncClient | None = None) -> None:
        self._token, self._secret = token, secret
        # read > 30 s do long polling do getUpdates
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=5.0))
        self._username: str | None = None

    def verify(self, request: Request) -> bool:
        got = request.headers.get("x-telegram-bot-api-secret-token", "")
        # sem segredo configurado nada passa; bytes: compare_digest recusa str não ASCII
        return bool(self._secret) and hmac.compare_digest(got.encode(), self._secret.encode())

    def parse_update(self, update: dict[str, Any]) -> InboundMessage | None:
        """Update da Bot API -> mensagem. Só conversa 1:1, de gente, com texto ou mídia."""
        msg = update.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            return None
        if (msg.get("from") or {}).get("is_bot"):
            return None
        chat_id = msg["chat"]["id"]
        media_kind: Any = None
        media_ref: str | None = None
        if "voice" in msg or "audio" in msg:
            media_kind, media_ref = "audio", (msg.get("voice") or msg["audio"])["file_id"]
        elif "photo" in msg:
            media_kind, media_ref = "image", msg["photo"][-1]["file_id"]  # a maior resolução
        text = msg.get("text") or msg.get("caption")
        if text is None and media_kind is None:
            return None
        return InboundMessage(
            channel=self.name,
            external_message_id=f"{chat_id}:{msg['message_id']}",
            external_user_id=str(chat_id),
            text=text,
            media_kind=media_kind,
            media_ref=media_ref,
            received_at=datetime.fromtimestamp(msg["date"], UTC),
        )

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        parsed = self.parse_update(await request.json())
        return [parsed] if parsed else []

    async def _call(self, method: str, **payload: Any) -> Any:
        try:
            r = await self._client.post(f"{API}/bot{self._token}/{method}", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ChannelError(f"telegram {method} failed ({type(e).__name__})") from None
        return r.json()["result"]

    async def send_text(self, external_user_id: str, text: str) -> None:
        await self._call("sendMessage", chat_id=int(external_user_id), text=text[:4096])

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        info = await self._call("getFile", file_id=media_ref)
        path = info["file_path"]
        try:
            r = await self._client.get(f"{API}/file/bot{self._token}/{path}")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ChannelError(f"telegram download failed ({type(e).__name__})") from None
        mime = _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        return r.content, mime

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return list(await self._call("getUpdates", **payload))

    async def set_webhook(self, url: str) -> None:
        await self._call(
            "setWebhook", url=url, secret_token=self._secret, allowed_updates=["message"]
        )

    async def delete_webhook(self) -> None:
        await self._call("deleteWebhook")

    async def bot_username(self) -> str:
        """@ do bot: TELEGRAM_BOT_USERNAME se houver; senão getMe (uma vez por processo)."""
        configured = get_settings().TELEGRAM_BOT_USERNAME
        if configured:
            return configured
        if self._username is None:
            self._username = str((await self._call("getMe"))["username"])
        return self._username
```
`backend/app/channels/meta_cloud.py`:
```python
from starlette.requests import Request

from app.channels.base import InboundMessage


class MetaCloudAdapter:
    """Esqueleto da API oficial do WhatsApp (fase de venda). Nada é registrado em `registry`."""

    name = "whatsapp_cloud"

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

    def verify(self, request: Request) -> bool:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

    async def send_text(self, external_user_id: str, text: str) -> None:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")
```
`backend/app/channels/registry.py`:
```python
from typing import cast

from app.channels.base import ChannelAdapter
from app.channels.telegram import TelegramAdapter
from app.core.config import get_settings

_adapters: dict[str, ChannelAdapter] = {}


def get_adapter(channel: str) -> ChannelAdapter:
    """Adaptador do canal; `KeyError` se o canal não existe/ainda não foi habilitado."""
    if channel not in _adapters:
        if channel != "telegram":  # M4 acrescenta whatsapp_evolution
            raise KeyError(channel)
        s = get_settings()
        _adapters[channel] = TelegramAdapter(s.TELEGRAM_BOT_TOKEN, s.TELEGRAM_WEBHOOK_SECRET)
    return _adapters[channel]


def telegram_adapter() -> TelegramAdapter:
    return cast(TelegramAdapter, get_adapter("telegram"))
```

- [ ] **Step 6: Rodar o adaptador**

Run: `cd ~/abby-cash/backend && uv run pytest tests/channels/test_telegram.py -q` → todos PASS.

- [ ] **Step 7: Testes de webhook/ingestão e de polling (falhando)**

`backend/tests/api/test_webhooks.py`:
```python
import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.api import webhooks
from app.channels import registry
from app.channels.telegram import TelegramAdapter
from app.core.redis import redis
from app.domain.channels.models import InboundMessage
from app.jobs.queue import enqueue_inbound

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "telegram"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}


def update(name: str = "text") -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def tg(monkeypatch):
    monkeypatch.setitem(registry._adapters, "telegram", TelegramAdapter("T0KEN", "s3cret"))


@pytest.fixture
def enqueued(monkeypatch) -> list[UUID]:
    got: list[UUID] = []

    async def fake(inbound_id: UUID) -> None:
        got.append(inbound_id)

    monkeypatch.setattr(webhooks, "enqueue_inbound", fake)
    return got


async def post(client, name: str = "text"):
    return await client.post("/webhooks/telegram", json=update(name), headers=HEADERS)


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(InboundMessage))


async def test_telegram_webhook_rejects_bad_secret(client, session, enqueued):
    r = await client.post("/webhooks/telegram", json=update())
    assert r.status_code == 401
    r = await client.post(
        "/webhooks/telegram", json=update(), headers={"X-Telegram-Bot-Api-Secret-Token": "errado"}
    )
    assert r.status_code == 401
    assert await count(session) == 0 and enqueued == []


async def test_webhook_enqueues_and_returns_200(client, session, enqueued):
    r = await post(client)
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = await session.scalar(select(InboundMessage))
    assert row is not None
    assert (row.channel, row.external_message_id, row.external_user_id) == (
        "telegram", "111:10", "111",
    )  # fmt: skip
    assert (row.text, row.status, row.user_id) == ("gastei 45 no mercado", "received", None)
    assert enqueued == [row.id]


async def test_webhook_ignores_unsupported_updates_with_200(client, session, enqueued):
    for name in ("group", "edited", "sticker"):
        assert (await post(client, name)).status_code == 200
    assert await count(session) == 0 and enqueued == []


async def test_webhook_unknown_channel_and_bad_payload(client, enqueued):
    r = await client.post("/webhooks/nope", json=update(), headers=HEADERS)
    assert r.status_code == 404
    r = await client.post("/webhooks/telegram", content=b"not json", headers=HEADERS)
    assert r.status_code == 400


async def test_duplicate_webhook_ingested_once(client, session, enqueued):
    for _ in range(3):  # reenvios do Telegram
        assert (
            await client.post("/webhooks/telegram", json=update(), headers=HEADERS)
        ).status_code == 200
    await asyncio.gather(
        *[
            client.post("/webhooks/telegram", json=update("voice"), headers=HEADERS)
            for _ in range(5)
        ]
    )  # entregas simultâneas
    assert await count(session) == 2
    assert len(enqueued) == 2


async def test_enqueue_failure_rolls_back_row_so_retry_works(client, session, monkeypatch):
    async def boom(_: UUID) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(webhooks, "enqueue_inbound", boom)
    with pytest.raises(RuntimeError):
        await post(client)
    assert await count(session) == 0  # sem linha órfã: o reenvio do Telegram entra de novo
    got: list[UUID] = []

    async def ok(inbound_id: UUID) -> None:
        got.append(inbound_id)

    monkeypatch.setattr(webhooks, "enqueue_inbound", ok)
    await post(client)
    assert await count(session) == 1 and len(got) == 1


async def test_enqueue_inbound_uses_arq_queue_with_dedupe():
    iid = uuid4()
    await enqueue_inbound(iid)
    await enqueue_inbound(iid)  # mesmo job_id: o ARQ não duplica
    assert await redis.zcard("arq:queue") == 1
```
`backend/tests/channels/test_poll.py`:
```python
import json
from uuid import UUID

import httpx
from sqlalchemy import select

from app.channels.poll import poll_once
from app.channels.telegram import TelegramAdapter
from app.domain.channels.models import InboundMessage
from tests.channels.test_telegram import fixture


async def test_poll_once_ingests_updates_and_advances_offset(session):
    sent_bodies = []

    def handler(r: httpx.Request) -> httpx.Response:
        sent_bodies.append(json.loads(r.content))
        updates = [fixture("text"), fixture("group"), fixture("voice")]
        return httpx.Response(200, json={"ok": True, "result": updates})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter("T0KEN", "s3cret", client=client)
    enqueued: list[UUID] = []

    async def enqueue(inbound_id: UUID) -> None:
        enqueued.append(inbound_id)

    offset = await poll_once(adapter, 5, enqueue)
    assert sent_bodies[0]["offset"] == 5 and sent_bodies[0]["timeout"] == 30
    assert offset == 900004  # último update_id (900003) + 1, mesmo o ignorado (grupo)
    rows = list(await session.scalars(select(InboundMessage).order_by(InboundMessage.created_at)))
    assert [r.external_message_id for r in rows] == ["111:10", "111:12"]
    assert len(enqueued) == 2
    await poll_once(adapter, offset, enqueue)  # mesma entrega de novo: nada duplica
    assert len(enqueued) == 2
```

Run: `cd ~/abby-cash/backend && uv run pytest tests/api/test_webhooks.py tests/channels/test_poll.py -q` → **FAIL** (`ModuleNotFoundError: No module named 'app.domain.channels.models'`).

- [ ] **Step 8: Implementar model, ingestão, fila, rota, polling e CLI**

`backend/app/domain/channels/models.py`:
```python
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        # idempotência: o mesmo webhook reenviado nunca vira duas linhas
        UniqueConstraint("channel", "external_message_id", name="uq_inbound_channel_msgid"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    channel: Mapped[str] = mapped_column(String(32))
    external_message_id: Mapped[str] = mapped_column(String(128))
    external_user_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    media_kind: Mapped[str | None] = mapped_column(String(8))
    media_ref: Mapped[str | None] = mapped_column(String(512))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # received -> processing -> processed | failed
    status: Mapped[str] = mapped_column(String(16), default="received")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```
`backend/app/channels/ingest.py`:
```python
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import InboundMessage as Inbound
from app.domain.channels.models import InboundMessage


async def ingest(
    session: AsyncSession, msgs: Sequence[Inbound], enqueue: Callable[[UUID], Awaitable[None]]
) -> int:
    """Grava cada mensagem uma única vez (UNIQUE canal+id externo) e enfileira só as novas.

    Webhook e polling usam esta mesma porta de entrada. Devolve quantas eram novas."""
    new = 0
    for m in msgs:
        inbound_id = await session.scalar(
            insert(InboundMessage)
            .values(
                channel=m.channel, external_message_id=m.external_message_id,
                external_user_id=m.external_user_id, text=m.text, media_kind=m.media_kind,
                media_ref=m.media_ref, received_at=m.received_at,
            )
            .on_conflict_do_nothing(constraint="uq_inbound_channel_msgid")
            .returning(InboundMessage.id)
        )  # fmt: skip
        await session.commit()  # o worker precisa enxergar a linha
        if inbound_id is None:
            continue  # duplicata (reenvio ou entrega simultânea): nada a fazer
        try:
            await enqueue(inbound_id)
        except Exception:
            # sem fila a mensagem se perderia: remove a linha para o reenvio entrar de novo
            await session.execute(delete(InboundMessage).where(InboundMessage.id == inbound_id))
            await session.commit()
            raise
        new += 1
    return new
```
`backend/app/jobs/queue.py`:
```python
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_pool: ArqRedis | None = None


async def enqueue_inbound(inbound_id: UUID) -> None:
    """Enfileira `process_inbound`. `_job_id` = id da mensagem: o ARQ ignora o duplicado."""
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().REDIS_URL))
    await _pool.enqueue_job("process_inbound", str(inbound_id), _job_id=str(inbound_id))
```
`backend/app/api/webhooks.py`:
```python
from fastapi import APIRouter, HTTPException, Request

from app.api.deps import Session
from app.channels.ingest import ingest
from app.channels.registry import get_adapter
from app.jobs.queue import enqueue_inbound

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/{channel}")
async def webhook(channel: str, request: Request, session: Session) -> dict[str, bool]:
    try:
        adapter = get_adapter(channel)
    except KeyError:
        raise HTTPException(404, "unknown_channel") from None
    if not adapter.verify(request):
        raise HTTPException(401, "invalid_secret")
    try:
        msgs = await adapter.parse_webhook(request)
    except ValueError:  # JSON inválido ou payload fora do formato
        raise HTTPException(400, "bad_payload") from None
    await ingest(session, msgs, enqueue_inbound)  # só grava e enfileira; o worker processa
    return {"ok": True}
```
`backend/app/channels/poll.py`:
```python
import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.channels.ingest import ingest
from app.channels.telegram import ChannelError, TelegramAdapter
from app.core.db import SessionLocal
from app.jobs.queue import enqueue_inbound

log = logging.getLogger(__name__)


async def poll_once(
    adapter: TelegramAdapter, offset: int | None, enqueue: Callable[[UUID], Awaitable[None]]
) -> int | None:
    """Um getUpdates: manda cada mensagem pela MESMA porta do webhook (`ingest`)."""
    for update in await adapter.get_updates(offset):
        msg = adapter.parse_update(update)
        if msg is not None:
            async with SessionLocal() as session:
                await ingest(session, [msg], enqueue)
        offset = update["update_id"] + 1  # só avança depois de gravar/enfileirar
    return offset


async def poll_forever(adapter: TelegramAdapter) -> None:
    """Long polling para dev sem HTTPS público. O worker (`arq`) precisa estar rodando."""
    offset: int | None = None
    while True:
        try:
            offset = await poll_once(adapter, offset, enqueue_inbound)
        except ChannelError as e:
            log.warning("telegram poll failed: %s", e)
            await asyncio.sleep(3)
```

`backend/app/cli.py` (substitua o arquivo; só `_poll`, `_set_webhook` e o `main` mudam):
`backend/app/cli.py`:
```python
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
```

Em `backend/app/main.py`: acrescente `webhooks,` à lista do `from app.api import (...)` (depois de `transactions,`) e `app.include_router(webhooks.router)` depois de `app.include_router(privacy.router)`.
Em `backend/app/domain/models.py`: acrescente `import app.domain.channels.models  # noqa: F401` depois da linha de `categories`.

Run: `cd ~/abby-cash/backend && uv run ruff format . && uv run ruff check --fix . && uv run mypy app && uv run pytest tests/channels tests/api/test_webhooks.py tests/core -q` → PASS (o teste `test_enqueue_inbound_uses_arq_queue_with_dedupe` usa o Redis real, DB 15).

- [ ] **Step 9: Migração**

```bash
cd ~/abby-cash/backend && uv run alembic upgrade head && uv run alembic revision --autogenerate -m "inbound messages"
uv run ruff format . && uv run ruff check --fix . && bash scripts/migrate_check.sh
```
Confira o arquivo gerado: só `create_table('inbound_messages', ...)` com `UniqueConstraint('channel','external_message_id', name='uq_inbound_channel_msgid')` e o índice de `user_id`; **nenhum** `drop`. `migrate_check.sh` termina com `No new upgrade operations detected.`

`backend/migrations/versions/bdab06c337c9_inbound_messages.py`:
```python
"""inbound messages

Revision ID: bdab06c337c9
Revises: c3e8f1a2b4d5
Create Date: 2026-11-23 13:47:33.952212

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "bdab06c337c9"
down_revision: str | Sequence[str] | None = "c3e8f1a2b4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_message_id", sa.String(length=128), nullable=False),
        sa.Column("external_user_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_kind", sa.String(length=8), nullable=True),
        sa.Column("media_ref", sa.String(length=512), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "external_message_id", name="uq_inbound_channel_msgid"),
    )
    op.create_index(
        op.f("ix_inbound_messages_user_id"), "inbound_messages", ["user_id"], unique=False
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_inbound_messages_user_id"), table_name="inbound_messages")
    op.drop_table("inbound_messages")
    # ### end Alembic commands ###
```
(o identificador da revisão será outro no seu ambiente; o conteúdo deve ser o mesmo.)

- [ ] **Step 10: Qualidade e commit**

```bash
cd ~/abby-cash/backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd ~/abby-cash && git add .env.example backend/app/core/config.py backend/app/cli.py backend/app/main.py \
  backend/app/domain/models.py backend/app/domain/channels backend/app/channels backend/app/jobs \
  backend/app/api/webhooks.py backend/migrations/versions/*_inbound_messages.py \
  backend/tests/core/test_config.py backend/tests/channels backend/tests/fixtures backend/tests/api/test_webhooks.py
git commit -m "feat(channels): add Telegram adapter, idempotent webhook ingestion and polling runner"
```

---

## Task 2 (T3.2): Vínculo de canal e processamento de entrada

**Files:** Create `backend/app/domain/channels/linking.py`, `backend/app/api/channel_links.py`, `backend/app/assistant/{__init__,processor}.py`, `backend/app/jobs/inbound.py`, `backend/tests/domain/test_channel_linking.py`, `backend/tests/api/test_channel_links_api.py`, `backend/tests/assistant/{__init__,fakes,conftest,test_inbound_flow}.py`, migração `*_channel_links.py`. Modify `backend/app/domain/channels/models.py`, `backend/app/worker.py`, `backend/app/main.py`, `backend/app/domain/privacy.py`, `backend/tests/factories.py`, `backend/tests/api/test_privacy_api.py`.

> Nota de escopo: o plano mestre põe `test_unlinked_sender_gets_instructions_only` e `test_duplicate_webhook_creates_single_transaction` aqui. O primeiro fica aqui (o processador nasce nesta tarefa, só com o ramo "não vinculado"). O segundo grava um lançamento e precisa do pipeline completo, então vive na Task 4 (T3.4); aqui a ingestão única já é coberta por `test_duplicate_webhook_ingested_once` (Task 1).

- [ ] **Step 1: Fakes e fábricas de teste**

Em `backend/tests/factories.py`: acrescente aos imports `from datetime import UTC, datetime` (no topo) e `from app.domain.channels.models import ChannelLink, InboundMessage` (junto dos outros `app.domain...`), e ao final do arquivo:
```python


TS = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)  # quarta-feira, 12:00 em São Paulo


async def make_link(session, user: User, ext: str = "111", channel: str = "telegram") -> None:
    session.add(ChannelLink(user_id=user.id, channel=channel, external_user_id=ext))
    await session.commit()


async def make_inbound(
    session, text: str | None, *, ext: str = "111", msg_id: int = 1, channel: str = "telegram",
    ts: datetime = TS, media_kind: str | None = None,
) -> UUID:  # fmt: skip
    row = InboundMessage(
        channel=channel, external_message_id=f"{ext}:{msg_id}", external_user_id=ext, text=text,
        media_kind=media_kind, media_ref="file-1" if media_kind else None, received_at=ts,
    )  # fmt: skip
    session.add(row)
    await session.commit()
    return row.id
```

```bash
cd ~/abby-cash/backend && mkdir -p tests/assistant && touch tests/assistant/__init__.py
```
`backend/tests/assistant/fakes.py`:
```python
from starlette.requests import Request

from app.channels.base import InboundMessage


class FakeAdapter:
    """Canal falso: guarda o que seria enviado ao usuário."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (external_user_id, texto)

    def verify(self, request: Request) -> bool:
        return True

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        return []

    async def send_text(self, external_user_id: str, text: str) -> None:
        self.sent.append((external_user_id, text))

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        return b"", "application/octet-stream"
```
`backend/tests/assistant/conftest.py`:
```python
import pytest

from app.channels import registry
from tests.assistant.fakes import FakeAdapter


@pytest.fixture
def adapter(monkeypatch) -> FakeAdapter:
    fake = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "telegram", fake)
    return fake
```

- [ ] **Step 2: Testes de vínculo, da API e do processador (falhando)**

`backend/tests/domain/test_channel_linking.py`:
```python
import asyncio

import pytest
from sqlalchemy import select

from app.core.redis import redis
from app.domain.channels.linking import (
    create_link_code,
    find_user_by_link,
    link_with_code,
    unlink,
)
from app.domain.channels.models import ChannelLink
from app.domain.errors import DomainError
from tests.factories import make_user


async def _links(session) -> list[ChannelLink]:
    return list(await session.scalars(select(ChannelLink)))


async def test_link_with_code(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    assert len(code) == 6 and code.isdigit()
    user = await link_with_code(session, channel="telegram", external_user_id="111", code=code)
    assert user is not None and user.id == ana.id
    assert [
        (link.user_id, link.channel, link.external_user_id) for link in await _links(session)
    ] == [(ana.id, "telegram", "111")]
    found = await find_user_by_link(session, "telegram", "111")
    assert found is not None and found.id == ana.id
    assert found.preferred_channel == "telegram"
    assert await find_user_by_link(session, "telegram", "999") is None
    # uso único
    again = await link_with_code(session, channel="telegram", external_user_id="222", code=code)
    assert again is None and len(await _links(session)) == 1


async def test_expired_code_rejected(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    await redis.pexpire(f"linkcode:{code}", 1)
    await asyncio.sleep(0.05)
    assert (
        await link_with_code(session, channel="telegram", external_user_id="111", code=code) is None
    )
    assert await _links(session) == []


async def test_code_is_bound_to_channel(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    got = await link_with_code(
        session, channel="whatsapp_evolution", external_user_id="1", code=code
    )
    assert got is None and await _links(session) == []


async def test_attempts_are_limited_per_sender(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(5):
        assert (
            await link_with_code(session, channel="telegram", external_user_id="9", code=wrong)
            is None
        )
    with pytest.raises(DomainError, match="too_many_attempts"):  # nem o código certo passa
        await link_with_code(session, channel="telegram", external_user_id="9", code=code)
    assert await _links(session) == []
    # outro remetente não é afetado
    assert await link_with_code(session, channel="telegram", external_user_id="8", code=code)


async def test_external_id_cannot_be_linked_to_two_users(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    c1 = await create_link_code(ana.id, "telegram")
    await link_with_code(session, channel="telegram", external_user_id="111", code=c1)
    c2 = await create_link_code(bia.id, "telegram")
    with pytest.raises(DomainError, match="already_linked"):
        await link_with_code(session, channel="telegram", external_user_id="111", code=c2)
    assert len(await _links(session)) == 1


async def test_relink_replaces_external_id_and_unlink_removes(session):
    ana = await make_user(session, "ana@x.com")
    await link_with_code(
        session, channel="telegram", external_user_id="111",
        code=await create_link_code(ana.id, "telegram"),
    )  # fmt: skip
    await link_with_code(
        session, channel="telegram", external_user_id="222",
        code=await create_link_code(ana.id, "telegram"),
    )  # fmt: skip
    assert [link.external_user_id for link in await _links(session)] == ["222"]
    await unlink(session, ana.id, "telegram")
    assert await _links(session) == []
```
`backend/tests/api/test_channel_links_api.py`:
```python
import pytest
from sqlalchemy import select

from app.channels.telegram import ChannelError, TelegramAdapter
from app.core.config import get_settings
from app.domain.channels.linking import link_with_code
from app.domain.channels.models import ChannelLink
from tests.factories import auth, make_user


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "")

    async def name(self) -> str:
        return "abby_bot"

    monkeypatch.setattr(TelegramAdapter, "bot_username", name)


async def test_link_code_returns_code_and_deep_link(client, session, bot):
    ana = await make_user(session, "ana@x.com")
    r = await client.post("/channels/link-code", json={"channel": "telegram"}, headers=auth(ana))
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) == 6 and body["expires_in_s"] == 600
    assert body["deep_link"] == f"https://t.me/abby_bot?start={body['code']}"
    # o código criado vincula de verdade
    assert await link_with_code(
        session, channel="telegram", external_user_id="111", code=body["code"]
    )


async def test_link_code_without_bot_name_still_returns_code(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "")

    async def boom(self) -> str:
        raise ChannelError("telegram getMe failed")

    monkeypatch.setattr(TelegramAdapter, "bot_username", boom)
    ana = await make_user(session, "ana@x.com")
    r = await client.post("/channels/link-code", json={"channel": "telegram"}, headers=auth(ana))
    assert r.status_code == 200 and r.json()["deep_link"] is None


async def test_link_code_requires_auth_and_valid_channel(client, session, bot):
    assert (
        await client.post("/channels/link-code", json={"channel": "telegram"})
    ).status_code == 401
    ana = await make_user(session, "ana@x.com")
    r = await client.post("/channels/link-code", json={"channel": "icq"}, headers=auth(ana))
    assert r.status_code == 422


async def test_link_code_is_rate_limited(client, session, bot):
    ana = await make_user(session, "ana@x.com")
    codes = [
        await client.post("/channels/link-code", json={"channel": "telegram"}, headers=auth(ana))
        for _ in range(6)
    ]
    assert [c.status_code for c in codes] == [200] * 5 + [429]


async def test_list_and_delete_links_are_scoped_to_user(client, session, bot):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    for user, ext in ((ana, "111"), (bia, "222")):
        r = await client.post(
            "/channels/link-code", json={"channel": "telegram"}, headers=auth(user)
        )
        await link_with_code(
            session, channel="telegram", external_user_id=ext, code=r.json()["code"]
        )
    listed = (await client.get("/channels", headers=auth(ana))).json()
    assert [k["channel"] for k in listed] == ["telegram"]
    assert (await client.delete("/channels/telegram", headers=auth(ana))).status_code == 204
    left = list(await session.scalars(select(ChannelLink)))
    assert [k.user_id for k in left] == [bia.id]  # o vínculo da outra pessoa continua
```
`backend/tests/assistant/test_inbound_flow.py`:
```python
import asyncio
from uuid import UUID

from sqlalchemy import func, select

from app.assistant.processor import UNLINKED
from app.domain.channels.linking import create_link_code
from app.domain.channels.models import ChannelLink, InboundMessage
from app.domain.transactions.models import Transaction
from app.jobs.inbound import process_inbound
from tests.factories import make_inbound, make_user


async def run(session, text, **kw) -> UUID:
    iid = await make_inbound(session, text, **kw)
    await process_inbound({}, str(iid))
    return iid


async def test_unlinked_sender_gets_instructions_only(session, adapter):
    await make_user(session, "ana@x.com")  # existe usuário, mas este chat não está vinculado
    iid = await run(session, "gastei 45 no mercado")
    assert adapter.sent == [("111", UNLINKED)]
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
    assert await session.scalar(select(func.count()).select_from(ChannelLink)) == 0
    row = await session.get(InboundMessage, iid)
    assert row.status == "processed" and row.user_id is None


async def test_start_with_code_links_and_welcomes(session, adapter):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    await run(session, f"/start {code}")
    assert "vinculado" in adapter.sent[0][1]
    link = await session.scalar(select(ChannelLink))
    assert link is not None and link.user_id == ana.id and link.external_user_id == "111"


async def test_bare_code_also_links_and_wrong_code_is_refused(session, adapter):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    wrong = "000000" if code != "000000" else "000001"
    await run(session, wrong, msg_id=1)
    assert "inválido" in adapter.sent[-1][1]
    assert await session.scalar(select(func.count()).select_from(ChannelLink)) == 0
    await run(session, code, msg_id=2)
    assert "vinculado" in adapter.sent[-1][1]


async def test_same_inbound_is_processed_only_once(session, adapter):
    iid = await make_inbound(session, "oi")
    await asyncio.gather(*[process_inbound({}, str(iid)) for _ in range(4)])
    assert len(adapter.sent) == 1
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_channel_linking.py tests/api/test_channel_links_api.py tests/assistant -q` → **FAIL** (`ModuleNotFoundError: No module named 'app.domain.channels.linking'`).

- [ ] **Step 4: Implementar o vínculo**

Acrescente ao final de `backend/app/domain/channels/models.py` (os imports já existem):
```python


class ChannelLink(Base):
    __tablename__ = "channel_links"
    __table_args__ = (
        UniqueConstraint("channel", "external_user_id", name="uq_channel_links_external"),
        UniqueConstraint("user_id", "channel", name="uq_channel_links_user_channel"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(32))
    external_user_id: Mapped[str] = mapped_column(String(64))  # chat_id / telefone
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```
`backend/app/domain/channels/linking.py`:
```python
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.domain.audit import audit
from app.domain.channels.models import ChannelLink
from app.domain.errors import DomainError
from app.domain.users.models import User

CODE_TTL_S = 600  # 10 minutos
MAX_ATTEMPTS = 5  # tentativas por remetente dentro da janela


def _key(code: str) -> str:
    return f"linkcode:{code}"


async def create_link_code(user_id: UUID, channel: str) -> str:
    """Código de 6 dígitos, válido por 10 min, de uso único (vive no Redis)."""
    for _ in range(10):  # colisão entre códigos ativos é improvável; tenta de novo
        code = f"{secrets.randbelow(10**6):06d}"
        if await redis.set(_key(code), f"{user_id}:{channel}", ex=CODE_TTL_S, nx=True):
            return code
    raise DomainError("code_generation_failed")


async def link_with_code(
    session: AsyncSession, *, channel: str, external_user_id: str, code: str
) -> User | None:
    """Vincula o remetente ao dono do código. None = código inválido/expirado/de outro canal."""
    attempts = f"link_attempts:{channel}:{external_user_id}"
    await redis.set(attempts, 0, ex=CODE_TTL_S, nx=True)  # TTL garantido antes do INCR
    if await redis.incr(attempts) > MAX_ATTEMPTS:
        raise DomainError("too_many_attempts")
    value = await redis.get(_key(code))
    if value is None:
        return None
    uid, _, code_channel = str(value).partition(":")
    if code_channel != channel:
        return None
    if await redis.delete(_key(code)) == 0:  # outro processo consumiu primeiro
        return None
    user = await session.get(User, UUID(uid))
    if user is None:
        return None
    taken = await session.scalar(
        select(ChannelLink).where(
            ChannelLink.channel == channel, ChannelLink.external_user_id == external_user_id
        )
    )
    if taken is not None and taken.user_id != user.id:
        raise DomainError("already_linked")
    mine = await session.scalar(
        select(ChannelLink).where(ChannelLink.user_id == user.id, ChannelLink.channel == channel)
    )
    if mine is None:
        session.add(
            ChannelLink(user_id=user.id, channel=channel, external_user_id=external_user_id)
        )
    else:  # trocou de conta no canal
        mine.external_user_id = external_user_id
        mine.verified_at = datetime.now(UTC)
    if user.preferred_channel is None:
        user.preferred_channel = channel
    audit(session, user.id, "channel.link", "user", user.id, {"channel": channel})
    await session.commit()
    await redis.delete(attempts)
    return user


async def find_user_by_link(
    session: AsyncSession, channel: str, external_user_id: str
) -> User | None:
    return await session.scalar(
        select(User)
        .join(ChannelLink, ChannelLink.user_id == User.id)
        .where(ChannelLink.channel == channel, ChannelLink.external_user_id == external_user_id)
    )


async def unlink(session: AsyncSession, user_id: UUID, channel: str) -> None:
    await session.execute(
        delete(ChannelLink).where(ChannelLink.user_id == user_id, ChannelLink.channel == channel)
    )
    audit(session, user_id, "channel.unlink", "user", user_id, {"channel": channel})
    await session.commit()
```

- [ ] **Step 5: Implementar a API de vínculo**

`backend/app/api/channel_links.py`:
```python
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import MAX_FAILS, _hit
from app.api.deps import CurrentUser, Session
from app.channels.registry import telegram_adapter
from app.channels.telegram import ChannelError
from app.core.config import get_settings
from app.domain.channels.linking import CODE_TTL_S, create_link_code, unlink
from app.domain.channels.models import ChannelLink

router = APIRouter(prefix="/channels", tags=["channels"])


class LinkCodeIn(BaseModel):
    channel: Literal["telegram"]  # M4 acrescenta whatsapp_evolution


async def _deep_link(code: str) -> str | None:
    """t.me/<bot>?start=<código>; o @ do bot vem do env ou de getMe, nunca fixo no código."""
    try:
        name = get_settings().TELEGRAM_BOT_USERNAME or await telegram_adapter().bot_username()
    except ChannelError:
        return None  # sem token/rede: o painel mostra só o código
    return f"https://t.me/{name}?start={code}"


@router.post("/link-code")
async def link_code(body: LinkCodeIn, user: CurrentUser) -> dict[str, object]:
    await _hit(f"link_code:{user.id}", MAX_FAILS)  # 5 códigos por janela
    code = await create_link_code(user.id, body.channel)
    return {
        "code": code,
        "expires_in_s": CODE_TTL_S,
        "deep_link": await _deep_link(code) if body.channel == "telegram" else None,
    }


@router.get("")
async def list_links(user: CurrentUser, session: Session) -> list[dict[str, object]]:
    links = await session.scalars(select(ChannelLink).where(ChannelLink.user_id == user.id))
    return [{"channel": k.channel, "verified_at": k.verified_at} for k in links]


@router.delete("/{channel}", status_code=204)
async def delete_link(channel: str, user: CurrentUser, session: Session) -> None:
    await unlink(session, user.id, channel)
```

Em `backend/app/main.py`: acrescente `channel_links,` ao `from app.api import (...)` (depois de `cards,`) e `app.include_router(channel_links.router)` antes do `webhooks.router`.

- [ ] **Step 6: Implementar o processador mínimo, o job e o worker**

O processador desta tarefa só sabe reivindicar a mensagem, tratar remetente não vinculado e responder; o ramo "vinculado" é substituído na Task 4 (Step 5).
`backend/app/assistant/processor.py`:
```python
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import get_adapter
from app.core.db import SessionLocal
from app.domain.channels.linking import find_user_by_link, link_with_code
from app.domain.channels.models import InboundMessage
from app.domain.errors import DomainError

log = logging.getLogger(__name__)

UNLINKED = (
    "Oi! Eu sou a Abby Cash, assistente de finanças. Para usar este chat, abra o painel web, "
    "vá em Canais, escolha Vincular Telegram e envie aqui o código de 6 dígitos "
    "(ou toque no link que o painel mostra)."
)
INVALID_CODE = "Código inválido ou expirado. Gere um novo no painel web (Canais)."
TOO_MANY = "Muitas tentativas. Aguarde 10 minutos e gere um novo código no painel web."
ALREADY_LINKED = "Este Telegram já está vinculado a outra conta."
LINKED_OK = (
    "✅ Telegram vinculado, {name}! Agora é só me mandar seus gastos, "
    "por exemplo: gastei 45 no mercado."
)
FAILED = "Tive um problema ao processar sua mensagem. Tente de novo em instantes."

_CODE = re.compile(r"(?:/start(?:@\w+)?\s+)?(\d{6})")


async def claim(session: AsyncSession, inbound_id: UUID) -> bool:
    """received -> processing de forma atômica: só um worker processa cada mensagem."""
    got = await session.scalar(
        update(InboundMessage)
        .where(InboundMessage.id == inbound_id, InboundMessage.status == "received")
        .values(status="processing")
        .returning(InboundMessage.id)
    )
    await session.commit()
    return got is not None


async def unlinked(session: AsyncSession, channel: str, external_user_id: str, text: str) -> str:
    """Remetente desconhecido: só instrução fixa (ou vínculo, se mandou um código). Nada é gravado
    no domínio."""
    m = _CODE.fullmatch(text.strip())
    if not m:
        return UNLINKED
    try:
        user = await link_with_code(
            session, channel=channel, external_user_id=external_user_id, code=m.group(1)
        )
    except DomainError as e:
        return TOO_MANY if str(e) == "too_many_attempts" else ALREADY_LINKED
    if user is None:
        return INVALID_CODE
    return LINKED_OK.format(name=user.name.split()[0])


async def handle(session: AsyncSession, ctx: dict[str, Any], row: InboundMessage) -> str | None:
    user = await find_user_by_link(session, row.channel, row.external_user_id)
    if user is None:
        return await unlinked(session, row.channel, row.external_user_id, row.text or "")
    row.user_id = user.id
    return None  # ramo vinculado: a conversa entra no T3.4 (Step 8)


async def handle_inbound(ctx: dict[str, Any], inbound_id: UUID) -> None:
    async with SessionLocal() as session:
        if not await claim(session, inbound_id):
            return  # já processada (reentrega do ARQ, corrida)
        row = await session.get(InboundMessage, inbound_id)
        assert row is not None
        channel, external_user_id = row.channel, row.external_user_id  # escalares: rollback expira
        status = "processed"
        try:
            reply = await handle(session, ctx, row)
            await session.commit()
        except Exception:
            log.exception("process_inbound failed")
            await session.rollback()
            reply, status = FAILED, "failed"
        row = await session.get(InboundMessage, inbound_id, populate_existing=True)
        assert row is not None
        row.status = status
        await session.commit()
        if reply:
            try:
                await get_adapter(channel).send_text(external_user_id, reply)
            except Exception:
                log.exception("send_text failed")
```
`backend/app/jobs/inbound.py`:
```python
from typing import Any
from uuid import UUID

from app.assistant.processor import handle_inbound


async def process_inbound(ctx: dict[str, Any], inbound_id: str) -> None:
    """Job do ARQ: interpreta e responde uma mensagem recebida (id vem como texto da fila)."""
    await handle_inbound(ctx, UUID(inbound_id))
```
`backend/app/worker.py`:
```python
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.jobs.inbound import process_inbound


class WorkerSettings:
    functions = [process_inbound]
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_tries = 1  # ponytail: sem retry; uma mensagem presa em "processing" exige reenvio manual
```

Run: `cd ~/abby-cash/backend && uv run ruff format . && uv run ruff check --fix . && uv run mypy app && uv run pytest tests/domain/test_channel_linking.py tests/api/test_channel_links_api.py tests/assistant -q` → PASS (a primeira passada precisa da tabela: os testes usam `create_all`, não a migração).

- [ ] **Step 7: Exclusão de conta (LGPD) — teste falhando, depois correção**

Em `backend/tests/api/test_privacy_api.py` acrescente ao final:
```python


async def test_delete_account_removes_channel_links_and_inbound_messages(client, session):
    from app.domain.channels.models import ChannelLink, InboundMessage
    from tests.factories import make_inbound, make_link

    ana = await make_user(session, "ana@x.com")
    await make_link(session, ana)
    iid = await make_inbound(session, "gastei 45 no mercado")
    row = await session.get(InboundMessage, iid)
    row.user_id = ana.id
    await session.commit()
    assert (await _delete(client, ana)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(ChannelLink)) == 0
    assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 0
```
Run: `uv run pytest tests/api/test_privacy_api.py -q -k channel_links` → **FAIL** (`ForeignKeyViolationError ... inbound_messages_user_id_fkey`).

Em `backend/app/domain/privacy.py`: acrescente ao import `from app.domain.channels.models import ChannelLink, InboundMessage` (depois da linha de `categories`) e, em `delete_account`, logo depois da linha que apaga `RefreshToken`:
```python
    await session.execute(delete(ChannelLink).where(ChannelLink.user_id == uid))
    await session.execute(delete(InboundMessage).where(InboundMessage.user_id == uid))
```
Run: `uv run pytest tests/api/test_privacy_api.py -q` → PASS.

- [ ] **Step 8: Migração**

```bash
cd ~/abby-cash/backend && uv run alembic upgrade head && uv run alembic revision --autogenerate -m "channel links"
uv run ruff format . && uv run ruff check --fix . && bash scripts/migrate_check.sh
```
O arquivo gerado deve só criar `channel_links` com as duas `UniqueConstraint`; `migrate_check.sh` termina com `No new upgrade operations detected.`

`backend/migrations/versions/ccb9dcb9c087_channel_links.py`:
```python
"""channel links

Revision ID: ccb9dcb9c087
Revises: bdab06c337c9
Create Date: 2026-11-23 13:50:04.713440

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ccb9dcb9c087"
down_revision: str | Sequence[str] | None = "bdab06c337c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "channel_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "external_user_id", name="uq_channel_links_external"),
        sa.UniqueConstraint("user_id", "channel", name="uq_channel_links_user_channel"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("channel_links")
    # ### end Alembic commands ###
```

- [ ] **Step 9: Qualidade e commit**

```bash
cd ~/abby-cash/backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd ~/abby-cash && git add backend/app/api/channel_links.py backend/app/main.py backend/app/worker.py \
  backend/app/assistant backend/app/jobs/inbound.py backend/app/domain/channels backend/app/domain/privacy.py \
  backend/migrations/versions/*_channel_links.py backend/tests/factories.py backend/tests/domain/test_channel_linking.py \
  backend/tests/api/test_channel_links_api.py backend/tests/api/test_privacy_api.py backend/tests/assistant
git commit -m "feat(channels): add channel linking by code and inbound message processor skeleton"
```

---

## Task 3 (T3.3): Interpretador (OpenAI), atalhos e conjunto de avaliação

**Files:** Create `backend/app/core/text.py`, `backend/app/ai/{__init__,models,usage,llm,openai_parser}.py`, `backend/app/assistant/{intents,context,shortcuts}.py`, `backend/scripts/run_eval.py`, `backend/tests/ai/{__init__,test_openai_parser}.py`, `backend/tests/assistant/{evalset.py,eval_cases.yaml,test_shortcuts,test_eval_cases,test_context}.py`, migração `*_ai_usage_and_category_rules.py`. Modify `backend/pyproject.toml` (+`uv.lock`), `backend/app/domain/categories/models.py`, `backend/app/domain/models.py`, `backend/app/domain/privacy.py`, `backend/tests/assistant/fakes.py`, `backend/tests/api/test_privacy_api.py`.

- [ ] **Step 1: Dependências**

```bash
cd ~/abby-cash/backend && uv add openai && uv add --dev pyyaml types-pyyaml
uv run python -c "import openai; print(openai.__version__); from openai import AsyncOpenAI; c = AsyncOpenAI(api_key='x'); print(hasattr(c.chat.completions, 'parse'))"
```
Deve imprimir a versão do SDK e `True`.

- [ ] **Step 2: Conferir a API atual do SDK (obrigatório antes de escrever o parser)**

Consulte a documentação corrente via context7 (`resolve-library-id` "openai python" → `/openai/openai-python`; `query-docs`: "AsyncOpenAI chat.completions.parse response_format Pydantic, message.parsed, refusal, usage prompt_tokens"). O que este plano assume (e que foi conferido na elaboração; refaça se a versão instalada for outra): `await client.chat.completions.parse(model=..., messages=[...], response_format=PydanticModel)` → `completion.choices[0].message.parsed` (`None` + `.refusal` se recusar) e `completion.usage.prompt_tokens/completion_tokens` (`usage` pode ser `None`). Se algo divergir, ajuste **só** `app/ai/openai_parser.py` e o fake de `tests/ai/test_openai_parser.py`, e registre a mudança nas "Decisões técnicas" deste arquivo.

- [ ] **Step 3: Testes falhando (atalhos, conjunto de avaliação, contexto, parser, uso de IA)**

```bash
cd ~/abby-cash/backend && mkdir -p app/ai tests/ai && touch app/ai/__init__.py tests/ai/__init__.py
```

`backend/tests/assistant/fakes.py` passa a ter também o interpretador falso (substitua o arquivo):
`backend/tests/assistant/fakes.py`:
```python
from starlette.requests import Request

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.channels.base import InboundMessage


class FakeAdapter:
    """Canal falso: guarda o que seria enviado ao usuário."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (external_user_id, texto)

    def verify(self, request: Request) -> bool:
        return True

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        return []

    async def send_text(self, external_user_id: str, text: str) -> None:
        self.sent.append((external_user_id, text))

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        return b"", "application/octet-stream"


class FakeParser:
    """Interpretador falso: devolve os resultados na ordem (ou levanta, se for uma exceção)."""

    def __init__(self, *results: "ParsedIntent | Exception") -> None:
        self._results = list(results)
        self.calls: list[tuple[str, SpaceContext]] = []

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent:
        self.calls.append((text, ctx))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
```

O conjunto de avaliação (≥ 40 mensagens reais em pt-BR; gírias, `#pessoal`, "em 3x", "ontem"/"sexta", valor por extenso, formas de pagamento, todas as 13 intenções + `desconhecido`):
`backend/tests/assistant/eval_cases.yaml`:
```yaml
# Conjunto de avaliação do interpretador: mensagens reais em pt-BR e o resultado esperado.
# `expect` lista só os campos que importam (os demais não são conferidos).
# Hoje = quarta-feira 2026-11-25 (ontem = 24, "sexta" = 20, "sábado" = 21, "segunda" = 23).
# Rodar contra o modelo real (manual, custa tokens): `uv run python scripts/run_eval.py`
today: "2026-11-25"
cases:
  # --- despesas à vista, com e sem gírias ---
  - text: "gastei 45 no mercado"
    expect: {intent: lancar_despesa, amount_cents: 4500, category_name: Mercado}
  - text: "mercado 45,90"
    expect: {intent: lancar_despesa, amount_cents: 4590, category_name: Mercado}
  - text: "comprei pão na padaria 12"
    expect: {intent: lancar_despesa, amount_cents: 1200, category_name: Alimentação}
  - text: "uber 23"
    expect: {intent: lancar_despesa, amount_cents: 2300, category_name: Transporte}
  - text: "gastei 30 de gasolina"
    expect: {intent: lancar_despesa, amount_cents: 3000, category_name: Transporte}
  - text: "almoço 38,50 no restaurante"
    expect: {intent: lancar_despesa, amount_cents: 3850, category_name: Alimentação}
  - text: "paguei 1.234,56 de aluguel"
    expect: {intent: lancar_despesa, amount_cents: 123456, category_name: Moradia}
  - text: "R$45 farmácia"
    expect: {intent: lancar_despesa, amount_cents: 4500, category_name: Saúde}
  - text: "45 reais de ração do cachorro"
    expect: {intent: lancar_despesa, amount_cents: 4500, category_name: Pets}
  - text: "netflix 55,90"
    expect: {intent: lancar_despesa, amount_cents: 5590, category_name: Assinaturas}
  - text: "vinte contos de lanche"
    expect: {intent: lancar_despesa, amount_cents: 2000, category_name: Alimentação}
  # --- valores por extenso (áudio transcrito) ---
  - text: "gastei mil e duzentos na reforma"
    expect: {intent: lancar_despesa, amount_cents: 120000, category_name: Moradia}
  - text: "dois mil no notebook"
    expect: {intent: lancar_despesa, amount_cents: 200000, category_name: Compras}
  - text: "quarenta e cinco no mercado"
    expect: {intent: lancar_despesa, amount_cents: 4500, category_name: Mercado}
  # --- datas relativas ---
  - text: "ifood 67 ontem"
    expect: {intent: lancar_despesa, amount_cents: 6700, category_name: Alimentação, occurred_on: "2026-11-24"}
  - text: "gastei 80 sexta no cinema"
    expect: {intent: lancar_despesa, amount_cents: 8000, category_name: Lazer, occurred_on: "2026-11-20"}
  - text: "anteontem paguei 25 de estacionamento"
    expect: {intent: lancar_despesa, amount_cents: 2500, category_name: Transporte, occurred_on: "2026-11-23"}
  - text: "paguei a luz 180 dia 10"
    expect: {intent: lancar_despesa, amount_cents: 18000, category_name: Contas da casa, occurred_on: "2026-11-10"}
  # --- espaço (#pessoal / #familia) ---
  - text: "#pessoal presente pra mim 150"
    expect: {intent: lancar_despesa, amount_cents: 15000, private: true, category_name: Compras}
  - text: "150 no tênis #pessoal"
    expect: {intent: lancar_despesa, amount_cents: 15000, private: true, category_name: Compras}
  - text: "#familia mercado 320"
    expect: {intent: lancar_despesa, amount_cents: 32000, category_name: Mercado}
  # --- parcelado ---
  - text: "tv 3000 em 10x no nubank"
    expect: {intent: lancar_parcelado, amount_cents: 300000, installments: 10, card_hint: nubank}
  - text: "geladeira 2400 em 12x no cartão"
    expect: {intent: lancar_parcelado, amount_cents: 240000, installments: 12}
  - text: "comprei um celular em 3x de 500"
    expect: {intent: lancar_parcelado, amount_cents: 150000, installments: 3}
  - text: "parcelei 900 em 3 vezes no cartão da nubank"
    expect: {intent: lancar_parcelado, amount_cents: 90000, installments: 3, card_hint: nubank}
  # --- forma de pagamento ---
  - text: "pizza 70 no pix"
    expect: {intent: lancar_despesa, amount_cents: 7000, account_hint: pix}
  - text: "gastei 25 no dinheiro com lanche"
    expect: {intent: lancar_despesa, amount_cents: 2500, account_hint: dinheiro}
  - text: "mercado 200 no itaú"
    expect: {intent: lancar_despesa, amount_cents: 20000, account_hint: itau}
  # --- receitas ---
  - text: "recebi 3000 de salário"
    expect: {intent: lancar_receita, amount_cents: 300000, category_name: Salário}
  - text: "caiu o pix de 500 de freela"
    expect: {intent: lancar_receita, amount_cents: 50000, category_name: Renda extra}
  - text: "recebi 80 de reembolso"
    expect: {intent: lancar_receita, amount_cents: 8000, category_name: Reembolso}
  # --- corrigir / apagar ---
  - text: "na verdade foi 50"
    expect: {intent: corrigir, amount_cents: 5000}
  - text: "era lazer, não mercado"
    expect: {intent: corrigir, category_name: Lazer}
  - text: "apagar o último lançamento"
    expect: {intent: apagar}
  - text: "apaga isso aí"
    expect: {intent: apagar}
  # --- pagar contas e contas a pagar ---
  - text: "paguei a conta de luz"
    expect: {intent: pagar_conta}
  - text: "quitei a fatura do nubank"
    expect: {intent: pagar_conta}
  - text: "paguei 500 da fatura"
    expect: {intent: pagar_conta, amount_cents: 50000}
  - text: "conta de internet 120 vence dia 10"
    expect: {intent: nova_conta_a_pagar, amount_cents: 12000, occurred_on: "2026-12-10"}
  # --- metas ---
  - text: "guardei 500 na viagem"
    expect: {intent: aporte_meta, amount_cents: 50000, goal_hint: viagem}
  - text: "coloquei 200 na meta do carro"
    expect: {intent: aporte_meta, amount_cents: 20000, goal_hint: carro}
  # --- consultas ---
  - text: "quanto gastei esse mês?"
    expect: {intent: consultar_gastos, period: mes}
  - text: "quanto gastei de mercado hoje"
    expect: {intent: consultar_gastos, period: hoje, category_name: Mercado}
  - text: "gastos da semana"
    expect: {intent: consultar_gastos, period: semana}
  - text: "como está o teto?"
    expect: {intent: consultar_teto}
  - text: "qual meu saldo"
    expect: {intent: consultar_saldo}
  - text: "quanto tem na carteira"
    expect: {intent: consultar_saldo}
  - text: "minhas faturas"
    expect: {intent: consultar_faturas}
  - text: "quanto falta pagar do cartão"
    expect: {intent: consultar_faturas}
  # --- ajuda e fora de assunto ---
  - text: "o que você faz?"
    expect: {intent: ajuda}
  - text: "bom dia"
    expect: {intent: desconhecido}
  - text: "qual a capital da França"
    expect: {intent: desconhecido}
```
`backend/tests/assistant/evalset.py`:
```python
"""Conjunto de avaliação do interpretador: carga, contexto fixo e comparação de resultados."""

from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from app.assistant.context import (
    CtxAccount,
    CtxCard,
    CtxCategory,
    CtxGoal,
    SpaceContext,
)
from app.assistant.intents import ParsedIntent
from app.core.text import fold
from app.domain.categories.defaults import DEFAULT_EXPENSE, DEFAULT_INCOME

EVAL_PATH = Path(__file__).with_name("eval_cases.yaml")
_FUZZY = {"category_name", "account_hint", "card_hint", "goal_hint"}


def load_cases() -> tuple[date, list[dict[str, Any]]]:
    data = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8"))
    return date.fromisoformat(data["today"]), data["cases"]


def eval_context(today: date) -> SpaceContext:
    space = uuid4()
    return SpaceContext(
        space_id=space,
        space_name="Pessoal",
        categories=[CtxCategory(uuid4(), n, "expense") for n in DEFAULT_EXPENSE]
        + [CtxCategory(uuid4(), n, "income") for n in DEFAULT_INCOME],
        accounts=[
            CtxAccount(uuid4(), "Carteira", "wallet", space),
            CtxAccount(uuid4(), "Nubank", "checking", space),
            CtxAccount(uuid4(), "Itaú", "checking", space),
        ],
        cards=[CtxCard(uuid4(), "Nubank", space), CtxCard(uuid4(), "Visa", space)],
        goals=[CtxGoal(uuid4(), "Viagem"), CtxGoal(uuid4(), "Carro")],
        rules=[("padaria pao quente", "Alimentação")],
        default_account_id=None,
        today=today,
        tz="America/Sao_Paulo",
    )


def mismatches(expect: dict[str, Any], got: ParsedIntent) -> list[str]:
    """Campos esperados que o resultado não cumpre. Texto livre compara sem acento/caixa."""
    out = []
    for key, want in expect.items():
        have = getattr(got, key)
        if key == "occurred_on":
            want = date.fromisoformat(str(want))
        if key == "category_name":
            ok = fold(str(have or "")) == fold(str(want))
        elif key in _FUZZY:
            ok = fold(str(want)) in fold(str(have or ""))
        else:
            ok = have == want
        if not ok:
            out.append(f"{key}: esperado {want!r}, veio {have!r}")
    return out
```
`backend/tests/assistant/test_shortcuts.py`:
```python
import pytest

from app.assistant.shortcuts import answer, try_shortcut


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("paguei", "pagar_conta"),
        ("Paguei!", "pagar_conta"),
        ("corrigir", "corrigir"),
        ("apagar último", "apagar"),
        ("Apagar ultimo.", "apagar"),
        ("saldo", "consultar_saldo"),
        ("/saldo", "consultar_saldo"),
        ("teto", "consultar_teto"),
        ("faturas", "consultar_faturas"),
        ("ajuda", "ajuda"),
        ("/start", "ajuda"),
    ],
)
def test_shortcuts_without_llm(text, intent):
    got = try_shortcut(text)
    assert got is not None and got.intent == intent and got.confidence == 1.0


def test_shortcut_number_is_a_list_choice():
    got = try_shortcut("2")
    assert got is not None and got.intent == "desconhecido" and got.choice == 2
    assert try_shortcut("45").choice == 45  # type: ignore[union-attr]
    assert try_shortcut("123") is None  # 3 dígitos: pode ser um valor


@pytest.mark.parametrize(
    "text", ["gastei 45 mercado", "saldo da carteira ontem", "paguei 500 da fatura", ""]
)
def test_non_commands_need_the_llm(text):
    assert try_shortcut(text) is None


def test_shortcut_results_are_independent_copies():
    a = try_shortcut("saldo")
    assert a is not None
    a.amount_cents = 1
    assert try_shortcut("saldo").amount_cents is None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("text", "want"),
    [("sim", "sim"), ("Sim!", "sim"), ("não", "nao"), ("nao", "nao"), ("cancelar", "cancelar"),
     ("deixa pra lá", "cancelar"), ("talvez", None)],
)  # fmt: skip
def test_yes_no_cancel(text, want):
    assert answer(text) == want
```
`backend/tests/assistant/test_eval_cases.py`:
```python
from app.assistant.intents import ParsedIntent
from tests.assistant.evalset import eval_context, load_cases, mismatches
from tests.assistant.fakes import FakeParser

ALL_INTENTS = set(ParsedIntent.model_fields["intent"].annotation.__args__)  # type: ignore[union-attr]


def test_eval_set_is_large_and_covers_every_intent():
    today, cases = load_cases()
    assert len(cases) >= 40
    assert {c["expect"]["intent"] for c in cases} == ALL_INTENTS
    texts = " ".join(c["text"] for c in cases).lower()
    for needle in ("#pessoal", "em 3x", "ontem", "sexta", "mil e duzentos", "no pix", "uber"):
        assert needle in texts


async def test_eval_cases():
    """O conjunto é válido e o avaliador funciona: um parser que devolve o esperado passa em
    tudo; um que erra é apontado. (Contra o modelo real: scripts/run_eval.py, fora do CI.)"""
    today, cases = load_cases()
    ctx = eval_context(today)
    category_names = {c.name for c in ctx.categories}
    for case in cases:
        expect = case["expect"]
        if "category_name" in expect:
            assert expect["category_name"] in category_names, case["text"]
        want = ParsedIntent.model_validate({"confidence": 1.0, **expect})  # esperado é válido
        parser = FakeParser(want)
        got = await parser.parse(case["text"], ctx)
        assert mismatches(expect, got) == [], case["text"]
    wrong = ParsedIntent.of("lancar_despesa", amount_cents=4501, category_name="mercado")
    assert mismatches({"amount_cents": 4500, "category_name": "Mercado"}, wrong) == [
        "amount_cents: esperado 4500, veio 4501"
    ]
```
`backend/tests/assistant/test_context.py`:
```python
from datetime import date

import pytest
from fastapi import HTTPException

from app.assistant.context import load_space_context
from tests.factories import make_account, make_card, make_family, make_user

TODAY = date(2026, 11, 25)


async def ctx(session, user, space_id):
    return await load_space_context(
        session, user_id=user.id, space_id=space_id, today=TODAY, tz=user.tz
    )


async def test_non_member_cannot_load_a_space_context(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    with pytest.raises(HTTPException) as e:
        await ctx(session, bia, ana.default_space_id)
    assert e.value.status_code == 404


async def test_context_lists_only_what_the_user_may_use(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    fam = await make_family(session, ana, bia)
    await make_account(session, fam.id, name="Conta Casa")
    await make_account(session, ana.default_space_id, name="Segredo da Ana")
    await make_card(session, ana, fam.id, name="Visa Casa")
    c = await ctx(session, bia, fam.id)
    assert c.space_id == fam.id and c.space_name == "Casa"
    assert {a.name for a in c.accounts} == {"Carteira", "Conta Casa"}  # a da Ana não aparece
    assert [x.name for x in c.cards] == ["Visa Casa"]
    assert "Mercado" in {x.name for x in c.categories if x.kind == "expense"}
    assert c.default_account_id is None  # a Bia ainda não escolheu conta padrão na família
    own = await ctx(session, bia, bia.default_space_id)
    assert own.default_account_id is not None  # carteira
    assert {a.name for a in own.accounts} == {"Carteira", "Conta Casa"}  # contas da família valem
```
`backend/tests/ai/test_openai_parser.py`:
```python
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai.models import AiUsage
from app.ai.openai_parser import IntentParseError, OpenAIIntentParser, build_system_prompt
from app.ai.usage import record_ai_usage
from app.assistant.context import load_space_context
from app.assistant.intents import ParsedIntent
from app.core.config import get_settings
from tests.factories import make_user

TODAY = date(2026, 11, 25)


USAGE = SimpleNamespace(prompt_tokens=120, completion_tokens=30)


class FakeCompletions:
    def __init__(self, parsed, refusal=None):
        self.kwargs: dict = {}
        self._msg = SimpleNamespace(parsed=parsed, refusal=refusal)

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self._msg)], usage=USAGE)


def client_with(completions: FakeCompletions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


async def ctx_for(session):
    user = await make_user(session, "ana@x.com")
    ctx = await load_space_context(
        session, user_id=user.id, space_id=user.default_space_id, today=TODAY, tz=user.tz
    )
    return user, ctx


async def test_parse_sends_structured_request_and_returns_parsed(session):
    _, ctx = await ctx_for(session)
    want = ParsedIntent.of("lancar_despesa", amount_cents=4500, category_name="Mercado")
    comp = FakeCompletions(want)
    got = await OpenAIIntentParser(client=client_with(comp)).parse("gastei 45 no mercado", ctx)
    assert got == want
    kw = comp.kwargs
    assert kw["model"] == get_settings().AI_MODEL
    assert kw["response_format"] is ParsedIntent
    system, user_msg = kw["messages"]
    assert system["role"] == "system" and user_msg["role"] == "user"
    assert "Mercado" in system["content"] and "Carteira" in system["content"]
    assert "25/11/2026" not in system["content"]  # a data fica fora do prefixo estável
    assert "25/11/2026" in user_msg["content"] and "quarta" in user_msg["content"]
    assert user_msg["content"].endswith("gastei 45 no mercado")


async def test_parse_records_usage_for_the_space(session):
    user, ctx = await ctx_for(session)
    parser = OpenAIIntentParser(client=client_with(FakeCompletions(ParsedIntent.of("ajuda"))))
    await parser.parse("ajuda", ctx)
    row = await session.scalar(select(AiUsage))
    assert row is not None
    assert (row.space_id, row.kind, row.input_tokens, row.output_tokens) == (
        user.default_space_id, "intent", 120, 30,
    )  # fmt: skip


async def test_refusal_or_empty_response_raises(session):
    _, ctx = await ctx_for(session)
    parser = OpenAIIntentParser(client=client_with(FakeCompletions(None, refusal="não posso")))
    with pytest.raises(IntentParseError, match="não posso"):
        await parser.parse("x", ctx)


async def test_model_can_be_overridden_and_defaults_to_settings():
    assert OpenAIIntentParser(client=object(), model="gpt-x").model == "gpt-x"
    assert OpenAIIntentParser(client=object()).model == get_settings().AI_MODEL


async def test_prompt_lists_space_data_and_learned_rules(session):
    _, ctx = await ctx_for(session)
    from dataclasses import replace

    prompt = build_system_prompt(replace(ctx, rules=[("padaria pao quente", "Alimentação")]))
    assert "Categorias de despesa:" in prompt and "Impostos e taxas" in prompt
    assert "Categorias de receita:" in prompt and "Salário" in prompt
    assert "padaria pao quente -> Alimentação" in prompt
    assert "Cartões: (nenhum)" in prompt
    assert "@" not in prompt  # nada de e-mail/identificadores do usuário


async def test_record_ai_usage_never_raises(session):
    from uuid import uuid4

    await record_ai_usage(
        uuid4(), "intent", input_tokens=1
    )  # espaço inexistente: FK falha, só loga
    assert await session.scalar(select(AiUsage)) is None


async def test_missing_api_key_fails_at_parse_time_not_at_construction(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    parser = OpenAIIntentParser()  # nunca levanta: o worker sobe mesmo sem chave
    _, ctx = await ctx_for(session)
    with pytest.raises(Exception, match="credentials"):
        await parser.parse("oi", ctx)
```


- [ ] **Step 4: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/assistant tests/ai -q` → **FAIL** (`ModuleNotFoundError: No module named 'app.assistant.intents'` / `app.ai`).

- [ ] **Step 5: Implementar modelos, intenção, contexto, atalhos e parser**

`fold` (usado em todo o marco para comparar texto sem acento/caixa):
`backend/app/core/text.py`:
```python
import unicodedata


def fold(text: str) -> str:
    """minúsculas e sem acentos: base de toda comparação de texto livre."""
    s = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in s if not unicodedata.combining(c))
```

Intenção estruturada (esquema estrito: opcionais `| None = None`, `confidence` obrigatório):
`backend/app/assistant/intents.py`:
```python
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

Intent = Literal[
    "lancar_despesa", "lancar_receita", "lancar_parcelado", "corrigir", "apagar", "pagar_conta",
    "nova_conta_a_pagar", "aporte_meta", "consultar_gastos", "consultar_teto", "consultar_saldo",
    "consultar_faturas", "ajuda", "desconhecido",
]  # fmt: skip
Period = Literal["hoje", "ontem", "semana", "mes", "mes_passado"]


class ParsedIntent(BaseModel):
    """Saída estruturada do LLM. Todo campo opcional é `| None = None` (e `confidence` não tem
    default): o SDK da OpenAI exige esquema estrito e o converte para "todos obrigatórios"."""

    intent: Intent
    confidence: float  # 0..1
    amount_cents: int | None = None  # valor TOTAL em centavos
    description: str | None = None
    merchant: str | None = None
    category_name: str | None = None
    account_hint: str | None = None  # "nubank", "pix", "dinheiro"
    card_hint: str | None = None
    installments: int | None = None
    occurred_on: date | None = None
    private: bool | None = None  # #pessoal
    goal_hint: str | None = None
    period: Period | None = None
    choice: int | None = None  # número escolhido numa lista

    @classmethod
    def of(cls, intent: Intent, **fields: Any) -> "ParsedIntent":
        """Resultado determinístico (atalhos, fallback): confiança máxima, salvo se informada."""
        return cls(intent=intent, **{"confidence": 1.0, **fields})
```

Tabelas `ai_usage` e `category_rules`. Em `backend/app/domain/categories/models.py` troque o import por `from sqlalchemy import ForeignKey, String, UniqueConstraint` e acrescente ao final:
```python


class CategoryRule(Base):
    """Aprendizado: estabelecimento normalizado -> categoria (precedência sobre o LLM)."""

    __tablename__ = "category_rules"
    __table_args__ = (
        UniqueConstraint("space_id", "merchant_norm", name="uq_category_rules_space_merchant"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    merchant_norm: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id"))
```
Em `backend/app/domain/models.py` acrescente `import app.ai.models  # noqa: F401` (o `ruff check --fix` ordena).
`backend/app/ai/models.py`:
```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiUsage(Base):
    """Consumo de IA por espaço (base para precificar na fase de venda)."""

    __tablename__ = "ai_usage"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # intent | receipt | stt
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)  # áudio (não é dinheiro)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```
`backend/app/ai/usage.py`:
```python
import logging
from uuid import UUID

from app.ai.models import AiUsage
from app.core.db import SessionLocal

log = logging.getLogger(__name__)


async def record_ai_usage(
    space_id: UUID, kind: str, *, input_tokens: int = 0, output_tokens: int = 0,
    seconds: float = 0.0,
) -> None:  # fmt: skip
    """Sessão própria: o consumo é registrado mesmo se a conversa der rollback. Nunca derruba
    quem chamou."""
    try:
        async with SessionLocal() as session:
            session.add(
                AiUsage(
                    space_id=space_id, kind=kind, input_tokens=input_tokens,
                    output_tokens=output_tokens, seconds=seconds,
                )
            )  # fmt: skip
            await session.commit()
    except Exception:
        log.exception("record_ai_usage failed")
```

Contexto do espaço (o que o interpretador e os fluxos sabem; valida a participação antes de tudo):
`backend/app/assistant/context.py`:
```python
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.models import Account
from app.domain.cards.models import CreditCard
from app.domain.categories.models import Category, CategoryRule
from app.domain.goals.models import Goal
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceMember


@dataclass(frozen=True)
class CtxCategory:
    id: UUID
    name: str
    kind: str  # expense | income


@dataclass(frozen=True)
class CtxAccount:
    id: UUID
    name: str
    type: str  # checking | wallet | savings
    space_id: UUID


@dataclass(frozen=True)
class CtxCard:
    id: UUID
    name: str
    space_id: UUID


@dataclass(frozen=True)
class CtxGoal:
    id: UUID
    name: str


@dataclass(frozen=True)
class SpaceContext:
    """O que o interpretador (e os fluxos) sabem do espaço-alvo. Categorias e metas são do espaço;
    contas e cartões são os que o usuário PODE USAR (qualquer espaço de que é membro)."""

    space_id: UUID
    space_name: str
    categories: list[CtxCategory]
    accounts: list[CtxAccount]
    cards: list[CtxCard]
    goals: list[CtxGoal]
    rules: list[tuple[str, str]]  # (estabelecimento normalizado, nome da categoria)
    default_account_id: UUID | None
    today: date
    tz: str


async def load_space_context(
    session: AsyncSession, *, user_id: UUID, space_id: UUID, today: date, tz: str
) -> SpaceContext:
    member = await require_member(session, user_id, space_id)  # isolamento antes de tudo
    mine = list(
        await session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == user_id))
    )
    space = await session.get(Space, space_id)
    assert space is not None
    cats = await session.scalars(
        select(Category).where(Category.space_id == space_id).order_by(Category.name)
    )
    accs = await session.scalars(
        select(Account).where(Account.space_id.in_(mine)).order_by(Account.name)
    )
    cards = await session.scalars(
        select(CreditCard).where(CreditCard.space_id.in_(mine)).order_by(CreditCard.name)
    )
    goals = await session.scalars(select(Goal).where(Goal.space_id == space_id).order_by(Goal.name))
    rules = await session.execute(
        select(CategoryRule.merchant_norm, Category.name)
        .join(Category, Category.id == CategoryRule.category_id)
        .where(CategoryRule.space_id == space_id)
        .limit(100)
    )
    return SpaceContext(
        space_id=space_id,
        space_name=space.name,
        categories=[CtxCategory(c.id, c.name, c.kind) for c in cats],
        accounts=[CtxAccount(a.id, a.name, a.type, a.space_id) for a in accs],
        cards=[CtxCard(c.id, c.name, c.space_id) for c in cards],
        goals=[CtxGoal(g.id, g.name) for g in goals],
        rules=[(m, n) for m, n in rules],
        default_account_id=member.default_account_id,
        today=today,
        tz=tz,
    )
```

Atalhos determinísticos (sem custo de IA) e respostas curtas (sim/não/cancelar):
`backend/app/assistant/shortcuts.py`:
```python
import re
from typing import Any, Literal

from app.assistant.intents import Intent, ParsedIntent
from app.core.text import fold

_COMMANDS: dict[str, ParsedIntent] = {}


def _register(intent: Intent, *phrases: str, **fields: Any) -> None:
    for p in phrases:
        _COMMANDS[p] = ParsedIntent.of(intent, **fields)


_register("pagar_conta", "paguei", "pago", "quitei")
_register("corrigir", "corrigir", "corrige", "errei", "corrigir ultimo")
_register(
    "apagar", "apagar", "apaga", "apagar ultimo", "apaga ultimo", "apagar o ultimo", "desfazer",
    "excluir ultimo",
)  # fmt: skip
_register("consultar_saldo", "saldo", "meu saldo", "qual o saldo", "qual meu saldo")
_register("consultar_teto", "teto", "meu teto", "como esta o teto")
_register("consultar_faturas", "fatura", "faturas", "minhas faturas")
_register("consultar_gastos", "gastos", "meus gastos", "quanto gastei", period="mes")
_register("ajuda", "ajuda", "help", "menu", "comandos", "start")

_YES = {"sim", "s", "isso", "ok", "pode", "confirmo", "certo", "yes"}
_NO = {"nao", "n", "no", "negativo"}
_CANCEL = {"cancelar", "cancela", "deixa pra la", "esquece", "esquece isso", "desisti"}


def _clean(text: str) -> str:
    s = re.sub(r"[^\w\s]", " ", fold(text)).strip()  # sem pontuação nem "/"
    return " ".join(s.split())


def try_shortcut(text: str) -> ParsedIntent | None:
    """Comandos simples resolvidos sem LLM; None = precisa interpretar."""
    s = _clean(text)
    if re.fullmatch(r"\d{1,2}", s):
        return ParsedIntent.of("desconhecido", choice=int(s))
    return _COMMANDS[s].model_copy() if s in _COMMANDS else None


def answer(text: str) -> Literal["sim", "nao", "cancelar"] | None:
    """Resposta curta a uma pergunta pendente."""
    s = _clean(text)
    if s in _YES:
        return "sim"
    if s in _NO:
        return "nao"
    return "cancelar" if s in _CANCEL else None
```

Interface e implementação OpenAI:
`backend/app/ai/llm.py`:
```python
from typing import Protocol

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent


class IntentParser(Protocol):
    """Interpreta uma mensagem de texto. Levanta qualquer exceção se não conseguir: quem chama
    degrada para o atalho determinístico (spec 9)."""

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent: ...
```
`backend/app/ai/openai_parser.py`:
```python
from typing import Any

from openai import AsyncOpenAI

from app.ai.usage import record_ai_usage
from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.core.config import get_settings

WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

INSTRUCTIONS = """\
Você interpreta mensagens de um assistente de finanças pessoais (Abby Cash), em português do \
Brasil, e devolve só o JSON do esquema. Regras:
- intent: lancar_despesa, lancar_receita, lancar_parcelado (compra dividida em 2 ou mais \
parcelas), corrigir (mudar o ÚLTIMO lançamento), apagar (apagar o último lançamento), \
pagar_conta (quitar conta/fatura já existente), nova_conta_a_pagar (conta com vencimento \
futuro), aporte_meta (guardar dinheiro numa meta), consultar_gastos, consultar_teto, \
consultar_saldo, consultar_faturas, ajuda ou desconhecido.
- amount_cents: valor TOTAL em centavos, inteiro. "45" = 4500; "1.234,56" = 123456; \
"mil e duzentos" = 120000; "3x de 500" = 150000. Nunca invente valor: sem valor, use null.
- occurred_on: data ISO (AAAA-MM-DD) calculada a partir do "hoje" da mensagem ("ontem", \
"sexta", "dia 15"); null se a mensagem não citar data. Em nova_conta_a_pagar é o vencimento.
- installments: número de parcelas (2 ou mais), só se a mensagem disser.
- category_name: EXATAMENTE um nome da lista de categorias abaixo (despesa ou receita, \
conforme o caso); null se nenhuma servir.
- merchant: nome do estabelecimento; description: descrição curta do gasto.
- account_hint e card_hint: o texto que o usuário usou para a forma de pagamento ("nubank", \
"pix", "dinheiro", "cartão"); null se não disse.
- private: true só se a mensagem tiver #pessoal.
- goal_hint: nome (ou parte) da meta. period: hoje, ontem, semana, mes ou mes_passado, nas \
consultas.
- choice: o número escolhido, apenas quando a mensagem é só um número.
- confidence: de 0 a 1; abaixo de 0.6 quando a mensagem for ambígua.
- corrigir: preencha apenas o que o usuário quer mudar (amount_cents, category_name, \
description, occurred_on).
- Mensagens fora do assunto: intent desconhecido.
"""


def build_system_prompt(ctx: SpaceContext) -> str:
    """Prefixo estável por espaço (instruções + listas): aproveita o cache automático de prompt.
    A data de hoje vai na mensagem do usuário, não aqui."""

    def names(items: list[str]) -> str:
        return ", ".join(items) if items else "(nenhum)"

    expense = names([c.name for c in ctx.categories if c.kind == "expense"])
    income = names([c.name for c in ctx.categories if c.kind == "income"])
    rules = "; ".join(f"{m} -> {c}" for m, c in ctx.rules) or "(nenhuma)"
    return (
        f"{INSTRUCTIONS}\n"
        f"Categorias de despesa: {expense}\n"
        f"Categorias de receita: {income}\n"
        f"Contas: {names([a.name for a in ctx.accounts])}\n"
        f"Cartões: {names([c.name for c in ctx.cards])}\n"
        f"Metas: {names([g.name for g in ctx.goals])}\n"
        f"Regras aprendidas (estabelecimento -> categoria; têm prioridade): {rules}\n"
    )


class IntentParseError(Exception):
    pass


class OpenAIIntentParser:
    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self.model = model or get_settings().AI_MODEL
        self._client = client

    def _get_client(self) -> Any:
        """Cliente criado no primeiro uso: sem OPENAI_API_KEY o worker sobe e as mensagens caem no
        fallback (spec 9), em vez de o processo morrer na partida."""
        if self._client is None:
            s = get_settings()
            self._client = AsyncOpenAI(
                api_key=s.OPENAI_API_KEY, timeout=s.AI_TIMEOUT_S, max_retries=1
            )
        return self._client

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent:
        today = f"{ctx.today:%d/%m/%Y}, {WEEKDAYS[ctx.today.weekday()]}"
        completion = await self._get_client().chat.completions.parse(
            model=self.model,
            temperature=0,  # modelos de raciocínio não aceitam: ao trocar AI_MODEL, remova
            response_format=ParsedIntent,
            messages=[
                {"role": "system", "content": build_system_prompt(ctx)},
                {"role": "user", "content": f"[hoje: {today}; fuso {ctx.tz}]\n{text}"},
            ],
        )
        if completion.usage is not None:
            await record_ai_usage(
                ctx.space_id, "intent", input_tokens=completion.usage.prompt_tokens,
                output_tokens=completion.usage.completion_tokens,
            )  # fmt: skip
        message = completion.choices[0].message
        if message.parsed is None:
            raise IntentParseError(message.refusal or "empty_response")
        parsed: ParsedIntent = message.parsed
        return parsed
```

Run: `cd ~/abby-cash/backend && uv run ruff format . && uv run ruff check --fix . && uv run mypy app && uv run pytest tests/assistant tests/ai -q` → PASS.

- [ ] **Step 6: Conferir o esquema estrito que o SDK vai enviar**

```bash
cd ~/abby-cash/backend && uv run python - <<'PY'
from openai.lib._parsing import type_to_response_format_param

from app.assistant.intents import ParsedIntent

js = type_to_response_format_param(ParsedIntent)["json_schema"]
schema = js["schema"]
assert js["strict"] is True and schema["additionalProperties"] is False
assert set(schema["required"]) == set(schema["properties"]), "todo campo precisa estar em required"
assert schema["properties"]["occurred_on"]["anyOf"][0]["format"] == "date"
print("esquema estrito ok:", len(schema["properties"]), "campos")
PY
```
Deve imprimir `esquema estrito ok: 14 campos`. (`_parsing` é módulo interno do SDK; se o caminho mudar numa versão futura, use `openai.pydantic_function_tool`/`to_strict_json_schema` equivalente e ajuste só este passo.)

- [ ] **Step 7: Script de avaliação contra o modelo real (manual)**

`backend/scripts/run_eval.py`:
```python
"""Roda o conjunto de avaliação contra o modelo REAL (usa OPENAI_API_KEY e custa tokens).

Manual, nunca no CI:  cd backend && uv run python scripts/run_eval.py [--min 0.9]
Sai com código 1 se a taxa de acerto ficar abaixo de --min.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # para importar `app` e `tests`

import app.ai.openai_parser as openai_parser  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from tests.assistant.evalset import eval_context, load_cases, mismatches  # noqa: E402


async def _no_usage(*_: Any, **__: Any) -> None:  # o contexto de avaliação não tem espaço no banco
    return None


async def main(minimum: float) -> int:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY ausente no .env")
    openai_parser.record_ai_usage = _no_usage  # type: ignore[assignment]
    today, cases = load_cases()
    ctx = eval_context(today)
    parser = openai_parser.OpenAIIntentParser()
    print(f"modelo: {parser.model} · {len(cases)} casos · hoje = {today}")
    ok = 0
    for case in cases:
        try:
            diff = mismatches(case["expect"], await parser.parse(case["text"], ctx))
        except Exception as e:  # noqa: BLE001 - qualquer falha da API conta como erro do caso
            diff = [f"erro: {type(e).__name__}"]
        ok += not diff
        print(("OK   " if not diff else "FALHA"), case["text"], *(f"\n       - {d}" for d in diff))
    rate = ok / len(cases)
    print(f"\nacertos: {ok}/{len(cases)} ({rate:.0%})")
    return 0 if rate >= minimum else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=0.9, help="taxa mínima de acerto (0 a 1)")
    raise SystemExit(asyncio.run(main(ap.parse_args().min)))
```

- [ ] **Step 8: Migração**

```bash
cd ~/abby-cash/backend && uv run alembic upgrade head && uv run alembic revision --autogenerate -m "ai usage and category rules"
uv run ruff format . && uv run ruff check --fix . && bash scripts/migrate_check.sh
```
O arquivo gerado cria `ai_usage` e `category_rules` (com `uq_category_rules_space_merchant` e índices de `space_id`), sem `drop`; `migrate_check.sh` termina com `No new upgrade operations detected.`

`backend/migrations/versions/a32953583fa0_ai_usage_and_category_rules.py`:
```python
"""ai usage and category rules

Revision ID: a32953583fa0
Revises: ccb9dcb9c087
Create Date: 2026-11-23 13:54:50.647268

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a32953583fa0"
down_revision: str | Sequence[str] | None = "ccb9dcb9c087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_usage_space_id"), "ai_usage", ["space_id"], unique=False)
    op.create_table(
        "category_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_norm", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "merchant_norm", name="uq_category_rules_space_merchant"),
    )
    op.create_index(
        op.f("ix_category_rules_space_id"), "category_rules", ["space_id"], unique=False
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_category_rules_space_id"), table_name="category_rules")
    op.drop_table("category_rules")
    op.drop_index(op.f("ix_ai_usage_space_id"), table_name="ai_usage")
    op.drop_table("ai_usage")
    # ### end Alembic commands ###
```

- [ ] **Step 9: Exclusão de conta com regras e uso de IA — teste falhando, depois correção**

Em `backend/tests/api/test_privacy_api.py` acrescente `category_id,` à lista importada de `tests.factories` e, ao final:
```python


async def test_delete_account_removes_category_rules_and_ai_usage(client, session):
    from app.ai.models import AiUsage
    from app.domain.categories.models import CategoryRule

    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    session.add(CategoryRule(
        space_id=sp, merchant_norm="padaria", category_id=await category_id(session, sp)
    ))  # fmt: skip
    session.add(AiUsage(space_id=sp, kind="intent", input_tokens=10, output_tokens=2))
    await session.commit()
    assert (await _delete(client, ana)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(CategoryRule)) == 0
    assert await session.scalar(select(func.count()).select_from(AiUsage)) == 0
```
Run: `uv run pytest tests/api/test_privacy_api.py -q -k category_rules` → **FAIL** (`ForeignKeyViolationError ... category_rules_category_id_fkey`).

Em `backend/app/domain/privacy.py`: acrescente `from app.ai.models import AiUsage`, troque o import para `from app.domain.categories.models import Category, CategoryRule` e, em `_purge_space`, **antes** da linha que apaga `Category`:
```python
    await session.execute(delete(CategoryRule).where(CategoryRule.space_id == space_id))
    await session.execute(delete(AiUsage).where(AiUsage.space_id == space_id))
```
Run: `uv run pytest tests/api/test_privacy_api.py -q` → PASS.

- [ ] **Step 10: Avaliação com o modelo real (manual, uma vez), qualidade e commit**

```bash
cd ~/abby-cash/backend && uv run python scripts/run_eval.py      # usa OPENAI_API_KEY do .env; custa alguns centavos
```
Meta: ≥ 90% de acertos. Falhas por prompt: ajuste `INSTRUCTIONS` em `app/ai/openai_parser.py` e rode de novo. Se a API recusar o modelo ou o `response_format` (erro `Unsupported model`/`invalid_request`), troque `AI_MODEL` no `.env` por um modelo que suporte Structured Outputs e registre qual em "Decisões técnicas". Cole o resumo (`acertos: N/M`) no corpo do PR.

```bash
cd ~/abby-cash/backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd ~/abby-cash && git add backend/pyproject.toml backend/uv.lock backend/app/core/text.py backend/app/ai backend/app/assistant \
  backend/app/domain/categories/models.py backend/app/domain/models.py backend/app/domain/privacy.py backend/scripts/run_eval.py \
  backend/migrations/versions/*_ai_usage_and_category_rules.py backend/tests/ai backend/tests/assistant \
  backend/tests/api/test_privacy_api.py
git commit -m "feat(ai): add OpenAI intent parser, shortcuts, learned category rules and eval set"
```

---

## Task 4 (T3.4): Orquestração da conversa (+ editar/apagar no domínio)

Três partes, um commit cada: **(A)** `update_transaction`/`delete_transaction` no domínio; **(B)** valor por extenso e pistas determinísticas; **(C)** a conversa (processador, fluxos, respostas, estado).

**Files:** Create `backend/app/assistant/{amounts,hints,models,state,turn,notify,replies}.py`, `backend/app/assistant/flows/{__init__,common,payment,launch,edit,query,pay,extras}.py`, `backend/tests/domain/test_transaction_edit.py`, `backend/tests/assistant/{test_amounts_hints,test_conversation,test_queries}.py`, `backend/tests/jobs/{__init__,test_worker}.py`, migração `*_conversation_state.py`. Modify `backend/app/domain/transactions/service.py`, `backend/app/assistant/processor.py` (substituído), `backend/app/worker.py`, `backend/app/domain/models.py`, `backend/app/domain/privacy.py`, `backend/tests/assistant/{fakes,conftest}.py`, `backend/tests/api/test_privacy_api.py`.

### Parte A — Editar e apagar lançamentos (domínio)

- [ ] **Step 1: Testes falhando**

`backend/tests/domain/test_transaction_edit.py`:
```python
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.domain.audit import AuditLog
from app.domain.bills.models import Bill
from app.domain.bills.service import create_bill
from app.domain.cards.models import Invoice
from app.domain.cards.service import invoice_total, register_card_purchase
from app.domain.errors import DomainError
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import (
    account_balance,
    create_transaction,
    delete_transaction,
    update_transaction,
)
from tests.factories import category_id, make_account, make_card, make_family, make_user

D = date(2026, 11, 10)


async def expense(session, user, space, acc, amount=10_000):
    return await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=D, description="x", account_id=acc.id,
    )  # fmt: skip


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Transaction))


async def test_update_changes_fields_and_balance(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    tx = await expense(session, ana, sp, acc)
    lazer = await category_id(session, sp, "Lazer")
    out = await update_transaction(
        session, actor_id=ana.id, tx_id=tx.id, amount_cents=25_000, category_id=lazer,
        description="cinema", merchant="Cine", occurred_on=date(2026, 11, 9),
    )  # fmt: skip
    assert (out.amount_cents, out.category_id, out.description, out.merchant) == (
        25_000, lazer, "cinema", "Cine",
    )  # fmt: skip
    assert out.occurred_on == date(2026, 11, 9)
    assert await account_balance(session, acc.id) == 75_000


async def test_update_validates_like_create(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    sp = ana.default_space_id
    tx = await expense(session, ana, sp, await make_account(session, sp))
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=0)
    foreign = await category_id(session, bia.default_space_id, "Lazer")
    with pytest.raises(DomainError, match="invalid_category"):
        await update_transaction(session, actor_id=ana.id, tx_id=tx.id, category_id=foreign)


async def test_payments_and_transfers_are_not_editable(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    bill = await create_bill(
        session, actor_id=ana.id, space_id=sp, description="Luz", amount_cents=5_000, due_on=D
    )
    paid = await pay_bill(session, actor_id=ana.id, bill_id=bill.id, account_id=acc.id, paid_on=D)
    with pytest.raises(DomainError, match="not_editable"):
        await update_transaction(session, actor_id=ana.id, tx_id=paid.id, amount_cents=1)


async def test_only_author_or_space_owner_may_edit_and_delete(session):
    husband, wife = await make_user(session, "h@x.com"), await make_user(session, "w@x.com")
    outsider = await make_user(session, "o@x.com")
    fam = await make_family(session, husband, wife)
    acc = await make_account(session, fam.id)
    by_husband = await expense(session, husband, fam.id, acc)
    by_wife = await expense(session, wife, fam.id, acc)
    with pytest.raises(HTTPException) as e:  # membro comum não mexe no lançamento dos outros
        await update_transaction(session, actor_id=wife.id, tx_id=by_husband.id, amount_cents=1)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await delete_transaction(session, actor_id=wife.id, tx_id=by_husband.id)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:  # quem não é do espaço nem descobre que existe
        await delete_transaction(session, actor_id=outsider.id, tx_id=by_wife.id)
    assert e.value.status_code == 404
    out = await update_transaction(session, actor_id=husband.id, tx_id=by_wife.id, amount_cents=7)
    assert out.amount_cents == 7  # dono do espaço pode
    await delete_transaction(session, actor_id=wife.id, tx_id=by_wife.id)  # autora pode
    assert await count(session) == 1


async def test_update_card_purchase_amount_resyncs_invoice_bill(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)  # fecha dia 10, vence dia 20
    [tx] = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=10_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=15_000)
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == tx.invoice_id))
    assert bill is not None and bill.amount_cents == 15_000
    assert await invoice_total(session, tx.invoice_id) == 15_000
    with pytest.raises(DomainError, match="card_date_not_editable"):
        await update_transaction(
            session, actor_id=ana.id, tx_id=tx.id, occurred_on=date(2026, 11, 20)
        )


async def test_installment_group_edit_rules(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)
    txs = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 11, 5), installments=3,
    )  # fmt: skip
    with pytest.raises(DomainError, match="installment_group_not_editable"):
        await update_transaction(session, actor_id=ana.id, tx_id=txs[0].id, amount_cents=1)
    lazer = await category_id(session, sp, "Lazer")
    await update_transaction(session, actor_id=ana.id, tx_id=txs[0].id, category_id=lazer)
    cats = list(await session.scalars(select(Transaction.category_id)))
    assert cats == [lazer] * 3  # categoria vale para o grupo inteiro


async def test_delete_restores_balance(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    tx = await expense(session, ana, sp, acc, 30_000)
    assert await account_balance(session, acc.id) == 70_000
    deleted = await delete_transaction(session, actor_id=ana.id, tx_id=tx.id)
    assert [d.id for d in deleted] == [tx.id] and deleted[0].amount_cents == 30_000
    assert await account_balance(session, acc.id) == 100_000


async def test_delete_installment_group_removes_all_and_resyncs_invoices(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)
    txs = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 11, 5), installments=3,
    )  # fmt: skip
    deleted = await delete_transaction(session, actor_id=ana.id, tx_id=txs[1].id)
    assert len(deleted) == 3 and await count(session) == 0
    bills = list(await session.scalars(select(Bill).where(Bill.kind == "invoice")))
    assert len(bills) == 3 and [b.amount_cents for b in bills] == [0, 0, 0]
    assert await session.scalar(select(func.count()).select_from(Invoice)) == 3  # faturas ficam


async def test_delete_invoice_payment_reopens_the_bill(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    card = await make_card(session, ana, sp)
    [buy] = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=10_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    paid = await pay_invoice(
        session, actor_id=ana.id, invoice_id=buy.invoice_id, account_id=acc.id, paid_on=D,
        amount_cents=10_000,
    )  # fmt: skip
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == buy.invoice_id))
    assert bill.status == "paid"
    await delete_transaction(session, actor_id=ana.id, tx_id=paid.id)
    await session.refresh(bill)
    assert bill.status == "open" and await account_balance(session, acc.id) == 100_000


async def test_delete_bill_payment_reopens_the_bill(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    bill = await create_bill(
        session, actor_id=ana.id, space_id=sp, description="Luz", amount_cents=5_000, due_on=D
    )
    paid = await pay_bill(session, actor_id=ana.id, bill_id=bill.id, account_id=acc.id, paid_on=D)
    await session.refresh(bill)
    assert bill.status == "paid"
    await delete_transaction(session, actor_id=ana.id, tx_id=paid.id)
    await session.refresh(bill)
    assert bill.status == "open"


async def test_edit_and_delete_are_audited(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    tx = await expense(session, ana, sp, await make_account(session, sp))
    await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=5_000)
    await delete_transaction(session, actor_id=ana.id, tx_id=tx.id)
    actions = list(
        await session.scalars(select(AuditLog.action).where(AuditLog.entity == "transaction"))
    )
    assert {"transaction.create", "transaction.update", "transaction.delete"} <= set(actions)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd ~/abby-cash/backend && uv run pytest tests/domain/test_transaction_edit.py -q` → **FAIL** (`ImportError: cannot import name 'delete_transaction' from 'app.domain.transactions.service'`).

- [ ] **Step 3: Implementar**

Em `backend/app/domain/transactions/service.py`: acrescente `from fastapi import HTTPException` junto dos imports de terceiros (antes de `from sqlalchemy import or_, select`) e **acrescente ao final do arquivo**:
`backend/app/domain/transactions/service.py` (acrescentar ao final):
```python
async def _target(session: AsyncSession, actor_id: UUID, tx_id: UUID) -> Transaction:
    """Lançamento que o autor pode alterar: ele mesmo é o autor ou é dono do espaço."""
    tx = await session.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="not_found")
    member = await require_member(session, actor_id, tx.space_id)  # não membro = 404
    if tx.created_by != actor_id and member.role != "owner":
        raise HTTPException(status_code=403, detail="edit_forbidden")
    await session.refresh(tx, with_for_update=True)
    return tx


async def _group(session: AsyncSession, tx: Transaction) -> list[Transaction]:
    if tx.installment_group_id is None:
        return [tx]
    rows = await session.scalars(
        select(Transaction)
        .where(Transaction.installment_group_id == tx.installment_group_id)
        .order_by(Transaction.installment_number)
    )
    return list(rows)


async def update_transaction(
    session: AsyncSession, *, actor_id: UUID, tx_id: UUID, amount_cents: int | None = None,
    description: str | None = None, merchant: str | None = None,
    category_id: UUID | None = None, occurred_on: date | None = None,
) -> Transaction:  # fmt: skip
    """Corrige um lançamento (None = não muda). Só despesa/receita: pagamentos e aportes têm
    fluxo próprio. Compra parcelada: só categoria/descrição/estabelecimento, no grupo todo."""
    from app.domain.cards.models import Invoice
    from app.domain.cards.service import sync_invoice_bill

    tx = await _target(session, actor_id, tx_id)
    if tx.type == "transfer" or tx.bill_id is not None or tx.goal_id is not None:
        raise DomainError("not_editable")
    if tx.installment_group_id is not None and (amount_cents is not None or occurred_on):
        raise DomainError("installment_group_not_editable")
    if tx.card_id is not None and occurred_on is not None:
        raise DomainError("card_date_not_editable")  # mudaria a fatura: apague e lance de novo
    await check_common(
        session, actor_id=actor_id, space_id=tx.space_id, type=tx.type,
        amount_cents=tx.amount_cents if amount_cents is None else amount_cents,
        category_id=tx.category_id if category_id is None else category_id,
        occurred_on=occurred_on or tx.occurred_on,
    )  # fmt: skip
    before = {"amount_cents": tx.amount_cents, "category_id": str(tx.category_id)}
    for t in await _group(session, tx):
        if amount_cents is not None:
            t.amount_cents = amount_cents
        if description is not None:
            t.description = description
        if merchant is not None:
            t.merchant = merchant
        if category_id is not None:
            t.category_id = category_id
        if occurred_on is not None:
            t.occurred_on = occurred_on
    await session.flush()
    if tx.invoice_id is not None and amount_cents is not None:
        invoice = await session.get(Invoice, tx.invoice_id)
        assert invoice is not None
        await sync_invoice_bill(session, invoice)  # conta espelho = total da fatura
    audit(
        session, actor_id, "transaction.update", "transaction", tx.id,
        {"space_id": str(tx.space_id), "before": before,
         "after": {"amount_cents": tx.amount_cents, "category_id": str(tx.category_id)}},
    )  # fmt: skip
    await session.commit()
    return tx


async def delete_transaction(
    session: AsyncSession, *, actor_id: UUID, tx_id: UUID
) -> list[Transaction]:
    """Apaga o lançamento (compra parcelada: o grupo inteiro) e reajusta fatura/conta a pagar.
    Devolve os lançamentos apagados (já desanexados) para a resposta ao usuário."""
    from app.domain.bills.models import Bill
    from app.domain.bills.status import refresh_status
    from app.domain.cards.models import Invoice
    from app.domain.cards.service import sync_invoice_bill

    tx = await _target(session, actor_id, tx_id)
    victims = await _group(session, tx)
    invoice_ids = {t.invoice_id for t in victims if t.invoice_id is not None}
    bill_ids = {t.bill_id for t in victims if t.bill_id is not None and t.invoice_id is None}
    for t in victims:
        await session.delete(t)
    await session.flush()
    for invoice_id in invoice_ids:  # compra apagada ou pagamento desfeito: total e status
        invoice = await session.get(Invoice, invoice_id)
        if invoice is not None:
            await sync_invoice_bill(session, invoice)
    for bill_id in bill_ids:  # pagamento de conta a pagar desfeito: reabre
        bill = await session.get(Bill, bill_id, with_for_update=True)
        if bill is not None:
            await refresh_status(session, bill)
    audit(
        session, actor_id, "transaction.delete", "transaction", tx.id,
        {"space_id": str(tx.space_id), "count": len(victims),
         "amount_cents": sum(t.amount_cents for t in victims)},
    )  # fmt: skip
    await session.commit()
    return victims
```

Regras que os testes fixam: não membro = 404; membro que não é autor nem dono = 403; `update` só em despesa/receita sem `bill_id`/`goal_id` (`not_editable`); parcelado só categoria/descrição/estabelecimento (`installment_group_not_editable`); data de compra no cartão (`card_date_not_editable`); `delete` apaga o grupo parcelado e reajusta a conta espelho da fatura (`sync_invoice_bill`, que também recalcula o status) e reabre a conta a pagar (`refresh_status`); tudo auditado.

- [ ] **Step 4: Rodar, qualidade e commit**

```bash
cd ~/abby-cash/backend && uv run ruff format . && uv run ruff check --fix . && uv run mypy app && uv run pytest tests/domain -q
cd ~/abby-cash && git add backend/app/domain/transactions/service.py backend/tests/domain/test_transaction_edit.py
git commit -m "feat(transactions): add update and delete services with permission and resync rules"
```

### Parte B — Valor por extenso e pistas determinísticas

- [ ] **Step 5: Testes falhando**

Cobrem os formatos de valor do "Foco de revisão" 3 ("1.234,56", "1234.56", "R$45", "45 reais", "45,5", "mil e duzentos", zero/negativo), datas relativas e a concordância das pistas com **todos** os casos do conjunto de avaliação.
`backend/tests/assistant/test_amounts_hints.py`:
```python
from datetime import date

import pytest

from app.assistant.amounts import extract_amount, parse_amount_words, parse_bare_amount
from app.assistant.hints import extract_hints, resolve_date
from tests.assistant.evalset import load_cases

TODAY = date(2026, 11, 25)  # quarta-feira


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("mil e duzentos", 120_000), ("quarenta e cinco", 4_500), ("dois mil", 200_000),
        ("cento e vinte reais", 12_000), ("tres mil e quinhentos", 350_000), ("cem", 10_000),
        ("quarenta e cinco reais e cinquenta centavos", 4_550), ("vinte contos", 2_000),
        ("dois mil e trezentos e cinquenta", 235_000), ("um real", 100),
        ("comprei uma pizza de quarenta", 4_000), ("nada de valor aqui", None), ("zero", None),
    ],
)  # fmt: skip
def test_parse_amount_words(text, cents):
    assert parse_amount_words(text) == cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("gastei 45 no mercado", 4_500), ("R$ 1.234,56", 123_456), ("1234.56", 123_456),
        ("R$45", 4_500), ("45 reais", 4_500), ("45,5", 4_550), ("2 mil", 200_000),
        ("2,5 mil", 250_000), ("gastei mil e duzentos", 120_000), ("gastei 30 dia 15", 3_000),
        ("mercado em 3x 90", 9_000), ("25 de dezembro gastei 10", 1_000),
        ("#pessoal pizza 50", 5_000), ("uber 23/11 18", 1_800),
        ("gastei 0", None), ("sem valor", None),
    ],
)  # fmt: skip
def test_extract_amount_formats(text, cents):
    assert extract_amount(text) == cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("45", 4_500), ("R$ 45,50", 4_550), ("quarenta e cinco reais", 4_500),
        ("mil e duzentos", 120_000), ("gastei 30 uber", None), ("30 uber", None), ("0", None),
        ("-10", None), ("saldo", None),
    ],
)  # fmt: skip
def test_parse_bare_amount_only_accepts_a_lone_value(text, cents):
    assert parse_bare_amount(text) == cents


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("ifood 67 ontem", date(2026, 11, 24)), ("anteontem 30", date(2026, 11, 23)),
        ("hoje 10", date(2026, 11, 25)), ("sexta 50", date(2026, 11, 20)),
        ("quarta 20", date(2026, 11, 18)), ("segunda-feira 10", date(2026, 11, 23)),
        ("sábado fui", date(2026, 11, 21)), ("dia 15 luz", date(2026, 11, 15)),
        ("dia 28 luz", date(2026, 10, 28)), ("23/11 uber", date(2026, 11, 23)),
        ("5 de outubro", date(2026, 10, 5)), ("dia 25 de dezembro", date(2025, 12, 25)),
        ("1 de março", date(2026, 3, 1)), ("31/12 x", date(2025, 12, 31)),
        ("1/2/25 x", date(2025, 2, 1)), ("sem data", None),
    ],
)  # fmt: skip
def test_resolve_date(text, want):
    assert resolve_date(text, TODAY) == want


def test_hints_installments_tags_and_total():
    h = extract_hints("tv 3x de 500", TODAY)
    assert (h.installments, h.amount_cents) == (3, 150_000)  # 3x de 500 = total 1.500
    h = extract_hints("tv 600 em 3x", TODAY)
    assert (h.installments, h.amount_cents) == (3, 60_000)
    h = extract_hints("tv 1200 em 10 vezes", TODAY)
    assert (h.installments, h.amount_cents) == (10, 120_000)
    assert extract_hints("paguei dia 10 a luz 180", TODAY).installments is None
    assert extract_hints("#Pessoal pizza 50", TODAY).private is True
    assert extract_hints("#família mercado 30", TODAY).family is True
    assert extract_hints("mercado 30", TODAY) == extract_hints("mercado 30", TODAY)
    assert extract_hints("mercado 30", TODAY).private is False


def test_hints_agree_with_every_eval_case():
    """A camada determinística nunca contradiz o esperado do conjunto de avaliação."""
    today, cases = load_cases()
    for case in cases:
        expect, h = case["expect"], extract_hints(case["text"], today)
        if h.amount_cents is not None and "amount_cents" in expect:
            assert h.amount_cents == expect["amount_cents"], case["text"]
        if h.installments is not None:
            assert h.installments == expect.get("installments"), case["text"]
        if h.private:
            assert expect.get("private") is True, case["text"]
        if expect.get("private"):
            assert h.private, case["text"]
        if h.occurred_on and "occurred_on" in expect and expect["intent"] != "nova_conta_a_pagar":
            assert h.occurred_on.isoformat() == expect["occurred_on"], case["text"]
        if "amount_cents" in expect and expect["intent"] not in ("consultar_gastos",):
            assert h.amount_cents == expect["amount_cents"], case["text"]  # extrai todos os valores
```

Run: `cd ~/abby-cash/backend && uv run pytest tests/assistant/test_amounts_hints.py -q` → **FAIL** (`ModuleNotFoundError: No module named 'app.assistant.amounts'`).

- [ ] **Step 6: Implementar**

`backend/app/assistant/amounts.py`:
```python
import re

from app.core.money import parse_brl
from app.core.text import fold

_MAX = 10**11  # R$ 1 bi: o mesmo teto de parse_brl
_UNITS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "quatorze": 14, "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
    "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40,
    "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
    "cem": 100, "cento": 100, "duzentos": 200, "trezentos": 300, "quatrocentos": 400,
    "quinhentos": 500, "seiscentos": 600, "setecentos": 700, "oitocentos": 800,
    "novecentos": 900,
}  # fmt: skip
_REAIS = {"real", "reais", "conto", "contos", "pila", "pilas"}
_CENTS = {"centavo", "centavos"}


def parse_amount_words(text: str) -> int | None:
    """Primeiro valor por extenso, em centavos: "mil e duzentos" -> 120000, "dois mil" -> 200000,
    "quarenta e cinco reais e cinquenta centavos" -> 4550. None se não houver."""
    toks = re.findall(r"[a-z]+", fold(text))
    n, i = len(toks), 0
    while i < n:
        if toks[i] not in _UNITS and toks[i] != "mil":
            i += 1
            continue
        total = cur = 0
        j = i
        while j < n:
            t = toks[j]
            if t in _UNITS:
                cur += _UNITS[t]
            elif t == "mil":
                total += (cur or 1) * 1000
                cur = 0
            elif not (t == "e" and j + 1 < n and (toks[j + 1] in _UNITS or toks[j + 1] == "mil")):
                break
            j += 1
        value = total + cur
        nxt = toks[j] if j < n else ""
        if nxt in _REAIS:
            cents, k = 0, j + 1
            if k + 1 < n and toks[k] == "e" and toks[k + 1] in _UNITS:
                k, c = k + 1, 0
                while k < n and toks[k] in _UNITS:
                    c, k = c + _UNITS[toks[k]], k + 1
                cents = c if k < n and toks[k] in _CENTS else 0
            result = value * 100 + cents
        elif value == 1:  # "uma pizza": artigo, não valor
            i = j
            continue
        else:
            result = value * 100
        return result if 0 < result <= _MAX else None
    return None


_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
MONTH_WORDS = (
    "janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
)
_NOISE = re.compile(
    rf"#\w+|\bdia\s+\d{{1,2}}\b|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b|\b\d{{1,2}}\s+de\s+(?:{MONTH_WORDS})\b"
)
_INSTALL_X = re.compile(r"\b\d{1,2}\s*x\b")
_INSTALL_V = re.compile(r"\b\d{1,2}\s*(?:vezes|parcelas)\b")
_THOUSAND = re.compile(rf"(?:r\$\s*)?({_NUM})\s*mil\b")
_MONEY = re.compile(rf"(?:r\$\s*)?({_NUM})")
_CURRENCY = re.compile(r"r\$|\b(?:reais|real|conto|contos)\b")


def extract_amount(text: str) -> int | None:
    """Primeiro valor monetário da mensagem (dígitos ou por extenso), em centavos. Ignora tags
    (#pessoal), datas ("dia 10", "23/11") e parcelas ("3x", "em 10 vezes")."""
    s = _INSTALL_V.sub(" ", _INSTALL_X.sub(" ", _NOISE.sub(" ", fold(text))))
    if (m := _THOUSAND.search(s)) and (base := parse_brl(m.group(1))):
        return base * 1000
    if m := _MONEY.search(s):
        return parse_brl(m.group(1))
    return parse_amount_words(s)


def parse_bare_amount(text: str) -> int | None:
    """Resposta que é SÓ um valor ("45", "R$ 45,50", "quarenta e cinco reais"); qualquer outra
    palavra -> None (a pessoa mudou de assunto)."""
    s = _CURRENCY.sub(" ", fold(text)).strip()
    if re.fullmatch(r"[\d.,\s]+", s):
        return parse_brl(s.replace(" ", ""))
    words = re.findall(r"[a-z]+", s)
    if words and all(w in _UNITS or w in {"mil", "e"} for w in words):
        return parse_amount_words(s)
    return None
```
`backend/app/assistant/hints.py`:
```python
import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.assistant.amounts import MONTH_WORDS, extract_amount
from app.core.dates import clamp_day
from app.core.money import parse_brl
from app.core.text import fold

_WEEKDAYS = {
    "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6,
}  # fmt: skip
_RELATIVE = {"anteontem": 2, "ontem": 1, "hoje": 0}
_DAY_MONTH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_DAY = re.compile(r"\bdia\s+(\d{1,2})\b")
_DAY_OF_MONTH = re.compile(rf"\b(\d{{1,2}})\s+de\s+({MONTH_WORDS})\b")
_MONTH_NUMBER = {m: i for i, m in enumerate(MONTH_WORDS.split("|"), 1)}
_X_DE = re.compile(r"\b(\d{1,2})\s*x\s*de\s*(?:r\$\s*)?(\d[\d.,]*)")
_X = re.compile(r"\b(\d{1,2})\s*x\b|\b(\d{1,2})\s*(?:vezes|parcelas)\b")


@dataclass(frozen=True)
class Hints:
    """O que dá para tirar da mensagem sem IA. Etiquetas, data e parcelas são determinísticas
    (valem mais que o LLM); o valor só preenche o que o LLM deixou vazio."""

    amount_cents: int | None
    occurred_on: date | None
    installments: int | None
    private: bool  # #pessoal
    family: bool  # #familia


def resolve_date(text: str, today: date) -> date | None:
    """ "hoje", "ontem", "anteontem", "sexta" (a última), "dia 15", "23/11"; None se não houver."""
    s = fold(text)
    for word, back in _RELATIVE.items():
        if re.search(rf"\b{word}\b", s):
            return today - timedelta(days=back)
    if m := _DAY_MONTH.search(s):
        day, month = int(m.group(1)), int(m.group(2))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return None
        if m.group(3):
            year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
            return clamp_day(year, month, day)
        found = clamp_day(today.year, month, day)
        return found if found <= today else clamp_day(today.year - 1, month, day)
    if m := _DAY_OF_MONTH.search(s):  # "5 de outubro", "dia 25 de dezembro"
        day, month = int(m.group(1)), _MONTH_NUMBER[m.group(2)]
        if not 1 <= day <= 31:
            return None
        found = clamp_day(today.year, month, day)
        return found if found <= today else clamp_day(today.year - 1, month, day)
    for word, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{word}(?:-feira)?\b", s):
            return today - timedelta(days=(today.weekday() - weekday) % 7 or 7)
    if m := _DAY.search(s):
        day = int(m.group(1))
        if not 1 <= day <= 31:
            return None
        this_month = clamp_day(today.year, today.month, day)
        if this_month <= today:
            return this_month
        last = today.replace(day=1) - timedelta(days=1)
        return clamp_day(last.year, last.month, day)
    return None


def extract_hints(text: str, today: date) -> Hints:
    s = fold(text)
    amount = extract_amount(text)
    installments: int | None = None
    plain = _DAY_OF_MONTH.sub(" ", _DAY_MONTH.sub(" ", _DAY.sub(" ", s)))  # datas não são parcelas
    if m := _X_DE.search(plain):  # "3x de 500": o valor informado é por parcela
        n, each = int(m.group(1)), parse_brl(m.group(2))
        if each and 2 <= n <= 48:
            installments, amount = n, n * each
    elif m := _X.search(plain):
        n = int(m.group(1) or m.group(2))
        installments = n if 2 <= n <= 48 else None
    return Hints(
        amount_cents=amount,
        occurred_on=resolve_date(text, today),
        installments=installments,
        private="#pessoal" in s,
        family="#familia" in s,
    )
```

- [ ] **Step 7: Rodar e commit**

```bash
cd ~/abby-cash/backend && uv run ruff format . && uv run ruff check --fix . && uv run mypy app && uv run pytest tests/assistant/test_amounts_hints.py -q
cd ~/abby-cash && git add backend/app/assistant/amounts.py backend/app/assistant/hints.py backend/tests/assistant/test_amounts_hints.py
git commit -m "feat(assistant): add amount-in-words parser and deterministic message hints"
```

### Parte C — A conversa

- [ ] **Step 8: Testes falhando**

Substitua `fakes.py` e `conftest.py` pelas versões finais (o `FakeAdapter` agora também faz `parse_webhook` de verdade; o `FakeParser` ganha `add`; `Chat.say` entrega a mensagem ao worker e devolve a resposta):
`backend/tests/assistant/fakes.py`:
```python
from typing import Any

from starlette.requests import Request

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.channels.base import InboundMessage
from app.channels.telegram import TelegramAdapter


class FakeAdapter:
    """Canal falso: guarda o que seria enviado ao usuário."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (external_user_id, texto)

    def verify(self, request: Request) -> bool:
        return True

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        parsed = TelegramAdapter("T", "s").parse_update(await request.json())
        return [parsed] if parsed else []

    async def send_text(self, external_user_id: str, text: str) -> None:
        self.sent.append((external_user_id, text))

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        return b"", "application/octet-stream"


class FakeParser:
    """Interpretador falso: devolve os resultados na ordem (ou levanta, se for uma exceção)."""

    def __init__(self, *results: "ParsedIntent | Exception") -> None:
        self._results = list(results)
        self.calls: list[tuple[str, SpaceContext]] = []

    def add(self, *results: "ParsedIntent | Exception") -> None:
        self._results.extend(results)

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent:
        self.calls.append((text, ctx))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def expense(amount: int | None, **fields: Any) -> ParsedIntent:
    return ParsedIntent.of("lancar_despesa", amount_cents=amount, **fields)
```
`backend/tests/assistant/conftest.py`:
```python
import pytest

from app.channels import registry
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import FakeAdapter, FakeParser
from tests.factories import TS, make_inbound, make_link, make_user


@pytest.fixture
def adapter(monkeypatch) -> FakeAdapter:
    fake = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "telegram", fake)
    return fake


@pytest.fixture
def parser() -> FakeParser:
    return FakeParser()


class Chat:
    """Uma pessoa conversando com o bot: `say` entrega a mensagem ao worker e devolve a resposta."""

    def __init__(self, session, user, adapter, parser, ext) -> None:
        self.session, self.user, self.adapter, self.parser, self.ext = (
            session, user, adapter, parser, ext,
        )  # fmt: skip
        self.n = 0

    async def say(self, text: str, *, ts=TS, media_kind: str | None = None) -> str:
        self.n += 1
        iid = await make_inbound(
            self.session, text, ext=self.ext, msg_id=self.n, ts=ts, media_kind=media_kind
        )
        before = len(self.adapter.sent)
        await process_inbound({"parser": self.parser}, str(iid))
        return "\n".join(t for e, t in self.adapter.sent[before:] if e == self.ext)


@pytest.fixture
def new_chat(session, adapter, parser):
    async def make(email: str = "ana@x.com", ext: str = "111") -> Chat:
        user = await make_user(session, email)
        await make_link(session, user, ext)
        return Chat(session, user, adapter, parser, ext)

    return make


@pytest.fixture
async def ana(new_chat) -> Chat:
    return await new_chat()
```

Os testes de conversa cobrem os obrigatórios do plano mestre (`test_expense_message_creates_tx_and_confirms`, `test_private_tag_goes_to_personal_space`, `test_missing_amount_asks_and_resumes`, `test_correction_learns_rule`, `test_llm_failure_fallback`, `test_parcelado_reply_mentions_future_budgets`, `test_zero_amount_rejected`, e `test_duplicate_webhook_creates_single_transaction`, que veio da T3.2) e mais: formatos de resposta exatos, `#familia` perguntando a conta e retomando, resposta que é outro comando, expiração de 30 min, confiança baixa, cancelar, apagar só o próprio último (e o grupo parcelado), alerta de teto + aviso aos outros membros, erros de domínio educados, data futura, mídia, atalhos sem LLM, `paguei` (0/1/várias), aporte em meta e conta a pagar.
`backend/tests/assistant/test_conversation.py`:
```python
import asyncio
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.api import webhooks
from app.assistant.intents import ParsedIntent
from app.assistant.replies import CORRECT_PROMPT, MEDIA, NOT_UNDERSTOOD
from app.domain.accounts.service import set_default_account
from app.domain.bills.models import Bill
from app.domain.bills.service import create_bill
from app.domain.budgets.service import set_budget
from app.domain.categories.models import CategoryRule
from app.domain.channels.models import InboundMessage
from app.domain.goals.service import create_goal
from app.domain.transactions.models import Transaction
from app.domain.users.models import User
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import expense
from tests.factories import (
    TS,
    category_id,
    make_account,
    make_card,
    make_family,
    make_link,
    make_user,
)

CONFIRM_TAIL = '\nResponda "corrigir" se errei.'


async def txs(session) -> list[Transaction]:
    q = (
        select(Transaction)
        .order_by(Transaction.created_at)
        .execution_options(populate_existing=True)
    )
    return list(await session.scalars(q))


async def nubank_default(session, user) -> None:
    acc = await make_account(session, user.default_space_id, name="Nubank")
    await set_default_account(
        session, actor_id=user.id, space_id=user.default_space_id, account_id=acc.id
    )


async def test_expense_message_creates_tx_and_confirms(ana, parser, session):
    await nubank_default(session, ana.user)
    parser.add(expense(4500, category_name="Alimentação", merchant="Mercado"))
    reply = await ana.say("gastei 45 no mercado")
    assert reply == "✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank" + CONFIRM_TAIL
    [tx] = await txs(session)
    assert (tx.amount_cents, tx.type, tx.origin, tx.source_message_id) == (
        4500, "expense", "telegram", "111:1",
    )  # fmt: skip
    assert (tx.created_by, tx.space_id) == (ana.user.id, ana.user.default_space_id)
    assert tx.occurred_on == date(2026, 11, 25)
    text, ctx = parser.calls[0]
    assert text == "gastei 45 no mercado" and ctx.today == date(2026, 11, 25)


async def test_date_hint_account_hint_and_income(ana, parser, session):
    await nubank_default(session, ana.user)
    parser.add(
        expense(6700, category_name="Alimentação", merchant="iFood", account_hint="dinheiro")
    )
    reply = await ana.say("ifood 67 ontem no dinheiro")
    assert reply.startswith("✅ R$ 67,00 · Alimentação · iFood · ontem · Carteira")
    parser.add(
        ParsedIntent.of(
            "lancar_receita", amount_cents=300_000, category_name="Salário", account_hint="nubank"
        )
    )
    reply = await ana.say("recebi 3000 de salário no nubank")
    assert reply.startswith("✅ R$ 3.000,00 · Salário · hoje · Conta Nubank")
    first, second = await txs(session)
    assert first.occurred_on == date(2026, 11, 24) and second.type == "income"


async def test_private_tag_goes_to_personal_space(ana, parser, session):
    fam = await make_family(session, ana.user)
    ana.user.default_space_id = fam.id
    await session.merge(ana.user)
    await session.commit()
    parser.add(expense(15_000, category_name="Compras", description="presente"))
    reply = await ana.say("#pessoal presente 150")
    [tx] = await txs(session)
    personal = await session.scalar(select(User.default_space_id).where(User.id == ana.user.id))
    assert tx.space_id != fam.id and tx.space_id is not None
    assert "🔒 pessoal" in reply and "Carteira" in reply
    assert parser.calls[0][1].space_id == tx.space_id  # o contexto da IA também é o pessoal
    assert personal == fam.id  # o padrão continua sendo a família


async def test_family_tag_asks_account_then_resumes(ana, parser, session):
    fam = await make_family(session, ana.user)
    await make_account(session, fam.id, name="Casa")
    parser.add(expense(32_000, category_name="Mercado"))
    reply = await ana.say("#familia mercado 320")
    assert reply.startswith("Em qual conta foi? Responda com o número:")
    assert "1) Carteira" in reply and "2) Conta Casa" in reply
    reply = await ana.say("2")
    assert reply.startswith("✅ R$ 320,00 · Mercado · hoje · Conta Casa")
    [tx] = await txs(session)
    assert tx.space_id == fam.id and len(parser.calls) == 1  # a resposta não passou pela IA


async def test_missing_amount_asks_and_resumes(ana, parser, session):
    parser.add(expense(None, category_name="Mercado", merchant="Mercado"))
    reply = await ana.say("fui no mercado")
    assert reply == "Quanto foi? (ex.: 45 ou 45,50)"
    assert await txs(session) == []
    reply = await ana.say("45,50")
    assert reply.startswith("✅ R$ 45,50 · Mercado · Mercado · hoje · Carteira")
    assert len(parser.calls) == 1


async def test_zero_amount_rejected(ana, parser, session):
    parser.add(expense(0, merchant="Mercado"))
    reply = await ana.say("gastei 0 no mercado")
    assert reply.startswith("O valor precisa ser maior que zero.")
    assert await txs(session) == []
    assert (await ana.say("0")).startswith("O valor precisa ser maior que zero.")
    assert (await ana.say("-10")).startswith("O valor precisa ser maior que zero.")
    assert (await ana.say("12")).startswith("✅ R$ 12,00")  # a pergunta seguia de pé


async def test_answer_that_is_a_new_command_is_not_taken_as_the_amount(ana, parser, session):
    parser.add(expense(None, merchant="Mercado"))
    await ana.say("fui no mercado")
    parser.add(expense(3000, merchant="Uber", category_name="Transporte"))
    reply = await ana.say("gastei 30 de uber")  # outra mensagem, não "30" do mercado
    assert reply.startswith("✅ R$ 30,00 · Transporte · Uber")
    [tx] = await txs(session)
    assert tx.merchant == "Uber"


async def test_state_expires_after_30_minutes(ana, parser, session):
    parser.add(expense(None, merchant="Mercado"))
    await ana.say("fui no mercado")
    reply = await ana.say("45", ts=TS + timedelta(minutes=31))
    assert reply == NOT_UNDERSTOOD and await txs(session) == []


async def test_low_confidence_asks_to_confirm(ana, parser, session):
    parser.add(expense(4500, merchant="Padaria", confidence=0.4))
    reply = await ana.say("acho que foi 45 na padaria")
    assert reply == 'Entendi R$ 45,00 em "Padaria". Posso lançar? (sim/não)'
    assert await txs(session) == []
    assert (await ana.say("sim")).startswith("✅ R$ 45,00")
    parser.add(expense(900, merchant="Bala", confidence=0.2))
    await ana.say("sei lá, uns 9 de bala")
    assert await ana.say("não") == "Ok, não lancei."
    assert len(await txs(session)) == 1


async def test_cancel_clears_pending_question(ana, parser, session):
    parser.add(expense(None))
    await ana.say("gastei no mercado")
    assert await ana.say("cancelar") == "Ok, cancelei."
    assert await ana.say("45") == NOT_UNDERSTOOD


async def test_correction_learns_rule(ana, parser, session):
    parser.add(expense(3000, category_name="Alimentação", merchant="Padaria Pão Quente 12"))
    await ana.say("gastei 30 na padaria pão quente 12")
    parser.add(ParsedIntent.of("corrigir", category_name="Mercado"))
    reply = await ana.say("era mercado")
    assert reply.startswith("✏️ Corrigi:\n✅ R$ 30,00 · Mercado · Padaria Pão Quente 12")
    mercado = await category_id(session, ana.user.default_space_id, "Mercado")
    rule = await session.scalar(select(CategoryRule))
    assert rule is not None and rule.merchant_norm == "padaria pao quente"
    assert rule.category_id == mercado
    # a regra vence a sugestão do LLM na próxima vez
    parser.add(expense(2000, category_name="Alimentação", merchant="padaria pão quente"))
    reply = await ana.say("20 na padaria pão quente")
    assert "· Mercado ·" in reply
    assert ("padaria pao quente", "Mercado") in parser.calls[-1][1].rules


async def test_correct_shortcut_asks_then_applies_value_and_unknown_category(ana, parser, session):
    parser.add(expense(4500, category_name="Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    assert await ana.say("corrigir") == CORRECT_PROMPT
    reply = await ana.say("valor 50")
    assert reply.startswith("✏️ Corrigi:\n✅ R$ 50,00 · Mercado")
    reply = await ana.say("corrigir")
    reply = await ana.say("categoria Inexistente")
    assert reply.startswith("Não achei a categoria Inexistente. Opções:")
    assert [t.amount_cents for t in await txs(session)] == [5000]


async def test_apagar_ultimo_deletes_only_my_chat_transaction(session, new_chat, parser):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    parser.add(expense(4500, merchant="Mercado", category_name="Mercado"))
    await ana.say("gastei 45 no mercado")
    assert (
        await bia.say("apagar último")
        == "Não achei nenhum lançamento seu feito pelo chat para apagar."
    )
    assert len(await txs(session)) == 1  # a da Ana continua
    reply = await ana.say("apagar último")
    assert reply == "🗑️ Apaguei: R$ 45,00 · Mercado · Mercado · hoje · Carteira"
    assert await txs(session) == []


async def test_apagar_installment_group_and_resync_invoice(ana, parser, session):
    sp = ana.user.default_space_id
    await make_card(session, ana.user, sp, name="Visa")
    parser.add(
        ParsedIntent.of(
            "lancar_parcelado",
            amount_cents=30_000,
            installments=3,
            card_hint="visa",
            merchant="TV",
            category_name="Compras",
        )
    )
    reply = await ana.say("tv 300 em 3x no visa")
    assert reply.startswith("✅ R$ 300,00 em 3x de R$ 100,00 · Compras · TV · hoje · Cartão Visa")
    assert len(await txs(session)) == 3
    reply = await ana.say("apagar último")
    assert reply.endswith("(3 parcelas)") and await txs(session) == []
    amounts = list(await session.scalars(select(Bill.amount_cents).where(Bill.kind == "invoice")))
    assert amounts == [0, 0, 0]


async def test_parcelado_reply_mentions_future_budgets(ana, parser, session):
    sp = ana.user.default_space_id
    await make_card(session, ana.user, sp, name="Visa", closing_day=10, due_day=20)
    for month in (date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)):
        await set_budget(
            session, actor_id=ana.user.id, space_id=sp, month=month, limit_cents=1_000_000
        )
    parser.add(
        ParsedIntent.of(
            "lancar_parcelado",
            amount_cents=60_000,
            installments=3,
            card_hint="visa",
            merchant="TV",
            category_name="Compras",
        )
    )
    reply = await ana.say("tv 600 em 3x no visa")
    assert "em 3x de R$ 200,00" in reply
    assert "Compromete R$ 200,00 dos tetos de dez, jan e fev." in reply
    assert [t.installment_number for t in await txs(session)] == [1, 2, 3]


async def test_threshold_alert_is_appended_and_other_member_notified(
    session, new_chat, parser, adapter
):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    fam = await make_family(session, ana.user, bia.user)
    acc = await make_account(session, fam.id, name="Casa")
    await set_default_account(session, actor_id=ana.user.id, space_id=fam.id, account_id=acc.id)
    await set_budget(
        session, actor_id=ana.user.id, space_id=fam.id, month=date(2026, 11, 1), limit_cents=10_000
    )
    parser.add(expense(8_500, category_name="Mercado"))
    reply = await ana.say("#familia mercado 85")
    alert = "⚠️ Você atingiu 80% do teto de novembro: R$ 85,00 de R$ 100,00."
    assert reply.endswith(alert)
    assert ("222", alert) in adapter.sent  # a Bia também é avisada
    assert ("111", alert) not in adapter.sent  # a Ana recebe junto da confirmação, uma vez só
    parser.add(expense(1_500, category_name="Mercado"))
    reply = await ana.say("#familia mercado 15")
    assert "⚠️ Você atingiu 100% do teto" in reply


async def test_domain_errors_become_polite_replies(ana, parser, session):
    await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    parser.add(
        ParsedIntent.of("lancar_parcelado", amount_cents=1000, installments=99, card_hint="visa")
    )
    assert await ana.say("tv 10 em 99 parcelas") == "Parcelas: de 2 a 48."
    assert await txs(session) == []


async def test_parcelado_without_a_card_explains(ana, parser):
    parser.add(ParsedIntent.of("lancar_parcelado", amount_cents=60_000, installments=3))
    reply = await ana.say("tv 600 em 3x")
    assert reply.startswith("Não achei nenhum cartão cadastrado.")


async def test_future_date_is_refused(ana, parser, session):
    parser.add(expense(1000, occurred_on=date(2026, 11, 26)))
    assert (await ana.say("gastei 10 amanhã")).startswith("Essa data é no futuro")
    assert await txs(session) == []


async def test_llm_failure_fallback(ana, parser, session):
    parser.add(RuntimeError("openai down"))
    reply = await ana.say("gastei 45 no mercado")
    assert reply.startswith("⚠️ A IA está indisponível agora; lancei do jeito simples")
    assert "✅ R$ 45,00 · Outros · no mercado · hoje · Carteira" in reply
    [tx] = await txs(session)
    assert tx.amount_cents == 4500 and tx.description == "no mercado"
    outros = await category_id(session, ana.user.default_space_id, "Outros")
    assert tx.category_id == outros
    parser.add(RuntimeError("openai down"))
    assert (await ana.say("bom dia")) == NOT_UNDERSTOOD  # sem valor não dá para adivinhar
    parser.add(TimeoutError())
    reply = await ana.say("recebi 3000 de salário")
    assert "✅ R$ 3.000,00 · Outros" in reply and (await txs(session))[-1].type == "income"


async def test_shortcuts_do_not_call_the_llm(ana, parser, session):
    assert (await ana.say("ajuda")).startswith("Eu lanço seus gastos pelo chat.")
    assert (await ana.say("saldo")).startswith("💰 Saldos:\n• Carteira: R$ 0,00")
    assert parser.calls == []


async def test_media_message_gets_polite_reply(ana, parser, session):
    assert await ana.say("", media_kind="audio") == MEDIA
    assert await ana.say("farmácia 87,40", media_kind="image") == MEDIA  # legenda não grava
    assert await txs(session) == [] and parser.calls == []


async def test_duplicate_webhook_creates_single_transaction(
    client, session, adapter, parser, monkeypatch
):
    ana = await make_user(session, "ana@x.com")
    await make_link(session, ana, "111")
    ids: list[UUID] = []

    async def record(inbound_id: UUID) -> None:
        ids.append(inbound_id)

    monkeypatch.setattr(webhooks, "enqueue_inbound", record)
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 10, "from": {"id": 111, "is_bot": False},
            "chat": {"id": 111, "type": "private"}, "date": 1795618800,
            "text": "gastei 45 no mercado",
        },
    }  # fmt: skip
    posts = [client.post("/webhooks/telegram", json=payload) for _ in range(6)]
    assert [r.status_code for r in await asyncio.gather(*posts)] == [
        200
    ] * 6  # reenvios simultâneos
    assert (await client.post("/webhooks/telegram", json=payload)).status_code == 200  # e depois
    assert len(ids) == 1
    parser.add(expense(4500, category_name="Mercado"))
    # mesmo que a fila entregue o mesmo job várias vezes, só uma execução grava
    await asyncio.gather(*[process_inbound({"parser": parser}, str(i)) for i in ids * 4])
    assert len(await txs(session)) == 1
    assert len(adapter.sent) == 1 and len(parser.calls) == 1
    row = await session.scalar(select(InboundMessage))
    assert row.status == "processed" and row.user_id == ana.id
    assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 1


async def test_unexpected_error_marks_row_failed_and_apologizes(ana, parser, session, monkeypatch):
    from app.assistant.flows import launch

    async def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(launch, "run", boom)
    parser.add(expense(4500))
    assert (await ana.say("gastei 45")).startswith("Tive um problema ao processar")
    row = await session.scalar(select(InboundMessage))
    assert row.status == "failed"


async def test_pay_one_pending_bill_from_default_account(ana, session, parser):
    sp = ana.user.default_space_id
    bill = await create_bill(
        session, actor_id=ana.user.id, space_id=sp, description="Luz", amount_cents=15_000,
        due_on=date(2026, 11, 30),
    )  # fmt: skip
    assert (await ana.say("paguei")).startswith("✅ Paguei R$ 150,00 · Luz · hoje · Carteira")
    await session.refresh(bill)
    assert bill.status == "paid" and parser.calls == []
    assert await ana.say("paguei") == "Não encontrei contas em aberto."
    reply = await ana.say("apagar último")  # desfaz o pagamento e reabre a conta
    assert reply.startswith("🗑️ Apaguei: R$ 150,00")
    await session.refresh(bill)
    assert bill.status == "open"


async def test_pay_many_lists_and_choose_second(ana, session, parser):
    sp = ana.user.default_space_id
    for name, day in (("Luz", 28), ("Internet", 30)):
        await create_bill(
            session, actor_id=ana.user.id, space_id=sp, description=name, amount_cents=10_000,
            due_on=date(2026, 11, day),
        )  # fmt: skip
    reply = await ana.say("paguei")
    assert reply.startswith("Qual conta você pagou? Responda com o número:\n1) Luz")
    assert "2) Internet · vence 30/11 · R$ 100,00" in reply
    assert (await ana.say("2")).startswith("✅ Paguei R$ 100,00 · Internet")
    status = {b.description: b.status for b in await session.scalars(select(Bill))}
    assert status == {"Luz": "open", "Internet": "paid"}


async def test_aporte_meta(ana, session, parser):
    sp = ana.user.default_space_id
    await create_goal(
        session, actor_id=ana.user.id, space_id=sp, name="Viagem", target_cents=500_000,
        created_on=date(2026, 11, 1),
    )  # fmt: skip
    parser.add(ParsedIntent.of("aporte_meta", amount_cents=50_000, goal_hint="viagem"))
    reply = await ana.say("guardei 500 na viagem")
    assert reply == (
        "✅ R$ 500,00 · Aporte na meta Viagem · hoje · Carteira\n"
        "Guardado: R$ 500,00 de R$ 5.000,00."
    )
    parser.add(ParsedIntent.of("aporte_meta", amount_cents=1_000, goal_hint="carro"))
    assert (await ana.say("guardei 10 no carro")).startswith("Qual meta? Suas metas: Viagem.")


async def test_nova_conta_a_pagar(ana, session, parser):
    parser.add(
        ParsedIntent.of(
            "nova_conta_a_pagar",
            amount_cents=12_000,
            description="Internet",
            occurred_on=date(2026, 12, 10),
        )
    )
    reply = await ana.say("conta de internet 120 vence dia 10")
    assert reply.startswith("📌 Anotei: Internet · R$ 120,00 · vence 10/12")
    bill = await session.scalar(select(Bill))
    assert (bill.amount_cents, bill.due_on, bill.status) == (12_000, date(2026, 12, 10), "open")
    parser.add(ParsedIntent.of("nova_conta_a_pagar", amount_cents=12_000, description="Luz"))
    assert (await ana.say("conta de luz 120")).startswith("Para anotar uma conta a pagar preciso")


async def test_unknown_goes_to_not_understood_and_help_lists_examples(ana, parser):
    parser.add(ParsedIntent.of("desconhecido"))
    assert await ana.say("qual a capital da França") == NOT_UNDERSTOOD
    assert "gastei 45 no mercado" in await ana.say("ajuda")
    assert (await ana.say("7")) == NOT_UNDERSTOOD  # número sem pergunta pendente


async def test_family_tag_without_family_space(ana, parser):
    parser.add(expense(1000))
    assert (await ana.say("#familia pão 10")).startswith("Você não tem um espaço familiar")
```

As consultas **não podem vazar** dados de outro espaço (foco de revisão 4):
`backend/tests/assistant/test_queries.py`:
```python
from datetime import date

from sqlalchemy import update

from app.assistant.intents import ParsedIntent
from app.domain.budgets.service import set_budget
from app.domain.cards.service import register_card_purchase
from app.domain.transactions.service import create_transaction
from app.domain.users.models import User
from tests.assistant.fakes import expense
from tests.factories import category_id, make_account, make_card, make_family

TODAY = date(2026, 11, 25)


async def spend(session, user, space, acc, amount, category, on=TODAY):
    return await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=on, category_id=await category_id(session, space, category),
        account_id=acc.id,
    )  # fmt: skip


async def test_gastos_by_period_and_category(ana, parser, session):
    sp = ana.user.default_space_id
    acc = await make_account(session, sp, name="Nubank")
    await spend(session, ana.user, sp, acc, 5_000, "Mercado")
    await spend(session, ana.user, sp, acc, 3_000, "Mercado", on=date(2026, 11, 24))
    await spend(session, ana.user, sp, acc, 2_000, "Lazer", on=date(2026, 11, 2))
    await spend(session, ana.user, sp, acc, 9_900, "Lazer", on=date(2026, 10, 30))
    assert await ana.say("gastos") == (  # atalho: sem IA
        "📊 Gastos em novembro: R$ 100,00 — Pessoal\n• Mercado: R$ 80,00\n• Lazer: R$ 20,00"
    )
    assert parser.calls == []
    parser.add(ParsedIntent.of("consultar_gastos", period="hoje", category_name="Mercado"))
    assert await ana.say("quanto gastei de mercado hoje") == "📊 Gastos hoje: R$ 50,00 — Pessoal"
    parser.add(ParsedIntent.of("consultar_gastos", period="mes_passado"))
    assert (await ana.say("e mês passado?")).startswith("📊 Gastos em outubro: R$ 99,00")
    parser.add(ParsedIntent.of("consultar_gastos", period="ontem"))
    assert (await ana.say("e ontem?")).startswith("📊 Gastos ontem: R$ 30,00")
    parser.add(ParsedIntent.of("consultar_gastos", period="hoje", category_name="Pets"))
    assert await ana.say("gastos com pets hoje") == "Nenhum gasto hoje — Pessoal."
    parser.add(ParsedIntent.of("consultar_gastos", period="hoje", category_name="Inexistente"))
    assert await ana.say("gastos com x") == "Não achei a categoria Inexistente."


async def test_gastos_never_include_spouse_personal_expenses(session, new_chat, parser):
    husband, wife = await new_chat("h@x.com", "111"), await new_chat("w@x.com", "222")
    fam = await make_family(session, husband.user, wife.user)
    fam_acc = await make_account(session, fam.id, name="Casa")
    wife_acc = await make_account(session, wife.user.default_space_id, name="Segredo da Bia")
    await spend(session, wife.user, fam.id, fam_acc, 10_000, "Mercado")
    await spend(session, wife.user, wife.user.default_space_id, wife_acc, 77_700, "Lazer")
    await session.execute(
        update(User).where(User.id == husband.user.id).values(default_space_id=fam.id)
    )
    await session.commit()
    reply = await husband.say("gastos")
    assert reply == "📊 Gastos em novembro: R$ 100,00 — Casa\n• Mercado: R$ 100,00"
    assert "777" not in reply and "Lazer" not in reply
    own = await husband.say("#pessoal gastos")  # o #pessoal do marido é o dele
    assert own == "Nenhum gasto em novembro — Pessoal."


async def test_saldo_only_own_spaces(session, new_chat):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    mine = await make_account(session, ana.user.default_space_id, name="Nubank", initial=12_345)
    await make_account(session, bia.user.default_space_id, name="Segredo da Bia", initial=999_999)
    reply = await ana.say("saldo")
    assert "Nubank: R$ 123,45" in reply and "Carteira: R$ 0,00" in reply
    assert "Segredo" not in reply and "9.999,99" not in reply
    assert reply.endswith("Total: R$ 123,45")
    assert mine.id is not None
    assert "Segredo da Bia: R$ 9.999,99" in await bia.say("saldo")


async def test_faturas_show_private_aggregate_but_never_the_details(session, new_chat, parser):
    husband, wife = await new_chat("h@x.com", "111"), await new_chat("w@x.com", "222")
    fam = await make_family(session, husband.user, wife.user)
    card = await make_card(session, husband.user, fam.id, name="Visa", closing_day=10, due_day=20)
    await register_card_purchase(
        session, actor_id=husband.user.id, space_id=fam.id, card_id=card.id, amount_cents=10_000,
        occurred_on=TODAY, description="Mercado da casa",
    )  # fmt: skip
    parser.add(
        expense(30_000, card_hint="visa", merchant="Presente surpresa", category_name="Compras")
    )
    reply = await wife.say("#pessoal presente surpresa 300 no visa")
    assert "Cartão Visa" in reply and "🔒 pessoal" in reply
    seen = await husband.say("faturas")
    assert (
        seen
        == "💳 Visa · vence 20/12: R$ 400,00 em aberto · inclui R$ 300,00 de lançamentos privados"
    )
    assert "Presente" not in seen
    assert await wife.say("fatura") == "💳 Visa · vence 20/12: R$ 400,00 em aberto"  # ela vê tudo


async def test_faturas_none_and_outsider_sees_nothing(session, new_chat):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    card = await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    await register_card_purchase(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, card_id=card.id,
        amount_cents=5_000, occurred_on=TODAY,
    )  # fmt: skip
    assert await bia.say("faturas") == "Nenhuma fatura em aberto."
    assert "R$ 50,00 em aberto" in await ana.say("faturas")


async def test_teto_overview_and_missing_budget(ana, parser, session):
    sp = ana.user.default_space_id
    assert await ana.say("teto") == (
        "Você ainda não definiu um teto para novembro. Defina no painel web."
    )
    mercado = await category_id(session, sp, "Mercado")
    await set_budget(
        session, actor_id=ana.user.id, space_id=sp, month=date(2026, 11, 1),
        limit_cents=300_000, categories={mercado: 100_000},
    )  # fmt: skip
    parser.add(expense(40_000, category_name="Mercado"))
    await ana.say("gastei 400 no mercado")
    assert await ana.say("teto") == (
        "🎯 Teto de novembro: R$ 400,00 de R$ 3.000,00 (13%).\n• Mercado: R$ 400,00 de R$ 1.000,00"
    )
```
`backend/tests/jobs/test_worker.py`:
```python
from app.ai.openai_parser import OpenAIIntentParser
from app.jobs.inbound import process_inbound
from app.worker import WorkerSettings


async def test_worker_registers_process_inbound_and_builds_the_parser_once():
    assert [f.__name__ for f in WorkerSettings.functions] == ["process_inbound"]
    assert WorkerSettings.functions[0] is process_inbound
    ctx: dict = {}
    await WorkerSettings.on_startup(ctx)
    assert isinstance(ctx["parser"], OpenAIIntentParser)
    assert WorkerSettings.max_tries == 1
```

```bash
cd ~/abby-cash/backend && mkdir -p app/assistant/flows tests/jobs && touch app/assistant/flows/__init__.py tests/jobs/__init__.py
uv run pytest tests/assistant tests/jobs -q
```
→ **FAIL** (`ModuleNotFoundError: No module named 'app.assistant.state'` / `app.worker` sem `on_startup`).

- [ ] **Step 9: Estado, turno, avisos e respostas**

`conversation_state` (uma pergunta pendente por usuário e canal; expira em 30 min **relativo à hora da mensagem**):
`backend/app/assistant/models.py`:
```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConversationState(Base):
    """Pergunta pendente de um usuário num canal (uma por vez; expira em 30 min)."""

    __tablename__ = "conversation_state"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(
        String(16)
    )  # amount | payment | confirm | pick_bill | correct
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```
`backend/app/assistant/state.py`:
```python
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import ConversationState

TTL = timedelta(minutes=30)


async def get_state(
    session: AsyncSession, user_id: UUID, channel: str, now: datetime
) -> ConversationState | None:
    """Pergunta pendente válida em `now` (hora da mensagem); expirada = como se não houvesse."""
    st = await session.get(ConversationState, (user_id, channel), populate_existing=True)
    if st is not None and st.expires_at <= now:
        await session.delete(st)
        await session.commit()
        return None
    return st


async def set_state(
    session: AsyncSession, user_id: UUID, channel: str, kind: str, data: dict[str, Any],
    now: datetime,
) -> None:  # fmt: skip
    st = await session.get(ConversationState, (user_id, channel), populate_existing=True)
    if st is None:
        st = ConversationState(user_id=user_id, channel=channel)
        session.add(st)
    st.kind, st.data, st.expires_at = kind, data, now + TTL
    await session.commit()


async def clear_state(session: AsyncSession, user_id: UUID, channel: str) -> None:
    await session.execute(
        delete(ConversationState).where(
            ConversationState.user_id == user_id, ConversationState.channel == channel
        )
    )
    await session.commit()
```

`Turn` (só escalares do usuário: depois de um rollback os objetos ORM expiram) e `Draft` (a ação que ficou esperando uma resposta; vai inteira para o JSON do estado):
`backend/app/assistant/turn.py`:
```python
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.context import SpaceContext, load_space_context
from app.assistant.intents import ParsedIntent


class Pay(BaseModel):
    """Uma opção/escolha: conta, cartão ou conta a pagar (rótulo já pronto para mostrar)."""

    type: Literal["account", "card", "bill"]
    id: UUID
    label: str


class Draft(BaseModel):
    """Ação em andamento que precisou perguntar algo; vai inteira para `conversation_state`."""

    action: Literal["launch", "pay", "aporte"]
    p: ParsedIntent
    space_id: UUID
    payment: Pay | None = None
    bill_id: UUID | None = None
    options: list[Pay] = []
    warn: str | None = None
    confirmed: bool = False
    private: bool = False


@dataclass
class Turn:
    """Tudo que um fluxo precisa de uma mensagem. Só escalares do usuário: um rollback expira
    os objetos ORM, e ler atributo expirado em sessão async dá erro."""

    session: AsyncSession
    user_id: UUID
    tz: str
    default_space_id: UUID | None
    channel: str
    message_id: str  # id externo: vira `source_message_id` dos lançamentos
    now: datetime
    today: date
    parser: Any  # IntentParser (ou None se o worker não configurou)
    intent: str | None = None
    _contexts: dict[UUID, SpaceContext] = field(default_factory=dict)

    async def context(self, space_id: UUID) -> SpaceContext:
        if space_id not in self._contexts:
            self._contexts[space_id] = await load_space_context(
                self.session, user_id=self.user_id, space_id=space_id, today=self.today, tz=self.tz
            )
        return self._contexts[space_id]
```
`backend/app/assistant/notify.py`:
```python
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import get_adapter
from app.domain.channels.models import ChannelLink
from app.domain.spaces.models import SpaceMember

log = logging.getLogger(__name__)


async def notify_members(
    session: AsyncSession, space_id: UUID, exclude_user_id: UUID, text: str
) -> None:
    """Avisa os OUTROS membros do espaço pelos canais vinculados (alerta de teto é do espaço).
    ponytail: sem fallback entre canais; o M4 troca por `notify_user`."""
    rows = (
        await session.execute(
            select(ChannelLink.channel, ChannelLink.external_user_id)
            .join(SpaceMember, SpaceMember.user_id == ChannelLink.user_id)
            .where(SpaceMember.space_id == space_id, ChannelLink.user_id != exclude_user_id)
        )
    ).all()
    for channel, external_user_id in rows:
        try:
            await get_adapter(channel).send_text(external_user_id, text)
        except Exception:
            log.exception("notify_members failed")
```

Todos os textos ao usuário (pt-BR, valores com `format_brl`), inclusive o formato exato da confirmação:
`backend/app/assistant/replies.py`:
```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import format_brl
from app.domain.accounts.models import Account
from app.domain.budgets.service import BudgetAlert
from app.domain.cards.billing import split_installments
from app.domain.cards.models import CreditCard
from app.domain.categories.models import Category
from app.domain.transactions.models import Transaction

MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
    "outubro", "novembro", "dezembro",
]  # fmt: skip

NOT_UNDERSTOOD = "Não entendi. Tente: gastei 45 mercado — ou mande 'ajuda'."
MEDIA = (
    "Ainda não entendo áudio nem foto, por enquanto só texto. Mande assim: gastei 45 no mercado."
)
HELP = (
    "Eu lanço seus gastos pelo chat. Exemplos:\n"
    "• gastei 45 no mercado\n"
    "• uber 23 ontem\n"
    "• tv 3000 em 10x no nubank\n"
    "• recebi 3000 de salário\n"
    "• #pessoal presente 150 (só você vê)\n"
    "Consultas: saldo · teto · faturas · quanto gastei esse mês\n"
    "Ajustes: corrigir · apagar último\n"
    "Contas: paguei · guardei 500 na viagem"
)
AI_DOWN = "⚠️ A IA está indisponível agora; lancei do jeito simples (categoria Outros)."
CORRECT_PROMPT = (
    "O que está errado? Responda como: valor 50 · categoria Lazer · descrição cinema · "
    "data ontem. Ou mande 'apagar último'."
)
NO_FAMILY = "Você não tem um espaço familiar. Crie ou entre em um no painel web."
NO_CARD = "Não achei nenhum cartão cadastrado. Cadastre um no painel web (Cartões)."
NO_ACCOUNT = "Não achei nenhuma conta cadastrada. Cadastre uma no painel web (Contas)."
FUTURE_DATE = "Essa data é no futuro. Mande uma data de hoje ou passada."

_DOMAIN_ERRORS = {
    "amount_must_be_positive": "O valor precisa ser maior que zero.",
    "amount_too_large": "Esse valor é alto demais.",
    "invalid_date": "Data inválida.",
    "invalid_installments": "Parcelas: de 2 a 48.",
    "invalid_category": "Essa categoria não existe neste espaço.",
    "insufficient_saved": "Não há tanto guardado nessa meta.",
    "invalid_payment_amount": "Esse valor é maior do que falta pagar.",
    "not_editable": "Esse lançamento não pode ser corrigido pelo chat.",
    "installment_group_not_editable": (
        "Compra parcelada: só dá para corrigir categoria ou descrição. "
        "Para mudar valor ou data, apague e lance de novo."
    ),
    "card_date_not_editable": "Para mudar a data de uma compra no cartão, apague e lance de novo.",
}


def domain_error_text(code: str) -> str:
    return _DOMAIN_ERRORS.get(code, f"Não consegui concluir ({code}).")


def http_error_text(status: int) -> str:
    if status == 403:
        return "Você não tem permissão para isso (conta ou lançamento de outra pessoa)."
    if status == 404:
        return "Não encontrei isso, ou você não tem acesso."
    return "Não consegui concluir."


def month_name(d: date) -> str:
    return MONTHS[d.month - 1]


def when_label(d: date, today: date) -> str:
    if d == today:
        return "hoje"
    return "ontem" if (today - d).days == 1 else f"{d:%d/%m}"


def account_label(type: str, name: str) -> str:
    if type == "wallet":
        return name
    return name if name.lower().startswith("conta") else f"Conta {name}"


def installments_text(total_cents: int, n: int) -> str:
    return (
        f"{format_brl(total_cents)} em {n}x de {format_brl(split_installments(total_cents, n)[-1])}"
    )


def months_list(months: list[date]) -> str:
    names = [MONTHS[m.month - 1][:3] for m in months]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]


def future_impact_text(each_cents: int, months: list[date]) -> str:
    return f"Compromete {format_brl(each_cents)} dos tetos de {months_list(months)}."


def alert_text(alert: BudgetAlert, month: date, category: str | None) -> str:
    spent, limit = format_brl(alert.spent), format_brl(alert.limit)
    scope = month_name(month) if category is None else f"{category} em {month_name(month)}"
    if alert.threshold == 101:
        return f"🚨 Você ultrapassou o teto de {scope}: {spent} de {limit}."
    return f"⚠️ Você atingiu {alert.threshold}% do teto de {scope}: {spent} de {limit}."


def options_text(question: str, labels: list[str]) -> str:
    return (
        question
        + " Responda com o número:\n"
        + "\n".join(f"{i}) {x}" for i, x in enumerate(labels, 1))
    )


async def tx_line(
    session: AsyncSession, tx: Transaction, today: date, *, total_cents: int | None = None,
    installments: int | None = None, private: bool = False,
) -> str:  # fmt: skip
    """`✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank` + linha de correção."""
    category = "Sem categoria"
    if tx.category_id is not None:
        category = (
            await session.scalar(select(Category.name).where(Category.id == tx.category_id))
            or category
        )
    payment = "—"
    if tx.card_id is not None:
        name = await session.scalar(select(CreditCard.name).where(CreditCard.id == tx.card_id))
        payment = f"Cartão {name}"
    elif tx.account_id is not None:
        acc = await session.get(Account, tx.account_id)
        if acc is not None:
            payment = account_label(acc.type, acc.name)
    amount = (
        installments_text(total_cents, installments)
        if installments and total_cents
        else format_brl(tx.amount_cents)
    )
    parts = [amount, category]
    if label := (tx.merchant or tx.description):
        parts.append(label)
    parts += [when_label(tx.occurred_on, today), payment]
    if private:
        parts.append("🔒 pessoal")
    return "✅ " + " · ".join(parts) + '\nResponda "corrigir" se errei.'
```

Em `backend/app/domain/models.py` acrescente `import app.assistant.models  # noqa: F401`.

- [ ] **Step 10: Fluxos**

Escolha de conta/cartão (dica → padrão → pergunta) e resposta a listas numeradas:
`backend/app/assistant/flows/payment.py`:
```python
import re
from uuid import UUID

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.assistant.replies import account_label
from app.assistant.turn import Pay
from app.core.text import fold

_STOP = {
    "no", "na", "nos", "nas", "o", "a", "de", "do", "da", "dos", "das", "em", "pelo", "pela",
    "com", "meu", "minha", "conta", "cartao", "credito", "debito", "pix", "transferencia",
    "ted", "doc", "dinheiro", "carteira", "especie",
}  # fmt: skip
Choice = tuple[Pay | None, list[Pay]]  # (escolhida, opções para perguntar)


def _accounts(ctx: SpaceContext, only: set[UUID] | None = None) -> list[Pay]:
    return [
        Pay(type="account", id=a.id, label=account_label(a.type, a.name))
        for a in ctx.accounts
        if only is None or a.id in only
    ]


def choose_account(ctx: SpaceContext, hints: list[str]) -> Choice:
    """Dica da mensagem -> conta padrão do espaço -> pergunta (spec 13). Dica que não casa com
    nenhuma conta pergunta, em vez de cair em silêncio na padrão."""
    text = fold(" ".join(hints))
    everyone = _accounts(ctx)
    if not ctx.accounts:
        return None, []
    if re.search(r"\b(dinheiro|carteira|especie)\b", text):
        wallets = _accounts(ctx, {a.id for a in ctx.accounts if a.type == "wallet"})
        return (wallets[0], []) if len(wallets) == 1 else (None, wallets or everyone)
    tokens = [w for w in re.findall(r"[a-z0-9]+", text) if w not in _STOP]
    if tokens:
        found = _accounts(
            ctx, {a.id for a in ctx.accounts if any(t in fold(a.name) for t in tokens)}
        )
        return (found[0], []) if len(found) == 1 else (None, found or everyone)
    default = next((a for a in ctx.accounts if a.id == ctx.default_account_id), None)
    if default is not None and re.search(r"\b(pix|debito)\b", text) and default.type == "wallet":
        banks = [a for a in ctx.accounts if a.type != "wallet"]  # pix não sai da carteira
        default = banks[0] if len(banks) == 1 else None
        if default is None:
            return None, _accounts(ctx, {a.id for a in banks}) or everyone
    if default is not None:
        return Pay(
            type="account", id=default.id, label=account_label(default.type, default.name)
        ), []
    return (everyone[0], []) if len(everyone) == 1 else (None, everyone)


def choose_card(ctx: SpaceContext, hints: list[str]) -> Choice:
    cards = [Pay(type="card", id=c.id, label=f"Cartão {c.name}") for c in ctx.cards]
    tokens = [w for w in re.findall(r"[a-z0-9]+", fold(" ".join(hints))) if w not in _STOP]
    if tokens:
        found = [
            Pay(type="card", id=c.id, label=f"Cartão {c.name}")
            for c in ctx.cards
            if any(t in fold(c.name) for t in tokens)
        ]
        return (found[0], []) if len(found) == 1 else (None, found or cards)
    return (cards[0], []) if len(cards) == 1 else (None, cards)


def choose_payment(ctx: SpaceContext, p: ParsedIntent, *, income: bool) -> Choice:
    """Cartão quando há parcelas, dica de cartão ou a palavra cartão/crédito; senão, conta."""
    hints = [h for h in (p.card_hint, p.account_hint) if h]
    wants_card = not income and (
        (p.installments or 1) > 1
        or bool(p.card_hint)
        or re.search(r"cartao|credito", fold(" ".join(hints))) is not None
    )
    return choose_card(ctx, hints) if wants_card else choose_account(ctx, hints)


def pick_option(options: list[Pay], text: str) -> Pay | None:
    """Resposta a uma lista numerada: o número ou parte única do nome."""
    s = fold(text).strip()
    if re.fullmatch(r"\d{1,2}", s):
        n = int(s)
        return options[n - 1] if 1 <= n <= len(options) else None
    if len(s) >= 3:
        found = [o for o in options if s in fold(o.label)]
        return found[0] if len(found) == 1 else None
    return None
```
`backend/app/assistant/flows/common.py`:
```python
from uuid import UUID

from sqlalchemy import update

from app.assistant.state import set_state
from app.assistant.turn import Draft, Turn
from app.domain.bills.models import Bill
from app.domain.bills.status import bill_paid_cents
from app.domain.cards.service import invoice_remaining
from app.domain.transactions.models import Transaction


async def ask(t: Turn, d: Draft, kind: str, text: str) -> str:
    """Guarda a ação em andamento e devolve a pergunta; a próxima mensagem retoma (30 min)."""
    await set_state(
        t.session, t.user_id, t.channel, kind, {"draft": d.model_dump(mode="json")}, t.now
    )
    return text


async def tag_origin(t: Turn, tx_id: UUID) -> None:
    """Pagamentos e aportes nascem com origem "web" no domínio; pelo chat passam a "telegram"
    (e guardam a mensagem), para o "apagar último" achá-los."""
    await t.session.execute(
        update(Transaction)
        .where(Transaction.id == tx_id)
        .values(origin=t.channel, source_message_id=t.message_id)
    )
    await t.session.commit()


async def remaining_of(t: Turn, bill: Bill) -> int:
    if bill.invoice_id is not None:
        return await invoice_remaining(t.session, bill.invoice_id)
    return bill.amount_cents - await bill_paid_cents(t.session, bill.id)
```

Lançamento (despesa, receita e parcelado): valor → confiança → conta/cartão → categoria (regra aprendida > sugerida > Outros) → serviço de domínio → confirmação + frase de impacto futuro + alertas de teto:
`backend/app/assistant/flows/launch.py`:
```python
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.assistant.context import SpaceContext
from app.assistant.flows.common import ask
from app.assistant.flows.payment import choose_payment
from app.assistant.hints import Hints
from app.assistant.intents import ParsedIntent
from app.assistant.notify import notify_members
from app.assistant.replies import (
    FUTURE_DATE,
    NO_ACCOUNT,
    NO_CARD,
    alert_text,
    future_impact_text,
    options_text,
    tx_line,
)
from app.assistant.turn import Draft, Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.budgets.service import evaluate_thresholds, future_impact
from app.domain.cards.service import register_card_purchase
from app.domain.categories.models import Category, CategoryRule
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import create_transaction, normalize_merchant

CONFIDENCE_MIN = 0.6


async def start(t: Turn, p: ParsedIntent, space_id: UUID, h: Hints, warn: str | None) -> str:
    return await run(
        t, Draft(action="launch", p=p, space_id=space_id, warn=warn, private=h.private)
    )


async def resolve_category(
    t: Turn, ctx: SpaceContext, p: ParsedIntent, space_id: UUID, kind: str
) -> UUID | None:
    """Regra aprendida > categoria sugerida (existente no espaço) > "Outros"."""
    cats = {fold(c.name): c.id for c in ctx.categories if c.kind == kind}
    norm = normalize_merchant(p.merchant or p.description or "")
    if norm:
        learned = await t.session.scalar(
            select(CategoryRule.category_id).where(
                CategoryRule.space_id == space_id, CategoryRule.merchant_norm == norm
            )
        )
        if learned in cats.values():
            return learned
    return cats.get(fold(p.category_name or "")) or cats.get("outros")


async def budget_notes(
    t: Turn, space_id: UUID, txs: list[Transaction], each_cents: int
) -> tuple[list[str], list[str]]:
    """(frase de impacto futuro, alertas de teto) de uma despesa recém-gravada."""
    impact = await future_impact(t.session, space_id, txs)  # meses de vencimento das faturas
    months = {f.month for f in impact} | {
        tx.occurred_on.replace(day=1) for tx in txs if tx.card_id is None
    }
    notes: list[str] = []
    if len(txs) > 1 and (with_limit := [f.month for f in impact if f.limit is not None]):
        notes.append(future_impact_text(each_cents, with_limit))
    alerts: list[str] = []
    for month in sorted(months):
        for a in await evaluate_thresholds(t.session, space_id, month):
            cat = None
            if a.category_id is not None:
                cat = await t.session.scalar(
                    select(Category.name).where(Category.id == a.category_id)
                )
            alerts.append(alert_text(a, month, cat))
    return notes, alerts


async def run(t: Turn, d: Draft) -> str:
    """Lança a despesa/receita ou faz a próxima pergunta que falta (valor, confiança, conta)."""
    p = d.p
    if p.amount_cents is None or p.amount_cents <= 0:
        prefix = "" if p.amount_cents is None else "O valor precisa ser maior que zero. "
        p.amount_cents = None
        return await ask(t, d, "amount", prefix + "Quanto foi? (ex.: 45 ou 45,50)")
    if p.confidence < CONFIDENCE_MIN and not d.confirmed:
        what = p.description or p.merchant or "isso"
        text = f'Entendi {format_brl(p.amount_cents)} em "{what}". Posso lançar? (sim/não)'
        return await ask(t, d, "confirm", text)
    ctx = await t.context(d.space_id)
    income = p.intent == "lancar_receita"
    if d.payment is None:
        chosen, options = choose_payment(ctx, p, income=income)
        if chosen is None:
            if not options:
                return NO_CARD if (p.installments or 1) > 1 or p.card_hint else NO_ACCOUNT
            d.options = options
            question = "Em qual cartão foi?" if options[0].type == "card" else "Em qual conta foi?"
            return await ask(t, d, "payment", options_text(question, [o.label for o in options]))
        d.payment = chosen
    occurred: date = p.occurred_on or t.today
    if occurred > t.today:
        return FUTURE_DATE
    n = p.installments if p.installments and p.installments > 1 else 1
    category_id = await resolve_category(t, ctx, p, d.space_id, "income" if income else "expense")
    description = (p.description or p.merchant or "")[:500]
    merchant = p.merchant[:200] if p.merchant else None
    if d.payment.type == "card":
        txs = await register_card_purchase(
            t.session, actor_id=t.user_id, space_id=d.space_id, card_id=d.payment.id,
            amount_cents=p.amount_cents, occurred_on=occurred, installments=n,
            description=description, merchant=merchant, category_id=category_id,
            origin=t.channel, source_message_id=t.message_id,
        )  # fmt: skip
    else:
        txs = [
            await create_transaction(
                t.session,
                actor_id=t.user_id,
                space_id=d.space_id,
                type="income" if income else "expense",
                amount_cents=p.amount_cents,
                occurred_on=occurred,
                description=description,
                merchant=merchant,
                category_id=category_id,
                account_id=d.payment.id,
                origin=t.channel,
                source_message_id=t.message_id,
            )  # fmt: skip
        ]
    line = await tx_line(
        t.session, txs[0], t.today, total_cents=p.amount_cents if n > 1 else None,
        installments=n if n > 1 else None, private=d.private,
    )  # fmt: skip
    lines = [d.warn, line] if d.warn else [line]
    if not income:
        each = txs[-1].amount_cents
        notes, alerts = await budget_notes(t, d.space_id, txs, each)
        lines += notes + alerts
        for text in alerts:  # o teto é do espaço: os outros membros também precisam saber
            await notify_members(t.session, d.space_id, t.user_id, text)
    return "\n".join(lines)
```

Corrigir/apagar o último lançamento (aprendizado de categoria incluído):
`backend/app/assistant/flows/edit.py`:
```python
import re
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.assistant.amounts import parse_bare_amount
from app.assistant.hints import Hints, resolve_date
from app.assistant.intents import ParsedIntent
from app.assistant.replies import CORRECT_PROMPT, tx_line
from app.assistant.state import set_state
from app.assistant.turn import Turn
from app.core.text import fold
from app.domain.categories.models import Category, CategoryRule
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import (
    delete_transaction,
    normalize_merchant,
    update_transaction,
)

_CORRECTION = re.compile(r"\s*(valor|categoria|descri[cç][aã]o|data)\s+(.+)", re.I | re.S)


async def last_tx(t: Turn) -> Transaction | None:
    """Último lançamento feito POR ESTE USUÁRIO neste canal (nunca o do web nem de outra pessoa)."""
    return await t.session.scalar(
        select(Transaction)
        .where(Transaction.created_by == t.user_id, Transaction.origin == t.channel)
        .order_by(Transaction.created_at.desc(), Transaction.installment_number.asc().nulls_last())
        .limit(1)
    )


def parse_correction(text: str, today: date) -> dict[str, Any] | None:
    """ "valor 50", "categoria Lazer", "descrição cinema", "data ontem" -> campos a mudar."""
    m = _CORRECTION.fullmatch(text)
    if m is None:
        return None
    key, rest = fold(m.group(1)), m.group(2).strip()
    if key == "valor":
        cents = parse_bare_amount(rest)
        return {"amount_cents": cents} if cents else None
    if key == "categoria":
        return {"category_name": rest}
    if key == "data":
        day = resolve_date(rest, today)
        return {"occurred_on": day} if day else None
    return {"description": rest}


async def learn_rule(
    t: Turn, space_id: UUID, merchant_or_description: str, category_id: UUID
) -> None:
    """Corrigiu a categoria: aquele estabelecimento passa a ir sempre para ela."""
    norm = normalize_merchant(merchant_or_description)
    if not norm:
        return
    await t.session.execute(
        insert(CategoryRule)
        .values(space_id=space_id, merchant_norm=norm, category_id=category_id)
        .on_conflict_do_update(
            constraint="uq_category_rules_space_merchant", set_={"category_id": category_id}
        )
    )
    await t.session.commit()


async def apply_correction(t: Turn, fields: dict[str, Any]) -> str:
    tx = await last_tx(t)
    if tx is None:
        return "Não achei nenhum lançamento seu feito pelo chat para corrigir."
    category_id: UUID | None = None
    if name := fields.get("category_name"):
        kind = "income" if tx.type == "income" else "expense"
        cats = await t.session.scalars(
            select(Category).where(Category.space_id == tx.space_id, Category.kind == kind)
        )
        by_name = {fold(c.name): c for c in cats}
        found = by_name.get(fold(name))
        if found is None:
            return f"Não achei a categoria {name}. Opções: " + ", ".join(
                c.name for c in by_name.values()
            )
        category_id = found.id
    space_id, label = tx.space_id, tx.merchant or tx.description
    out = await update_transaction(
        t.session, actor_id=t.user_id, tx_id=tx.id, amount_cents=fields.get("amount_cents"),
        category_id=category_id, description=fields.get("description"),
        occurred_on=fields.get("occurred_on"),
    )  # fmt: skip
    if category_id is not None:
        await learn_rule(t, space_id, label or "", category_id)
    return "✏️ Corrigi:\n" + await tx_line(t.session, out, t.today)


async def corrigir(t: Turn, p: ParsedIntent, h: Hints) -> str:
    fields: dict[str, Any] = {
        "amount_cents": p.amount_cents, "category_name": p.category_name,
        "description": p.description, "occurred_on": p.occurred_on,
    }  # fmt: skip
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        await set_state(t.session, t.user_id, t.channel, "correct", {}, t.now)
        return CORRECT_PROMPT
    return await apply_correction(t, fields)


async def apagar(t: Turn) -> str:
    tx = await last_tx(t)
    if tx is None:
        return "Não achei nenhum lançamento seu feito pelo chat para apagar."
    line = (await tx_line(t.session, tx, t.today)).split("\n")[0]  # sem o "Responda corrigir"
    deleted = await delete_transaction(t.session, actor_id=t.user_id, tx_id=tx.id)
    extra = f" ({len(deleted)} parcelas)" if len(deleted) > 1 else ""
    return f"🗑️ Apaguei: {line.removeprefix('✅ ')}{extra}"
```

Consultas (respeitam o isolamento de espaços e a privacidade da fatura compartilhada):
`backend/app/assistant/flows/query.py`:
```python
from datetime import date, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from app.assistant.intents import ParsedIntent
from app.assistant.replies import month_name
from app.assistant.turn import Turn
from app.core.dates import add_months
from app.core.money import format_brl
from app.core.text import fold
from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.budgets.service import budget_overview
from app.domain.cards.models import CreditCard, Invoice
from app.domain.cards.service import invoice_statement, invoice_summary
from app.domain.categories.models import Category
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance

# Toda consulta parte do espaço-alvo (já checado com require_member) ou dos espaços de que o
# usuário é membro: o que está em espaço alheio (ex.: #pessoal de outro membro) nunca entra.


def period_bounds(period: str, today: date) -> tuple[date, date, str]:
    first = today.replace(day=1)
    if period == "hoje":
        return today, today, "hoje"
    if period == "ontem":
        return today - timedelta(days=1), today - timedelta(days=1), "ontem"
    if period == "semana":
        return today - timedelta(days=6), today, "nos últimos 7 dias"
    if period == "mes_passado":
        prev = add_months(first, -1)
        return prev, first - timedelta(days=1), f"em {month_name(prev)}"
    return first, today, f"em {month_name(today)}"


async def _member_spaces(t: Turn) -> list[UUID]:
    return list(
        await t.session.scalars(
            select(SpaceMember.space_id).where(SpaceMember.user_id == t.user_id)
        )
    )


async def gastos(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    await require_member(t.session, t.user_id, space_id)
    start, end, label = period_bounds(p.period or "mes", t.today)
    cats = {
        c.id: c.name
        for c in await t.session.scalars(
            select(Category).where(Category.space_id == space_id, Category.kind == "expense")
        )
    }
    q = select(Transaction.category_id, func.sum(Transaction.amount_cents)).where(
        Transaction.space_id == space_id, Transaction.type == "expense",
        Transaction.occurred_on >= start, Transaction.occurred_on <= end,
    )  # fmt: skip
    if p.category_name:
        wanted = next((i for i, n in cats.items() if fold(n) == fold(p.category_name)), None)
        if wanted is None:
            return f"Não achei a categoria {p.category_name}."
        q = q.where(Transaction.category_id == wanted)
    rows = (await t.session.execute(q.group_by(Transaction.category_id))).all()
    space = await t.session.get(Space, space_id)
    where = f" — {space.name}" if space else ""
    if not rows:
        return f"Nenhum gasto {label}{where}."
    total = sum(int(v) for _, v in rows)
    head = f"📊 Gastos {label}: {format_brl(total)}{where}"
    if p.category_name:
        return head
    top = sorted(rows, key=lambda r: -int(r[1]))[:5]
    lines = [
        f"• {cats.get(c, 'Sem categoria') if c else 'Sem categoria'}: {format_brl(int(v))}"
        for c, v in top
    ]
    return head + "\n" + "\n".join(lines)


async def saldo(t: Turn) -> str:
    accounts = list(
        await t.session.scalars(
            select(Account)
            .where(Account.space_id.in_(await _member_spaces(t)))
            .order_by(Account.name)
        )
    )
    if not accounts:
        return "Você ainda não tem contas cadastradas."
    balances = [(a.name, await account_balance(t.session, a.id)) for a in accounts]
    lines = [f"• {name}: {format_brl(cents)}" for name, cents in balances]
    return "💰 Saldos:\n" + "\n".join(lines) + f"\nTotal: {format_brl(sum(c for _, c in balances))}"


async def teto(t: Turn, space_id: UUID) -> str:
    month = t.today.replace(day=1)
    try:
        ov = await budget_overview(t.session, viewer_id=t.user_id, space_id=space_id, month=month)
    except HTTPException:  # 404 sem teto definido (membro já foi checado por quem chamou)
        await require_member(t.session, t.user_id, space_id)
        return f"Você ainda não definiu um teto para {month_name(month)}. Defina no painel web."
    limit, spent = ov["limit_cents"], ov["spent_cents"]
    pct = spent * 100 // limit
    lines = [
        f"🎯 Teto de {month_name(month)}: {format_brl(spent)} de {format_brl(limit)} ({pct}%)."
    ]
    cats = await t.session.scalars(select(Category).where(Category.space_id == space_id))
    names = {c.id: c.name for c in cats}
    for c in ov["categories"]:
        name = names.get(c["category_id"], "?")
        lines.append(f"• {name}: {format_brl(c['spent_cents'])} de {format_brl(c['limit_cents'])}")
    return "\n".join(lines)


async def faturas(t: Turn) -> str:
    rows = (
        await t.session.execute(
            select(Invoice, CreditCard)
            .join(CreditCard, CreditCard.id == Invoice.card_id)
            .join(Bill, Bill.invoice_id == Invoice.id)
            .where(
                CreditCard.space_id.in_(await _member_spaces(t)),
                Bill.status != "paid", Bill.amount_cents > 0,
            )
            .order_by(Invoice.due_on)
            .limit(5)
        )
    ).all()  # fmt: skip
    if not rows:
        return "Nenhuma fatura em aberto."
    lines = []
    for inv, card in rows:
        s = await invoice_summary(t.session, inv)
        open_ = format_brl(s["remaining_cents"])
        line = f"💳 {card.name} · vence {inv.due_on:%d/%m}: {open_} em aberto"
        if s["paid_cents"]:
            line += f" (total {format_brl(s['total_cents'])})"
        private = (await invoice_statement(t.session, t.user_id, inv.id)).private_total_cents
        if private:  # compras de espaços alheios: só o total agregado (spec 14.1)
            line += f" · inclui {format_brl(private)} de lançamentos privados"
        lines.append(line)
    return "\n".join(lines)
```

Pagar contas e faturas, e metas/contas a pagar:
`backend/app/assistant/flows/pay.py`:
```python
from sqlalchemy import select

from app.assistant.flows.common import ask, remaining_of, tag_origin
from app.assistant.flows.payment import choose_account
from app.assistant.intents import ParsedIntent
from app.assistant.replies import NO_ACCOUNT, options_text
from app.assistant.turn import Draft, Pay, Turn
from app.core.money import format_brl
from app.domain.bills.models import Bill
from app.domain.payments import pay_bill, pay_invoice
from app.domain.spaces.models import SpaceMember


async def pending(t: Turn) -> list[tuple[Bill, int]]:
    """Contas a pagar (e faturas) em aberto dos espaços do usuário, com o que falta pagar."""
    mine = select(SpaceMember.space_id).where(SpaceMember.user_id == t.user_id)
    bills = await t.session.scalars(
        select(Bill)
        .where(Bill.space_id.in_(mine), Bill.status != "paid")
        .order_by(Bill.due_on)
        .limit(10)
    )
    out = [(b, await remaining_of(t, b)) for b in bills]
    return [(b, rem) for b, rem in out if rem > 0]


async def start(t: Turn, p: ParsedIntent) -> str:
    items = await pending(t)
    if not items:
        return "Não encontrei contas em aberto."
    if len(items) == 1:
        bill = items[0][0]
        return await run(t, Draft(action="pay", p=p, space_id=bill.space_id, bill_id=bill.id))
    options = [
        Pay(
            type="bill",
            id=b.id,
            label=f"{b.description} · vence {b.due_on:%d/%m} · {format_brl(rem)}",
        )
        for b, rem in items
    ]
    d = Draft(action="pay", p=p, space_id=items[0][0].space_id, options=options)
    return await ask(
        t, d, "pick_bill", options_text("Qual conta você pagou?", [o.label for o in options])
    )


async def run(t: Turn, d: Draft) -> str:
    """Quita a conta escolhida: origem = dica -> padrão -> pergunta; valor = o que falta."""
    bill = await t.session.get(Bill, d.bill_id)
    assert bill is not None
    description, due_invoice, space_id = bill.description, bill.invoice_id, bill.space_id
    ctx = await t.context(space_id)
    if d.payment is None:
        hints = [d.p.account_hint] if d.p.account_hint else []
        chosen, options = choose_account(ctx, hints)
        if chosen is None:
            if not options:
                return NO_ACCOUNT
            d.options = options
            return await ask(
                t, d, "payment", options_text("De qual conta saiu?", [o.label for o in options])
            )
        d.payment = chosen
    if due_invoice is not None:
        amount = d.p.amount_cents or await remaining_of(t, bill)
        tx = await pay_invoice(
            t.session, actor_id=t.user_id, invoice_id=due_invoice, account_id=d.payment.id,
            paid_on=t.today, amount_cents=amount,
        )  # fmt: skip
    else:
        tx = await pay_bill(
            t.session, actor_id=t.user_id, bill_id=bill.id, account_id=d.payment.id,
            paid_on=t.today, amount_cents=d.p.amount_cents,
        )  # fmt: skip
    await tag_origin(t, tx.id)
    left = await remaining_of(t, bill)
    tail = f"\nFalta {format_brl(left)}." if left > 0 else ""
    return (
        f"✅ Paguei {format_brl(tx.amount_cents)} · {description} · hoje · {d.payment.label}{tail}"
    )
```
`backend/app/assistant/flows/extras.py`:
```python
from uuid import UUID

from app.assistant.flows.common import ask, tag_origin
from app.assistant.flows.launch import resolve_category
from app.assistant.flows.payment import choose_account
from app.assistant.intents import ParsedIntent
from app.assistant.replies import NO_ACCOUNT, options_text
from app.assistant.turn import Draft, Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.bills.service import create_bill
from app.domain.goals.service import contribute, goal_progress


async def nova_conta(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    if not p.amount_cents or p.amount_cents <= 0 or p.occurred_on is None:
        return (
            "Para anotar uma conta a pagar preciso do valor e do vencimento. "
            "Ex.: conta de internet 120 vence dia 10"
        )
    ctx = await t.context(space_id)
    category_id = await resolve_category(t, ctx, p, space_id, "expense")
    bill = await create_bill(
        t.session, actor_id=t.user_id, space_id=space_id, amount_cents=p.amount_cents,
        description=(p.description or p.merchant or "Conta")[:200], due_on=p.occurred_on,
        category_id=category_id,
    )  # fmt: skip
    return (
        f"📌 Anotei: {bill.description} · {format_brl(bill.amount_cents)} · "
        f"vence {bill.due_on:%d/%m}\nQuando pagar, é só mandar 'paguei'."
    )


async def aporte(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    return await run_aporte(t, Draft(action="aporte", p=p, space_id=space_id))


async def run_aporte(t: Turn, d: Draft) -> str:
    p = d.p
    if p.amount_cents is None or p.amount_cents <= 0:
        prefix = "" if p.amount_cents is None else "O valor precisa ser maior que zero. "
        p.amount_cents = None
        return await ask(t, d, "amount", prefix + "Quanto você guardou? (ex.: 500)")
    ctx = await t.context(d.space_id)
    hint = fold(p.goal_hint or "")
    goals = [g for g in ctx.goals if hint and (hint in fold(g.name) or fold(g.name) in hint)]
    if len(goals) != 1:
        if not ctx.goals:
            return "Você ainda não tem metas. Crie uma no painel web (Metas)."
        return "Qual meta? Suas metas: " + ", ".join(g.name for g in ctx.goals) + "."
    goal = goals[0]
    if d.payment is None:
        chosen, options = choose_account(ctx, [p.account_hint] if p.account_hint else [])
        if chosen is None:
            if not options:
                return NO_ACCOUNT
            d.options = options
            return await ask(
                t, d, "payment", options_text("De qual conta saiu?", [o.label for o in options])
            )
        d.payment = chosen
    tx = await contribute(
        t.session, actor_id=t.user_id, goal_id=goal.id, from_account_id=d.payment.id,
        amount_cents=p.amount_cents, on=t.today,
    )  # fmt: skip
    await tag_origin(t, tx.id)
    progress = await goal_progress(t.session, goal.id, today=t.today)
    return (
        f"✅ {format_brl(tx.amount_cents)} · Aporte na meta {goal.name} · hoje · "
        f"{d.payment.label}\n"
        f"Guardado: {format_brl(progress.saved)} de {format_brl(progress.target)}."
    )
```

- [ ] **Step 11: Processador completo e worker**

Substitua `backend/app/assistant/processor.py` (o ramo "vinculado" agora chama a conversa; os erros de domínio/acesso viram respostas educadas):
`backend/app/assistant/processor.py`:
```python
import asyncio
import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.amounts import parse_bare_amount
from app.assistant.flows import edit, extras, launch, pay, query
from app.assistant.flows.payment import pick_option
from app.assistant.hints import Hints, extract_hints
from app.assistant.intents import Intent, ParsedIntent
from app.assistant.replies import (
    AI_DOWN,
    HELP,
    MEDIA,
    NO_FAMILY,
    NOT_UNDERSTOOD,
    domain_error_text,
    http_error_text,
)
from app.assistant.shortcuts import answer, try_shortcut
from app.assistant.state import clear_state, get_state
from app.assistant.turn import Draft, Turn
from app.channels.registry import get_adapter
from app.core.config import get_settings
from app.core.dates import to_local_date
from app.core.db import SessionLocal
from app.core.text import fold
from app.domain.channels.linking import find_user_by_link, link_with_code
from app.domain.channels.models import InboundMessage
from app.domain.errors import DomainError
from app.domain.spaces.models import Space, SpaceMember

log = logging.getLogger(__name__)

UNLINKED = (
    "Oi! Eu sou a Abby Cash, assistente de finanças. Para usar este chat, abra o painel web, "
    "vá em Canais, escolha Vincular Telegram e envie aqui o código de 6 dígitos "
    "(ou toque no link que o painel mostra)."
)
INVALID_CODE = "Código inválido ou expirado. Gere um novo no painel web (Canais)."
TOO_MANY = "Muitas tentativas. Aguarde 10 minutos e gere um novo código no painel web."
ALREADY_LINKED = "Este Telegram já está vinculado a outra conta."
LINKED_OK = (
    "✅ Telegram vinculado, {name}! Agora é só me mandar seus gastos, "
    "por exemplo: gastei 45 no mercado."
)
FAILED = "Tive um problema ao processar sua mensagem. Tente de novo em instantes."

_CODE = re.compile(r"(?:/start(?:@\w+)?\s+)?(\d{6})")
_LAUNCH = {"lancar_despesa", "lancar_receita", "lancar_parcelado"}
_NEEDS_AMOUNT = _LAUNCH | {"corrigir", "pagar_conta", "nova_conta_a_pagar", "aporte_meta"}
_INCOME_VERBS = re.compile(r"\s*(recebi|ganhei|entrou|caiu)\b")
_LEADING_VERB = re.compile(r"^\s*(gastei|paguei|comprei|recebi|ganhei|foi|deu)\b\s*", re.I)


async def claim(session: AsyncSession, inbound_id: UUID) -> bool:
    """received -> processing de forma atômica: só um worker processa cada mensagem."""
    got = await session.scalar(
        update(InboundMessage)
        .where(InboundMessage.id == inbound_id, InboundMessage.status == "received")
        .values(status="processing")
        .returning(InboundMessage.id)
    )
    await session.commit()
    return got is not None


async def unlinked(session: AsyncSession, channel: str, external_user_id: str, text: str) -> str:
    """Remetente desconhecido: só instrução fixa (ou vínculo, se mandou um código). Nada é gravado
    no domínio."""
    m = _CODE.fullmatch(text.strip())
    if not m:
        return UNLINKED
    try:
        user = await link_with_code(
            session, channel=channel, external_user_id=external_user_id, code=m.group(1)
        )
    except DomainError as e:
        return TOO_MANY if str(e) == "too_many_attempts" else ALREADY_LINKED
    if user is None:
        return INVALID_CODE
    return LINKED_OK.format(name=user.name.split()[0])


def merge_hints(p: ParsedIntent, h: Hints) -> ParsedIntent:
    """O determinístico vale mais que o LLM em etiquetas, datas e parcelas; o valor do LLM vale,
    exceto com parcelas (aí o total da mensagem manda: "3x de 500") ou se ele não achou nenhum."""
    p.confidence = min(max(p.confidence, 0.0), 1.0)
    p.private = h.private
    if p.intent in _NEEDS_AMOUNT and (
        p.amount_cents is None or (h.installments and h.amount_cents is not None)
    ):
        p.amount_cents = h.amount_cents
    if p.intent in _LAUNCH:
        p.occurred_on = h.occurred_on or p.occurred_on
        p.installments = h.installments or p.installments
        many = (p.installments or 1) > 1
        p.intent = "lancar_parcelado" if many and p.intent != "lancar_receita" else p.intent
        if p.intent == "lancar_parcelado" and not many:
            p.intent = "lancar_despesa"
    return p


def fallback_launch(text: str, h: Hints) -> ParsedIntent | None:
    """IA fora do ar: valor + resto como descrição, categoria Outros (spec 9)."""
    if h.amount_cents is None:
        return None
    rest = re.sub(r"#\w+", " ", text)
    rest = re.sub(r"(?i)(?:r\$\s*)?\d[\d.,]*(?:\s*(?:reais|real))?", " ", rest, count=1)
    description = " ".join(_LEADING_VERB.sub("", rest).split()) or None
    income = _INCOME_VERBS.match(fold(text)) is not None
    intent: Intent = "lancar_despesa"
    if income:
        intent = "lancar_receita"
    elif h.installments:
        intent = "lancar_parcelado"
    return ParsedIntent.of(
        intent, amount_cents=h.amount_cents, description=description, category_name="Outros",
        occurred_on=h.occurred_on, installments=h.installments,
    )  # fmt: skip


async def target_space(t: Turn, h: Hints) -> tuple[UUID | None, str | None]:
    """#pessoal -> espaço pessoal; #familia -> espaço familiar; senão o espaço padrão."""
    s = t.session
    if h.family and not h.private:
        sid = await s.scalar(
            select(Space.id)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == t.user_id, Space.type == "family")
        )
        return (sid, None) if sid else (None, NO_FAMILY)
    if not h.private and t.default_space_id is not None:
        return t.default_space_id, None
    sid = await s.scalar(
        select(Space.id).where(Space.owner_id == t.user_id, Space.type == "personal")
    )
    return (sid, None) if sid else (None, "Não achei seu espaço pessoal.")


async def run_draft(t: Turn, d: Draft) -> str:
    if d.action == "pay":
        return await pay.run(t, d)
    if d.action == "aporte":
        return await extras.run_aporte(t, d)
    return await launch.run(t, d)


async def resume(t: Turn, text: str) -> str | None:
    """Responde a uma pergunta pendente. None = a mensagem não era a resposta (o estado foi
    descartado e ela segue como mensagem nova)."""
    state = await get_state(t.session, t.user_id, t.channel, t.now)
    if state is None:
        return None
    kind, data, reply = state.kind, dict(state.data), answer(text)
    if reply == "cancelar":
        await clear_state(t.session, t.user_id, t.channel)
        return "Ok, cancelei."
    if kind == "correct":
        await clear_state(t.session, t.user_id, t.channel)
        fields = edit.parse_correction(text, t.today)
        return await edit.apply_correction(t, fields) if fields else None
    d = Draft.model_validate(data["draft"])
    if kind == "amount":
        amount = parse_bare_amount(text)
        if amount is None:
            if re.fullmatch(r"-?[\d.,\s]+", text.strip()):  # parece valor, mas é zero/negativo
                return "O valor precisa ser maior que zero. Quanto foi?"
            await clear_state(t.session, t.user_id, t.channel)
            return None
        d.p.amount_cents = amount
    elif kind == "confirm":
        if reply != "sim":
            await clear_state(t.session, t.user_id, t.channel)
            return "Ok, não lancei." if reply == "nao" else None
        d.confirmed = True
    else:  # payment | pick_bill
        picked = pick_option(d.options, text)
        if picked is None:
            if re.fullmatch(r"\d{1,2}", text.strip()):
                return "Responda com um dos números da lista."
            await clear_state(t.session, t.user_id, t.channel)
            return None
        d.options = []
        if kind == "pick_bill":
            d.bill_id = picked.id
        else:
            d.payment = picked
    await clear_state(t.session, t.user_id, t.channel)
    return await run_draft(t, d)


async def interpret(
    t: Turn, text: str, h: Hints, space_id: UUID
) -> tuple[ParsedIntent | None, str | None]:
    """Atalho sem LLM; senão LLM + determinístico; se o LLM falhar, o fallback simples."""
    shortcut = try_shortcut(re.sub(r"#\w+", " ", text))  # "#pessoal gastos" também é atalho
    if shortcut is not None:
        return shortcut, None
    try:
        if t.parser is None:
            raise RuntimeError("no parser configured")
        ctx = await t.context(space_id)
        timeout = get_settings().AI_TIMEOUT_S + 5
        return merge_hints(await asyncio.wait_for(t.parser.parse(text, ctx), timeout), h), None
    except HTTPException:
        raise  # isolamento: não é falha da IA
    except Exception:
        log.warning("intent parser failed; using the plain fallback", exc_info=True)
        return fallback_launch(text, h), AI_DOWN


async def fresh(t: Turn, text: str) -> str:
    h = extract_hints(text, t.today)
    space_id, error = await target_space(t, h)
    if space_id is None:
        return error or NOT_UNDERSTOOD
    p, warn = await interpret(t, text, h, space_id)
    if p is None:
        return NOT_UNDERSTOOD
    t.intent = p.intent
    match p.intent:
        case "lancar_despesa" | "lancar_receita" | "lancar_parcelado":
            return await launch.start(t, p, space_id, h, warn)
        case "corrigir":
            return await edit.corrigir(t, p, h)
        case "apagar":
            return await edit.apagar(t)
        case "pagar_conta":
            return await pay.start(t, p)
        case "nova_conta_a_pagar":
            return await extras.nova_conta(t, p, space_id)
        case "aporte_meta":
            return await extras.aporte(t, p, space_id)
        case "consultar_gastos":
            return await query.gastos(t, p, space_id)
        case "consultar_teto":
            return await query.teto(t, space_id)
        case "consultar_saldo":
            return await query.saldo(t)
        case "consultar_faturas":
            return await query.faturas(t)
        case "ajuda":
            return HELP
        case _:
            return NOT_UNDERSTOOD


async def converse(t: Turn, text: str) -> str:
    return await resume(t, text) or await fresh(t, text)


async def handle(session: AsyncSession, ctx: dict[str, Any], row: InboundMessage) -> str | None:
    user = await find_user_by_link(session, row.channel, row.external_user_id)
    if user is None:
        return await unlinked(session, row.channel, row.external_user_id, row.text or "")
    row.user_id = user.id
    if row.media_kind is not None:  # áudio e foto entram no M6
        return MEDIA
    text = (row.text or "").strip()
    if not text:
        return None
    t = Turn(
        session=session, user_id=user.id, tz=user.tz, default_space_id=user.default_space_id,
        channel=row.channel, message_id=row.external_message_id, now=row.received_at,
        today=to_local_date(row.received_at, user.tz), parser=ctx.get("parser"),
    )  # fmt: skip
    reply = await converse(t, text)
    row.result = {"intent": t.intent}
    return reply


async def handle_inbound(ctx: dict[str, Any], inbound_id: UUID) -> None:
    async with SessionLocal() as session:
        if not await claim(session, inbound_id):
            return  # já processada (reentrega do ARQ, corrida)
        row = await session.get(InboundMessage, inbound_id)
        assert row is not None
        channel, external_user_id = row.channel, row.external_user_id  # escalares: rollback expira
        status = "processed"
        try:
            reply = await handle(session, ctx, row)
            await session.commit()
        except DomainError as e:
            await session.rollback()
            reply = domain_error_text(str(e))
        except HTTPException as e:
            await session.rollback()
            reply = http_error_text(e.status_code)
        except Exception:
            log.exception("process_inbound failed")
            await session.rollback()
            reply, status = FAILED, "failed"
        row = await session.get(InboundMessage, inbound_id, populate_existing=True)
        assert row is not None
        row.status = status
        await session.commit()
        if reply:
            try:
                await get_adapter(channel).send_text(external_user_id, reply)
            except Exception:
                log.exception("send_text failed")
```

O worker cria o interpretador uma vez por processo (`on_startup`):
`backend/app/worker.py`:
```python
from typing import Any

from arq.connections import RedisSettings

from app.ai.openai_parser import OpenAIIntentParser
from app.core.config import get_settings
from app.jobs.inbound import process_inbound


async def startup(ctx: dict[str, Any]) -> None:
    ctx["parser"] = OpenAIIntentParser()  # um cliente por processo do worker


class WorkerSettings:
    functions = [process_inbound]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_tries = 1  # ponytail: sem retry; uma mensagem presa em "processing" exige reenvio manual
```

Run: `cd ~/abby-cash/backend && uv run ruff format . && uv run ruff check --fix . && uv run mypy app && uv run pytest tests/assistant tests/jobs tests/ai -q` → PASS.

- [ ] **Step 12: Exclusão de conta com estado de conversa — teste falhando, depois correção**

Em `backend/tests/api/test_privacy_api.py` acrescente ao final:
```python


async def test_delete_account_removes_conversation_state(client, session):
    from datetime import UTC, datetime, timedelta

    from app.assistant.models import ConversationState

    ana = await make_user(session, "ana@x.com")
    session.add(
        ConversationState(
            user_id=ana.id, channel="telegram", kind="amount", data={},
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )  # fmt: skip
    await session.commit()
    assert (await _delete(client, ana)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(ConversationState)) == 0
```
Run: `uv run pytest tests/api/test_privacy_api.py -q -k conversation_state` → **FAIL** (`ForeignKeyViolationError ... conversation_state_user_id_fkey`).

Em `backend/app/domain/privacy.py`: acrescente `from app.assistant.models import ConversationState` e, em `delete_account`, **antes** da linha que apaga `ChannelLink`:
```python
    await session.execute(delete(ConversationState).where(ConversationState.user_id == uid))
```
Run: `uv run pytest tests/api/test_privacy_api.py -q` → PASS.

- [ ] **Step 13: Migração**

```bash
cd ~/abby-cash/backend && uv run alembic upgrade head && uv run alembic revision --autogenerate -m "conversation state"
uv run ruff format . && uv run ruff check --fix . && bash scripts/migrate_check.sh
```
O arquivo gerado cria só `conversation_state` (PK composta `user_id`+`channel`, `data` JSONB); `migrate_check.sh` termina com `No new upgrade operations detected.`

`backend/migrations/versions/191690511414_conversation_state.py`:
```python
"""conversation state

Revision ID: 191690511414
Revises: a32953583fa0
Create Date: 2026-11-23 14:07:13.273774

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "191690511414"
down_revision: str | Sequence[str] | None = "a32953583fa0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "conversation_state",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "channel"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("conversation_state")
    # ### end Alembic commands ###
```

- [ ] **Step 14: Suíte completa, qualidade e commit**

```bash
cd ~/abby-cash/backend && uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd ~/abby-cash && git add backend/app/assistant backend/app/worker.py backend/app/domain/models.py backend/app/domain/privacy.py \
  backend/migrations/versions/*_conversation_state.py backend/tests/assistant backend/tests/jobs backend/tests/api/test_privacy_api.py
git commit -m "feat(assistant): add Telegram conversation flows with pending questions and budget alerts"
```

---

## Fechamento do marco

- [ ] **Revisão por tarefa:** o revisor do subagent-driven-development aprova cada task (e cada parte do T3.4) antes da próxima. Foco: (1) o webhook **nunca** grava sem o segredo e nada vaza token em log/erro; (2) idempotência em três camadas (reenvio simultâneo não cria dois lançamentos); (3) valores sempre `int` em centavos, zero/negativo nunca lança, valor por extenso e "3x de 500" corretos; (4) `#pessoal`/isolamento: nenhuma consulta do assistente devolve dado de espaço de que o usuário não é membro, e fatura compartilhada só mostra privados agregados; (5) permissão de editar/apagar (autor ou dono) e reajuste de fatura/conta; (6) remetente não vinculado não grava nada; (7) fallback sem IA.
- [ ] **Atualize o `CLAUDE.md`** acrescentando ao final a seção:
  ```markdown

  ## Assistente no Telegram (M3)

  - Entrada única: webhook (`POST /webhooks/telegram`, header de segredo) e polling (`python -m app.cli telegram-poll`) chamam `app.channels.ingest.ingest` → `inbound_messages` (UNIQUE canal + id externo) → fila ARQ `process_inbound` → `app/assistant/processor.py`.
  - Dev sem HTTPS: três processos em `backend/`: `uv run arq app.worker.WorkerSettings`, `uv run python -m app.cli telegram-poll` e `uv run uvicorn app.main:app --reload`. Produção: `uv run python -m app.cli telegram-set-webhook`. O `@` do bot vem de `TELEGRAM_BOT_USERNAME` (opcional) ou `getMe`; nunca fixo no código.
  - O interpretador fica atrás de `IntentParser`; OpenAI via `AI_MODEL`/`OPENAI_API_KEY`. Testes usam `FakeParser` (sem rede). Avaliação com o modelo real, **manual e nunca no CI**: `cd backend && uv run python scripts/run_eval.py` (rode ao mudar o prompt).
  - Etiquetas (`#pessoal`/`#familia`), data, parcelas e valor por extenso são determinísticos (`assistant/hints.py`, `amounts.py`) e valem mais que o LLM. Zero ou negativo nunca lança: pergunta de novo.
  - Todo texto ao usuário sai de `assistant/replies.py` (pt-BR, `format_brl`). Fluxos chamam serviços de domínio; nunca gravam direto no banco.
  - Pergunta pendente = `conversation_state` (30 min, relativo à hora da mensagem), via `flows/common.ask`. Depois de rollback os objetos ORM expiram: use os escalares do `Turn`.
  - "Último lançamento" = o do próprio usuário com `origin == <canal>`. `update_transaction`/`delete_transaction`: só o autor ou o dono do espaço; apagar parcelado apaga o grupo; reajustam fatura e conta a pagar.
  - Consultas só do espaço-alvo ou dos espaços do usuário; fatura compartilhada mostra privados só agregados. Segredos do Telegram/OpenAI só no `.env`; erros do cliente Telegram nunca incluem a URL (token).
  ```
  Commit: `cd ~/abby-cash && git add CLAUDE.md && git commit -m "docs: document M3 assistant conventions"`.
- [ ] **`superpowers:verification-before-completion`:** rode a suíte completa e cole a saída real no PR:
  ```bash
  cd ~/abby-cash/backend && uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy app
  bash scripts/migrate_check.sh
  uv run python -c "from app.main import app; print(sorted({r.path for r in app.routes if r.path.startswith(('/webhooks','/channels'))}))"
  uv run python -c "from app.worker import WorkerSettings as W; print([f.__name__ for f in W.functions])"
  uv run python -m app.cli --help
  ```
  Esperado: tudo verde (no ensaio: 378 testes, 198 do M1+M2 + 180 do M3); rotas `['/channels', '/channels/link-code', '/channels/{channel}', '/webhooks/{channel}']`; `['process_inbound']`; o `--help` lista `telegram-poll` e `telegram-set-webhook`.
- [ ] **Teste manual com o bot de verdade (dev, polling)** — o `.env` já tem os tokens (não imprimir):
  ```bash
  cd ~/abby-cash && docker compose -f infra/docker-compose.dev.yml up -d postgres redis
  cd ~/abby-cash/backend && uv run alembic upgrade head
  uv run python -m app.cli create-admin --email dono@exemplo.com --name "Dono"      # pede a senha
  # três terminais, todos em ~/abby-cash/backend:
  uv run arq app.worker.WorkerSettings
  uv run python -m app.cli telegram-poll          # imprime "polling como @<bot>"
  uv run uvicorn app.main:app --port 8000
  # vincular (outro terminal):
  TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
    -d '{"email":"dono@exemplo.com","password":"<senha>"}' | python -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
  curl -s localhost:8000/channels/link-code -H "authorization: Bearer $TOKEN" \
    -H 'content-type: application/json' -d '{"channel":"telegram"}'     # {"code": "...", "deep_link": "https://t.me/<bot>?start=<código>"}
  ```
  Abra o `deep_link` (ou mande o código) no Telegram e confira: "Telegram vinculado" → `gastei 45 no mercado` (confirmação no formato `✅ R$ 45,00 · Mercado · Mercado · hoje · Carteira`) → `corrigir`/`valor 50` → `apagar último` → `saldo` → mensagem de uma conta não vinculada recebe só a instrução. Anote no PR o que foi feito (sem tokens).
- [ ] **`/code-review high`** no diff `feat/m2-domain...feat/m3-telegram` (a branch anterior; o M3 está empilhado sobre o M2 e a `main` ainda não tem o M2). Corrija, rode os testes de novo e repita até limpar.
- [ ] **Push e PR** (só aqui): `cd ~/abby-cash && git push -u origin feat/m3-telegram`; confirme com `git branch -r --merged origin/main` se a `feat/m2-domain` já entrou na `main` — se **sim**, abra o PR contra `main`; se **não**, contra `feat/m2-domain`:
  ```bash
  cd ~/abby-cash && gh pr create --base feat/m2-domain --title "feat: M3 Telegram assistant" --body "<resumo, saída dos testes, resultado do run_eval.py, roteiro do teste manual>

  🤖 Generated with [Claude Code](https://claude.com/claude-code)"
  ```
  Depois: `/code-review high --comment <número do PR>`.
- [ ] **Parar e pedir a revisão do PR ao dono** (e as respostas de "Pontos que dependem do dono").

## Pontos que dependem do dono

- **Chaves já no `.env` local** (não imprimir nem versionar): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `OPENAI_API_KEY`. Em produção entram no servidor como variáveis de ambiente (M8). Os testes automáticos não precisam delas.
- **`@` do bot (para o link `t.me`):** o código descobre com `getMe` em tempo de execução e guarda em cache por processo; `TELEGRAM_BOT_USERNAME` é um atalho opcional (útil se o `getMe` estiver bloqueado). Nunca é escrito no código. O bot precisa existir no @BotFather.
- **Modelo da OpenAI:** confirmar `AI_MODEL` com o resultado do `scripts/run_eval.py` (Task 3.3, Step 10). Se `gpt-4.1` não aceitar o `response_format` estrito, escolher outro modelo com Structured Outputs e visão (o M6 reutiliza). Custo: uma chamada por mensagem não-atalho; consumo fica em `ai_usage` por espaço.
- **Privacidade com a OpenAI:** a cada mensagem seguem para o provedor o texto, os nomes de categorias/contas/cartões/metas do espaço e as regras aprendidas; nunca e-mail, CPF ou senha (spec 9). Dizer se está de acordo.
- **Webhook em produção** exige HTTPS público e subdomínio (M8); até lá o `telegram-poll` basta. Fixtures do Telegram foram escritas à mão no formato da Bot API: se quiser, capture 2–3 updates reais (com `telegram-poll` + log temporário, sem token) e substitua os JSON.
- **Decisões que o dono pode corrigir:** (1) "apagar último" não pede confirmação; (2) "gastos" soma por data da compra (o teto continua por mês de vencimento da fatura); (3) o alerta de teto também é enviado aos outros membros do espaço pelo Telegram; (4) `paguei`/aporte/conta a pagar já funcionam no M3 em versão mínima (o M5 refina).
- **Para o M4:** alargar `transactions.origin` (hoje `VARCHAR(16)`; `whatsapp_evolution` tem 18) e widenar `LinkCodeIn.channel`.

## Autorrevisão do plano

- **Ensaio real:** todo o código e os testes deste plano (e as migrações) foram aplicados numa cópia do repositório (M1 + M2) com Postgres/Redis reais: 378 testes PASS (198 existentes + 180 novos), `ruff check`, `ruff format --check` e `mypy app` limpos, `scripts/migrate_check.sh` sem diferenças em cada uma das 4 migrações, e a verificação do esquema estrito do SDK (14 campos). Os testes de privacidade novos foram vistos **falhando** (`ForeignKeyViolationError`) antes da correção. Os trechos de código dos passos vêm dos arquivos ensaiados, não de memória. Não foi possível ensaiar `run_eval.py` contra o modelo real (sem chave na cópia): é o Step 10 da Task 3.3.
- **Cobertura do plano mestre:** T3.1 (`test_telegram_webhook_rejects_bad_secret`, `test_webhook_enqueues_and_returns_200` em `tests/api/test_webhooks.py`; adaptador com fixtures JSON em `tests/channels/test_telegram.py`; polling em `test_poll.py`), T3.2 (`test_link_with_code`, `test_expired_code_rejected` em `tests/domain/test_channel_linking.py`; `test_unlinked_sender_gets_instructions_only` em `tests/assistant/test_inbound_flow.py`; `test_duplicate_webhook_creates_single_transaction` em `tests/assistant/test_conversation.py`, com concorrência de 6 entregas e 4 execuções do mesmo job), T3.3 (`test_shortcuts_without_llm`, `test_eval_cases` com 52 casos cobrindo as 13 intenções + `desconhecido`; `scripts/run_eval.py`), T3.4 (`test_expense_message_creates_tx_and_confirms`, `test_private_tag_goes_to_personal_space`, `test_missing_amount_asks_and_resumes`, `test_correction_learns_rule`, `test_llm_failure_fallback`, `test_parcelado_reply_mentions_future_budgets`, `test_zero_amount_rejected`, em `tests/assistant/test_conversation.py`; `parse_amount_words` com "mil e duzentos" → 120000, "quarenta e cinco" → 4500, "dois mil" → 200000 em `tests/assistant/test_amounts_hints.py`).
- **Spec:** 8.1 (interface + adaptador + verificação por segredo), 8.2 (código 6 dígitos/10 min/5 tentativas, `t.me/<bot>?start=`, remetente desconhecido só recebe instrução), 8.3 (idempotência, atalhos, LLM estruturado com categorias/contas/cartões/metas/regras, validação, perguntas curtas em `conversation_state`, confirmação exata, checagem de teto), 8.4 (parcelas, frase de impacto futuro), 9 (degradação sem IA, `ai_usage` por espaço, nada além do necessário ao provedor), 13 (conta padrão por espaço, `OpenAI`/`AI_MODEL`), 14.1 (conta compartilhada e fatura com privados agregados em `faturas`), 14.6 (pagamento sempre com conta de origem; "paguei" usa a padrão e aceita "no dinheiro"). Áudio/foto (8.3 normalização, comprovante) e WhatsApp ficam para M6/M4 com resposta educada.
- **Foco de revisão do plano mestre:** item 2 (webhook duplicado) → testes de ingestão (Task 1), de claim (Task 2) e `test_duplicate_webhook_creates_single_transaction` (Task 4); item 3 (formatos de valor) → `test_extract_amount_formats`, `test_parse_amount_words`, `test_parse_bare_amount_only_accepts_a_lone_value`, `test_zero_amount_rejected`; item 4 (privacidade) → `test_gastos_never_include_spouse_personal_expenses`, `test_saldo_only_own_spaces`, `test_faturas_show_private_aggregate_but_never_the_details`, `test_context_lists_only_what_the_user_may_use`.
- **Consistência de nomes:** `process_inbound(ctx, inbound_id)` (ARQ recebe o id como texto e converte), `enqueue_inbound`, `ingest`, `ParsedIntent`/`ParsedIntent.of`, `IntentParser`/`OpenAIIntentParser`, `SpaceContext`/`load_space_context`, `try_shortcut`/`answer`, `record_ai_usage(space_id, kind, *, input_tokens, output_tokens, seconds)`, `Turn`/`Draft`/`Pay`, `ask` (um só, em `flows/common.py`), `tag_origin`, `alert_text` (reaproveitado no M5), `notify_members` (trocado por `notify_user` no M4). `fold` é único (`app/core/text.py`).
- **Limites conhecidos (ponytail):** polling num processo só e `offset` em memória (reiniciar rebusca updates; a idempotência absorve); `max_tries = 1` no ARQ (mensagem presa em `processing` exige reenvio); escolha de conta por substring do nome; valor por extenso até R$ 1 bi e sem frações ("e meio"); pistas só em português; um estado pendente por usuário e canal; `inbound_messages` crescem sem retenção (M8); sem limite de taxa no webhook (M8) nem no polling; alertas de teto aos outros membros sem fallback de canal (M4); "gastos" por data da compra; `apagar último` sem confirmação; edição por REST só no M7; o limite global de códigos de vínculo (30 apresentações/10 min) pode bloquear todos os vínculos durante um ataque (troca consciente contra força bruta de tomada de conta; revisar com limite por IP no proxy no M8).
