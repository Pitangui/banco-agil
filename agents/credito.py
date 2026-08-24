"""Agente de Crédito: consulta de limite e solicitação de aumento de limite."""

from langchain_core.tools import tool

from agents.common import make_direcionar_tool, make_encerrar_tool, run_tool_loop
from agents.state import AgentState
from data_access import (
    DataAccessError,
    atualizar_limite_cliente,
    obter_limite_maximo_por_score,
    registrar_solicitacao_aumento,
)

SYSTEM_PROMPT = """Você é o atendente virtual do Banco Ágil (o cliente enxerga apenas um único
assistente; nunca mencione "agentes" ou transições internas).

Papel atual: especialista em crédito, atendendo um cliente já autenticado.

Responsabilidades:
1. Se o cliente perguntar o limite de crédito disponível, chame 'consultar_limite_credito'.
2. Se o cliente quiser solicitar aumento de limite, pergunte qual o novo limite desejado (um
   valor numérico em reais) e então chame 'solicitar_aumento_limite' com esse valor.
3. Reporte o resultado da solicitação de forma clara e formal (ela já foi registrada
   automaticamente em nosso sistema).
4. Se o pedido for REJEITADO, explique isso ao cliente e ofereça, de forma opcional, participar de
   uma entrevista financeira rápida para tentar melhorar o score e reavaliar o limite. Só chame
   'direcionar_para' com "entrevista" se o cliente aceitar explicitamente. Se o cliente recusar,
   pergunte se pode ajudar em algo mais; se ele mencionar outro assunto (ex: câmbio) ou quiser
   encerrar, chame 'direcionar_para' com "triagem" para identificar o novo assunto, ou
   'encerrar_atendimento' se ele quiser parar por aqui.
5. Se o cliente mencionar um assunto fora do escopo de crédito (ex: cotação de moedas), chame
   'direcionar_para' com "triagem".
6. Se o cliente pedir para encerrar a conversa a qualquer momento, chame 'encerrar_atendimento'.

Seja respeitoso, objetivo e evite repetições desnecessárias.
"""


def credito_node(state: AgentState) -> dict:
    cliente = state.get("cliente") or {}
    ctx = {
        "cliente": dict(cliente),
        "active_agent": state["active_agent"],
        "handoff_pending": False,
        "ended": state.get("ended", False),
    }

    @tool
    def consultar_limite_credito() -> str:
        """Consulta o limite de crédito atual do cliente autenticado."""
        return f"Limite de crédito atual: R$ {ctx['cliente'].get('limite_credito', 0):.2f}."

    @tool
    def solicitar_aumento_limite(novo_limite: float) -> str:
        """Registra formalmente uma solicitação de aumento de limite de crédito e avalia
        automaticamente a aprovação com base no score de crédito do cliente.

        Args:
            novo_limite: Novo limite de crédito desejado pelo cliente, em reais.
        """
        cpf = ctx["cliente"].get("cpf")
        limite_atual = ctx["cliente"].get("limite_credito", 0.0)
        score = ctx["cliente"].get("score", 0)

        if novo_limite <= limite_atual:
            return (
                "O novo limite solicitado deve ser maior que o limite atual. Peça ao cliente um "
                "valor de limite superior ao atual."
            )

        try:
            limite_maximo_permitido = obter_limite_maximo_por_score(score)
            status = "aprovado" if novo_limite <= limite_maximo_permitido else "rejeitado"
            registrar_solicitacao_aumento(cpf, limite_atual, novo_limite, status)
            if status == "aprovado":
                atualizar_limite_cliente(cpf, novo_limite)
                ctx["cliente"]["limite_credito"] = novo_limite
        except DataAccessError as exc:
            return (
                f"Erro técnico ao processar a solicitação: {exc} "
                "Peça desculpas ao cliente e sugira tentar novamente em instantes."
            )

        if status == "aprovado":
            return (
                f"Pedido APROVADO. Novo limite de crédito: R$ {novo_limite:.2f} "
                f"(limite anterior: R$ {limite_atual:.2f})."
            )
        return (
            f"Pedido REJEITADO para o valor de R$ {novo_limite:.2f} com base no score atual do "
            f"cliente ({score}). Ofereça ao cliente a possibilidade de fazer uma entrevista "
            "financeira para tentar melhorar o score."
        )

    tools = [
        consultar_limite_credito,
        solicitar_aumento_limite,
        make_direcionar_tool(ctx, ["entrevista", "triagem"]),
        make_encerrar_tool(ctx),
    ]

    new_messages = run_tool_loop(
        SYSTEM_PROMPT, state["messages"], tools, stop_check=lambda: ctx["handoff_pending"]
    )

    return {
        "messages": new_messages,
        "cliente": ctx["cliente"],
        "active_agent": ctx["active_agent"],
        "handoff_pending": ctx["handoff_pending"],
        "ended": ctx["ended"],
    }
