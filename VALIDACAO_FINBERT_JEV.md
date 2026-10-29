# Integração FinBERT-PT-BR, memória e Jev

Implementação e verificação em 28/10/2026.

## Fluxo disponível

1. Notícias brasileiras são classificadas localmente pelo FinBERT-PT-BR.
2. Texto original, classe, três escores e horários ficam juntos no episódio.
3. A memória recupera episódios anteriores, ocultando resultados ainda desconhecidos.
4. O Jev recebe notícia e sentimento atuais, contexto, memórias e reflexões disponíveis.
5. Retorna `buy`, `sell` ou `hold`, expostos também como comprar, vender ou manter.

O sentimento fica estruturado no estado enviado à API; ele não define a ação
por votação nem altera os pesos do Jev. Neutro não é sinônimo de manter.
Os comandos e opções estão no [README](README.md#sentimento-local-com-finbert-pt-br).

## Verificações executadas

- `.venv/bin/python -m unittest -v`: **71 testes passaram**.
- `.venv/bin/python -m pip check`: nenhuma dependência incompatível.
- Compilação dos módulos e verificação de ajuda dos três comandos.
- Pesos oficiais do modelo baixados e verificados por SHA-256:
  `123352c03b252152acc9d71e6678aad015d9cd5200e4c4abc5f5cc20a48c6866`.
- Checkpoint fixado em `c3bf75c85f9b1b0dd257d688822d64390420936c`.
- Inferência real local, sem rede, nos exemplos sintéticos abaixo.

| Texto sintético | Classe | Escore da classe |
|---|---|---:|
| Empresa anuncia aumento de lucro e receita. | Positivo | 91,36% |
| Empresa registra prejuízo e queda das vendas. | Negativo | 92,99% |
| A reunião será realizada na próxima semana. | Neutro | 71,92% |

Esses exemplos verificam carregamento e mapeamento de classes; não estimam
acurácia em notícias reais nem probabilidade de retorno financeiro.

Foram realizadas **duas chamadas reais ao Jev** com entradas sintéticas:
uma para verificar o novo contrato de ações e outra para verificar o fluxo
FinBERT → memória → Jev. Na segunda, o Jev recebeu sentimento atual positivo
e uma memória com sentimento negativo e escolheu **manter** (escore 0,60),
com base classificada como insuficiente. Isso confirma o transporte do sentimento
e a autonomia da decisão; não constitui recomendação de investimento.

Os estados e respostas estão em `dados_noticias/validacao_finbert/`, fora do
versionamento e sem credenciais. A resolução DNS do servidor de pesos falhou
inicialmente; o download foi concluído do servidor oficial e validado pelo hash.
Tokenizer e pesos estão disponíveis no cache local do Hugging Face.

## Alcance desta entrega

O pipeline XGBoost conserva seu retorno `(metrics, prediction, probability)`.
Os relatórios financeiros anteriores permanecem históricos: não foram recalculados
nem atribuídos ao novo agente. A base completa de 9.590 notícias ainda não foi
reclassificada nesta entrega; os comandos permitem processá-la em lotes com cache.
Não foi executado novo estudo de desempenho com FinBERT.

O agente ainda não reproduz todo o FinMem: não gerencia ordens ou carteira,
não promove memórias automaticamente e não reforça camadas por desempenho.
A avaliação disponível usa ações como proxy direcional, com manter separado
da acurácia; ela não calcula lucro, custos ou retorno de uma estratégia.
