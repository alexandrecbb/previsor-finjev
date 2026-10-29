# Coleta histórica e piloto contextual com Jev

Execução em 28/10/2026. **O piloto não demonstrou vantagem da memória na previsão
de três pregões.** Nos oito casos respondidos pelas duas versões, ambas acertaram
3/8 (37,5%). A memória fez o modelo responder em mais casos, sem demonstrar melhor
acurácia nos casos comparáveis. A amostra é pequena e retrospectiva; não valida
uma estratégia de investimento.

## Dados recuperados

Período solicitado: `[2016-10-28, 2026-10-28)`. O snapshot avaliado contém **171
textos completos**, antes da limitação de tamanho aplicada ao prompt, e 2.521
registros de preços diários do Ibovespa, de 01/09/2016 a 27/10/2026.

| Fonte | Resultado da coleta | Limitações |
|---|---|---|
| Banco Central | 158 documentos: 79 atas e 79 comunicados, de 30/11/2016 a 22/09/2026 | Todos os documentos encontrados nas duas listas da API para o intervalo; não representa todas as publicações do BC. Parte das atas foi extraída de PDF. |
| Agência Brasil | 14 matérias coletadas; 13 dentro do intervalo solicitado e no snapshot | Acervo parcial: 11.011 URLs descobertas; dois sitemaps falharam. Amostra de duas URLs por ano encontrado, mais quatro URLs oficiais adicionais. Uma matéria de 14/10/2016 ficou fora da avaliação. |
| GDELT | 3.362 metadados WEB de um arquivo GKG de 28/10/2016, com 60 registros contendo menções ao Brasil | Zero textos integrais recuperados por essa fonte; busca DOC retornou HTTP 429. Metadados não entraram na avaliação. |

A API do BC forneceu todos os 158 documentos esperados nesta consulta após retomadas
das falhas de rede. Os sitemaps EBC recuperados forneceram URLs até 2020; a busca
por URLs oficiais complementou 2022, 2023, 2025 e 2026. Isso não comprova cobertura
integral da Agência Brasil em nenhum desses anos. O GDELT foi auditado como índice;
não se deve contar seus metadados como 3.362 notícias com conteúdo disponível.

Referências: [API oficial do Copom](https://www.bcb.gov.br/conteudo/dadosabertos/BCBDeinf/elements_copom.html),
[sitemaps EBC](https://agenciabrasil.ebc.com.br/sitemap.xml),
[arquivo GKG usado](https://data.gdeltproject.org/gdeltv2/20161028120000.gkg.csv.zip),
[documentação GKG](https://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf).

### Textos no snapshot por ano de publicação

Os anos inicial e final são parciais. A presença de documentos em um ano não
significa que o noticiário inteiro daquele ano foi coletado.

| Ano | BC | Agência Brasil |
|---|---:|---:|
| 2016 | 2 | 1 |
| 2017 | 16 | 2 |
| 2018 | 16 | 2 |
| 2019 | 16 | 2 |
| 2020 | 16 | 2 |
| 2021 | 16 | 0 |
| 2022 | 16 | 1 |
| 2023 | 16 | 1 |
| 2024 | 16 | 0 |
| 2025 | 16 | 1 |
| 2026 | 12 | 1 |

## Protocolo fixado antes das consultas

- Modelo `jev-1.14.0`, horizonte de três registros de negociação, 12 datas
  distribuídas no tempo e entre as fontes elegíveis, após um ano de aquecimento.
  As janelas de alvos não se sobrepõem. A amostra foi escolhida sem usar a direção
  ou a magnitude dos resultados.
- Duas consultas por data: notícia e contexto atuais sem memórias; os mesmos
  dados acrescidos de até três memórias. Foram feitas 24 decisões reais, sem
  erros da API. A retomada com orçamento zero reproduziu as decisões armazenadas.
- Contexto com último fechamento conhecido, retornos de 5 e 20 registros e
  volatilidade de 20 registros. Nenhum alvo atual é enviado ao modelo.
- Primeiros 4.000 caracteres de cada texto no prompt; originais preservados na
  coleta. Não houve otimização de tamanho, limiar, amostra ou ranking pelo teste.
- Notícias com apenas data foram disponibilizadas conservadoramente na meia-noite
  seguinte em São Paulo. O corte da previsão é a meia-noite local do dia posterior
  à disponibilidade candidata. A data-base é o último registro anterior ao corte;
  o alvo compara seu fechamento ao de três registros seguintes.
- Resultados históricos só são revelados a memórias após a meia-noite seguinte
  à data do fechamento futuro. Contextos usam exclusivamente fechamentos de dias
  anteriores ao respectivo corte. O evento atual é excluído da recuperação.
- Nenhuma reflexão gerada hoje foi retroagida. O piloto mede recuperação de notícias
  e experiências conhecidas, sem medir aprendizado por reflexões históricas.

## Resultados

| Versão | Respostas direcionais | Abstenções | Acertos/respostas | Acurácia nas respostas | Cobertura |
|---|---:|---:|---:|---:|---:|
| Jev sem memória | 8 | 4 | 3/8 | 37,5% | 66,7% |
| Jev com memória | 10 | 2 | 4/10 | 40,0% | 83,3% |
| Sempre alta | 12 | 0 | 7/12 | 58,3% | 100% |

Os 37,5% e 40,0% referem-se a subconjuntos diferentes e não demonstram melhoria
por si mesmos. **Nos oito casos respondidos por ambos, o resultado foi 37,5% para
as duas versões.** Nesses mesmos oito casos, prever sempre alta teria acertado
5/8 (62,5%). A memória acrescentou uma resposta correta e uma incorreta nas duas
datas em que o modelo sem memória se absteve.

A acurácia balanceada entre respostas foi 36,7% sem memória e 37,5% com memória.
Os intervalos descritivos de Wilson de 95% foram 13,7%–69,4% (3/8) e 16,8%–68,7%
(4/10). São largos, não corrigem dependência entre mercados e não sustentam uma
conclusão de superioridade. As probabilidades do Jev não foram calibradas como
probabilidades financeiras.

### Previsões individuais

A data abaixo é o corte UTC (a meia-noite local coincide com o mesmo dia UTC).
Classe 0 inclui fechamento igual. Resultados representam o alvo definido acima,
sem atribuir causalidade à notícia.

| Corte | Fonte da notícia atual | Observado | Sem memória | Com memória |
|---|---|---|---|---|
| 2017-12-08 | bcb | Alta | Alta | Alta |
| 2017-12-15 | agencia_brasil | Alta | Abstenção | Abstenção |
| 2018-01-16 | agencia_brasil | Alta | Abstenção | Alta |
| 2018-12-07 | agencia_brasil | Baixa/igual | Abstenção | Abstenção |
| 2019-09-20 | bcb | Baixa/igual | Alta | Alta |
| 2019-12-13 | agencia_brasil | Alta | Alta | Alta |
| 2020-08-04 | agencia_brasil | Alta | Baixa/igual | Baixa/igual |
| 2021-06-18 | bcb | Alta | Baixa/igual | Baixa/igual |
| 2023-03-24 | bcb | Alta | Baixa/igual | Baixa/igual |
| 2023-08-04 | agencia_brasil | Baixa/igual | Abstenção | Alta |
| 2024-12-13 | bcb | Baixa/igual | Baixa/igual | Baixa/igual |
| 2026-09-23 | agencia_brasil | Baixa/igual | Alta | Alta |

## Limites da interpretação

Textos foram coletados hoje; não há comprovação de que cada versão era idêntica
à publicada originalmente. O pré-treinamento do Jev pode conter notícias e preços
posteriores aos cortes simulados. O modo retrospectivo ignora o horário real da
classificação, mas não transforma esse teste em avaliação prospectiva.

A amostra tem 5 documentos do BC e 7 matérias da Agência Brasil e não é um retrato
representativo do noticiário financeiro. Há lacunas de fontes, seleção por
sobrevivência dos links e inclusões editoriais. A recuperação usa similaridade
textual local e não embeddings semânticos. Não há agrupamento semântico geral de
acontecimentos entre fontes: URLs diferentes podem relatar o mesmo fato. Não foi
calculado lucro, retorno de carteira ou custo de negociação.

Portanto, a implementação e o piloto com dados reais foram executados, mas **a
coleta integral de dez anos nas três fontes e a comprovação de assertividade
financeira continuam pendentes**. O próximo teste independente deve registrar
notícias, previsões e horários antes dos resultados futuros, mantendo estes
resultados como referência sem ajustar a estratégia sobre os mesmos 12 casos.

## Artefatos e verificações

- [Métricas e previsões, sem textos nem credenciais](avaliacao_noticias_real.json).
- `dados_noticias/historico/fontes.sqlite`: textos, URLs, proveniência e falhas;
  `raw/`: respostas originais e hashes; `evaluation_snapshot.json`: corpus congelado;
  `precos_ibov.csv`: preços usados; `avaliacao_*.sqlite`: estados enviados e decisões.
- Dados brutos, caches e bancos permanecem em diretórios excluídos pelo `.gitignore`.
  Os hashes dos dados e dos módulos usados constam no JSON das métricas.
- `.venv/bin/python -m unittest -v`: **50 testes passaram**, com dados sintéticos e
  transportes simulados. Verificam integridade temporal, extração de HTML/PDF,
  ocultação dos alvos, comparação pareada, abstenções e retomada sem chamadas.
  Houve avisos de depreciação de dependências e do gráfico sem interface; nenhuma
  falha. Esses testes não são evidência de desempenho financeiro.
