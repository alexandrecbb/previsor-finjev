# Comparação de suavização — três pregões

Execução em 28/10/2026. Foram comparadas três configurações sem dados externos:
indicadores com suavização exponencial (alpha 0,7), indicadores sem suavização
e combinação das duas versões. O horizonte é de três registros de negociação.

A combinação mantém os 25 atributos relativos existentes e acrescenta 15 versões
sem suavização: ADX, RSI, estocásticos K/D, CMF, MACD e sinal relativos, ATR relativo,
distâncias às médias 21/50 e PSAR, razão entre médias, posição/largura das bandas
e mudança de OBV. Retornos e outras medidas já calculadas no OHLCV original não
são duplicados. São 40 atributos no total. Não há seleção de atributos nesta rodada.

## Protocolo e resultados

Histórico: 31/10/2016 a 27/10/2026, 2.481 registros e 2.429 datas elegíveis comuns.
O hash do histórico coincide com a avaliação anterior de juros. Foram mantidos
três blocos cronológicos de validação externa, buscas internas de dez combinações,
semente 42, parada antecipada e ajuste de limiar apenas no treino. Todas as divisões
usam lacuna de três registros. A escolha é feita pela acurácia média na validação.

| Configuração | Acurácia média na validação | Acurácia no teste | Acurácia balanceada | ROC AUC | Previsões de alta |
|---|---:|---:|---:|---:|---:|
| Suavizados | 53,55% | 52,96% | 50,00% | 0,5328 | 100,00% |
| Sem suavização | 54,04% | 52,96% | 50,00% | 0,5644 | 100,00% |
| Combinados | 54,21% | 52,96% | 50,00% | 0,5241 | 100,00% |

A combinação venceu na validação, com desvio de 2,83 pontos percentuais entre
os três blocos. No teste, todas as configurações acertaram 429 de 810 observações,
de 26/07/2023 a 22/10/2026, prevendo alta em todos os casos. Portanto, não houve
ganho sobre a referência de sempre prever alta. Os limiares escolhidos foram
0,50 (suavizados), 0,51 (sem suavização) e 0,52 (combinados).

Os intervalos descritivos de ganho por bootstrap em blocos de dez observações
foram [0, 0], pois as decisões coincidiram com a referência em todos os casos.
Isso não significa ausência de incerteza sobre o desempenho futuro.

## Limitações e reprodução

O teste já foi consultado em rodadas anteriores; a comparação é exploratória,
não uma confirmação independente. A busca usa dez combinações em vez das 50
padrão. O resultado não demonstra vantagem financeira nem esgota outras formas
de combinar indicadores. Os padrões do pipeline permanecem inalterados.

```bash
.venv/bin/python avaliar_suavizacao.py
.venv/bin/python -m unittest -v
```

O script aceita `--horizon` e `--output`, mantendo o corte exclusivo de download
em 28/10/2026. As métricas, parâmetros e hash estão em
[avaliacao_suavizacao.json](avaliacao_suavizacao.json).

Os 25 testes automatizados passaram. Os novos testes verificam a preservação
das duas versões, a ausência de duplicação de retornos, a causalidade diante de
mudanças futuras e a comparação em datas comuns sem depender de dados externos.
Os testes sintéticos verificam funcionamento, não desempenho financeiro.
