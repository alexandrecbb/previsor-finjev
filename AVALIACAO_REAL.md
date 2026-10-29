# Avaliação com dados reais — horizonte de 3 pregões

Execução: 28/10/2026. Fonte: Yahoo Finance via yfinance. Histórico de 31/10/2016 a 27/10/2026, com 2.481 registros; 2.429 datas comuns com atributos e alvo conhecidos.

## Protocolo

- Dez configurações predefinidas, semente 42 e dez combinações aleatórias por busca XGBoost (quatro valores de C na regressão logística). A busca padrão do pipeline continua em 50; esta comparação usou orçamento reduzido de 10.
- Três validações externas cronológicas no desenvolvimento. Cada treino contém sua própria busca com três divisões, ajuste de limiar e validação interna para parada antecipada.
- Lacuna de três registros em todas as divisões. Todas as configurações usam exatamente as mesmas datas elegíveis.
- Escolha pela acurácia média de validação. Teste reservado: 26/07/2023 a 22/10/2026, com 810 observações. Só a vencedora e a referência predefinida foram avaliadas nesse teste.
- Dados externos: BRL=X, ^GSPC, ^VIX e BZ=F. Retornos de uma e cinco observações, volatilidade de 20 observações e nível do VIX. Somente datas estritamente anteriores à data brasileira; validade máxima de sete dias.

## Validação

| Configuração | Acurácia média | Desvio entre divisões |
|---|---:|---:|
| sem_suavizacao | 54.04% | 3.03% |
| logistica | 53.80% | 3.95% |
| relativos | 53.55% | 3.67% |
| com_seletor | 53.55% | 3.67% |
| limiar_fixo | 53.55% | 3.67% |
| relativos_externos | 53.47% | 3.78% |
| sem_suavizacao_externos | 53.47% | 3.78% |
| indicadores_originais | 53.22% | 4.10% |
| janela_756 | 53.14% | 3.25% |
| logistica_externos | 53.14% | 3.29% |

A referência de classe majoritária obteve média de 53,55% nas mesmas validações.

## Teste reservado

| Configuração | Acurácia | Acurácia balanceada | ROC AUC | Previsões de alta |
|---|---:|---:|---:|---:|
| sem_suavizacao | 52.96% | 50.00% | 0.5644 | 100% |
| relativos | 52.96% | 50.00% | 0.5328 | 100% |

**Não houve ganho de acurácia sobre a referência de prever sempre alta: ambas acertaram 429 de 810 observações (52,96%).** A configuração vencedora na validação também previu alta em todas as datas do teste. AUC acima de 0,5 não se converteu em decisões melhores no limiar escolhido.

Os intervalos pareados por bootstrap em blocos de dez observações resultaram em [0, 0] para o ganho sobre a referência, porque as decisões foram idênticas. Isso não significa ausência de incerteza sobre desempenho futuro.

Os dados externos não melhoraram a acurácia média nas três comparações pareadas (relativos, sem suavização e regressão logística). As variantes externas não foram avaliadas no teste final, pois não venceram a seleção. Sua utilidade futura não está descartada por este experimento.

Não foram alterados automaticamente os padrões de suavização nem ativados dados externos por padrão. A escolha entre configurações foi feita por acurácia; o resultado expõe a preferência por classe majoritária. Uma próxima pesquisa deve predefinir critérios adicionais de equilíbrio entre classes e usar novo período reservado, pois este teste agora já foi consultado.

## Reprodutibilidade e limites

```bash
.venv/bin/python avaliar_configuracoes.py --horizon 3 --n-iter 10 --n-jobs 2 --end 2026-10-28
```

O arquivo `avaliacao_real.json` contém métricas por divisão, parâmetros, datas, fontes e hashes SHA-256 dos dados usados. Os históricos não são versionados. Downloads futuros podem mudar por revisões do provedor. Os contratos de Brent podem conter efeitos de rolagem. A defasagem diária evita antecipação de fechamentos, mas não constitui uma base histórica com todas as revisões arquivadas. Não foi simulado retorno financeiro nem custo de negociação.
