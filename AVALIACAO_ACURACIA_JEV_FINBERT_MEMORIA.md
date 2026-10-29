# Jev + FinBERT-PT-BR: memória versus sem memória

## Resultado

Teste pareado em **24 datas, concluído sem erros**, com o mesmo Jev e sentimento
FinBERT-PT-BR em ambas as condições. Cada data usa a mesma notícia, o mesmo
corte e o mesmo contexto de mercado.

| Medida | FinBERT + Jev, sem memória | FinBERT + Jev, com memória |
|---|---:|---:|
| Respostas direcionais | 4/24 | 6/24 |
| Manter (sem previsão direcional) | 20 | 18 |
| Acertos direcionais | 3/4 (75.0%) | 4/6 (66.7%) |
| Acertos nas 24 datas | 3/24 (12.5%) | 4/24 (16.7%) |
| Acurácia balanceada nas respostas direcionais | 75.0% | 66.7% |

Em comum, ambas as versões deram previsão direcional em **1 das 24 datas**,
e ambas acertaram nessa data. Assim, o desempenho comum é **1/1 para cada versão**;
esse caso isolado não é evidência de superioridade. Nos demais casos, a versão
com memória emitiu duas respostas direcionais a mais. A precisão entre essas
respostas foi menor: 66,7% com memória e 75,0% sem memória.

Como referência simples, prever sempre alta acertou 13/24 (54,2%). A acurácia
direcional responde apenas pelos casos em que Jev não escolheu manter; esse número
da referência não representa retorno ou lucro de uma carteira.

**Conclusão:** neste piloto, a memória aumentou um pouco a quantidade de previsões,
mas os dados não mostram que tenha melhorado a acurácia. Em 18 e 20 das datas,
respectivamente, o Jev escolheu manter, reduzindo a amostra efetiva para quatro
e seis previsões direcionais. Os intervalos de Wilson de 95% são amplos e se
sobrepõem: 30.1%–95.4% sem memória,
30.0%–90.3% com memória.

## Protocolo

- FinBERT-PT-BR fixado na revisão `c3bf75c85f9b1b0dd257d688822d64390420936c`;
  classe e três escores foram calculados antes do Jev e preservados nas duas condições.
- Jev `jev-1.14.0`, com ações comprar, vender ou manter, horizonte de três pregões,
  aquecimento de 90 dias e até três memórias recuperadas.
- Amostra temporal determinística e pareada, sem usar os resultados para selecionar
  notícias. Houve 24 pares completos e 48 chamadas novas ao Jev; nenhuma falhou.
- Sem memória, todas as memórias históricas são excluídas da consulta. Com memória,
  episódios disponíveis antes do corte podem ser recuperados. O sentimento atual
  e o contexto são iguais nas duas versões.
- O sentido observado compara fechamento a três registros de negociação futuros.
  Manter não conta como acerto ou erro direcional.
- Dados e previsões completos, além dos hashes do conjunto de notícias e preços,
  constam em `dados_noticias/avaliacao_finbert_memoria_24/avaliacao.json`.

## Limites

A amostra tem apenas quatro e seis respostas direcionais, e somente uma data em que
ambos os sistemas previram uma direção. O resultado é retrospectivo: os textos foram
coletados e classificados hoje, e o pré-treinamento do Jev pode conter informação
posterior aos cortes. As matérias podem ter sido revisadas; a seleção de fontes é
limitada a InfoMoney e Money Times; o intervalo de Wilson não corrige dependência
temporal. O teste compara classificação direcional e não simula lucro, custos de
negociação, nem isola o efeito do sentimento contra uma condição sem FinBERT.

A classificação positiva, negativa ou neutra descreve o texto; não é um rótulo do
movimento futuro. Este piloto não demonstra desempenho financeiro nem vantagem
confiável da memória. Uma confirmação exige previsões prospectivas, registradas
antes dos resultados, e amostra maior de decisões que não sejam manter.
