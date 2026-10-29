# Comparação exploratória — horizonte de sete pregões

Execução em 28/10/2026, repetindo as três configurações da avaliação de três
pregões. Fonte: Yahoo Finance e meta Selic SGS 432 do Banco Central.
Histórico do Ibovespa de 31/10/2016 a 27/10/2026, com 2.481 registros;
2.425 datas elegíveis comuns às três configurações.

## Protocolo

- Alvo: fechamento estritamente maior após sete registros de negociação.
- Lacunas de sete registros entre treino e avaliação, inclusive nas validações
  internas, busca de parâmetros e parada antecipada.
- Três validações temporais externas, dez combinações por busca, semente 42.
- Atributos relativos, suavização 0,7, sem seletor, com ajuste de limiar.
- Dados externos estritamente anteriores à data-base: dólar/real, S&P 500,
  VIX, Brent; variante adicional com nível e variações da meta Selic.
- Configuração escolhida pela média de acurácia de validação. Todas as variantes
  predefinidas avaliadas no teste para comparação exploratória.

## Resultados

| Configuração | Acurácia média na validação | Acurácia no teste | Acurácia balanceada | ROC AUC | Previsões de alta |
|---|---:|---:|---:|---:|---:|
| Sem externos | 55,14% | 52,16% | 49,57% | 0,5718 | 98,76% |
| Dólar, S&P 500, VIX e Brent | 55,14% | 52,66% | 50,00% | 0,5234 | 100,00% |
| Quatro mercados + Selic | 55,56% | 52,66% | 50,00% | 0,5366 | 100,00% |

Teste: 809 observações de 21/07/2023 a 16/10/2026. A referência de prever
sempre alta acertou 426/809 (52,66%). Sem externos houve 422 acertos;
as duas variantes externas acertaram 426 e previram alta em todos os casos.

A variante com Selic venceu na validação, mas não superou a referência no teste.
O intervalo descritivo por bootstrap em blocos de dez observações para o ganho
sobre a referência foi [0, 0] em ambas as variantes externas porque suas decisões
foram idênticas às da referência; isso não elimina a incerteza sobre o futuro.
Sem externos, o intervalo foi de -1,85 a +0,62 ponto percentual.

## Comparação com três pregões e limitações

Com os cinco dados externos, a rodada de três pregões teve 52,96% de acurácia
e 54,60% de acurácia balanceada; nesta rodada, 52,66% e 50,00%, respectivamente.
O equilíbrio entre as classes observado com três pregões não se manteve.
Alvos e datas elegíveis mudam com o horizonte, portanto as porcentagens não
constituem uma comparação pareada sobre o mesmo problema.

A rodada é exploratória: o período histórico se sobrepõe ao teste já consultado.
Não demonstra vantagem financeira nem confirma um horizonte ótimo. A busca é
reduzida a dez combinações; não foram avaliados custos ou retornos de negociação.
Os padrões de previsão e os relatórios anteriores foram preservados.

## Reprodução e verificações

```bash
.venv/bin/python avaliar_juros.py --horizon 7
.venv/bin/python -m unittest -v
```

Os 23 testes automatizados passaram. O script agora aceita `--horizon` e
`--output`; o arquivo padrão para esta rodada é
[avaliacao_juros_7pregoes.json](avaliacao_juros_7pregoes.json), contendo parâmetros,
métricas por divisão, fontes e hashes dos dados. Os testes sintéticos verificam
funcionamento, não desempenho financeiro.
