# Previsor Ibovespa com XGBoost

Modelo de classificação para prever a tendência de alta ou baixa do IBOVESPA em uma data alvo futura.
A classe 0 inclui queda e estabilidade. O horizonte conta registros de negociação,
não dias corridos. O download padrão exclui o dia atual para evitar uma vela em formação.

O projeto também oferece um agente contextual inspirado no FinMem e adaptado
ao Brasil: **notícias → sentimento FinBERT-PT-BR → memórias → Jev → comprar,
vender ou manter**. Esse fluxo tem entrada própria em `memoria_noticias.py`;
o pipeline XGBoost e seu retorno público continuam disponíveis separadamente.

## Organização do código

```text
ibov/
    __init__.py        # API de entrada do pacote
    config.py          # Constantes e hiperparâmetros
    dados.py           # Download e validação dos históricos
    atributos.py       # Suavização, indicadores, alvo e dados externos
    modelo.py          # Seleção, treinamento e ajuste do limiar
    avaliacao.py       # Divisões temporais, métricas e gráficos
    pipeline.py        # Coordenação das etapas
    sentimento.py      # FinBERT-PT-BR local, lotes e cache
    memoria.py         # Episódios, recuperação temporal e reflexões
    decisao_noticias.py # Decisão comprar/vender/manter pelo Jev
classificar_finbert.py                 # Enriquece notícias JSONL com sentimento
previsor_ibovespa_versão_xgboost_pynb.py  # Entrada de execução e imports compatíveis
avaliar_configuracoes.py                # Comparação de configurações
test_previsor.py                       # Testes sem rede
```

Em código Python, a entrada recomendada é:

```python
from ibov import run_ibov_pipeline

metrics, prediction, probability = run_ibov_pipeline(horizon=3, show_plots=False)
```

O arquivo original continua executável e reexporta as funções, classes e constantes
próprias do projeto para manter os imports anteriores. As implementações ficam nos
módulos do pacote; mocks devem apontar para o módulo que utiliza a dependência.
As configurações padrão ficam em `ibov/config.py`; prefira os parâmetros de
`run_ibov_pipeline` para mudar horizonte e opções em cada execução.
Importar o pacote ou o arquivo de entrada não baixa dados nem inicia treinamento.

## Executar

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python 'previsor_ibovespa_versão_xgboost_pynb.py'
```

Em Debian/Ubuntu, caso a criação do ambiente falhe por ausência de `ensurepip`,
instale o pacote `python3-venv` correspondente à versão do Python.
No Colab, instale as dependências com `%pip install -r requirements.txt` antes de
executar o código. A execução normal precisa de acesso ao Yahoo Finance.

## Correções

- Normalização das colunas simples ou MultiIndex do Yahoo e validação de histórico vazio.
- Dependências explícitas; importar o módulo não tenta instalar pacotes automaticamente.
- Alvos futuros desconhecidos permanecem ausentes, em vez de receberem classe 0.
- Lacuna equivalente ao horizonte, em registros antes do teste e de cada validação para que os preços usados
  nos alvos do treino não alcancem os períodos avaliados.
- Seleção de indicadores dentro do `Pipeline`, ajustada em cada treino da validação.
- Métricas calculadas no teste reservado. Depois, um novo ajuste usa todo o histórico
  com alvo conhecido para prever a partir do último pregão disponível.
- Tratamento de indicadores inválidos, históricos curtos e períodos com uma única classe.
- Paralelismo na busca; cada XGBoost usa uma thread para evitar excesso de threads.

`run_ibov_pipeline()` retorna `(metrics, prediction, probability)`: as métricas são
do teste histórico; os dois arrays são da previsão mais recente, com formatos `(1,)`
e `(1, 2)`. As colunas de probabilidade representam não alta e alta, respectivamente.
A probabilidade exibida é uma estimativa do classificador, sem calibração adicional.

## Verificar

```bash
python -m unittest -v
```

Os testes usam dados sintéticos, sem rede, e executam o XGBoost com uma combinação
de parâmetros. Eles verificam os alvos desconhecidos, as datas dos treinos e das
validações, os formatos do Yahoo, a causalidade dos indicadores e a previsão recente.
Esses testes verificam o funcionamento do código; não medem seu desempenho no mercado.

Referências: [formato do download do yfinance](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html),
[lacuna temporal do scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
e [seleção de atributos sem vazamento](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage-during-pre-processing).

## Configuração e experimentos

`run_ibov_pipeline(horizon=3)` preserva o retorno `(metrics, prediction, probability)`.
O horizonte conta pregões e pode ser alterado em cada chamada.

- `feature_set="relative"` (padrão): distâncias percentuais, retornos, volatilidade e volume relativo; `"legacy"` usa os 14 indicadores anteriores e `"combined"` combina ambos.
- `alpha=0.7`: suavização atual; `alpha=None` calcula indicadores sem suavização.
- `select_features=False`: usa todos os atributos; `True` ativa o seletor dentro de cada treino.
- `tune_threshold=True`: ajusta o limiar usando previsões das validações temporais do treino. `False` mantém 0,5.
- `early_stopping=True`: escolhe o número de árvores numa divisão interna temporal de 80/20, com lacuna igual ao horizonte; depois reajusta no treino recebido. O seletor também respeita essa divisão.
- `model_type="xgb"`; `"logistic"` permite comparar regressão logística com padronização dentro do pipeline.
- `max_train_size=None`: histórico completo; um inteiro de pelo menos 100 limita a janela de treino e o ajuste final.

A busca otimiza acurácia. O teste final permanece no último terço do histórico.
As métricas incluem `baseline_accuracy` (classe majoritária do treino) e `threshold`.
O limiar escolhido no treino também é aplicado à previsão recente; as probabilidades
continuam sem calibração. Compare alternativas nas validações de desenvolvimento,
sem escolher repetidamente configurações pelo teste final.

As novas opções são hipóteses de melhoria, não garantia de ganho. Dados externos são opcionais, conforme descrito abaixo. Testes sintéticos verificam funcionamento e causalidade,
não desempenho financeiro.

## Dados externos e comparação com histórico real

Ative os quatro mercados externos com:

```python
metrics, prediction, probability = run_ibov_pipeline(
    horizon=3, use_external=True, show_plots=False
)
```

São coletados dólar/real (`BRL=X`), S&P 500 (`^GSPC`), VIX (`^VIX`) e Brent
(`BZ=F`). Cada data brasileira recebe somente fechamentos externos de datas
anteriores, respeitando feriados e um limite de sete dias de defasagem. Nenhum
valor futuro preenche lacunas. Falhas de download são explícitas; indicadores
externos incompletos na última data impedem a previsão.

Para execução sem rede, forneça `raw_data` e `external_data`, um dicionário de
Series de fechamentos indexadas por datas locais, únicas, ordenadas e sem fuso.
`external_data` fornecido ativa os atributos externos mesmo sem `use_external`.
As séries precisam incluir aquecimento de pelo menos 20 observações anteriores.

```bash
.venv/bin/python avaliar_configuracoes.py --horizon 3 --n-iter 10 --n-jobs 2
```

O script compara dez configurações com validação temporal aninhada, datas comuns
e teste final reservado. O relatório JSON contém resultados por divisão, parâmetros,
fontes e hashes dos dados. A execução baixa os históricos novamente; revisões do
provedor podem alterar resultados. Nenhum modelo ou histórico baixado é versionado.

Consulte [a avaliação realizada](AVALIACAO_REAL.md) e [as métricas completas](avaliacao_real.json).
No experimento de 28/10/2026, a vencedora teve 52,96% de acurácia no teste, empatando
com prever sempre alta. Não foi demonstrado ganho com dados externos. Os padrões
não foram alterados automaticamente com base nesse resultado.

### Experimento com juros brasileiros

```bash
.venv/bin/python avaliar_juros.py
```

Compara três configurações XGBoost: sem externos, com dólar/S&P 500/VIX/Brent,
e com esses quatro mercados mais a meta Selic do Banco Central
([SGS 432, % ao ano](https://dadosabertos.bcb.gov.br/dataset/432-taxa-de-juros---meta-selic-definida-pelo-copom)).
A Selic entra como nível e mudanças em pontos percentuais em uma e 30 observações
diárias da fonte, sempre de datas estritamente anteriores à data-base.
O download usa consultas anuais e limite final exclusivo, sem dependências novas.
Para usar juros em uma previsão, acrescente a série retornada por
`ibov.dados.fetch_interest_data(start, end)` ao dicionário `external_data`, com a chave
`"selic"`, juntamente com as quatro séries de `fetch_external_data`.

O experimento usa horizonte de três pregões, dez combinações por busca, três
validações temporais e datas elegíveis comuns. Mantém suavização e ajuste do limiar
iguais nas três configurações para isolar o efeito dos dados externos. O corte de
download é 28/10/2026 (exclusivo), o mesmo da avaliação anterior. Todas as três
configurações são medidas no teste para comparação exploratória: esse período já
foi consultado e não representa uma nova confirmação independente. O relatório é
salvo em `avaliacao_juros.json`; os padrões de previsão não são alterados.

Resultado desta rodada: com Selic, 52,96% de acurácia e 54,60% de acurácia
balanceada no teste; sem ganho de acurácia sobre prever sempre alta. Consulte
[relatório com juros](AVALIACAO_JUROS.md) e [métricas completas](avaliacao_juros.json).

Para repetir a mesma comparação com horizonte de sete pregões:

```bash
.venv/bin/python avaliar_juros.py --horizon 7
```

`--horizon` ajusta o alvo e as lacunas temporais em todas as etapas. O padrão
continua em três pregões. Para outros horizontes, o nome automático é
`avaliacao_juros_<horizonte>pregoes.json`, preservando o relatório anterior.
Use `--output caminho.json` para escolher outro destino. O corte do download,
as três configurações e o orçamento da busca permanecem iguais.

Na rodada de sete pregões, as duas variantes externas acertaram 52,66%,
prevendo alta em todos os casos e empatando com a referência. Sem externos,
a acurácia foi de 52,16%. Veja o [relatório de sete pregões](AVALIACAO_JUROS_7PREGOES.md)
e as [métricas completas](avaliacao_juros_7pregoes.json).

### Comparação de indicadores com e sem suavização

```bash
.venv/bin/python avaliar_suavizacao.py
```

Compara suavização exponencial (`alpha=0.7`), ausência de suavização (`alpha=None`)
e a combinação dos dois, sem dados externos. Usa três pregões, dez combinações
por busca e o mesmo corte exclusivo de download em 28/10/2026. Aceita `--horizon`
e `--output`, salvando por padrão `avaliacao_suavizacao.json` para três pregões
ou `avaliacao_suavizacao_<horizonte>pregoes.json` para outros horizontes.

A opção `feature_set="dual_smoothing"` de `run_ibov_pipeline` mantém os atributos
relativos suavizados e acrescenta 15 indicadores sem suavização com sufixo
`_unsmoothed`, totalizando 40 atributos. Retornos e medidas já calculadas nos dados
originais não são duplicados. Essa opção exige `alpha` diferente de `None`.
Ela é distinta de `feature_set="combined"`, que combina indicadores relativos e
níveis absolutos, sob uma única escolha de suavização.

A combinação teve 54,21% de acurácia média na validação, mas as três versões
empataram no teste em 52,96%, prevendo sempre alta. Consulte o
[relatório de suavização](AVALIACAO_SUAVIZACAO.md) e as
[métricas completas](avaliacao_suavizacao.json). A comparação é exploratória e
não alterou os padrões de previsão.

### Notícias classificadas pelo Jev (opcional)

A integração usa a [API oficial TypeSafe](https://api.typesafe.ai/redoc),
`POST /v1/systemone`, com modelo fixado em `jev-1.14.0`. Classifica o conteúdo
como favorável, desfavorável ou neutro para ações brasileiras e identifica temas
de juros, inflação e risco fiscal. Essas probabilidades descrevem o texto;
não são probabilidades de alta ou baixa do índice.

A credencial é lida de `TYPESAFE_API_KEY` ou, como alternativa local, de
`.secrets/jev_api_key`. Nunca inclua a chave em código, exemplos ou argumentos
na linha de comando. `.secrets/`, `.env*`, `.cache/` e `dados_noticias/` estão
excluídos pelo `.gitignore`. O arquivo local da chave deve ter permissão `600`.
Não há novas dependências nem chamadas de rede durante a importação.

Prepare um CSV UTF-8 em `dados_noticias/entrada.csv`, com as colunas:

| Campo | Conteúdo |
|---|---|
| `id` | Identificador único da notícia |
| `text` | Texto disponível na data registrada, sem revisões posteriores |
| `published_at` | Publicação com fuso, por exemplo `2026-10-20T15:00:00-03:00` |
| `available_at` | Quando essa versão do texto ficou disponível para o sistema, com fuso |

A classificação aceita textos e horários fornecidos em CSV. Para coleta
histórica, consulte a seção de coleta e piloto com notícias reais abaixo. Não trate a data de publicação como prova de que
um texto revisado posteriormente estava disponível naquela data.

```bash
.venv/bin/python classificar_noticias.py dados_noticias/entrada.csv --max-requests 100
```

O comando salva `dados_noticias/classificadas.csv`. Há uma chamada por texto
inédito, com cache em `.cache/jev` identificado pelo conteúdo, perguntas e modelo.
O limite é verificado antes das chamadas. Para outros destinos/modelos, use
`--output` e `--model`. Falhas de API são explícitas; não viram sentimento neutro.
O cache e a saída contêm probabilidades, identificador, modelo, versão das
perguntas, hash e horários, sem texto nem credencial. O texto é enviado à TypeSafe.

```python
import pandas as pd
from ibov import run_ibov_pipeline

news = pd.read_csv("dados_noticias/classificadas.csv")
metrics, prediction, probability = run_ibov_pipeline(
    horizon=3, news_data=news, show_plots=False,
)
```

Os atributos são a quantidade de notícias e as médias das seis probabilidades
nos sete dias corridos anteriores à meia-noite de cada data-base em São Paulo.
Notícias do próprio dia são excluídas conservadoramente. Por padrão, publicação,
disponibilidade do texto e classificação devem anteceder o corte. Notícias
antigas classificadas hoje não são consideradas disponíveis no passado.
Sem notícias elegíveis, os atributos são zero e a contagem indica ausência;
isso não comprova que a coleta esteve funcionando nem equivale a sentimento neutro.

Para estudar um histórico classificado posteriormente, `retrospective_news=True`
ignora apenas o horário da classificação, preservando publicação e disponibilidade.
Esse modo é exploratório: o pré-treinamento do Jev pode incluir eventos futuros
em relação ao histórico, mesmo que os horários dos textos sejam corretos.
Use um único modelo e versão de perguntas por experimento. O horizonte do alvo
continua sendo medido em pregões; a janela de notícias usa dias corridos.

A comparação temporal com e sem notícias está disponível sem chamadas adicionais
à API (use um histórico classificado que cubra treino e avaliação):

```python
from avaliar_configuracoes import evaluate

# raw: OHLCV do Ibovespa no formato esperado pelo pipeline.
report = evaluate(
    raw, None, horizon=3, n_iter=10, n_jobs=2,
    configurations={"sem_noticias": {}, "com_jev": {"news": True}},
    news_data=news, retrospective_news=True,
)
```

A API foi verificada com um texto fictício, e os testes automatizados usam mocks.
Isso não demonstra melhoria financeira. Ainda é necessário um histórico de notícias
com cobertura adequada para comparar os modelos; para confirmação independente,
prefira coleta e avaliação prospectivas. O retorno do pipeline e seus padrões
permanecem inalterados quando `news_data` não é fornecido.

### Sentimento local com FinBERT-PT-BR

Usamos [lucas-leme/FinBERT-PT-BR](https://huggingface.co/lucas-leme/FinBERT-PT-BR),
com revisão padrão fixada em `c3bf75c85f9b1b0dd257d688822d64390420936c`.
O mapeamento é **0=positivo, 1=negativo, 2=neutro**, conforme o autor; não
reutilizamos a ordem de classes do FinBERT em inglês. A inferência usa softmax
nos logits, em CPU, modo de avaliação e sem gradientes. São considerados os
primeiros 512 tokens de cada notícia, com truncamento explícito registrado na saída.
Textos longos não são analisados integralmente.

As dependências estão em `requirements.txt`. Para uma instalação somente CPU,
pode-se instalar primeiro o PyTorch e depois os demais requisitos:

```bash
.venv/bin/python -m pip install 'torch>=2.10,<3' --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements.txt
```

A primeira classificação baixa tokenizer e pesos do Hugging Face (cerca de
437 MB no checkpoint original); importação do módulo não baixa nem instala nada.
Depois, a inferência é local e não usa créditos do Jev. `--local-files-only`
no comando abaixo permite exigir pesos já disponíveis localmente.

```bash
.venv/bin/python classificar_finbert.py \
  dados_noticias/portais_12_meses/noticias_12_meses.jsonl \
  --output dados_noticias/portais_12_meses/noticias_finbert.jsonl \
  --batch-size 8
```

A saída preserva texto, identificação, fonte e horários originais. Acrescenta
`sentiment` com classe, três probabilidades, modelo, revisão, hash do texto e
horário real de classificação. O cache em `.cache/finbert` não contém textos.
Não há falha silenciosa para neutro nem inferência de sentimento a partir dos preços.
`--revision` permite fixar outro checkpoint compatível e separa seu cache.
O JSONL de notícias ainda precisa de contexto e metadados de episódios para
importação na memória; ele não inventa resultados históricos.

Como no FinMem, o sentimento acompanha a notícia até o modelo decisor. Nesta
implementação, os escores ficam em campos estruturados (`current_sentiment` e
`memories[].sentiment`), sem modificar o corpo editorial. O Jev pode contrariar
o sentimento ao avaliar expectativas, riscos e condições do ativo.
Neutro descreve o texto; manter descreve a ação. Nenhum escore é uma probabilidade
calibrada de alta do Ibovespa.

Consulte o [registro da validação da integração](VALIDACAO_FINBERT_JEV.md), com
71 testes e verificações dos pesos reais e da API Jev. Os exemplos de integração
são sintéticos e não demonstram desempenho financeiro.

### Previsão contextual com memória de notícias

`memoria_noticias.py` oferece uma previsão independente por **contexto e experiências
recuperadas**. O Jev recebe a notícia atual, o contexto de mercado informado, textos
históricos selecionados, escores FinBERT e reflexões anteriores. Retorna a ação
`buy` (comprar), `sell` (vender) ou `hold` (manter), com probabilidades do modelo
e uma categoria para a base da decisão. O ranking seleciona memórias;
o Jev decide a ação considerando o contexto, sem votação de resultados históricos.
O comando não substitui a avaliação e o retorno de `run_ibov_pipeline`.

A inspiração é o [FinMem](https://github.com/pipiku915/FinMem-LLM-StockTrading),
especialmente a combinação de similaridade, recência e importância. Nesta adaptação:

- A similaridade é semântica, via cosseno entre embeddings locais do modelo
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revisão fixa
  `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. São vetores de 384 dimensões,
  obtidos por média dos tokens com máscara de atenção e normalização L2.
  O modelo considera os primeiros 128 tokens, conforme sua configuração publicada;
  textos longos não são representados integralmente. Não há ajuste de pesos ou
  vocabulário nas notícias do projeto.
- Cada episódio pertence a `short`, `mid` ou `long`. O score soma similaridade,
  `exp(-idade/escala)` e `importancia_inicial * fator**idade / 100`. Escalas e
  fatores são respectivamente `(3, 0.92)`, `(90, 0.967)` e `(365, 0.988)`;
  a idade é medida em dias corridos desde a disponibilidade do episódio.
- A importância inicial padrão é 50 e a camada padrão é `short`; podem ser
  informadas na importação com justificativa conhecida naquele momento.
  Promoção automática entre camadas e reforço por acesso ainda não são implementados.
- Uma notícia pode ser recuperada antes de se conhecer seu resultado; nesse caso,
  o resultado enviado ao modelo é `null`. Resultados futuros são ocultados.
- `event_id` agrupa o mesmo acontecimento em vários veículos. A recuperação
  elimina eventos e textos normalizados repetidos. O agrupamento de paráfrases
  de um mesmo evento depende do `event_id` fornecido pelo responsável pelos dados.
- As reflexões incluem contexto, decisão original, resultado observado e uma
  lição estruturada do Jev. Só entram em consultas posteriores à sua criação,
  quando ligadas a memórias recuperadas. Não há justificativa narrativa livre:
  a API Jev oferece respostas tipadas. Isso é uma adaptação, não uma reprodução
  integral do agente FinMem.

O SQLite padrão fica em `dados_noticias/memoria_finbert.sqlite`, fora do versionamento.
O banco anterior `memoria.sqlite` e seus registros permanecem preservados.

Os embeddings são calculados com `torch` e `transformers`, já declarados em
`requirements.txt`, sem API paga. A primeira busca com candidatos baixa os pesos
do Hugging Face; a importação do módulo e a criação do banco não iniciam downloads.
Depois, os vetores ficam em `.cache/embeddings`, identificados por hash exato do
texto, modelo, revisão, pooling e limite de tokens. Não são armazenados textos
nesse cache. Para exigir pesos já locais, use `HF_HUB_OFFLINE=1` no ambiente;
em Python, `SemanticEmbeddings(local_files_only=True)` permite o mesmo controle.
Falhas no modelo ou no cache são explícitas; não há retorno automático à busca
por palavras. Somente episódios elegíveis pelo corte temporal são vetorizados.

O score continua sendo **cosseno + recência + importância**, com os componentes
registrados por memória. `min_similarity=0.15` é um limiar inicial configurável
em `retrieve`, ainda sem calibração financeira para o novo espaço semântico.
O ranking é exato por produto matricial NumPy, sem necessidade de FAISS nesta base.
Essa implementação segue a combinação de sinais do FinMem, usando um encoder
local multilíngue em lugar da API de embeddings do projeto original.

A configuração da recuperação aparece em `retrieval_config`, inclusive no estado
enviado ao Jev. O contrato `ibov-memory-trading-v3-semantic` e as assinaturas de
avaliação/carteira incluem a mudança, separando decisões novas das avaliações
lexicais anteriores. Os resultados já publicados não medem esta nova busca.
O encoder pode ter aprendido fatos posteriores a cortes históricos durante seu
pré-treinamento; isso é uma limitação adicional dos estudos retrospectivos.
Consultas muito curtas ou com siglas podem produzir vetores pouco informativos.
A busca semântica não garante equivalência entre todos os termos financeiros;
a qualidade precisa ser medida no acervo, sem assumir ganho de acurácia.
Veja a [validação da busca semântica](VALIDACAO_BUSCA_SEMANTICA.md), incluindo
testes sem rede, pesos reais e uma limitação observada com consultas abreviadas.
Guarda textos, contextos, decisões e reflexões. Prepare um JSON por linha em
`dados_noticias/episodios.jsonl`, por exemplo (exemplo sintético, em uma linha):

```json
{"id":"copom-exemplo-1","event_id":"copom-exemplo","text":"Texto da notícia disponível naquele momento.","published_at":"2020-01-08T18:00:00-03:00","available_at":"2020-01-08T18:01:00-03:00","classified_at":"2020-01-08T18:02:00-03:00","model":"jev-1.14.0","prompt_version":"ibov-news-v1","asset":"^BVSP","horizon":3,"layer":"short","importance":50,"context":{"expectativa":"Informação conhecida na disponibilidade do episódio"},"outcome":0,"outcome_at":"2020-01-14T18:00:00-03:00"}
```

`outcome` é opcional: 1 significa fechamento maior, 0 menor ou igual. `outcome_at`
é obrigatório quando há resultado e deve indicar quando o fechamento futuro
ficou disponível. Associe o resultado a uma data-base explícita na sua preparação
 dos dados, contando três registros de negociação a partir dela; não use dias
corridos nem presuma que uma notícia depois do fechamento antecedeu aquele preço.
`directional_outcomes` em `ibov/memoria.py` auxilia esse cálculo sobre uma série
com horários reais de disponibilidade dos fechamentos e mantém ausente a cauda
sem futuro conhecido. Ainda não há associação automática de notícias a preços.

Os contextos históricos devem conter exclusivamente informações conhecidas em
`available_at`; a importação não verifica a veracidade de seu conteúdo.
Episódios são imutáveis por id. Para outra versão, forneça outro id conservando
`event_id`. Reimportações idênticas são ignoradas; versões conflitantes são rejeitadas.
O arquivo de classificação de sentimento anterior não basta para esta memória:
são necessários os textos e seus contextos.

```bash
.venv/bin/python memoria_noticias.py importar dados_noticias/episodios.jsonl
```

A importação calcula sentimento FinBERT por padrão e o preserva junto ao episódio.
O comando `prever` também classifica a notícia atual antes de consultar o Jev.
Ambos aceitam `--finbert-revision`; `--without-finbert` permite uma ablação
explícita sem nova classificação. Episódios já existentes permanecem imutáveis:
use outro banco ou novos ids para migrar episódios anteriormente sem sentimento.

Para importar diretamente as notícias brutas já coletadas, forneça preços reais
para preparar os episódios e seus alvos separados do contexto:

```bash
.venv/bin/python memoria_noticias.py importar \
  dados_noticias/portais_12_meses/noticias_12_meses.jsonl \
  --prices dados_noticias/historico/precos_ibov.csv --horizon 3
```

Esse preparo preserva a cauda de resultados desconhecidos e aceita InfoMoney,
Money Times e BC; rejeita outras fontes. Os resultados históricos são somente
memórias de experiência, sem retroagir coleta ou classificação.

Prepare `dados_noticias/contexto.json` com contexto **atual** e seu horário:

```json
{"available_at":"2026-10-28T12:00:00-03:00","data":{"expectativa_juros":"Descreva a expectativa disponível","mercado":"Descreva os indicadores conhecidos e sua data-base","position":{"exposure":0,"short_selling_allowed":false}}}
```

```bash
.venv/bin/python memoria_noticias.py prever \
  --text 'Texto atual a ser avaliado' \
  --context dados_noticias/contexto.json \
  --cutoff now --query-id previsao-001
```

Para consulta atual, omita `--cutoff` ou use `--cutoff now`: o corte é obtido
depois de calcular o sentimento. Um corte histórico exige `--retrospective`
quando a classificação foi feita hoje.

Cada execução de `prever` consulta primeiro **InfoMoney, Money Times e Banco
Central (comunicados e atas do Copom)** e incorpora notícias novas à memória.
O arquivo incremental fica em `dados_noticias/diarias`; altere-o com
`--news-directory`. As listagens são buscadas novamente a cada execução, sem
reutilizar respostas antigas do cache. Na primeira consulta são buscados os
últimos sete dias; depois, a busca parte da última publicação armazenada por
fonte, com sobreposição de dois dias para recuperar publicações atrasadas.

A identidade combina URL e hash do texto: reexecuções não duplicam notícias;
um texto revisado na mesma URL é uma nova versão, preservando a anterior.
Notícias já presentes no banco também são ignoradas. Apenas episódios novos
recebem classificação FinBERT. Se as três fontes não trouxerem novidades, os
bancos de notícias e episódios existentes permanecem sem alterações. A previsão
e seu registro de auditoria continuam sendo executados normalmente.

O resultado inclui `news_update`, com contagens, período consultado, completude
e erros por fonte. Falha de acesso não significa ausência de notícias: as outras
fontes continuam sendo consultadas e seus erros ficam explícitos. Textos já
coletados podem ser retomados na execução seguinte se a classificação falhar.
As notícias novas mantêm o horário real de coleta e classificação, sem retroagir
disponibilidade nem atribuir resultados futuros; entram sem contexto de mercado
histórico inferido. A rotina não agenda tarefas em segundo plano, não baixa
preços e não atualiza automaticamente resultados de mercado. Importação,
reflexão e avaliadores históricos não acionam essa coleta diária.

Ao consultar uma notícia que já está na memória, informe seu `event_id` com
`--event-id` para excluir esse evento das experiências recuperadas e evitar
usar a própria notícia como analogia histórica.

Os resultados da coleta real, da reexecução sem novidades e das decisões com
notícias armazenadas estão em [validação da atualização diária](VALIDACAO_ATUALIZACAO_DIARIA.md).

O contexto não pode ter disponibilidade posterior ao corte. Publicação,
disponibilidade e classificação dos episódios devem antecedê-lo; modelos e
versões de classificação são filtrados. O horizonte padrão é 3 pregões,
configurável com `--horizon`; o ativo padrão é `^BVSP`, configurável com `--asset`.
O resultado traz `action`, `action_pt`, as memórias e o ranking para auditoria.
`prediction` permanece como proxy direcional compatível: 1 para comprar, 0 para
vender e `null` para manter. Manter é uma ação de conservar a posição, inclusive
ficar sem exposição; não é uma classe de preço estável. A categoria `basis` indica contexto
atual, analogias, diferenças ou insuficiência. As probabilidades do Jev não
foram calibradas como chances de movimentação financeira.

A posição atual pode ser informada em `context.data.position`, junto às restrições
conhecidas de exposição e venda a descoberto. Sem essa informação, a ação é uma
indicação contextual, sem supor saldo ou quantidade. O índice `^BVSP` é referência;
o sistema não envia ordens à corretora nem gerencia conta real. A simulação
fictícia com custos tem entrada própria em `simular_carteira.py`, descrita abaixo.
A memória evolui entre `short`, `mid` e `long`, seguindo como referência a
[configuração TSLA](https://github.com/pipiku915/FinMem-LLM-StockTrading/blob/main/config/tsla_gpt_config.toml)
e o [ciclo de memória do FinMem](https://github.com/pipiku915/FinMem-LLM-StockTrading/blob/main/puppy/memorydb.py).
Continua sendo uma adaptação, sem reproduzir o agente integral.

| Camada | Escala da recência (dias) | Fator diário da importância | Promoção | Rebaixamento |
| --- | --- | --- | --- | --- |
| `short` | 3 | 0,92 | importância ≥ 60 → `mid` | — |
| `mid` | 90 | 0,967 | importância ≥ 80 → `long` | importância < 60 → `short` |
| `long` | 365 | 0,988 | — | importância < 80 → `mid` |

A importância inicial padrão é 50 na escala 0–100. A evolução usa passos fixos
de 24 horas desde `available_at` e instantes de feedback, com decaimento
proporcional nas frações de dia. Esses são dias corridos de envelhecimento;
o horizonte dos alvos continua contado em pregões. Há no máximo uma transição
por passo; a inicialização também verifica a camada. Promoções reiniciam a
recência; rebaixamentos preservam a idade. Importância abaixo de 5 ou recência
abaixo de 0,05 exclui logicamente a memória da recuperação. Assim, notícias
curtas sem reforço podem desaparecer em aproximadamente nove dias.

`NewsMemory.memory_state(id, cutoff)` informa camada, importância, recência,
transições e exclusão lógica. Episódios permanecem imutáveis no SQLite para
auditoria. A reconstrução é determinística: consultas repetidas não reforçam
memórias e consultar o futuro não altera o passado. O ranking passa à versão
`semantic_cosine_recency_importance_v2_layered`, incorporada às assinaturas de
avaliação e carteira. Resultados financeiros anteriores não validam essa mudança.

O modelo de reflexão pode atribuir utilidade explicitamente por memória,
retornando, por exemplo,
`{"lesson": "consistent", "memory_feedback": {"id-da-memoria": 5.0}}`.
Os ajustes devem ser finitos entre −100 e 100; a importância resultante fica
entre 0 e 100. Reflexão e ajustes são gravados atomicamente após resultado
observado, com no máximo um ajuste por memória e `query_id`. O feedback só vale
para cortes estritamente posteriores à criação; não é retroativo. O Jev agora
responde a uma pergunta tipada para cada memória recuperada: `helpful` soma 5,
`misleading` subtrai 5 e `insufficient` mantém a importância. Cada resposta inclui
suas probabilidades em `memory_assessments`, e `memory_feedback` contém os ajustes
aplicados. A lição geral não determina o crédito de todas as memórias. O protocolo
`jev-memory-utility-v2` separa esse cache das antigas reflexões só com lição.
Após registrar uma reflexão sem ajustes, também é possível atribuir crédito
explicitamente em Python:

```python
memory.feedback("id-da-memoria", feedback_id="credito-001", query_id="previsao-001",
                delta=5.0, created_at="2026-11-03T18:10:00-03:00")
```

Somente memórias usadas na decisão podem receber esse feedback. Memórias
excluídas não ressuscitam. Bancos existentes recebem a nova tabela ao abrir,
sem reescrever episódios ou decisões.

Para distribuir automaticamente o feedback de uma operação às memórias usadas,
registre seu retorno líquido observado, incluindo custos e posição:

```bash
.venv/bin/python memoria_noticias.py feedback \
  --query-id previsao-001 --net-return 0.02 \
  --outcome-at 2026-11-03T18:00:00-03:00 \
  --created-at 2026-11-03T18:10:00-03:00
```

O equivalente em Python é `memory.record_outcome(query_id, net_return=0.02,
outcome_at=..., created_at=...)`. Não chama Jev nem exige reflexão. Lucro soma
5 pontos à importância de cada memória recuperada; perda subtrai 5; retorno
zero não ajusta. O retorno informado deve corresponder à operação e ao horizonte
da decisão, já encerrado; a API valida os horários, mas não verifica execução
nem calcula custos. Não infere lucro de `buy`, `sell`, `hold` ou da classe do
preço: vender não implica posição vendida, e manter pode ter exposição.

Esta é uma adaptação do [feedback do FinMem](https://github.com/pipiku915/FinMem-LLM-StockTrading/blob/main/puppy/portfolio.py):
usa o sinal do resultado e passo de 5 por evento, enquanto o original utiliza
PnL de uma janela da carteira e multiplica 5 pelo contador acumulado por memória.
O reforço é uma heurística de utilidade, sem comprovação causal da justificativa.
O registro é persistente, atômico e imutável por decisão; repetir dados idênticos
não duplica crédito. Um feedback manual prévio para a mesma memória/decisão
impede a aplicação automática inteira. Ajustes valem somente após `created_at`,
preservam o histórico e respeitam o ciclo de vida e os limites de importância.

Depois de observado o resultado no horizonte da previsão, registre uma reflexão:

```bash
.venv/bin/python memoria_noticias.py refletir \
  --query-id previsao-001 --reflection-id reflexao-001 --outcome 1 \
  --outcome-at '2026-11-03T18:00:00-03:00' \
  --created-at '2026-11-03T18:05:00-03:00'
```

O resultado deve ocorrer após o corte original e antes da criação da reflexão;
o horário de geração efetivo do Jev também impede retroagir a reflexão. A lição
pode ser compatibilidade com a hipótese, necessidade de reavaliação ou evidência
insuficiente. Isso não atribui causalidade à notícia nem altera fatos passados.

### Ciclo automático de reflexão por memória

Registre o resultado **já observado** de uma decisão para enfileirar e executar
sua reflexão, aplicar os ajustes por memória e atualizar o estado das camadas:

```bash
.venv/bin/python memoria_noticias.py resultado \
  --query-id previsao-001 --outcome 1 \
  --outcome-at '2026-11-03T18:00:00-03:00' \
  --observed-at '2026-11-03T18:05:00-03:00' \
  --net-return 0.02 --max-requests 1
```

`outcome` continua sendo a direção observada do fechamento (1 alta, 0 baixa/igual)
no horizonte em pregões. `--net-return` é opcional e representa o retorno efetivo
da operação após custos, fornecido pelo responsável pelos dados. Não inferimos
lucro a partir da classe do preço. Esse comando não aplica o reforço uniforme
do antigo comando `feedback`; o Jev avalia a utilidade de cada memória.
Não use os dois modos para reforçar a mesma decisão: crédito duplicado é rejeitado.

O resultado é imutável e fica na tabela `observed_results`. Em caso de falha de
API, permanece pendente, sem reflexão ou feedback parcial. Repetir a mesma
observação não duplica crédito. A gravação da reflexão e dos ajustes é atômica;
se houver interrupção antes de concluir a fila, a retomada reutiliza a reflexão
persistida sem nova chamada ao Jev.

Para importar resultados de várias decisões, use um JSONL com `query_id`,
`outcome`, `outcome_at`, `observed_at` e `net_return` opcional:

```bash
.venv/bin/python memoria_noticias.py atualizar \
  --results dados_noticias/resultados_observados.jsonl --max-requests 10
```

Sem `--results`, `atualizar` processa somente os resultados já pendentes. Por padrão,
processa no máximo uma reflexão por execução. `--max-requests 0` registra as
observações sem chamar o Jev. Em Python, use `memory.register_result(...)` e
`memory.process_pending_reflections(model.reflect, as_of=..., limit=...)`.

O comando `prever` processa automaticamente até uma reflexão pendente antes da
próxima decisão. Seu orçamento é separado: `--max-reflection-requests` controla
reflexões (padrão 1; 0 desativa), e `--max-requests` controla a decisão (padrão 1).
Assim, havendo pendência, uma previsão atual pode fazer até duas novas chamadas.
O corte `now` é obtido depois da reflexão e da classificação, permitindo usar
somente o feedback efetivamente disponível. Cortes históricos continuam ocultando
reflexões criadas hoje.

A atualização é acionada pela chegada de resultados observados ou por `prever`;
não há serviço que consulte uma corretora ou descubra os resultados sozinho.
Os avaliadores retrospectivos e a simulação histórica não retroagem reflexões
atuais. Os testes anteriores de acurácia não medem este ciclo automático novo.

Há no máximo uma chamada inédita por decisão/reflexão por padrão (`--max-requests`), com
cache em `.cache/jev_memoria`. `--model` permite fixar outra versão. Usa a mesma
credencial da classificação de sentimento. Notícia, contexto e experiências são
enviados à TypeSafe; a chave não é gravada no SQLite nem no cache. O contrato
`ibov-memory-trading-v3-semantic` tem identidade de cache própria; respostas antigas de
alta/baixa não são reutilizadas como decisões novas de negociação.

Respostas inválidas não entram no cache. O erro de validação informa se houve
estrutura incompleta, modelo incompatível, classes inesperadas, probabilidades
inválidas, soma diferente de um ou escolha divergente da maior probabilidade;
quando aplicável, identifica a pergunta (`action`, `basis` ou reflexão).

Para investigação retrospectiva, `prever --retrospective` ignora somente o horário
da classificação histórica. Os horários dos textos, resultados e reflexões
continuam sendo respeitados. Dados antigos classificados hoje e o conhecimento
prévio do Jev tornam esse estudo exploratório. O sistema ainda requer coleta
histórica das fontes e avaliação temporal com dados reais; os testes sintéticos
verificam o funcionamento, sem demonstrar assertividade financeira.

### Carteira fictícia com decisões do Jev

Após classificar o consolidado com `classificar_finbert.py`, execute:

```bash
.venv/bin/python simular_carteira.py \
  --documents dados_noticias/portais_12_meses/noticias_finbert.jsonl \
  --prices dados_noticias/historico/precos_ibov.csv \
  --initial-cash 100000 --fee-rate 0.001 \
  --sample-size 24 --warmup-days 90 --max-requests 24
```

O capital é fictício. A simulação usa cotas fracionárias do índice `^BVSP` como
referência; não representa execução de BOVA11 ou de contratos futuros. Comprar
aplica o caixa disponível após custos, vender liquida a posição existente e
manter conserva caixa e cotas. Compras sem caixa e vendas sem posição não geram
negócios. Não há alavancagem, posições vendidas ou ordens enviadas à corretora.

São selecionadas até 24 datas sem usar o sinal dos alvos, com janelas de três
pregões não sobrepostas e aquecimento inicial de 90 dias. O Jev recebe sentimento,
memórias e posição da carteira avaliada pelo último fechamento conhecido.
A ordem é executada na primeira abertura de data posterior ao contexto conhecido,
depois do corte da decisão. O preço dessa abertura não é enviado ao Jev antes
da decisão. Os textos completos preservam os hashes das classificações existentes;
o FinBERT continua considerando somente seus primeiros 512 tokens. Para limitar
o contexto da API, o Jev recebe até 4.000 caracteres por notícia, com o tamanho
original registrado. O sentimento é o do texto original, sem recomputar ou
atribuir um hash diferente ao trecho enviado. O estado exato enviado é auditável.

O custo padrão de 0,1% por negócio é uma hipótese de simulação, configurável com
`--fee-rate`. Não inclui spread, slippage, impostos ou rendimento do caixa.
A referência comprar e manter usa a mesma abertura inicial e o mesmo custo de
entrada. A posição final é marcada pelo fechamento, sem liquidação compulsória.

Saídas em `dados_noticias/simulacao_carteira_semantica/`: `ordens.csv`,
`carteira_diaria.csv`, `simulacao.json` e SQLite auditável. A assinatura inclui
configuração, notícias, preços e versão do contrato Jev. Reexecutar reconstitui
a carteira com decisões persistidas; falhas de API interrompem a simulação e
não são convertidas em manter. Novos parâmetros ou dados geram outro banco.
Use `--directory` para preservar relatórios de experimentos diferentes.

Essa execução é retrospectiva e exploratória: textos e sentimentos foram obtidos
hoje, e o Jev pode conhecer eventos posteriores pelo pré-treinamento. Não cria
reflexões de hoje como se fossem passadas nem comprova retorno futuro.

### Coleta histórica e piloto com notícias reais

`coletar_historico_noticias.py` preserva respostas brutas, hashes, horários reais
de coleta e textos em `dados_noticias/historico/`. Usa `curl` instalado no sistema
para limitar o tempo total de cada requisição e `pypdf` (declarado em
`requirements.txt`) para atas disponíveis somente em PDF. Não instala bibliotecas
na importação. Falhas de rede e documentos sem texto ficam registrados.

```bash
.venv/bin/python coletar_historico_noticias.py bcb
.venv/bin/python coletar_historico_noticias.py ebc --per-year 2
.venv/bin/python coletar_historico_noticias.py gdelt
```

O intervalo padrão é `[2016-10-28, 2026-10-28)`, configurável com `--start` e
`--end`. O coletor BC percorre comunicados e atas. Na Agência Brasil, descobre
matérias de economia nos sitemaps e seleciona até duas por ano encontrado,
espalhadas deterministicamente pela ordem das URLs; `--per-year 0` tenta todas.
Respeita dez segundos entre requisições EBC. `--url-file arquivo.json` permite
acrescentar uma lista explícita de URLs oficiais de matérias que não apareceram
nos índices. Essas inclusões têm viés editorial e não formam censo do noticiário.
`--max-documents` limita o volume. Reexecuções reutilizam os downloads anteriores.

O GDELT DOC fornece descoberta de artigos, não um arquivo integral dos textos.
Erros 429 são registrados e não contornados. Um ZIP histórico público GKG já
baixado pode ser catalogado com `gdelt --gkg-file caminho.zip`: a tabela
`gdelt_index` guarda identificadores, URLs, veículo, temas e menções ao Brasil.
Esses registros **não contam como notícias com texto recuperado** e não são
usados no piloto. A cobertura integral de dez anos nas três fontes ainda não
está estabelecida. Consulte o [relatório da coleta e avaliação](RELATORIO_HISTORICO_NOTICIAS.md).

`fontes.sqlite` separa `available_at` (quando coletamos de fato) de
`historical_available_at` (candidato usado somente no estudo retrospectivo).
Para BC, a API muitas vezes informa apenas data: usa-se a meia-noite seguinte
em São Paulo, respeitando o horário de verão histórico. Na EBC, usam-se metadados
de publicação e, quando presente, a atualização mais recente. Nenhuma dessas
regras comprova que a versão recuperada hoje era a versão original.

```bash
.venv/bin/python avaliar_historico_noticias.py --sample-size 12 --max-requests 24
```

O avaliador usa preços diários reais de `^BVSP`, preservados em `precos_ibov.csv`.
O comando atual lê por padrão o consolidado ativo de InfoMoney e Money Times,
salva em `dados_noticias/avaliacao_portais_semantica` e usa 90 dias de aquecimento.
`--prices` permite reutilizar o CSV existente. A função Python de amostragem
mantém seu padrão de 365 dias; a CLI informa explicitamente 90 dias.
Escolhe até 12 datas distribuídas no
tempo e entre as fontes com textos elegíveis, sem usar o sinal dos resultados. As janelas selecionadas não se sobrepõem.
Na primeira execução, congela os documentos em `evaluation_snapshot.json`;
reexecuções usam o mesmo snapshot e retomam decisões já registradas. Novas coletas
não alteram silenciosamente a amostra avaliada. Para outro experimento, utilize
outro diretório com os dados e os preços desejados, sem substituir o snapshot
anterior. O piloto histórico anterior usava 2016-10-28 a 2026-10-28 e um ano
de aquecimento; seus relatórios permanecem preservados. A nova amostra segue
as datas do JSONL escolhido em `--documents`, limitado às duas fontes ativas.

A disponibilidade candidata do texto é seguida por um corte à meia-noite local
do dia posterior. A data-base é o último registro de negociação de data anterior
a esse corte. O alvo compara esse fechamento ao de três registros posteriores
(`--horizon` altera o horizonte). O resultado só fica disponível para outras
memórias à meia-noite seguinte à data do fechamento futuro. Não se atribui um
horário intradiário exato ao fechamento do Yahoo. O último trecho sem resultado
futuro permanece ausente e não entra na amostra avaliada.

O contexto contém fechamento e retornos de 5 e 20 pregões, mais volatilidade de
20 pregões, usando exclusivamente dados anteriores ao corte. Cada episódio
histórico recebe contexto calculado na sua disponibilidade candidata. O protocolo
fixa as primeiras 4.000 posições de cada texto e até três memórias recuperadas
por consulta. O acontecimento atual é excluído da recuperação. Os textos são
enriquecidos com FinBERT antes da avaliação, sem forjar seu horário de classificação.
Use `--without-finbert` para ablação com texto sem sentimento. O piloto anterior,
preservado nos relatórios, usava textos diretamente e decisões alta/baixa/abstenção.
O modo retrospectivo ignora apenas o horário da classificação, mantendo os
horários dos textos e dos resultados. Reflexões geradas hoje não são retroagidas:
este piloto ainda não mede aprendizado por reflexões acumuladas em tempo real.

Para cada data, o mesmo Jev e o mesmo contexto atual são avaliados em duas
condições: sem memórias e com recuperação histórica. O resultado em
`avaliacao.json` inclui acurácia entre respostas direcionais, cobertura,
abstenções, acurácia balanceada quando há ambas as classes, intervalo descritivo
de Wilson, comparação nos pares completos e nos casos respondidos por ambos,
e a referência simples de prever sempre alta. A referência não depende do Jev.
Falhas de API não viram abstenções: interrompem a execução e são registradas.
O orçamento limita novas chamadas; caches e previsões persistidas permitem retomar.
As avaliações novas usam comprar/vender/manter e assinatura que inclui a versão
do contrato Jev e os episódios enriquecidos. `n_hold` registra manter; o campo
legado `n_abstained` inclui essas consultas sem direção para compatibilidade.
A acurácia continua sendo apenas um proxy direcional (`buy`=alta, `sell`=baixa/igual,
`hold` sem direção), sem avaliar retorno da ação ou lucro de carteira.

Esse é um estudo exploratório: a amostra pequena, lacunas do acervo, revisões de
texto e eventual conhecimento dos acontecimentos no pré-treinamento do Jev
impedem apresentá-lo como validação financeira independente. A confirmação requer
avaliação futura com notícias e previsões registradas antes de conhecer os preços.

### Notícias dos portais nos últimos 12 meses

O coletor retomável consulta a API editorial pública WordPress de InfoMoney e
Money Times, buscando `ibovespa` no conteúdo com paginação. Nos demais portais,
tenta sitemaps públicos e filtra URLs sobre Ibovespa e fatores econômicos.
Confirma o intervalo pela publicação da matéria. Não representa todas as notícias
dos portais nem garante relevância de cada resultado da busca.
O fim é exclusivo; os padrões cobrem 28/10/2025 a 27/10/2026:

```bash
.venv/bin/python coletar_portais_noticias.py --source infomoney
.venv/bin/python coletar_portais_noticias.py --source moneytimes
.venv/bin/python coletar_portais_noticias.py --source investing
.venv/bin/python coletar_portais_noticias.py --source advfn
```

`--start`, `--end` e `--directory` permitem mudar o período e o destino.
Textos e respostas brutas ficam em `dados_noticias/portais_12_meses/`, fora do Git.
Cada fonte produz um manifesto de URLs (quando a descoberta funciona) e um relatório `*_collection.json` com
falhas e contagens. Reexecutar reutiliza o cache e os textos já salvos; bloqueios
não são contornados. As APIs fornecem o campo editorial `content.rendered`;
na extração HTML, o coletor aceita corpo editorial identificado ou `articleBody`
estruturado. Páginas incompatíveis são registradas como falhas.
A data de atualização é preservada, e a disponibilidade real é a coleta atual:
esses textos não comprovam a versão originalmente disponível no passado.

Resultado da coleta inicial: [relatório dos 12 meses](RELATORIO_COLETA_12_MESES.md).

### Escopo atual das fontes de notícias

A partir de 28/10/2026, a Agência Brasil fica fora das próximas análises e
avaliações solicitadas para este estudo. Seus registros e os resultados do piloto
anterior são preservados apenas como histórico de auditoria; não devem ser
incluídos em novos conjuntos de avaliação. Esta é uma definição de escopo, não
um filtro automático do avaliador histórico.
A base consolidada dos últimos 12 meses contém somente InfoMoney e Money Times;
os documentos do Banco Central permanecem como fonte complementar disponível.

### Textos localizados a partir do GDELT

`coletar_gdelt_noticias.py` testa a recuperação dos corpos editoriais nos sites
originais, a partir dos links dos arquivos GKG históricos. O padrão é uma **amostra
semanal de um intervalo de 15 minutos às 21h UTC**, entre 28/10/2025 e 27/10/2026;
não é uma coleta completa dos 12 meses. São selecionados registros originalmente
em português, por palavras na URL ou temas de bolsa, juros, inflação e câmbio.
O título também passa por um filtro econômico antes da inclusão.

```bash
.venv/bin/python coletar_gdelt_noticias.py --index-only
.venv/bin/python coletar_gdelt_noticias.py --reuse-index
```

`--interval-days` controla o espaçamento entre os arquivos (padrão 7), e `--hour`
o horário UTC (padrão 21). `--start`, `--end` exclusivo e `--directory` permitem
mudar o recorte. O índice contém metadados, sem ser contado como texto integral.
O modo `--reuse-index` exige o mesmo período do índice salvo. Para mudar a amostra,
refaça o índice, preferencialmente em outro diretório.

Dados ficam em `dados_noticias/gdelt_12_meses/`: `gdelt_discovery.json`,
`gdelt_collection.json`, `fontes.sqlite`, `raw/` e o consolidado `noticias_gdelt.jsonl`.
Textos conhecidos na base dos portais são reaproveitados e contabilizados
separadamente dos novos. Versões da exploração permanecem no banco para auditoria;
o consolidado inclui somente as URLs aprovadas na execução atual.

A coleta respeita robots.txt, não contorna bloqueios e suspende novas tentativas
no domínio após HTTP 429/403 ou falhas de rede repetidas. Agência Brasil e créditos
identificados como Agência Brasil/ABR ficam excluídos. Páginas sem publicação
explícita, textos curtos, restritos ou significativamente menores que o tamanho
declarado não entram. A completude de cada corpo extraído ainda requer revisão
manual. O horário de observação do GDELT não substitui a publicação. Datas sem
fuso são disponibilizadas conservadoramente na meia-noite seguinte em São Paulo;
a versão real só fica disponível a partir da coleta atual.

Resultado desta tentativa: [relatório GDELT dos 12 meses](RELATORIO_GDELT_12_MESES.md).
O consolidado contém 56 textos aceitos, dos quais 53 novos e 3 já conhecidos no
arquivo dos portais. Essa amostra permanece separada do snapshot inicial.

### GDELT fora do escopo ativo por enquanto

Por decisão do usuário, os textos localizados a partir do GDELT ficam fora das
próximas análises e avaliações devido à distribuição irregular das datas. A
amostra e os relatórios permanecem preservados para auditoria. Não incorporar
`noticias_gdelt.jsonl` à base ativa sem uma nova decisão do usuário.
A base ativa de notícias permanece no snapshot inicial de 9.590 textos de
InfoMoney e Money Times; os documentos do Banco Central seguem disponíveis como
fonte complementar. Agência Brasil também permanece fora do escopo ativo.
Esta definição de escopo não acrescenta um filtro automático aos avaliadores.

### Comparação Jev com e sem memória nos portais

Para o consolidado ativo de InfoMoney e Money Times, use um diretório separado
e aquecimento de 90 dias (padrão da CLI atual; a função Python mantém 365 dias):

```bash
.venv/bin/python avaliar_historico_noticias.py \
  --directory dados_noticias/avaliacao_portais_semantica \
  --documents dados_noticias/portais_12_meses/noticias_12_meses.jsonl \
  --prices dados_noticias/historico/precos_ibov.csv \
  --warmup-days 90 --sample-size 24 --max-requests 48
```

`--documents` lê JSONL e aceita somente as fontes `infomoney` e `moneytimes`.
`--prices` reutiliza preços locais, sem novo download. O snapshot, as decisões
retomáveis e `avaliacao.json` ficam no diretório do experimento. O horizonte
permanece em três pregões. A seleção de datas não usa a direção dos alvos;
notícias anteriores ao corte podem ser recuperadas, mas seus resultados só são
expostos após conhecidos. A comparação mede recuperação de episódios históricos,
sem simular reflexões geradas no passado. Não mede o ganho incremental sobre o
XGBoost nem lucro de uma estratégia de negociação.

Resultado anterior, **sem FinBERT e com contrato alta/baixa/abstenção**:
[avaliação das memórias nos portais](AVALIACAO_MEMORIA_PORTAIS.md)
e [métricas completas](avaliacao_memoria_portais.json). Em 24 pares, a memória
reduziu abstenções de 10 para 5; nos 14 casos respondidos por ambos, os acertos
passaram de 9 para 10. A precisão entre respostas de cada versão foi 64,3% sem
memória e 63,2% com memória. O piloto não demonstra superioridade confiável.

Avaliação pareada **com FinBERT-PT-BR nas duas condições**:
[relatório de acurácia Jev com e sem memória](AVALIACAO_ACURACIA_JEV_FINBERT_MEMORIA.md)
e [respostas e métricas completas](dados_noticias/avaliacao_finbert_memoria_24/avaliacao.json).
Em 24 datas, houve quatro previsões direcionais sem memória e seis com memória;
a acurácia entre essas previsões foi 75,0% e 66,7%, respectivamente. O teste é
retrospectivo, e só uma data teve previsão direcional em comum.
