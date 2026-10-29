# Atualização diária e teste com notícias reais

Verificação em 28/10/2026, horário de Fortaleza (29/10 em UTC).

## Comportamento implementado

`memoria_noticias.py prever` consulta InfoMoney, Money Times e documentos do
Copom no Banco Central antes de executar a previsão. A consulta usa um arquivo
temporário novo para não reutilizar listagens antigas. Documentos inéditos ficam
em `dados_noticias/diarias/fontes.sqlite`, recebem sentimento FinBERT e entram
no banco de memória escolhido com `--database`.

A identidade por URL e hash preserva versões e evita duplicatas. Não há nova
classificação quando o episódio já existe. Sem novidades, documentos e episódios
permanecem intactos; a decisão e sua auditoria continuam sendo registradas.
As notícias novas têm disponibilidade real e resultado futuro ausente.

`news_update` apresenta período, contagens, erros e completude por fonte. Uma
fonte indisponível não impede consultar as demais e não é apresentada como
ausência de notícias. O arquivo permite retomar classificações interrompidas.

A opção `--event-id` exclui o evento atual das memórias recuperadas. Ela foi
usada nos dois testes comparáveis abaixo para evitar autorreferência.

## Preparação e coleta reais

Foram copiados os 9.590 episódios já classificados do banco histórico semântico
para `dados_noticias/memoria_finbert.sqlite`, sem alterar os bancos históricos
e sem copiar suas decisões ou reflexões de avaliação. Os episódios mantiveram
seus textos, sentimentos e horários originais.

Na primeira execução completa, as três fontes responderam sem erros:

| Fonte | Novos registros |
|---|---:|
| InfoMoney | 40 |
| Money Times | 9 |
| Banco Central | 0 |
| Total | 49 |

O banco passou a conter **9.639 episódios**. Na segunda execução as três fontes
responderam novamente, sem novidades. Os hashes dos episódios ordenados e do
arquivo SQLite de documentos permaneceram iguais antes e depois. A decisão nova
foi registrada separadamente na tabela de auditoria da memória.

## Decisões com notícias reais

Foram feitas três chamadas reais ao Jev. A primeira verificou o fluxo completo
com uma notícia já armazenada, sem excluir seu evento: retornou manter (0,75).
Ela é apenas um teste operacional, pois permite recuperar a própria notícia.

Nos dois testes seguintes, o evento da notícia atual foi explicitamente excluído:

| Notícia | Memórias recuperadas | Ação | Escore da ação | Base |
|---|---:|---|---:|---|
| Money Times, Ibovespa de 28/10 | 10 | manter | 0,52 | contexto |
| InfoMoney, produção de petróleo da Petrobras no 3º trimestre | 10 | manter | 0,53 | contexto |

Os textos vieram dos documentos reais armazenados e a classificação usou o
FinBERT local. O contexto usou o CSV de preços já existente, com fechamentos
anteriores ao corte, posição informada sem exposição e venda a descoberto
desativada. Não foram enviados preços futuros. O horizonte foi de três pregões.
O modelo foi `jev-1.14.0`, com contrato `ibov-memory-trading-v3-semantic`.

Na terceira atualização, o Banco Central teve timeout de DNS. O erro foi
registrado em `news_update`, com `complete=false` e `status=source_errors`;
InfoMoney e Money Times responderam, sem novidades. A previsão foi concluída.
Esse episódio confirma o tratamento de falha parcial, mas não confirma ausência
de publicações no Banco Central naquela terceira consulta.

Estados, decisões e verificação dos hashes estão em
`dados_noticias/teste_agente_noticias_reais/`, fora do versionamento.

## Testes e limites

`.venv/bin/python -m unittest -v`: **100 testes passaram**. A suíte verifica
fontes simuladas, reexecução sem escrita nos bancos, duplicatas e revisões,
preservação de resultados desconhecidos, disponibilidade temporal, retomada após
falha de classificação, falhas parciais e recuperação após dias sem execução.
Permanecem avisos de depreciação de dependências, sem falhas nos testes.

O teste real demonstra funcionamento operacional. Não mede acurácia financeira,
lucro ou vantagem da memória. Os escores do Jev não são probabilidades calibradas
de retorno. Não há tarefa em segundo plano: a atualização ocorre ao executar
`prever`; importações, reflexões, XGBoost e avaliações históricas conservam seus
fluxos próprios. A rotina não calcula automaticamente resultados futuros das
novas notícias; o ciclo de resultados observados continua separado.
