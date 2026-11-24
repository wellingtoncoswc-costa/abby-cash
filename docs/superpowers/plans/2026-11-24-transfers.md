# Transferência entre contas (backend, web, chat)

Feito: guard `insufficient_available` em `create_transaction` (type=transfer); testes de API
(`tests/api/test_transfers_api.py`); intenção `transferir_contas` + `to_account_hint`
(`assistant/flows/transfer.py`); formulário "Transferir entre contas", lista e detalhe na web;
casos no `eval_cases.yaml`; ajuda e prompt do parser.

## Decisões
- Guard só no lançamento manual (web/chat), em `create_transaction`; pagamentos/aportes intactos.
  Vale quando a conta de origem tem dinheiro em caixinhas (`pockets_cents > 0`); senão saldo negativo segue permitido. Conta travada (`FOR UPDATE`) para serializar saídas.
- PATCH de transferência continua `not_editable` (422): editar = excluir e lançar de novo; a web só oferece excluir.
- A transferência pertence ao espaço da conta de origem (web usa o `space_id` da origem; chat idem).
- Excluir a transferência de ENTRADA não é guardado contra caixinhas do destino (fora do escopo).
- Chat: executa na hora; origem sem dica sempre pergunta (não usa conta padrão); destino sem dica pergunta com a lista sem a origem; novo estado `dest` reaproveita `conversation_state`. Dica por tipo (poupança/corrente/carteira). Data: ontem/dia dito vale; futura é recusada.
- Análises ignoram transferências (já filtradas), sem mudança. Atalho em Contas não feito.
