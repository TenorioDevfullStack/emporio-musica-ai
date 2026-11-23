# Recuperação de políticas da loja

O experimento compara a busca BM25 do agente com embeddings multilíngues e PostgreSQL com pgvector. O corpus é o mesmo manual do desafio, dividido pelo extrator da aplicação em 29 seções. Cada uma das 20 perguntas em português tem uma seção de referência definida antes da execução. O acerto (Hit@3) ocorre quando essa seção aparece nas três primeiras posições.

| Método | Acertos | Hit@3 |
| --- | ---: | ---: |
| BM25 com o filtro lexical da aplicação | 6/20 | 30% |
| MiniLM multilíngue + pgvector por distância cosseno | 15/20 | 75% |

A pergunta sobre trocar o modelo azul pelo vermelho recuperou a seção 4.3 apenas com o modelo vetorial. Na consulta sobre a razão social, somente o BM25 recuperou a seção 1.2. Ambos perderam a seção 4.4 na pergunta sobre troca de boquilha. Os rankings de todas as perguntas estão em [results.json](results.json) e as referências em [questions.tsv](questions.tsv).

## Como interpretar

Este conjunto manual cobre perguntas sobre um único documento, incluindo paráfrases. Uma pergunta tem um único rótulo mesmo quando outras seções poderiam ser úteis. Comparamos somente os resultados primários da etapa de recuperação. O filtro BM25 pode se abster, enquanto a consulta vetorial sempre retorna três vizinhos. O contexto adicional curado que o agente anexa depois da busca fica fora da métrica. Este teste não mede respostas do LLM, precisão em perguntas fora de escopo, custo nem latência.

O atendimento continua com BM25. O resultado justifica testar a busca vetorial em mais perguntas, incluindo casos sem resposta e um limiar de abstenção, antes de alterar o comportamento do agente.

## Reprodução

Em Linux, com Python 3.12 e uma conta de usuário comum, execute na raiz do repositório em um ambiente virtual. O banco PostgreSQL 16.2 com pgvector 0.6.2 é criado em uma pasta temporária, em modo local de usuário único, e removido ao terminar. O serviço de atendimento não precisa dessas dependências.

```bash
python -m pip install -r evaluation/requirements.txt
model_dir=$(mktemp -d)
revision=2c4055b12046f11709e9df2c122e59ffbdc2f900
base_url="https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/resolve/$revision"
curl -fL "$base_url/tokenizer.json" -o "$model_dir/tokenizer.json"
curl -fL "$base_url/onnx/model_quantized.onnx" -o "$model_dir/model.onnx"
python -m evaluation.compare --model-dir "$model_dir" > resultado-local.json
```

O modelo MiniLM quantizado gera vetores de 384 dimensões. Seções longas são divididas em janelas de 128 tokens. O vetor da seção combina os estados dos tokens de todas as janelas e é normalizado antes da consulta por distância cosseno. A busca percorre todas as seções, com desempate por ID.

| Arquivo | SHA-256 |
| --- | --- |
| model.onnx | 66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc |
| tokenizer.json | b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441 |
