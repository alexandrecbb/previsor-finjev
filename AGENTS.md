# Orientações para agentes

## Contexto e estrutura

Este projeto Python classifica a direção futura do fechamento do Ibovespa usando indicadores técnicos e XGBoost.

- `previsor_ibovespa_versão_xgboost_pynb.py`: coleta OHLCV, suavização, indicadores, alvos, seleção de atributos, validação temporal e previsão.
- `test_previsor.py`: testes de regressão com `unittest`, dados sintéticos e mocks do Yahoo Finance.
- `requirements.txt`: dependências e intervalos de versões.
- `README.md`: instalação, execução e descrição do comportamento.

## Ambiente e comandos

Use o ambiente `.venv` quando disponível. Para preparar um ambiente novo:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Execute os testes após alterações no código:

```bash
.venv/bin/python -m unittest -v
```

A execução completa exige rede e pode realizar uma busca de hiperparâmetros demorada:

```bash
.venv/bin/python 'previsor_ibovespa_versão_xgboost_pynb.py'
```

Prefira os testes sem rede para verificar mudanças. Para verificações pontuais do pipeline, use `raw_data`, reduza `n_iter` e desative gráficos com `show_plots=False`.

## Regras de implementação

- Preserve nomes públicos e o retorno `(metrics, prediction, probability)` de `run_ibov_pipeline`, salvo mudança explicitamente solicitada.
- Faça alterações pequenas e relacionadas ao pedido. Siga o estilo existente e escreva comentários e documentação em português.
- Não instale dependências durante a importação do módulo. Declare alterações de dependências em `requirements.txt`.
- Não versione `.venv`, caches, dados baixados ou artefatos de treinamento.
- Atualize o README quando alterar parâmetros, execução ou comportamento documentado.
## Integridade temporal e avaliação

- Conte o horizonte em registros de negociação, não em dias corridos.
- Mantenha ausentes os alvos cujo preço futuro ainda não é conhecido; não os converta em classe 0.
- Preserve a ordem cronológica e a lacuna equivalente ao horizonte entre treino e avaliação, inclusive na validação cruzada.
- Ajuste seleção de atributos e outros transformadores aprendidos dentro do `Pipeline`, usando apenas o treino de cada divisão.
- Mantenha indicadores causais: valores futuros não podem afetar atributos de datas anteriores.
- Separe métricas do teste histórico do ajuste final usado para a previsão mais recente. Não apresente testes sintéticos como evidência de desempenho financeiro.
- Preserve o tratamento de colunas simples e MultiIndex, históricos vazios, valores inválidos e dados insuficientes.
- Ao modificar essas regras, acrescente testes de regressão com dados sintéticos e mocks, sem depender da rede. Preserve sementes de aleatoriedade para reprodutibilidade.

## Entrega

Informe o que mudou e quais verificações foram executadas. Se algum teste falhar ou não puder ser executado, descreva a limitação sem afirmar que passou.
