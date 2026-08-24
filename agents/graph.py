"""Monta o grafo de agentes (LangGraph) do Banco Ágil."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.cambio import cambio_node
from agents.credito import credito_node
from agents.entrevista import entrevista_node
from agents.state import AgentState
from agents.triagem import triagem_node

AGENT_NODES = ("triagem", "credito", "entrevista", "cambio")


def _route_entry(state: AgentState) -> str:
    """Cada turno começa no agente que estava ativo ao final do turno anterior."""
    return state.get("active_agent") or "triagem"


def _route_after_agent(state: AgentState) -> str:
    """Handoff implícito: se um agente pediu redirecionamento, segue direto para o próximo nó
    dentro do mesmo turno (o cliente não percebe a transição). Caso contrário, o turno termina
    aguardando a próxima mensagem do usuário."""
    if state.get("ended"):
        return END
    if state.get("handoff_pending"):
        return state["active_agent"]
    return END


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("triagem", triagem_node)
    graph.add_node("credito", credito_node)
    graph.add_node("entrevista", entrevista_node)
    graph.add_node("cambio", cambio_node)

    graph.add_conditional_edges(START, _route_entry, {n: n for n in AGENT_NODES})

    path_map = {n: n for n in AGENT_NODES}
    path_map[END] = END
    for nome in AGENT_NODES:
        graph.add_conditional_edges(nome, _route_after_agent, path_map)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
