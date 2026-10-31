# Empório da Música AI

Protótipo em Python de um agente de atendimento para a loja fictícia Empório da Música. Combina chamadas de funções pela Groq, consultas locais ao catálogo em SQLite e recuperação de trechos do manual em PDF.

O foco é responder com base nos dados fornecidos no desafio e encaminhar condições não definidas para confirmação humana. Os CSVs representam uma base estática: consultar o banco durante a execução **não equivale a consultar estoque em tempo real**.

## O que está implementado

- Busca por produto e categoria, com disponibilidade e teto de preço final.
- Cotação de uma unidade, considerando promoção ativa ou desconto PIX sem acumulação.
- Consulta a políticas com seção, página e contexto relacionado.
- Estimativa de frete local e encaminhamento de casos sem regra ou sem integração de transportadora.
- Redirecionamento de assuntos fora do atendimento da loja.
- Saída JSON com resposta, ferramentas consultadas, fontes e uso de tokens.

## Executar no Windows / PowerShell

Use Python instalado e uma chave de API da Groq com acesso ao modelo configurado. O desenvolvimento foi validado pelo autor no Windows com Python 3.14. Os testes automatizados também foram executados em Python 3.12.

Na primeira instalação:

```powershell
git clone https://github.com/TenorioDevfullStack/emporio-musica-ai.git
cd emporio-musica-ai
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Abra `.env`, preencha `GROQ_API_KEY` com sua chave e salve. `GROQ_MODEL` pode permanecer como `openai/gpt-oss-120b`. A chave é configurada no computador de quem executa o projeto. O `.gitignore` exclui o `.env` e permite versionar o exemplo sem segredo.

Importe a base e teste uma pergunta:

```powershell
.\.venv\Scripts\python.exe app/import_data.py
.\.venv\Scripts\python.exe app/check_groq.py
.\.venv\Scripts\python.exe app/agent.py --query "Tem Ohana CK-20 por até 500 reais?"
```

`import_data.py` usa os seis CSVs originais em `data/` para criar `data/store.sqlite3`. As reexecuções atualizam registros por ID e não removem registros ausentes de versões futuras dos CSVs. O banco gerado não é versionado.

Os comandos acima chamam o executável da venv diretamente. Se a venv já estiver ativa, é possível usar apenas `python`.

### Linux / macOS

Após clonar e entrar no projeto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Preencha a chave no .env antes dos comandos que usam a Groq.
.venv/bin/python app/import_data.py
.venv/bin/python app/agent.py --query "Tem Ohana CK-20 por até 500 reais?"
```

Variáveis já definidas no ambiente têm prioridade sobre o `.env`. O modelo padrão é servido pela **Groq** e é acessado com uma chave da Groq. O nome `openai/` no identificador do modelo não exige uma chave da API da OpenAI.

## Testes

Na raiz, com as dependências instaladas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

São **32 testes locais**, sem chamada real à Groq e sem necessidade de chave. Os testes de catálogo criam um banco temporário a partir dos CSVs e não alteram o banco do aplicativo. Os testes de políticas leem o PDF original. O ciclo do agente recebe respostas simuladas no formato do SDK.

Cobrem preços e não acumulação de descontos, recuperação de políticas, argumentos inválidos, protocolo de ferramentas, limites de chamadas, respostas incompletas, regras de frete, ausência de informações e redirecionamento de escopo. Esses testes verificam a lógica do aplicativo; não medem a precisão geral do modelo nem garantem resistência a toda tentativa de desvio de instruções.

No Linux/macOS, use `.venv/bin/python -m unittest discover -s tests -v`.

As interações reais executadas pelo autor com a Groq estão nos cinco arquivos de [examples/](examples/). Cada arquivo identifica o cenário e registra resposta e metadados selecionados daquela execução. Foram coletados durante o desenvolvimento, em etapas diferentes; não são resultados de uma nova avaliação automática de todos os cenários na última versão.

| Exemplo | Cenário |
|---|---|
| [01 - Catálogo](examples/01_catalogo.md) | Produto abaixo do orçamento após promoção. |
| [02 - Devolução](examples/02_devolucao.md) | Prazo, frete de devolução e referência ao manual. |
| [03 - Frete local](examples/03_frete_local.md) | Estimativa com ressalva sobre a base de descontos. |
| [04 - Limite de frete](examples/04_frete_limite.md) | Confirmação humana para exatamente R$ 500. |
| [05 - Fora de escopo](examples/05_fora_escopo.md) | Redirecionamento de uma receita para o atendimento da loja. |

## Como funciona

| Módulo | Responsabilidade |
|---|---|
| `app/import_data.py` | Valida os CSVs e importa dados em transação para SQLite. |
| `app/catalog.py` | Faz consultas parametrizadas, normaliza texto e informa disponibilidade. |
| `app/pricing.py` | Aplica a regra de preço e filtra ofertas pelo valor final. |
| `app/policies.py` | Extrai seções do PDF, classifica trechos por BM25 e acrescenta contexto relacionado. |
| `app/shipping.py` | Estima frete com valor do pedido e região informados. |
| `app/agent.py` | Define a persona, disponibiliza ferramentas, executa o ciclo e aplica respostas controladas. |
| `app/check_groq.py` | Faz um teste pequeno de acesso ao modelo. |

O modelo recebe a pergunta, o prompt de sistema e os esquemas das ferramentas. Ele solicita uma função com argumentos JSON; o aplicativo valida esses argumentos, executa uma função permitida e devolve seu resultado. Consultas de catálogo e políticas normalmente podem ser seguidas de outra chamada ao modelo para formular a resposta.

Para frete, conflito de parcelamento, saudações e redirecionamentos de escopo, o aplicativo pode encerrar com texto controlado. Essa decisão veio de falhas observadas nos testes reais: o modelo descreveu incorretamente um conflito do manual, acrescentou uma regra de frete que não estava definida e respondeu a uma receita fora do escopo. A resposta controlada evita uma nova interpretação livre nesses caminhos específicos.

O roteamento inicial continua dependendo do modelo. Não há classificador baseado apenas em palavras como “bolo”. Se o modelo retornar texto livre sem chamar ferramenta alguma, o aplicativo substitui esse texto por um pedido de esclarecimento dentro do atendimento da loja.

### Decisões técnicas

- **Python e SDK oficial da Groq:** mantêm o protótipo pequeno, permitem inspecionar o protocolo e reaproveitam as funções locais. Não foi necessário um framework de agentes para este escopo.
- **`openai/gpt-oss-120b` na Groq:** foi o modelo escolhido e validado com a chave do autor. Cotas e disponibilidade dependem do provedor e da conta; o projeto não pressupõe uso gratuito ilimitado.
- **SQLite:** suficiente para a base pequena, reproduzível a partir dos CSVs e sem exigir serviço externo. O agente não recebe uma ferramenta para executar SQL arbitrário e as consultas de atendimento abrem o banco em modo de leitura.
- **Valores em centavos inteiros:** evitam arredondamento binário nas contas. A conversão de entrada usa `Decimal`; o preço final é arredondado para centavos.
- **Recuperação textual por seção:** BM25, normalização e sinônimos simples são uma escolha verificável para um manual curto. Não há embeddings, banco vetorial nem classificação semântica geral.
- **CLI com JSON:** permite usar o agente sem interface adicional e torna ferramentas, fontes e consumo inspecionáveis.
- **Sem histórico nesta versão:** cada execução é independente. Isso simplifica a reprodução dos cenários, mas exige informar novamente dados necessários em outra pergunta.

## Regras e ambiguidades preservadas

### Produtos e preços

A disponibilidade depende de produto ativo e estoque positivo na base fornecida. Produtos descontinuados ou futuros não são oferecidos como disponíveis. `search_offers` filtra pelo preço final de uma unidade, sem frete. A promoção ativa e o desconto PIX não são acumulados; várias promoções ativas exigem confirmação. A vigência segue `is_active`, sem deduzir datas a partir do nome de uma campanha.

### Políticas

Os resultados incluem páginas e contexto relacionado, por exemplo as exceções da seção 4.4 junto às condições de devolução. As marcações de ambiguidade são anotações revisadas no código, não expressões que necessariamente aparecem no manual nem detecção automática de toda contradição.

O parcelamento recebe tratamento conservador: quando a recuperação sinaliza o conflito entre a tabela geral e as faixas detalhadas, o agente apresenta os trechos e pede confirmação. Isso também pode ocorrer em perguntas sobre uma faixa em que as seções coincidem. Não há calculadora de parcelas nem decisão automática sobre qual seção prevalece.

### Frete

Para a região metropolitana de Campo Grande/MS, o manual indica R$ 35 abaixo de R$ 500 e gratuidade acima de R$ 500. Para exatamente R$ 500, a taxa fica indefinida e o agente pede confirmação. `null` não é convertido em frete zero.

A estimativa usa o valor do pedido sem frete informado pelo cliente. O manual não esclarece se o limiar deve considerar o valor antes ou depois dos descontos. O aplicativo não resolve essa ambiguidade e não usa automaticamente o preço de um produto como total do pedido.

Para outras cidades, o valor depende de CEP, peso e dimensões e exige cotação. Não há integração com Correios ou Jadlog, consulta automática de CEP nem determinação automática de pertencimento de municípios à região metropolitana. Prazos são estimativas em dias úteis.

## Interpretar a saída

`response` é o texto para o cliente. `tools_used` registra as ferramentas executadas; `sources` identifica dados ou trechos consultados, inclusive contexto adicional que pode não aparecer na resposta. `shipping_quotes` contém as estimativas estruturadas de frete.

Quando presente, `response_origin` informa um caminho controlado como `policy_guard`, `shipping_guard` ou `scope_guard`. A lista de fontes fornece rastreabilidade da consulta, mas não representa uma validação automática de cada afirmação da resposta gerada pelo modelo.

| `status` do agente | Interpretação |
|---|---|
| `ok` | O fluxo terminou com uma resposta. Não é uma certificação de veracidade. |
| `needs_information` | É preciso esclarecer o pedido ou fornecer dados. |
| `needs_confirmation` | Uma regra precisa ser confirmada pela equipe. |
| `requires_quote` | É necessária uma cotação não integrada ao protótipo. |
| `out_of_scope` | O assunto foi redirecionado para o atendimento da loja. |
| `incomplete_response` / `step_limit` | A geração ou o limite de etapas impediu a conclusão. |
| `error` | A CLI encontrou erro de configuração, autenticação ou comunicação. |

Na CLI do agente, `ok` retorna código de saída 0. Estados como confirmação, cotação e fora de escopo retornam 2, embora possam representar um comportamento esperado de atendimento. Erros tratados de configuração/API retornam 1 e mensagem no stderr.

`usage` soma os tokens reportados pela API nas chamadas realizadas. `usage_complete` indica se todas forneceram contagem. O agente limita cada pergunta a cinco chamadas à API e oito execuções de ferramentas, sem repetição automática de chamadas. O timeout de 30 segundos é por chamada, não pelo atendimento inteiro.

## Limitações e próximos passos

Não há consulta de status de pedidos, identificação/autenticação de clientes, reserva, fechamento de compra ou alteração de registros. Os CSVs de clientes e pedidos são importados, mas essas tabelas não são expostas ao modelo. A escolha foi priorizar catálogo, regras comerciais e políticas; o enunciado permite selecionar os dados necessários ao protótipo.

Perguntas com várias intenções podem ter resposta parcial porque um caminho controlado pode encerrar o turno antes de sintetizar todos os resultados. A recuperação lexical pode perder paráfrases e pode incluir trechos pouco relevantes. Há extrações com palavras coladas no PDF e a classificação de escopo não foi avaliada em um conjunto amplo de perguntas adversariais. A disponibilidade das dependências Groq e python-dotenv não está fixada por versão no `requirements.txt` atual.

Com mais tempo, priorizaria histórico de conversa, avaliação com conjunto maior de perguntas e verificações de fidelidade, normalização da extração do manual, cálculo de parcelas com regras validadas pela loja, tratamento de múltiplas intenções e ambiente de dependências fixado. Consulta de pedidos exigiria também uma estratégia de identificação e restrição de acesso aos dados do cliente.

## Uso de assistente de código

O ChatGPT foi usado de forma iterativa para propor a arquitetura, gerar e revisar módulos, elaborar testes e preparar documentação. O autor incorporou os arquivos ao projeto, configurou a chave localmente, executou os comandos e compartilhou as saídas reais para análise. A revisão dessas saídas revelou falhas que levaram às correções de parcelamento, frete e escopo, registradas em commits incrementais.

Os testes locais com respostas de API simuladas não foram apresentados como chamadas reais ao modelo. Os exemplos de interação foram selecionados dos testes reais fornecidos pelo autor. A assistência por IA faz parte do workflow declarado deste protótipo.
