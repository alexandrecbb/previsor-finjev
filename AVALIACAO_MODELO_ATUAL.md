# Verificação do modelo padrão — 28/10/2026

O pipeline XGBoost padrão completou coleta, preparação dos indicadores, busca de
hiperparâmetros, avaliação histórica e reajuste para previsão recente sem erros.
A acurácia histórica foi **53,58%**, contra **52,96%** da referência que prevê
sempre alta: cinco acertos adicionais em 810 observações. Esse resultado não
demonstra uma vantagem preditiva consistente.

## Execução e dados

- Download real do Yahoo Finance: 2.481 registros, de 31/10/2016 a 27/10/2026.
- Horizonte de três registros de negociação; indicadores relativos, suavização
  0,7, sem seleção de atributos, sem notícias e sem mercados externos.
- Busca padrão com 50 combinações, três divisões temporais, semente 42,
  parada antecipada e ajuste do limiar no treino; duas tarefas em paralelo.
- Treino histórico: 1.616 observações, de 11/01/2017 a 20/07/2023.
- Teste histórico: 810 observações, de 26/07/2023 a 22/10/2026.
- Lacuna de três registros entre treino e teste e em cada divisão de validação.
- A chamada usada foi `run_ibov_pipeline(show_plots=False, n_jobs=2)`, com
  instrumentação apenas para registrar datas, métricas e matriz de confusão.

Os resultados detalhados e o hash do histórico estão em
[avaliacao_modelo_atual.json](avaliacao_modelo_atual.json).

## Desempenho no teste

| Medida | Resultado |
|---|---:|
| Acurácia | 53,58% (434/810) |
| Referência: sempre alta | 52,96% (429/810) |
| Diferença sobre a referência | +0,62 ponto percentual |
| Acurácia balanceada | 52,30% |
| Precisão da classe alta | 54,56% |
| Sensibilidade para alta | 73,89% |
| F1 da classe alta | 62,77% |
| ROC AUC | 0,5596 |
| Limiar escolhido no treino | 0,54 |

| Direção real / previsão | Não alta | Alta |
|---|---:|---:|
| Não alta | 117 | 264 |
| Alta | 112 | 317 |

O modelo previu alta em 581 dos 810 casos. As probabilidades de alta variaram
somente de 53,9906% a 55,0042%, muito próximas do limiar de 54%. A classificação
é sensível a pequenas mudanças nessas estimativas; elas não são calibradas.

Após medir o teste, o pipeline reajustou um modelo no histórico com alvo conhecido
e produziu uma previsão a partir de 27/10/2026: alta, com estimativa de 54,19%.
Essa previsão recente não entra na acurácia histórica e ainda não possui resultado
observado nesta execução.

## Verificação do processo

Comando executado: `.venv/bin/python -m unittest -v`.
**91 testes passaram em 7,201 segundos**, sem falhas. A suíte usa dados sintéticos
e mocks: verifica funcionamento, não desempenho financeiro.

Foram verificados pela suíte e pela leitura do código:

- alvos futuros desconhecidos preservados como ausentes;
- indicadores causais e formatos simples/MultiIndex do Yahoo;
- separação temporal dos alvos no teste e nas validações;
- seleção de atributos dentro do treino, quando ativada;
- divisão interna com lacuna para parada antecipada;
- ajuste do limiar sem consultar o teste;
- avaliação histórica anterior ao reajuste final;
- previsão na última data e tratamento de dados insuficientes ou inválidos.

Há avisos de compatibilidade futura de pandas/NumPy, incluindo a implementação
PSAR da dependência `ta` e cálculos temporais de notícias. Não impediram os testes
nem a execução real; não foram feitas alterações no código ou nas dependências.

## Limites da conclusão

O teste histórico já foi consultado em experimentos anteriores do projeto.
Esta execução confirma o comportamento atual, mas não constitui uma nova
validação independente. Os alvos de três pregões em datas consecutivas se
sobrepõem, portanto as 810 observações não são ensaios independentes.

A avaliação não mede retorno, custos ou lucro e não reexecuta o agente separado
de notícias FinBERT/Jev/memória. Para confirmar capacidade preditiva, é necessário
avaliar previsões registradas antes dos resultados em um período ainda não usado
nas escolhas do modelo. Nenhum parâmetro foi alterado com base neste teste.
