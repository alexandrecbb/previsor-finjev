# Coleta de notícias dos últimos 12 meses

Período: **28/10/2025 a 27/10/2026**, inclusive, pela data de publicação em São Paulo. Coleta executada em 28/10/2026.

## Resultado

| Fonte | Textos por URL no consolidado | Situação |
|---|---:|---|
| InfoMoney | 6.181 | Paginação da busca concluída |
| Money Times | 3.409 | Paginação da busca concluída |
| Investing.com Brasil | 0 | Sitemap tentado retornou HTTP 404; robots exibiu desafio de acesso |
| ADVFN | 0 | Sitemap retornou HTTP 403; alternativa editorial não forneceu API JSON |

**Total: 9.590 textos, uma versão por URL.** Os registros contêm o corpo editorial retornado pelos portais.

## Método e limites

- APIs públicas WordPress de InfoMoney e Money Times: busca por `ibovespa`, ordenação cronológica e páginas de 100 resultados. A última página parcial encerrou cada busca.
- Isso esgota os resultados retornados por essa consulta, não todo o noticiário dos portais. Há menções incidentais ao índice e conteúdos analíticos ou comerciais; relevância e qualidade editorial ainda precisam de triagem.
- Textos são os corpos fornecidos pelos portais, sem auditoria manual de completude de cada matéria. Conteúdo protegido, ausente ou curto é recusado. A extração pode preservar chamadas promocionais inseridas no corpo.
- O sitemap do InfoMoney descobriu inicialmente 5.318 URLs sobre temas econômicos; a coleta definitiva utilizou a API. O banco preserva essa exploração, mas o consolidado inclui somente URLs das duas buscas da API.
- URLs repetidas foram consolidadas pela versão coletada mais recentemente. Notícias de URLs diferentes sobre o mesmo acontecimento não foram agrupadas semanticamente.
- Textos exatamente idênticos excedentes entre as URLs consolidadas: 0.
- Publicação, atualização, coleta, URL, fonte e hashes são preservados. `available_at` é a coleta real; `historical_available_at` considera a atualização mais recente. Não há prova da versão disponível na publicação original.
- As fontes bloqueadas não foram contornadas. Nenhuma nova previsão ou avaliação de desempenho foi executada nesta coleta.

## Cobertura mensal

| Mês | InfoMoney | Money Times |
|---|---:|---:|
| 2025-10 | 74 | 69 |
| 2025-11 | 433 | 297 |
| 2025-12 | 398 | 257 |
| 2026-01 | 468 | 287 |
| 2026-02 | 420 | 243 |
| 2026-03 | 522 | 291 |
| 2026-04 | 514 | 245 |
| 2026-05 | 499 | 274 |
| 2026-06 | 586 | 243 |
| 2026-07 | 579 | 306 |
| 2026-08 | 541 | 326 |
| 2026-09 | 570 | 300 |
| 2026-10 | 577 | 271 |

Outubro de 2025 começa no dia 28; outubro de 2026 termina no dia 27. Contagens mensais não comprovam cobertura de cada pregão.

## Arquivos e verificações

- [Resumo auditável e métricas da coleta](coleta_portais_12_meses.json).
- `dados_noticias/portais_12_meses/noticias_12_meses.jsonl`: consolidado com os textos.
- `dados_noticias/portais_12_meses/fontes.sqlite`: versões e tentativas de acesso.
- `dados_noticias/portais_12_meses/raw/`: respostas originais e metadados de coleta.
- `*_api_urls.json` e `*_collection.json` no mesmo diretório: manifestos e relatórios por fonte.
- Dados e caches permanecem fora do Git, conforme `.gitignore`.
- `.venv/bin/python -m unittest -v`: **55 testes passaram**. Incluem extração, fusos, revisões, intervalo, conteúdo protegido, falha na paginação e retomada sem duplicação de documentos. Não medem desempenho financeiro.
