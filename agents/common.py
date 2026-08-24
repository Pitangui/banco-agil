"""Utilitários compartilhados pelos nós de agente: LLM, loop de tool-calling e tools genéricas."""

import logging

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from config import ERROS_LOG, GEMINI_API_KEY, GEMINI_MODEL

logging.basicConfig(
    filename=str(ERROS_LOG),
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("banco_agil.agents")

MAX_TOOL_ITERATIONS = 6


def get_llm(tools: list | None = None):
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.3,
    )
    if tools:
        llm = llm.bind_tools(tools)
    return llm


def make_encerrar_tool(ctx: dict):
    """Tool global: encerra o atendimento. Disponível em todos os agentes."""

    @tool
    def encerrar_atendimento() -> str:
        """Encerra definitivamente o atendimento. Use a qualquer momento em que o cliente pedir
        explicitamente para encerrar, sair ou parar a conversa."""
        ctx["ended"] = True
        return "Atendimento encerrado."

    return encerrar_atendimento


def make_direcionar_tool(ctx: dict, destinos: list[str]):
    """Tool de handoff implícito: muda o agente ativo sem que o cliente perceba a transição."""
    destinos_tuple = tuple(destinos)

    @tool
    def direcionar_para(agente: str) -> str:
        """Redireciona o atendimento internamente para outro agente especializado do banco,
        de forma transparente ao cliente (ele não deve perceber a troca). O valor de 'agente'
        deve ser exatamente um dos destinos permitidos indicados no seu prompt de sistema."""
        if agente not in destinos_tuple:
            return f"Destino inválido: '{agente}'. Destinos permitidos: {', '.join(destinos_tuple)}."
        ctx["active_agent"] = agente
        ctx["handoff_pending"] = True
        return "ok"

    return direcionar_para


def run_tool_loop(system_prompt: str, messages: list, tools: list, stop_check=None) -> list:
    """Roda um loop de chamadas de ferramenta com o LLM até obter uma resposta final em texto.

    Se 'stop_check' for informado, é avaliado após cada rodada de tool calls; quando retornar
    True (ex: um handoff para outro agente foi disparado), o loop para imediatamente, sem fazer
    uma nova chamada ao LLM. Isso é necessário porque, ao entregar o turno a outro nó do grafo
    dentro da mesma invocação, o histórico de mensagens precisa terminar em uma ToolMessage (ou
    HumanMessage) — a API do Gemini rejeita requisições cuja última mensagem é do assistente.

    Retorna a lista de novas mensagens (AIMessage/ToolMessage) geradas nesta rodada, prontas
    para serem anexadas ao histórico do estado do grafo.
    """
    llm = get_llm(tools)
    tools_by_name = {t.name: t for t in tools}
    conversation = [SystemMessage(content=system_prompt)] + list(messages)
    new_messages: list = []

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            ai_message: AIMessage = llm.invoke(conversation)
        except Exception as exc:  # falha de comunicação com o provedor do LLM
            logger.error("Falha ao chamar o modelo LLM: %s", exc)
            new_messages.append(
                AIMessage(
                    content=(
                        "Estamos com instabilidade para processar sua solicitação agora. "
                        "Por favor, tente novamente em instantes."
                    )
                )
            )
            return new_messages

        conversation.append(ai_message)
        new_messages.append(ai_message)

        if not ai_message.tool_calls:
            break

        for call in ai_message.tool_calls:
            tool_fn = tools_by_name.get(call["name"])
            if tool_fn is None:
                result = f"Ferramenta desconhecida: {call['name']}"
            else:
                try:
                    result = tool_fn.invoke(call["args"])
                except Exception as exc:
                    logger.error("Falha ao executar tool '%s': %s", call["name"], exc)
                    result = "Ocorreu um erro técnico ao processar essa ação. Informe ao cliente e sugira tentar novamente."
            tool_message = ToolMessage(content=str(result), tool_call_id=call["id"])
            conversation.append(tool_message)
            new_messages.append(tool_message)

        if stop_check and stop_check():
            break

    return new_messages
