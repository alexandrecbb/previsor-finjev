# Busca semântica da memória

A recuperação agora usa embeddings locais do
[modelo multilíngue MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2),
na revisão `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
O score é cosseno + recência + importância. Permanecem os filtros de ativo,
horizonte, disponibilidade, evento atual, duplicatas e resultados conhecidos.

Os vetores têm 384 dimensões e usam média com máscara de atenção, normalização L2
e os primeiros 128 tokens. O modelo não é ajustado nas notícias. Os pesos oficiais
foram baixados e verificados pelos hashes publicados pelo Hugging Face.

## Verificação real local

Consulta: “O Banco Central reduziu a taxa de juros.”

| Candidato | Similaridade por cosseno |
|---|---:|
| A autoridade monetária anunciou um corte nos juros. | 0,4836 |
| O time de futebol venceu o campeonato. | −0,0597 |

A recuperação retornou a paráfrase sobre juros como primeira memória. Essa é
uma verificação de funcionamento em frases sintéticas, não um teste de acurácia
financeira nem uma estimativa da qualidade de todo o acervo.

Uma verificação anterior com a consulta curta “Selic recua” teve cosseno de
0,0747 com “Autoridade monetária reduz juros”, abaixo do limiar inicial de 0,15.
Portanto, siglas e consultas curtas ainda podem falhar; a busca semântica não
garante equivalência financeira em todos os casos.

## Integridade e cache

- Cache por hash exato do texto, modelo, revisão, pooling e limite de tokens.
- Vetores persistidos são reutilizados sem nova inferência ou renormalização.
- Notícias futuras são filtradas antes de gerar embeddings.
- Resultados de mercado só entram no contexto após seu horário de disponibilidade.
- Configuração da busca registrada no estado enviado ao Jev e nas assinaturas
  das avaliações e simulações. Contrato `ibov-memory-trading-v3-semantic`.
- Diretórios padrão novos: `avaliacao_portais_semantica` e
  `simulacao_carteira_semantica`, dentro de `dados_noticias/`.

`HF_HUB_OFFLINE=1 .venv/bin/python -m unittest -v`: **79 testes passaram**.
Os testes usam vetores simulados e cobrem cache, retomada, normalização, rejeição
de vetores inválidos, ranking, recência, importância e preservação temporal.
Há avisos de depreciação de dependências, sem falhas.

A verificação com pesos reais está em `dados_noticias/validacao_embeddings/smoke.json`.
Não houve chamada ao Jev nesta entrega. As 9.590 notícias mantêm suas classificações
FinBERT; os embeddings serão calculados em lotes conforme as consultas da memória.
Não foi executada nova avaliação de previsão ou carteira com a busca semântica.
