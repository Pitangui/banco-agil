"""Estado compartilhado entre os nós do grafo de agentes."""

from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

AgentName = Literal["triagem", "credito", "entrevista", "cambio"]


class ClienteState(TypedDict):
    cpf: str
    nome: str
    data_nascimento: str
    limite_credito: float
    score: int


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    active_agent: AgentName
    handoff_pending: bool
    authenticated: bool
    auth_attempts: int
    cliente: Optional[ClienteState]
    ended: bool
