# 🏦 Banco Ágil — Agente Bancário Inteligente

Sistema de atendimento bancário conversacional com múltiplos agentes de IA especializados
(Triagem, Crédito, Entrevista de Crédito e Câmbio), orquestrados com **LangGraph** e **Gemini**,
com interface de chat em **Streamlit**.

## Visão Geral

O cliente conversa com um único assistente do Banco Ágil. Por trás da conversa, quatro agentes
especializados dividem responsabilidades — autenticação, crédito, entrevista financeira e
câmbio — e se revezam de forma **implícita**: o cliente nunca percebe a troca de "quem" está
respondendo. O sistema:

- Autentica o cliente por CPF + data de nascimento contra `data/clientes.csv`, com no máximo
  3 tentativas (1 inicial + 2 novas).
- Consulta e processa solicitações de aumento de limite de crédito, registrando cada pedido em
  `data/solicitacoes_aumento_limite.csv` e aprovando/rejeitando automaticamente com base no score
  do cliente e na tabela `data/score_limite.csv`.
- Conduz uma entrevista financeira conversacional para recalcular o score de crédito do cliente
  (fórmula ponderada) e atualiza `data/clientes.csv`.
- Consulta cotação de moedas em tempo real via API pública (AwesomeAPI).
- Trata erros de forma amigável (falha de CSV, API fora do ar, entrada inválida) sem derrubar a
  conversa, registrando os detalhes técnicos em `data/erros.log`.

## Arquitetura

### Os 4 agentes

| Agente | Responsabilidade | Arquivo |
|---|---|---|
| Triagem | Saudação, coleta de CPF/data de nascimento, autenticação, identificação do assunto e roteamento | `agents/triagem.py` |
| Crédito | Consulta de limite, solicitação de aumento de limite (aprovação/rejeição automática) | `agents/credito.py` |
| Entrevista de Crédito | Entrevista financeira e recálculo de score | `agents/entrevista.py` |
| Câmbio | Consulta de cotação de moedas | `agents/cambio.py` |

### Orquestração (LangGraph)

Cada agente é um **nó** de um `StateGraph` do LangGraph. O estado compartilhado
(`agents/state.py`) guarda o histórico de mensagens, quem é o cliente autenticado, quantas
tentativas de login já ocorreram, qual agente está ativo (`active_agent`) e se a conversa deve
ser encerrada (`ended`).

Cada nó roda seu próprio mini-loop de *tool calling* (`agents/common.py::run_tool_loop`): chama o
LLM (Gemini) com as ferramentas do seu escopo, executa as ferramentas solicitadas e repete até o
modelo devolver uma resposta final em texto. Uma das ferramentas comuns é `direcionar_para`, que
apenas marca no estado qual deve ser o próximo agente ativo. Uma aresta condicional decide, após
cada nó, se deve:

1. seguir **imediatamente** para o próximo agente (quando houve um redirecionamento) — dentro da
   **mesma** chamada ao grafo, sem esperar nova mensagem do cliente: é isso que torna a transição
   invisível para quem está do outro lado da conversa;
2. ou encerrar o turno (`END`), aguardando a próxima mensagem do cliente.

```
        ┌───────────┐
 ──────▶│  Triagem  │──┐
        └───────────┘  │ direcionar_para("credito"/"cambio"/"entrevista")
                        ▼
        ┌───────────┐        ┌──────────────────────┐
        │  Crédito  │◀──────▶│ Entrevista de Crédito │
        └───────────┘        └──────────────────────┘
              │
              ▼
        ┌───────────┐
        │  Câmbio   │
        └───────────┘
```

A persistência de estado entre mensagens usa o `MemorySaver` (checkpointer em memória do
LangGraph), indexado por `thread_id` — uma sessão por usuário do Streamlit.

### Dados

- `data/clientes.csv` — base de clientes (`cpf`, `nome`, `data_nascimento`, `limite_credito`,
  `score`). Também é atualizada em runtime quando o score ou o limite mudam.
- `data/score_limite.csv` — faixas de score → limite máximo de crédito aprovável
  (`score_min`, `score_max`, `limite_maximo_permitido`).
- `data/solicitacoes_aumento_limite.csv` — log de todas as solicitações de aumento de limite
  (`cpf_cliente`, `data_hora_solicitacao` em ISO 8601, `limite_atual`, `novo_limite_solicitado`,
  `status_pedido`), criado/anexado em runtime.
- `data/erros.log` — log técnico de erros (falhas de CSV, de API externa, de chamada ao LLM),
  criado em runtime.

Toda leitura/escrita de CSV passa por `data_access.py`, que trata erros de IO e os converte em
mensagens amigáveis para o agente repassar ao cliente, sem derrubar a conversa.

## Funcionalidades implementadas

- [x] Saudação, coleta de CPF/data de nascimento e autenticação contra `clientes.csv`.
- [x] Controle de tentativas de autenticação (até 2 novas tentativas após a primeira falha,
  encerramento amigável na 3ª falha consecutiva).
- [x] Identificação do assunto e redirecionamento implícito entre agentes.
- [x] Consulta de limite de crédito disponível.
- [x] Solicitação de aumento de limite, com geração formal do pedido e registro em CSV.
- [x] Aprovação/rejeição automática do pedido de aumento, com base em `score_limite.csv`.
- [x] Oferta de entrevista de crédito quando o pedido é rejeitado.
- [x] Entrevista financeira conversacional (renda, tipo de emprego, despesas, dependentes,
  dívidas) com recálculo de score pela fórmula ponderada e atualização em `clientes.csv`.
- [x] Retorno automático ao Agente de Crédito após a entrevista, para nova análise.
- [x] Consulta de cotação de moedas em tempo real (API AwesomeAPI).
- [x] Encerramento da conversa a qualquer momento, em qualquer agente.
- [x] Tratamento de erros (CSV indisponível/corrompido, API de câmbio fora do ar, falha do
  provedor de LLM, entrada inválida) com mensagens amigáveis e log técnico.
- [x] UI de chat em Streamlit, com histórico de conversa e reinício de atendimento.
- [x] Modo de teste rápido via terminal (`python main.py --cli`).

## Desafios enfrentados e como foram resolvidos

- **Transições "invisíveis" entre agentes.** O desafio pede que o cliente não perceba a troca de
  agente. Em vez do padrão de handoff via `Command`/`InjectedState` do LangGraph (mais opaco),
  optei por uma flag simples no estado (`handoff_pending`) lida por uma aresta condicional: se um
  agente decidiu redirecionar, o grafo já entra no próximo nó **dentro da mesma invocação**, sem
  esperar nova mensagem do usuário. É mais fácil de entender, testar e depurar do que o padrão
  "mágico" de handoff nativo, com o mesmo efeito para o cliente.

- **Contagem confiável de tentativas de autenticação.** Deixar o LLM contar tentativas é
  arriscado (ele pode se confundir ou ser induzido pelo usuário). A contagem de
  `auth_attempts` e a decisão de encerrar após a 3ª falha são feitas em **Python puro**, dentro da
  própria tool de autenticação — o LLM só recebe a instrução do que dizer, nunca decide o número.

- **Erro da API do Gemini ao entregar o turno entre agentes.** Ao testar o handoff (ex.:
  Triagem → Crédito) na mesma resposta, a chamada seguinte ao Gemini falhava com
  `"The final request turn must be a user message or a function response"`. O problema: depois de
  chamar a ferramenta de redirecionamento, o loop de tool-calling do agente de origem fazia mais
  uma chamada ao LLM, terminando o histórico em uma mensagem do assistente — e o próximo nó
  herdava esse histórico como está. A correção foi parar o loop de um agente **imediatamente**
  após um redirecionamento bem-sucedido (sem chamar o LLM de novo), garantindo que o histórico
  sempre termine em uma `ToolMessage` (ou `HumanMessage`) antes de outro nó assumir a conversa.

- **Cálculo de score sensível a variações de texto livre.** Como o tipo de emprego, número de
  dependentes e existência de dívidas vêm de uma conversa livre, normalizei essas respostas
  (acentos, sinônimos como "autônomo"/"autonomo", "sim"/"não") antes de aplicar a fórmula, para
  não quebrar o cálculo por causa de uma variação de digitação do modelo.

- **Fonte de cotação de câmbio confiável.** Em vez de buscar na web e pedir para o LLM extrair o
  valor (sugerido no enunciado, porém propenso a alucinação), usei a API pública AwesomeAPI, que
  devolve dados estruturados (compra/venda) sem necessidade de chave — resultado mais confiável
  para um caso de uso financeiro.

## Escolhas técnicas e justificativas

- **LangGraph** para orquestração: o fluxo exige controle fino de estado (contagem de tentativas,
  cliente autenticado, agente ativo) e transições condicionais — o modelo de grafo de estados do
  LangGraph mapeia diretamente para esses requisitos, com mais previsibilidade do que abstrações
  de "crew"/"squad" mais declarativas.
- **Gemini (`langchain-google-genai`)** como LLM: free tier generoso e bom suporte a
  *function calling*, essencial para a arquitetura de tools por agente.
- **Um nó por agente, cada um com seu próprio system prompt e conjunto de tools**, em vez de um
  único agente genérico com um prompt gigante: mantém o escopo de cada agente estritamente
  delimitado (o próprio LLM só enxerga as ferramentas do seu papel atual) e facilita testar cada
  agente isoladamente.
- **Pandas** para leitura/escrita de CSV: manipulação de faixas de score e atualização de linhas
  específicas fica mais simples e legível do que com o módulo `csv` puro.
- **`MemorySaver`** (checkpointer em memória) para persistência de conversa: suficiente para uma
  aplicação de demonstração local via Streamlit; trocar por um checkpointer persistente (SQLite,
  Postgres) é direto caso o projeto evolua para múltiplos processos/usuários simultâneos.
- **Streamlit** para a UI: forma mais rápida de expor um chat funcional para testes manuais do
  fluxo completo, sem construir front-end dedicado.

## Tutorial de execução e testes

### Pré-requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (ou `pip`, como alternativa)
- Uma chave da API Gemini ([Google AI Studio](https://aistudio.google.com/))

### Instalação

```bash
git clone <url-do-repositorio>
cd banco-agil
uv sync
```

Alternativa sem `uv`:

```bash
pip install -e .
```

### Configuração

Copie o arquivo de exemplo e preencha sua chave:

```bash
cp .env.example .env
# edite .env e defina GEMINI_API_KEY=sua-chave-aqui
```

### Executando a UI (Streamlit)

```bash
uv run streamlit run app.py
```

Abra o endereço exibido no terminal (geralmente `http://localhost:8501`).

### Testando pelo terminal (modo CLI)

Para uma conversa rápida sem abrir o navegador:

```bash
uv run python main.py --cli
```

### Clientes de teste (`data/clientes.csv`)

| CPF | Nome | Data de nascimento | Limite atual | Score |
|---|---|---|---|---|
| 123.456.789-00 | Ana Beatriz Souza | 15/03/1990 | R$ 2.000,00 | 780 |
| 987.654.321-00 | Carlos Eduardo Lima | 22/07/1985 | R$ 1.500,00 | 420 |
| 456.123.789-00 | Fernanda Costa Almeida | 03/11/1978 | R$ 5.000,00 | 910 |
| 321.654.987-00 | João Pedro Rocha | 09/01/1995 | R$ 800,00 | 260 |
| 789.123.456-00 | Mariana Oliveira Santos | 30/05/1988 | R$ 3.000,00 | 650 |
| 654.987.123-00 | Ricardo Alves Pereira | 18/09/1972 | R$ 1.200,00 | 340 |

O CPF pode ser digitado com ou sem pontuação; a data de nascimento aceita formatos comuns
(`DD/MM/AAAA`, `DD-MM-AAAA`, `AAAA-MM-DD`).

### Roteiro de testes manuais sugerido

1. **Autenticação com sucesso** — use um CPF/data da tabela acima.
2. **Falha de autenticação 3x seguidas** — informe dados incorretos repetidamente e confirme o
   encerramento amigável na 3ª tentativa.
3. **Consulta de limite** — "qual meu limite de crédito?".
4. **Aumento aprovado** — autentique como Ana Beatriz (score 780, limite até R$ 15.000,00) e peça
   um novo limite dentro da faixa (ex.: R$ 8.000,00).
5. **Aumento rejeitado + entrevista** — autentique como João Pedro (score 260) e peça um limite
   alto (ex.: R$ 10.000,00); aceite a entrevista quando oferecida, responda as 5 perguntas e
   confirme que o score é atualizado e que você é redirecionado de volta ao crédito.
6. **Câmbio** — "quanto está o dólar hoje?" / "e o euro?".
7. **Encerramento a qualquer momento** — em qualquer ponto da conversa, peça para encerrar o
   atendimento.

### Estrutura do projeto

```
banco-agil/
├── app.py                 # UI Streamlit
├── main.py                 # CLI de teste rápido / instruções de execução
├── config.py                # variáveis de ambiente e caminhos de dados
├── data_access.py           # camada de acesso a CSV, com tratamento de erros
├── agents/
│   ├── state.py             # estado compartilhado do grafo (AgentState)
│   ├── graph.py              # montagem do StateGraph e regras de handoff
│   ├── common.py             # LLM, loop de tool-calling, tools genéricas
│   ├── triagem.py            # Agente de Triagem
│   ├── credito.py            # Agente de Crédito
│   ├── entrevista.py          # Agente de Entrevista de Crédito
│   └── cambio.py              # Agente de Câmbio
└── data/
    ├── clientes.csv
    ├── score_limite.csv
    └── solicitacoes_aumento_limite.csv
```
