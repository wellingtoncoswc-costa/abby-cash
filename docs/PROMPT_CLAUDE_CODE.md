# Prompt para o Claude Code local — implementação do Abby Cash v1

Copie o bloco abaixo e cole no Claude Code, aberto na pasta do repositório `abby-cash` clonado na sua máquina.

---

```
Você vai implementar o Abby Cash v1 do zero neste repositório. Ele é um assistente de finanças pessoais e familiares operado por WhatsApp e Telegram (texto, áudio e foto de comprovante), com painel web PWA, auto-hospedado no meu servidor (o mesmo que já roda o abby-chat).

## Documentos que mandam
1. Spec: docs/superpowers/specs/2026-11-23-abby-cash-design.md. Em caso de conflito, as seções 13 e 14 prevalecem.
2. Plano: docs/superpowers/plans/2026-11-23-abby-cash-v1.md. Ele tem os marcos M1–M8, as interfaces, os testes obrigatórios e o aceite.
Leia os dois inteiros antes de qualquer código. As "Restrições globais" e o "Foco de revisão" do plano valem para todas as tarefas. Não renomeie as interfaces do plano. Se precisar mudar alguma, atualize o plano no mesmo commit e me avise.

## Como trabalhar
- Use os skills do superpowers, se estiverem instalados (se não estiverem, siga o mesmo processo manualmente):
  - para cada marco, primeiro detalhe as tarefas em passos TDD com superpowers:writing-plans, salvando em docs/superpowers/plans/2026-11-23-abby-cash-mN-<nome>.md;
  - depois execute com superpowers:subagent-driven-development (um subagente implementa e outro revisa cada tarefa);
  - antes de declarar algo pronto, use superpowers:verification-before-completion.
- Economia de tokens com o ponytail: use o ponytail (já instalado no meu Claude Code) em TUDO, ou seja, na leitura da spec e do plano, no planejamento de cada marco, na implementação, nos subagentes, nos testes, nos code reviews e nos relatórios. Passe a mesma instrução para todo subagente que você criar. A economia nunca pode pular etapas obrigatórias: TDD, testes, code review e verificação continuam integrais. Se o ponytail não estiver disponível nesta sessão, pare e me avise antes de começar.
- Code review obrigatório, em três momentos:
  1. ao fim de cada tarefa, o revisor do subagent-driven-development precisa aprovar antes da próxima tarefa;
  2. ao fim de cada marco, antes de abrir o PR, rode `/code-review high` no diff do branch do marco contra `main`, corrija os achados confirmados, rode os testes de novo e repita até não sobrar nada importante;
  3. com o PR aberto, rode `/code-review high --comment <número do PR>` para deixar os achados registrados no PR.
  No M8, rode também `/security-review` antes do deploy. No PR, liste o que cada revisão encontrou e como foi resolvido. Achados que você decidir não corrigir precisam de justificativa.
- TDD sempre: teste falhando → implementação mínima → teste passando → commit. Os testes nomeados no plano são obrigatórios. Os testes do "Foco de revisão" também.
- Antes de escrever o código que chama o Claude (interpretador de mensagens e leitura de comprovante), carregue o skill claude-api e siga-o: SDK oficial `anthropic`, saída estruturada com Pydantic, modelo vindo de AI_MODEL (padrão claude-opus-5-5).
- Commits pequenos, em inglês, no padrão Conventional Commits.
- Git: crie a branch `main` a partir de `claude/laughing-pasteur-s90m4c` se `main` ainda não existir (me pergunte antes de fazer push dela). Para cada marco, crie a branch `feat/mN-<nome>` a partir de `main`, faça push e abra um PR para `main` com um resumo do que foi feito e de como testar. Ao fim de cada marco, pare e me peça a revisão do PR antes de começar o próximo, a menos que eu diga para seguir direto.
- O CI (GitHub Actions) precisa estar verde em todo PR. Nunca desative, pule ou apague um teste para passar.

## Regras inegociáveis
- Dinheiro sempre em centavos (int). Nunca float.
- Nenhum segredo no git. Use o .env local (no .gitignore) e mantenha o .env.example atualizado. Quando precisar de um token ou chave, pare e me peça para colocar no .env. Nunca peça para eu colar segredos no chat.
- Isolamento entre espaços: todo acesso passa por require_member. Lançamentos #pessoal nunca aparecem para quem não é membro do espaço pessoal (nas faturas compartilhadas, só o total agregado de "Outros lançamentos (privados)").
- Todo pagamento (conta a pagar ou fatura) tem conta de origem (conta cadastrada ou carteira/dinheiro) e gera um lançamento.
- Foto de comprovante nunca grava sem a minha confirmação.
- No servidor: NÃO altere, reinicie nem derrube nada do abby-chat. Postgres e Redis do abby-cash são próprios. Antes de mexer no Nginx, inspecione a configuração atual, adicione só um server novo para o subdomínio do abby-cash, rode `nginx -t` e me mostre o diff antes de recarregar.
- Nada destrutivo no servidor (apagar volumes, `docker system prune`, `DROP`) sem a minha confirmação explícita.

## Pontos em que você para e me pede algo
- Antes do M3: TELEGRAM_BOT_TOKEN e ANTHROPIC_API_KEY no .env.
- Antes do M4: o chip dedicado e a leitura do QR code da Evolution API.
- Antes do M8: acesso SSH ao servidor, o subdomínio/DNS, a configuração do `rclone config` com o remote `gdrive` (Google Drive) e a chave de criptografia dos backups.
- Sempre que a spec e o plano não decidirem algo que mude o comportamento para o usuário final, me pergunte. Para detalhes técnicos internos, decida e registre a decisão no plano do marco.

## Começo
1. Leia a spec e o plano e me diga, em até 10 linhas, como entendeu o projeto e se viu algum conflito.
2. Detalhe o plano do M1 e comece a implementá-lo.

Ao final de cada marco, me envie: o que foi entregue, os testes rodados com o resultado real, o link do PR, as decisões que você tomou e o que precisa de mim para o próximo marco.
```
