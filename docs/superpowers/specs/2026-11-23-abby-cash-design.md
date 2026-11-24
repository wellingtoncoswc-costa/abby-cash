# Abby Cash — Documento de Design

Data: 2026-11-23 · Status: aprovado pelo dono · **Em caso de conflito, as seções 13 e 14 prevalecem sobre o restante.**

## 1. Intenção e o porquê

O dono do projeto esquece de lançar gastos e de categorizá-los. Apps tradicionais exigem abrir o app e preencher formulários — e por isso são abandonados. O Abby Cash resolve isso trazendo o controle financeiro para **onde a pessoa já está: o chat (WhatsApp e Telegram)**. Mandar "gastei 45 no mercado" (texto, áudio ou foto do comprovante) basta para lançar e categorizar. O app também **puxa a pessoa de volta**: lembra contas a pagar e avisa quando o teto do mês está perto.

O web (e, futuramente, os apps Android/iOS) é o lugar para **ver, analisar e configurar** — não o caminho principal de entrada de dados.

Fases do produto:
1. **Uso próprio** — o dono e a esposa (compartilhando um espaço familiar).
2. **Venda por assinatura** — mesma base, com planos (individual e família) e cobrança.

## 2. Objetivos, não-objetivos e anti-objetivos

### Objetivos (v1)
- Lançar gastos e receitas por **texto, áudio e foto de comprovante** via WhatsApp e Telegram, com categorização automática e confirmação.
- Corrigir/apagar lançamentos pelo próprio chat.
- Contas (corrente, carteira) e **cartões de crédito com fatura e parcelas**.
- **Contas a pagar** avulsas e recorrentes, com lembretes no chat e quitação respondendo "paguei".
- **Teto de gastos mensal** (geral e opcional por categoria) com alertas em 80%, 100% e acima.
- **Metas de economia** com aportes pelo chat e alerta de ritmo.
- **Espaços pessoal e familiar** com convites e marcação `#pessoal`.
- Painel web responsivo (PWA instalável) com resumo, gráficos, lançamentos e configurações.
- Arquitetura **multiusuário desde o dia 1**, pronta para venda.

### Não-objetivos (v1)
- Apps nativos Android/iOS (fase posterior, com Expo, consumindo a mesma API).
- Cobrança/assinatura e limites por plano (estrutura preparada, não implementada).
- Importação de extrato (OFX/CSV) e Open Finance.
- Integração ativa com a API oficial do WhatsApp (só a interface/adaptador preparado).
- Investimentos, múltiplas moedas, contabilidade empresarial.

### Anti-objetivos (falha mesmo que "funcione")
- **Lançar valor errado em silêncio.** Todo lançamento via chat gera confirmação; foto de comprovante exige confirmação explícita antes de gravar.
- **Vazar dados entre espaços/usuários.** Um gasto `#pessoal` nunca aparece para outro membro; dados de um espaço nunca aparecem em outro.
- **Ficar dependente de um único canal.** Se o WhatsApp não oficial cair/for banido, avisos seguem pelo Telegram.
- **Usar o número pessoal do dono no bot não oficial** (risco de banimento). O bot usa chip dedicado.
- Fluxos que exigem abrir o web para tarefas do dia a dia.

## 3. Restrições

- **Deploy em servidor próprio** do dono, via Docker Compose atrás de Nginx com HTTPS.
- O dono já domina **Python/FastAPI, React/TypeScript, Docker, Nginx, PostgreSQL, Alembic** (projeto `abby-chat`). A stack deve aproveitar isso.
- WhatsApp não oficial (Evolution API) viola os termos do WhatsApp: risco aceito pelo dono para a fase inicial; a API oficial será suportada para a fase de venda.
- Dados financeiros pessoais → **LGPD**: exportação e exclusão de dados, mínimo de dados sensíveis enviados a terceiros, segredos fora do repositório.
- Moeda: BRL. Idioma: pt-BR. Fuso padrão: America/Sao_Paulo (configurável por usuário).

## 4. Abordagens consideradas

| # | Abordagem | Prós | Contras |
|---|---|---|---|
| 1 | **FastAPI + React (web) + Expo (mobile, depois)** | Stack que o dono já domina; web com cara de painel; mobile nativo depois sobre a mesma API | Duas UIs no futuro |
| 2 | FastAPI + Expo único para web/Android/iOS | Menos código | Web com cara de app esticado; painéis limitados |
| 3 | Tudo TypeScript (NestJS + Next.js + Expo) | Uma linguagem | Abandona o Python que o dono domina; ganho pequeno |

**Escolhida: abordagem 1**, com os apps Android/iOS **adiados** até o restante estar pronto (decisão do dono). Até lá, o web é **responsivo e instalável como PWA**. Motivo: o chat já faz o papel de "app rápido"; web e app são para análise/configuração e merecem UIs próprias; reaproveitar a stack conhecida reduz risco.

## 5. Decisões do dono (como decididas)

1. Público: uso próprio primeiro, venda por assinatura depois.
2. Canais: **WhatsApp via API não oficial (Evolution API)** e **Telegram** desde o início; **API oficial da Meta** suportada por adaptador — "as 3 formas".
3. Família: **opcional**. Compartilhado com a esposa. Gastos pessoais separados via **espaço padrão + marcação `#pessoal`**.
4. Cartão de crédito: **cada parcela conta no teto do mês da fatura em que cai**; o alerta é emitido **no momento da compra**, informando o impacto nos meses futuros.
5. Escopo v1 inclui **áudio, foto do comprovante e metas de economia**.
6. Apps Android/iOS **depois** que tudo estiver pronto.

## 6. Arquitetura

```
             WhatsApp (Evolution API)   Telegram Bot API   WhatsApp Cloud API (Meta)
                        │                      │                    │
                        └──────── webhooks ────┴────────────────────┘
                                         │
                                 ┌───────▼────────┐
  Navegador (React PWA) ──HTTPS──►   API FastAPI   │──► PostgreSQL
                                 │  (REST + auth)  │──► Redis (fila/cache)
                                 └───────┬────────┘──► Armazenamento de arquivos
                                         │ enfileira
                                 ┌───────▼────────┐
                                 │  Worker (ARQ)   │──► IA: interpretação (LLM),
                                 │  jobs + cron    │     transcrição (STT), leitura de comprovante
                                 └────────────────┘──► envia respostas/avisos pelos canais
```

### 6.1 Componentes
- **API (FastAPI, Python 3.12, SQLAlchemy 2 async, Alembic, Pydantic v2)**: REST para o web/app, autenticação, recebimento de webhooks dos canais (responde 200 rápido e enfileira).
- **Worker (ARQ + Redis)**: processa mensagens recebidas (IA, lançamento, resposta), executa tarefas agendadas (lembretes, alertas, geração de recorrências, fechamento de faturas, backups). *Escolha do builder registrada: ARQ por ser async e simples; Celery é alternativa aceitável.*
- **Web (React + Vite + TypeScript, TanStack Router/Query, Tailwind + shadcn/ui, Recharts)**: mesma família de ferramentas do `abby-chat`. PWA instalável.
- **Evolution API**: container próprio no Compose, com um número/chip dedicado.
- **Nginx**: TLS (Let's Encrypt), proxy para API e web estático, limites de tamanho de upload.

### 6.2 Estrutura do repositório (monorepo)
```
abby-cash/
  backend/        # FastAPI + worker (mesmo pacote, entrypoints distintos)
    app/
      core/       # config, segurança, db, logging
      domain/     # modelos e regras: spaces, accounts, cards, transactions, bills, budgets, goals
      channels/   # base.py (interface) + evolution.py, telegram.py, meta_cloud.py
      assistant/  # interpretação de mensagens, fluxos de conversa, respostas
      ai/         # provedores: llm, stt, ocr/visão (interfaces + implementações)
      api/        # rotas REST
      jobs/       # tarefas do worker e agendamentos
    migrations/
    tests/
  web/            # React PWA
  infra/          # docker-compose.yml, nginx, scripts de backup
  docs/
```

## 7. Modelo de dados (essencial)

Todos os valores monetários em **centavos (inteiro, BIGINT)** — nunca float. Datas de competência em `date`; eventos em `timestamptz`.

- **users**: nome, e-mail, hash de senha (Argon2id), fuso, 2FA (TOTP, opcional), canal preferido de avisos, espaço padrão.
- **spaces**: tipo (`personal` | `family`), nome, dono. Todo usuário tem exatamente um espaço `personal` criado no cadastro.
- **space_members**: user, space, papel (`owner` | `member`).
- **invites**: espaço, e-mail/código, expiração.
- **channel_links**: user, canal (`whatsapp_evolution` | `telegram` | `whatsapp_cloud`), identificador externo (telefone/chat_id), verificado em.
- **categories**: por espaço, com tipo (despesa/receita), ícone, cor; conjunto padrão criado com o espaço.
- **category_rules** (aprendizado): espaço, padrão (estabelecimento/termo normalizado) → categoria; criada quando o usuário corrige.
- **accounts**: espaço, tipo (`checking` | `wallet` | `savings`), nome, saldo inicial.
- **credit_cards**: espaço, nome, dia de fechamento, dia de vencimento, limite (opcional), conta de pagamento.
- **invoices** (faturas): cartão, mês de referência, fechamento, vencimento, status. Gera uma conta a pagar.
- **transactions**: espaço, tipo (`expense` | `income` | `transfer` | `goal_contribution`), valor, data, descrição, estabelecimento, categoria, conta **ou** cartão+fatura, `installment_group_id`, nº/total da parcela, criado_por (user), origem (`whatsapp` | `telegram` | `web` | ...), mensagem de origem, anexo.
- **bills** (contas a pagar): espaço, descrição, valor, vencimento, recorrência (regra), responsável (user ou todos), status, transação de pagamento vinculada.
- **budgets**: espaço, mês, teto geral; **budget_categories**: teto por categoria.
- **budget_alerts_sent**: espaço, mês, escopo (geral/categoria), limiar (80/100/acima) — evita alerta duplicado.
- **goals**: espaço, nome, valor alvo, prazo; aportes são `transactions` do tipo `goal_contribution`.
- **inbound_messages**: canal, id externo (para **idempotência**), user, conteúdo/anexo, status de processamento, resultado da interpretação.
- **conversation_state**: user + canal → estado pendente (ex.: aguardando confirmação de comprovante, escolha de conta).
- **attachments**: chave no armazenamento, tipo, tamanho.
- **audit_log**: quem fez o quê em dados financeiros.

**Isolamento**: todas as tabelas financeiras têm `space_id`. Toda consulta passa por uma camada de repositório que exige o espaço e verifica a participação do usuário. Testes automatizados cobrem tentativas de acesso cruzado. *(Row-Level Security no PostgreSQL fica como reforço opcional, decisão do builder.)*

## 8. Comportamento

### 8.1 Canais (adaptadores)
Interface comum: `parse_webhook(request) → InboundMessage`, `send_text`, `send_buttons/opções` (quando suportado; senão texto com números), `download_media`. Cada adaptador valida a autenticidade do webhook (segredo/token do canal). O núcleo nunca conhece detalhes do canal.

### 8.2 Vínculo de canal
No web, o usuário clica "Vincular WhatsApp/Telegram" → recebe um código de 6 dígitos válido por 10 minutos (e um link direto `t.me/<bot>?start=<código>` para Telegram). Envia ao bot → vínculo criado. Mensagens de identificadores não vinculados recebem instrução de cadastro e nada é gravado.

### 8.3 Interpretação de mensagens
Pipeline no worker:
1. **Idempotência**: descartar mensagem já processada (id externo).
2. **Normalização**: áudio → texto (STT); imagem → extração estruturada de comprovante (visão).
3. **Atalhos determinísticos** para comandos simples (`paguei`, `corrigir`, `apagar último`, `saldo`, `teto`, `ajuda`) — sem custo de IA.
4. **LLM com saída estruturada** para o resto: retorna `intent` + campos (valor, tipo, descrição, estabelecimento, categoria sugerida, conta/cartão, parcelas, data, espaço `#pessoal`, meta). O prompt recebe as categorias, contas, cartões e metas do espaço e as regras aprendidas.
5. **Validação** dos campos (valor > 0, categoria existente, etc.). Se faltar algo essencial ou a confiança for baixa → pergunta curta ao usuário (estado em `conversation_state`).
6. **Execução** da ação e **resposta de confirmação**, por exemplo:
   `✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank` + `Responda "corrigir" se errei.`
7. **Checagem do teto** após qualquer despesa.

Intents v1: `lancar_despesa`, `lancar_receita`, `lancar_parcelado`, `corrigir`, `apagar`, `pagar_conta`, `nova_conta_a_pagar`, `aporte_meta`, `consultar_gastos` (por período/categoria), `consultar_teto`, `consultar_saldo`, `consultar_faturas`, `ajuda`.

**Espaço**: lançamentos vão para o espaço padrão do usuário; `#pessoal` envia para o espaço pessoal. *(Escolha do builder: aceitar também "#familia" como marcação explícita quando o padrão for o pessoal.)*

**Aprendizado de categorias**: ao corrigir a categoria de um lançamento, cria/atualiza `category_rules` para o estabelecimento normalizado. Regras têm precedência sobre a sugestão do LLM.

**Comprovante (foto)**: extrai valor, estabelecimento, data, forma de pagamento → **sempre pede confirmação** ("Lançar R$ 87,40 · Farmácia São João · 22/11? Sim / Corrigir"). A imagem fica anexada ao lançamento.

**Áudio**: transcrito e tratado como texto; a resposta mostra a transcrição resumida para o usuário perceber erros.

### 8.4 Cartões, faturas e parcelas
- Compra com data **até o dia de fechamento** cai na fatura que vence no mês seguinte ao fechamento corrente; após o fechamento, na fatura seguinte. *(Builder implementa a regra padrão de mercado e cobre com testes, incluindo meses curtos: fechamento dia 31 em fevereiro → último dia do mês.)*
- Parcelado em N vezes: N transações com o mesmo `installment_group_id`, valor dividido em centavos (resto na 1ª parcela), cada uma na fatura correspondente.
- Cada fatura gera uma conta a pagar com valor = soma das transações (atualiza até o fechamento). Lembretes como qualquer conta. "Paguei" registra o pagamento a partir da conta de pagamento do cartão.
- **Teto**: cada parcela conta no mês da fatura em que cai. Na compra, se alguma parcela futura impactar tetos, a resposta informa ("Compromete R$ 200 dos tetos de dez, jan e fev").
- Saldo de conta corrente: saldo inicial + receitas − despesas à vista − pagamentos de fatura.

### 8.5 Contas a pagar e lembretes
- Avulsas ou recorrentes (mensal no dia X; anual; a cada N meses). Ocorrências futuras geradas por job (horizonte de 3 meses).
- Lembretes: **1 dia antes e no dia do vencimento**, às 9h no fuso do usuário *(horário padrão configurável)*; e aviso de atraso no dia seguinte se não paga.
- Destino: responsável da conta ou todos os membros do espaço, no canal preferido de cada um.
- Responder "paguei" a um lembrete quita aquela conta (vinculação pelo contexto/estado da conversa; se ambíguo, lista opções numeradas).

### 8.6 Teto de gastos
- Teto mensal geral por espaço; teto opcional por categoria. Mês = mês calendário *(dia de início configurável fica para depois)*.
- Gasto do mês = despesas à vista com data no mês + parcelas de cartão cujas faturas vencem no mês.
- Alertas em **80%, 100% e ao ultrapassar** (o "acima" uma única vez por mês, e depois só no resumo). Uma vez por limiar/escopo/mês (`budget_alerts_sent`). Enviados a todos os membros do espaço.
- Espaços pessoais têm seu próprio teto (opcional).

### 8.7 Metas de economia
- Meta: nome, valor alvo, prazo (opcional), conta onde o dinheiro fica (opcional).
- Aporte pelo chat ("guardei 500 na viagem") ou web; retirada também suportada.
- Progresso e **ritmo**: valor necessário por mês para cumprir o prazo; alerta mensal se estiver atrasado.

### 8.8 Resumos proativos *(sugestão incluída — escolha do builder sobre horários)*
- Resumo semanal opcional no chat (domingo à noite): total gasto, top categorias, % do teto, próximas contas.

### 8.9 Web (PWA)
Telas: login/cadastro (+2FA), onboarding (criar contas/cartões, teto, vincular canal), **Painel do mês** (gasto vs teto, por categoria, próximas contas, metas), Lançamentos (lista com filtros, edição, anexos), Contas a pagar, Cartões e faturas, Metas, Orçamento/teto, Categorias, Espaços e membros (convites), Canais vinculados, Configurações (fuso, horário de lembretes, canal preferido), Privacidade (exportar dados, excluir conta).
Seletor de espaço no topo (Pessoal / Família).

## 9. Segurança, privacidade e robustez

- **Segredos** só em variáveis de ambiente/arquivo `.env` fora do git (`.env.example` versionado). Varredura de segredos no CI.
- Senhas com **Argon2id**; JWT de acesso curto (15 min) + refresh rotativo em cookie `httpOnly`/`Secure`/`SameSite`; 2FA TOTP opcional; rate limit em login e webhooks.
- Webhooks autenticados por segredo por canal; mensagens de identificadores não vinculados são ignoradas (apenas instruções).
- **IA**: enviar ao provedor só o necessário (mensagem, categorias/contas do espaço); nada de e-mail/CPF. Provedores atrás de interfaces (trocáveis). Timeouts, retries e **degradação**: se a IA falhar, responder "não entendi, tente: gastei 45 mercado" e tentar o atalho determinístico de "valor + descrição".
- **Backups**: `pg_dump` diário com retenção (7 diários, 4 semanais, 6 mensais) + cópia para fora do servidor *(destino a definir pelo dono)*; anexos incluídos. Teste de restauração documentado.
- **Observabilidade**: logs estruturados em JSON, healthchecks (`/health`, worker heartbeat), monitor de status da conexão da Evolution API com alerta ao dono via Telegram se desconectar. Sentry opcional.
- **Fallback de canal**: falha de envio por WhatsApp → reenvio pelo Telegram se vinculado.
- **LGPD**: exportação (JSON/CSV) e exclusão de conta com remoção de dados pessoais; registro de auditoria.
- Testes: unitários para regras financeiras (faturas, parcelas, teto, recorrência), testes de API, testes de isolamento entre espaços, testes do interpretador com casos reais de mensagens (conjunto de avaliação versionado).
- CI (GitHub Actions): lint (ruff, eslint), type-check (mypy/tsc), testes, build das imagens. Deploy: `docker compose pull && up -d` no servidor, migrações Alembic automáticas no start.

## 10. Preparação para a fase de venda (não implementar agora)
- Tabela `subscriptions`/`plans` ligada ao espaço (individual = espaço pessoal; família = espaço familiar com N membros).
- Pontos de checagem de limite por plano centralizados (ex.: nº de membros, uso de IA por mês).
- Adaptador `whatsapp_cloud` com modelos de mensagem (templates) para lembretes/alertas fora da janela de 24h.
- Contabilizar uso de IA por espaço desde já (tokens/minutos de áudio) para precificar.

## 11. Ordem sugerida de entrega (marcos)
1. Fundação: monorepo, Compose, CI, auth, usuários, espaços, categorias padrão.
2. Domínio financeiro: contas, lançamentos, cartões/faturas/parcelas, contas a pagar, teto, metas — com API REST e testes.
3. Canal Telegram + vínculo + interpretação de texto + confirmações/correções.
4. Canal WhatsApp (Evolution API) + fallback.
5. Lembretes, alertas de teto, metas, resumo semanal (worker/cron).
6. Áudio e comprovante.
7. Web PWA completo.
8. Endurecimento: backups, monitoramento, LGPD, deploy no servidor.
(Apps Android/iOS e venda vêm depois.)

## 12. Deixado para o builder
- Bibliotecas específicas dentro da stack definida (ex.: cliente HTTP, lib de TOTP, lib de PWA).
- Escolha do provedor de IA e modelos (interfaces obrigatórias; ver perguntas em aberto).
- Formato exato das mensagens de resposta, mantendo o padrão de confirmação curta.
- Design visual do web (seguir shadcn/ui, modo claro/escuro, mobile-first).
- RLS no Postgres como reforço.

## 13. Decisões do builder após revisão (o dono pode corrigir)
- **Conta/cartão padrão**: cada usuário tem uma conta/cartão padrão **por espaço** (campo em `space_members`). Mensagem sem forma de pagamento usa o padrão; "no nubank", "no pix", "no dinheiro" sobrescrevem. A confirmação sempre mostra a conta usada.
- **Teto x cartão (esclarecimento)**: toda compra no cartão (à vista ou parcelada) conta no teto pelo **mês de vencimento da fatura** em que cai. O **pagamento da fatura nunca conta** como gasto (evita contagem dupla). Despesas fora do cartão contam pela data do gasto.
- **Aportes em metas**: são **transferências** da conta de origem para a meta (conta da meta, se houver). Reduzem o saldo da conta de origem, **não contam no teto**. Retirada é a transferência inversa. A fórmula de saldo considera transferências.
- **Um espaço familiar por usuário** na v1 (além do pessoal). O esquema permite vários no futuro.
- **Somente conversas 1:1** com o bot na v1 (sem grupos).
- Interpretação de texto e leitura de comprovante: modelo da **OpenAI** via SDK oficial `openai` (padrão `gpt-4.1`, configurável por `AI_MODEL`), com saída estruturada (Structured Outputs/Pydantic) e visão para comprovantes. Transcrição de áudio: interface própria, Whisper auto-hospedado. *(Atualizado em 2026-11-23: o dono trocou o provedor de Anthropic para OpenAI; chave em `OPENAI_API_KEY`, nunca no git.)*

## 14. Respostas do dono (2026-11-23)
1. **Cartões e contas compartilháveis (opção a).** Toda conta/cartão pertence a um espaço "dono" (`accounts.space_id`), mas um lançamento pode usar conta/cartão de outro espaço **desde que o autor seja membro do espaço dono da conta**. Visibilidade:
   - o lançamento é visível para os membros do espaço do **lançamento** (`transactions.space_id`);
   - quem vê a conta/fatura (membros do espaço dono da conta) vê todos os itens dos espaços de que também é membro; itens de espaços dos quais não é membro aparecem **agregados** como "Outros lançamentos (privados) — R$ X", para que o total da fatura/saldo feche sem revelar detalhes;
   - o teto de cada espaço só considera lançamentos daquele espaço.
2. **IA e servidor.** O servidor é o mesmo que roda o `abby-chat` (reaproveitar Nginx e certificados; não quebrar o abby-chat). **Transcrição de áudio com Whisper auto-hospedado** (faster-whisper, CPU, int8, modelo `small` por padrão, idioma pt, configurável) em container próprio `stt`. Interpretação de texto e leitura de comprovante: **OpenAI** (decisão do dono, 2026-11-23). Registrar consumo de IA por espaço.
3. **Cadastro somente por convite** nesta fase. Um usuário administrador (o dono, criado por comando de CLI) gera convites de cadastro; convites de espaço familiar continuam como descrito.
4. **API oficial do WhatsApp fica para depois**: apenas a interface `ChannelAdapter` e um esqueleto `meta_cloud.py` que lança `NotImplementedError`.
5. **Backups fora do servidor no Google Drive**, via `rclone` (remote configurado pelo dono no servidor).
6. **Todo pagamento é registrado e tem origem.** Pagamento de fatura, de conta a pagar ou qualquer outro pagamento sai de uma **conta cadastrada** (corrente/poupança) **ou da carteira (dinheiro)** — sempre gera um lançamento:
   - pagamento de **conta a pagar** → lançamento de despesa (categoria da conta) na conta escolhida, na data do pagamento; conta no teto pela data do pagamento;
   - pagamento de **fatura** → **transferência** da conta escolhida para o cartão (não conta no teto, pois as compras já contaram); pagamento parcial permitido, o restante fica em aberto;
   - "paguei" pelo chat usa a conta padrão do usuário e permite sobrescrever ("paguei no dinheiro", "paguei pela conta Itaú"); a confirmação mostra a conta debitada;
   - a carteira é uma conta do tipo `wallet` criada automaticamente em cada espaço pessoal.
