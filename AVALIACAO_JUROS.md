# Comparação exploratória com mercados externos e Selic

Execução em 28/10/2026. Horizonte: três pregões. Histórico do Ibovespa:
31/10/2016 a 27/10/2026, com 2.481 registros e 2.429 datas elegíveis comuns.

Foram comparadas três configurações predefinidas, mantendo atributos relativos,
suavização 0,7, ausência do seletor, parada antecipada e ajuste do limiar.
Cada busca usou dez combinações e semente 42. As três validações cronológicas
externas contêm buscas temporais internas; todas preservam lacuna de três registros.

Os quatro mercados são dólar/real, S&P 500, VIX e Brent (Yahoo Finance).
Os juros são a meta Selic brasileira, série SGS 432 do Banco Central, em % a.a.
Atributos de juros: nível e mudanças em pontos percentuais em uma e 30 observações
diárias da fonte. Todos os dados externos são alinhados exclusivamente a datas
anteriores à data-base brasileira, com validade máxima de sete dias.

## Resultados

| Configuração | Acurácia média na validação | Acurácia no teste | Acurácia balanceada no teste | ROC AUC | Previsões de alta |
|---|---:|---:|---:|---:|---:|
| Sem externos | 53,55% | 52,96% | 50,00% | 0,5328 | 100,00% |
| Dólar, S&P 500, VIX e Brent | 53,47% | 47,04% | 50,00% | 0,5328 | 0,00% |
| Quatro mercados + Selic | 53,71% | 52,96% | 54,60% | 0,5443 | 22,72% |

A configuração com Selic venceu a seleção pela acurácia média de validação.
O teste contém 810 observações, de 26/07/2023 a 22/10/2026. A referência de
prever sempre alta acertou 429/810 (52,96%). Com Selic, foram igualmente
429 acertos, mas com decisões diferentes: 184 previsões de alta e 626 de não alta.
A acurácia balanceada é a média das taxas de acerto de cada classe.

Não houve ganho de acurácia total sobre a referência. A inclusão da Selic
melhorou o equilíbrio entre classes nesta rodada. Isso não comprova um ganho
reproduzível: o intervalo descritivo de 95% por bootstrap em blocos de dez
observações para a diferença de acurácia contra a referência foi de
-8,77 a +8,27 pontos percentuais, incluindo zero.

## Limitações e reprodução

O período de teste já foi usado na avaliação anterior. Nesta rodada todas as
três configurações predefinidas foram medidas nele para comparação exploratória;
não é uma nova confirmação independente. A busca foi reduzida a dez combinações
por execução, em vez das 50 padrão. Não houve avaliação de retorno financeiro,
custos de negociação ou calibração das probabilidades. A Selic representa a
meta de juros, não a curva de juros futuros. Downloads podem sofrer revisões.
Nenhum padrão do pipeline foi alterado com base nesses resultados.

```bash
.venv/bin/python avaliar_juros.py
.venv/bin/python -m unittest -v
```

Os 23 testes automatizados passaram, incluindo alinhamento causal da Selic,
variações em pontos percentuais, download simulado, limite final exclusivo,
repetição após erro HTTP transitório e exclusão da Selic na variante de quatro
mercados. Os testes sintéticos verificam funcionamento, não desempenho financeiro.
O primeiro download real recebeu HTTP 502; a nova execução com repetição para
falhas transitórias completou o experimento.

As métricas completas, parâmetros e hashes dos dados estão em
[avaliacao_juros.json](avaliacao_juros.json). O script reproduz o protocolo com
corte de download exclusivo em 28/10/2026, mas revisões das fontes podem mudar
os resultados. Históricos baixados e modelos não são versionados.

Fonte dos juros: [Banco Central — meta Selic, SGS 432](https://dadosabertos.bcb.gov.br/dataset/432-taxa-de-juros---meta-selic-definida-pelo-copom).
