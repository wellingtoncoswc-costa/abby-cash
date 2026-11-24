# M5 — Agendamentos (plano curto)

Base: plano mestre M5 (T5.1–T5.3), spec 8.5–8.8 e 14.6, decisões do dono do M3 (alertas a todos os membros; ambiguidade com lista numerada).

## Decisões
- Crons em `WorkerSettings.cron_jobs` (UTC): lembretes e resumo a cada 15 min; recorrências + espelhos de fatura + teto diários; metas dia 1; purge de inbound diário; `check_evolution_connection` mantido. Toda função aceita `now` opcional (testes) e isola falhas por usuário/espaço/fatura (sessão própria, `try/except`, log só com tipo da exceção, nunca texto/valores).
- **Lembretes** (`jobs/bills.py`): por usuário, se a hora local >= `reminder_time`; contas não pagas dos seus espaços com vencimento amanhã (`day_before`), hoje (`due`) ou ontem (`overdue`); destinatário = responsável, ou todos os membros se não houver. Idempotência: `bill_reminders_sent(bill_id, user_id, kind)` UNIQUE, INSERT ... ON CONFLICT DO NOTHING antes de enviar; se `notify_user` falhar, apaga a linha (reenvia no próximo ciclo). Valor = o que falta (espelho de fatura incluso).
- **Contexto do "paguei"**: após enviar, grava `conversation_state(kind="reminder", data={last_reminded_bill_id}, 24h)` no canal que entregou, sem sobrescrever pergunta pendente viva. `resume` ignora `kind="reminder"`; `pay.start` o consome (qualquer canal).
- **Recorrência**: coluna `bills.recurrence_id` (= id da conta-origem, com a regra) + UNIQUE `(space_id, recurrence_id, due_on)`; o job gera ocorrências de `due_on` da origem até hoje+3 meses (só datas >= hoje) com ON CONFLICT DO NOTHING. Migração preenche `recurrence_id = id` onde há regra. Espelhos: `sync_invoice_bill` nas faturas com fechamento >= hoje.
- **"paguei"**: já tem 0/1/várias, dica de conta, `pay_invoice` parcial (M3); acrescenta contexto de lembrete e filtra faturas quando o texto diz "fatura".
- **Teto** (`jobs/budgets.py`): `evaluate_thresholds` diário nos orçamentos do mês; alerta (`alert_text`) a todos os membros. **Metas** (`jobs/goals.py`, dia 1): `goal_progress.behind` -> aviso aos membros, 1x por meta/mês (chave Redis NX). **Resumo** (`jobs/digest.py`): domingo >= 20:00 local, 1x/semana (chave Redis NX por usuário/data); só espaços de que é membro (privado de terceiros nunca entra; espelho de fatura é total agregado). Comando "resumo semanal on/off" no `fresh`, sem LLM.
- `delete_account`/`_purge_space` limpam `bill_reminders_sent`.

## Arquivos
`jobs/{scheduler,bills,budgets,goals,digest}.py`, `domain/bills/models.py` (+ migração), `assistant/flows/{pay,extras}.py`, `assistant/processor.py`, `domain/privacy.py`, `worker.py`.

## Testes
`tests/jobs/test_{reminders,recurrence,budget_alerts,goals,digest}.py`, `tests/assistant/test_pay_m5.py`, `test_worker.py` (crons), `test_privacy_api.py` (limpeza).
Obrigatórios: reminder (3), paguei (5), teto/meta/resumo (3); extras: isolamento por usuário, recorrência idempotente, toggle do resumo.
