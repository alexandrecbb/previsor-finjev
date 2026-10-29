# Recuperação de textos a partir do GDELT — últimos 12 meses

Execução em 28/10/2026. Período solicitado: **28/10/2025 a 27/10/2026**, inclusive.

**Foi possível recuperar corpos editoriais nos sites originais. A coleta é uma amostra parcial, sem comprovação de completude manual de cada texto ou cobertura integral do período.**

## Resultado

- 53 arquivos GKG lidos, sem falhas, de 53 programados.
- 104.768 registros de metadados examinados, sem contá-los como textos.
- 252 URLs candidatas de notícias econômicas em português.
- **56 textos aceitos: 53 novos em relação ao arquivo dos portais e 3 reaproveitados desse arquivo.**
- 23 domínios de origem no consolidado; 196 candidatos recusados ou inacessíveis.
- Publicações aceitas entre 2025-11-04 e 2026-10-13; 0 duplicatas exatas de texto entre URLs aceitas.

Os 53 textos novos ficam no arquivo GDELT separado. O snapshot inicial de 9.590 notícias não foi sobrescrito nem teve suas contagens alteradas. O banco GDELT preserva versões da exploração; o consolidado contém apenas as URLs aprovadas nesta execução.

## O que funcionou e o que falhou

A API DOC não respondeu na nova tentativa registrada: `curl (28) Connection timed out after 8001 milliseconds`. Portanto, não foi possível usar essa busca para esgotar notícias do ano.

Os arquivos históricos GKG estavam acessíveis. Eles forneceram URLs e metadados; os corpos foram recuperados nos sites de origem ou reaproveitados do cache conhecido. O GDELT não forneceu os textos integrais nesta operação.

A descoberta usou **um arquivo de 15 minutos às 21h UTC, a cada sete dias**, começando em 28/10/2025 e terminando em 27/10/2026. O índice inclui candidatos em todos os meses, mas observa apenas 53 intervalos do ano. Não é um censo diário do noticiário.

Foram selecionados registros originalmente em português com palavras econômicas na URL ou temas GKG de bolsa, inflação, juros e câmbio. O título passou por um filtro adicional. Esse filtro é heurístico e não garante relevância financeira para cada matéria.

Os corpos aceitos vieram de `articleBody` estruturado ou contêiner editorial identificado. Páginas sem publicação explícita, restritas, muito curtas ou com texto significativamente inferior ao `wordCount` declarado foram recusadas. Bloqueios e robots.txt não foram contornados. Agência Brasil e créditos identificados como Agência Brasil/ABR foram excluídos, inclusive quando reproduzidos por outros portais.

Não houve revisão manual da completude de cada corpo. Textos de páginas com vídeo representam o corpo textual publicado, sem transcrição adicional do vídeo. Podem restar chamadas ou trechos promocionais nos corpos extraídos.

Datas de publicação, atualização, coleta e observação GDELT são separadas. `available_at` registra a coleta real. Horários sem fuso são tratados conservadoramente como data, disponíveis na meia-noite seguinte em São Paulo. Atualizações posteriores adiam a disponibilidade histórica exploratória. A versão original de cada matéria não foi comprovada. Nenhum novo teste de previsão foi executado.

Referência do formato e dos arquivos históricos: [documentação oficial do GDELT 2.0](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/).

## Cobertura mensal dos textos aceitos

| Mês | Textos |
|---|---:|
| 2025-10 | 0 |
| 2025-11 | 3 |
| 2025-12 | 4 |
| 2026-01 | 3 |
| 2026-02 | 3 |
| 2026-03 | 7 |
| 2026-04 | 8 |
| 2026-05 | 9 |
| 2026-06 | 3 |
| 2026-07 | 4 |
| 2026-08 | 7 |
| 2026-09 | 4 |
| 2026-10 | 1 |

Os meses das extremidades são parciais. Presença mensal não comprova cobertura de cada pregão.

## Motivos de recusa

| Motivo | URLs |
|---|---:|
| Fora do tema pelo título | 77 |
| Publicação explícita ausente | 38 |
| Falha de acesso/rede ou domínio suspenso | 31 |
| Corpo ausente, curto ou não identificado | 23 |
| Agência Brasil/ABR excluída | 10 |
| Possível texto incompleto | 8 |
| Conteúdo restrito | 5 |
| Restrição ou falha em robots.txt | 4 |

## Domínios dos textos aceitos

| Domínio | Textos |
|---|---:|
| jornaldebrasilia.com.br | 12 |
| dgabc.com.br | 10 |
| infomoney.com.br | 8 |
| veja.abril.com.br | 5 |
| sapo.pt | 2 |
| rondoniadinamica.com | 2 |
| folhavitoria.com.br | 1 |
| tribunaonline.com.br | 1 |
| reporterdiario.com.br | 1 |
| emtempo.com.br | 1 |
| diariodolitoral.com.br | 1 |
| agroemcampo.ig.com.br | 1 |
| dw.com | 1 |
| odia.ig.com.br | 1 |
| jornalcruzeiro.com.br | 1 |
| meionews.com | 1 |
| diariodosudoeste.com.br | 1 |
| jornalfolhadoestado.com | 1 |
| nenoticias.com.br | 1 |
| brasil247.com | 1 |
| conexaoto.com.br | 1 |
| conjur.com.br | 1 |
| tvbrasil.ebc.com.br | 1 |

## Arquivos e verificações

- [Resumo auditável da coleta](coleta_gdelt_12_meses.json).
- `dados_noticias/gdelt_12_meses/noticias_gdelt.jsonl`: consolidado aceito, com textos e proveniência GDELT.
- `dados_noticias/gdelt_12_meses/fontes.sqlite`: documentos e tentativas de acesso, inclusive versões exploratórias.
- `gdelt_discovery.json`, `gdelt_collection.json` e `raw/` no mesmo diretório: índice, resultados e respostas originais.
- Dados brutos e bancos permanecem fora do Git, conforme `.gitignore`.
- `.venv/bin/python -m unittest -v`: **62 testes passaram**, sem rede. Incluem filtragem GKG, exclusão Agência Brasil/ABR, corpos editoriais, datas, revisões, fuso ausente, conteúdo protegido, textos curtos e reaproveitamento sem inflar o número de textos novos.
- Conferidos no consolidado: URLs únicas, período, exclusões de escopo, hashes dos textos e hash do arquivo. Testes sintéticos não medem desempenho financeiro.
