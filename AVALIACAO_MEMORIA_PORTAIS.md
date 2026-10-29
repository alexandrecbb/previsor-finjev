# Jev com memória: avaliação nas notícias dos portais

Execução em 28/10/2026, com `jev-1.14.0`, horizonte de **três pregões** e
9.590 textos do snapshot ativo (6.181 InfoMoney e 3.409 Money Times).
Agência Brasil, GDELT e Banco Central não entraram neste experimento.

## Resultado

Foram concluídas **24 comparações pareadas, sem erros**, com 48 decisões.

| Medida | Sem memória | Com memória |
|---|---:|---:|
| Respostas direcionais | 14/24 | 19/24 |
| Abstenções | 10 | 5 |
| Cobertura | 58,3% | 79,2% |
| Acertos entre respostas direcionais | 9/14 (64,3%) | 12/19 (63,2%) |
| Acurácia balanceada entre respostas | 62,5% | 62,8% |
| Acertos nos 14 casos respondidos por ambos | 9/14 (64,3%) | 10/14 (71,4%) |
| Acertos divididos pelas 24 consultas | 37,5% | 50,0% |

Nos casos comuns, a memória corrigiu um erro e manteve os outros 13 resultados.
Nas cinco respostas adicionais, acertou duas e errou três. A redução de abstenções
não veio acompanhada de melhora na precisão agregada das respostas direcionais.
A diferença nos casos comuns depende de **um único acerto adicional**.

Prever sempre alta acertaria 13/24 (54,2%), respondendo a todas as consultas;
nos 14 casos respondidos por ambas as versões, acertaria 6/14 (42,9%).
Assim, a maior precisão condicional do Jev não implica mais acertos no total:
com memória foram 12 acertos e cinco abstenções, contra 13 acertos da referência.
Não foi simulada operação financeira, lucro ou custo de negociação.

**As memórias ajudaram a produzir mais respostas e corrigiram um caso, mas este
piloto não demonstra melhora confiável da previsão do mercado.** Os intervalos
descritivos de Wilson de 95% são amplos: 38,8%–83,7% sem memória e 41,0%–80,9%
com memória, entre respostas direcionais de cada versão.

## Protocolo e integridade temporal

- Aquecimento inicial de 90 dias; não houve alteração dos padrões de previsão.
- Cortes avaliados de 27/01/2026 a 23/10/2026: 11 notícias de InfoMoney e 13 de
  Money Times, selecionadas deterministicamente sem usar o sinal dos alvos.
- Janelas de três registros de negociação sem sobreposição.
- Mesma notícia atual e mesmo contexto de preços em cada par; até 4.000 caracteres
  por texto e três memórias recuperadas em todas as consultas com memória.
- A recuperação usa similaridade textual, recência e importância. Somente textos
  anteriores ao corte são elegíveis; resultados históricos só aparecem após seu
  horário de disponibilidade. O evento atual é excluído pelo identificador.
- O alvo atual não entra no contexto enviado ao Jev. A cauda sem preço futuro
  permanece sem alvo e não pode ser selecionada para avaliação.
- Sem reflexões retrospectivamente inventadas, seleção por acertos ou ajuste de
  hiperparâmetros sobre esses resultados. O teste mede episódios recuperados,
  não aprendizado por reflexões nem ganho incremental sobre o XGBoost.

O aquecimento menor é explícito porque o requisito anterior de 365 dias não
permite avaliar utilmente esta base de apenas 12 meses. Não comparar diretamente
com o piloto anterior, que usava outras fontes, datas e condições.

## Limitações

Amostra de 24 datas, com apenas 14 respostas comuns. Textos coletados hoje podem
ter sido revisados, e o pré-treinamento do Jev pode conter eventos posteriores
aos cortes. Notícias de URLs diferentes sobre o mesmo acontecimento não têm
agrupamento semântico geral; excluir o event_id atual não resolve todas as
republicações. O corpus resulta de busca por Ibovespa, sem triagem manual completa.
Os intervalos são descritivos e não corrigem dependência entre datas de mercado.

O próximo teste confirmatório deve registrar previsões com e sem memória antes
dos resultados futuros, mantendo o protocolo fixo. Este piloto não estabelece
que o mesmo ganho ocorrerá em novas notícias.

## Artefatos e verificações

- [Métricas, previsões e hashes](avaliacao_memoria_portais.json), sem textos nem credenciais.
- Snapshot, SQLite com os estados e respostas: `dados_noticias/avaliacao_portais_90dias/`.
- Preços reais reutilizados de `dados_noticias/historico/precos_ibov.csv`, até 27/10/2026.
- Comando reproduzível documentado no README; reexecução retoma decisões persistidas.
- `.venv/bin/python -m unittest -v`: **63 testes passaram**. Incluem regressão
  do aquecimento curto, ausência de sobreposição e preservação do padrão anual.
  Houve avisos de dependências; esses testes sintéticos não medem desempenho financeiro.

## Decisões individuais

| Corte local | Fonte | Observado | Sem memória | Com memória |
|---|---|---|---|---|
| 2026-01-27 | infomoney | Alta | Abstenção | Alta |
| 2026-01-31 | moneytimes | Alta | Baixa/igual | Baixa/igual |
| 2026-02-06 | moneytimes | Alta | Abstenção | Abstenção |
| 2026-02-12 | infomoney | Baixa/igual | Alta | Alta |
| 2026-02-21 | moneytimes | Alta | Alta | Alta |
| 2026-02-27 | infomoney | Baixa/igual | Abstenção | Baixa/igual |
| 2026-03-05 | moneytimes | Baixa/igual | Abstenção | Alta |
| 2026-03-11 | infomoney | Baixa/igual | Baixa/igual | Baixa/igual |
| 2026-03-17 | moneytimes | Alta | Baixa/igual | Alta |
| 2026-03-21 | moneytimes | Alta | Baixa/igual | Baixa/igual |
| 2026-03-27 | infomoney | Alta | Abstenção | Baixa/igual |
| 2026-04-02 | infomoney | Alta | Alta | Alta |
| 2026-04-11 | moneytimes | Alta | Alta | Alta |
| 2026-04-17 | moneytimes | Baixa/igual | Alta | Alta |
| 2026-04-24 | infomoney | Baixa/igual | Baixa/igual | Baixa/igual |
| 2026-04-30 | infomoney | Alta | Abstenção | Abstenção |
| 2026-05-09 | moneytimes | Baixa/igual | Baixa/igual | Baixa/igual |
| 2026-06-03 | moneytimes | Baixa/igual | Baixa/igual | Baixa/igual |
| 2026-06-30 | infomoney | Baixa/igual | Abstenção | Abstenção |
| 2026-07-22 | infomoney | Alta | Abstenção | Baixa/igual |
| 2026-08-14 | infomoney | Baixa/igual | Baixa/igual | Baixa/igual |
| 2026-09-05 | moneytimes | Alta | Abstenção | Abstenção |
| 2026-10-01 | moneytimes | Alta | Abstenção | Abstenção |
| 2026-10-23 | moneytimes | Baixa/igual | Baixa/igual | Baixa/igual |
