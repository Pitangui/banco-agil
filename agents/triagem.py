"""Agente de Triagem: recepciona o cliente, autentica e direciona ao agente adequado."""

from langchain_core.tools import tool

from agents.common import make_direcionar_tool, make_encerrar_tool, run_tool_loop
from agents.state import AgentState
from config import MAX_AUTH_ATTEMPTS
from data_access import DataAccessError, autenticar_cliente

SYSTEM_PROMPT = """Você é o atendente virtual do Banco Ágil (o cliente enxerga apenas um único
assistente, nunca mencione "agentes", "triagem" ou transições internas).

Papel atual: recepção e autenticação.

Fluxo obrigatório quando o cliente ainda não está autenticado:
1. Cumprimente o cliente de forma calorosa e objetiva.
2. Peça o CPF.
3. Peça a data de nascimento (formato livre, ex: 15/03/1990).
4. Assim que tiver os dois dados, chame a ferramenta 'autenticar' — nunca tente validar você mesmo.
5. Se a autenticação falhar, siga exatamente a instrução retornada pela ferramenta (ela informa
   quantas tentativas restam ou se deve encerrar o atendimento). Peça novamente os dados com
   gentileza quando ainda houver tentativas.
6. Se a autenticação for bem-sucedida, cumprimente o cliente pelo nome e pergunte, de forma aberta,
   como pode ajudar (ex: consultar/aumentar limite de crédito, consultar cotação de moedas).

Quando o cliente já estiver autenticado (você retomou a conversa após outro assunto), não peça CPF
ou data de nascimento novamente: apenas identifique o novo assunto desejado.

Assim que identificar claramente o assunto, chame 'direcionar_para' com um destes valores:
- "credito": dúvidas sobre limite de crédito ou pedido de aumento de limite.
- "entrevista": o cliente pede explicitamente para refazer/atualizar a entrevista de crédito.
- "cambio": consulta de cotação de moedas.
Não responda pelo assunto você mesmo; apenas direcione — o próximo especialista assume a conversa
de forma transparente.

Se o cliente pedir para encerrar a conversa a qualquer momento, chame 'encerrar_atendimento'.
Seja respeitoso, objetivo e evite repetições desnecessárias.
"""


def triagem_node(state: AgentState) -> dict:
    ctx = {
        "authenticated": state.get("authenticated", False),
        "auth_attempts": state.get("auth_attempts", 0),
        "cliente": state.get("cliente"),
        "active_agent": state["active_agent"],
        "handoff_pending": False,
        "ended": state.get("ended", False),
    }

    @tool
    def autenticar(cpf: str, data_nascimento: str) -> str:
        """Autentica o cliente pelo CPF e data de nascimento contra a base de clientes.
        Chame assim que tiver coletado os dois dados do cliente na conversa.

        Args:
            cpf: CPF informado pelo cliente (com ou sem pontuação).
            data_nascimento: Data de nascimento informada pelo cliente, em qualquer formato comum.
        """
        if ctx["authenticated"]:
            return "Cliente já autenticado."

        try:
            cliente = autenticar_cliente(cpf, data_nascimento)
        except DataAccessError as exc:
            return (
                f"Erro técnico ao autenticar: {exc} "
                "Peça desculpas ao cliente e sugira tentar novamente em instantes."
            )

        if cliente:
            ctx["authenticated"] = True
            ctx["cliente"] = cliente
            return f"Autenticado com sucesso. Nome do cliente: {cliente['nome']}."

        ctx["auth_attempts"] += 1
        tentativas_restantes = MAX_AUTH_ATTEMPTS - ctx["auth_attempts"]
        if tentativas_restantes <= 0:
            ctx["ended"] = True
            return (
                "Falha na autenticação e limite de tentativas excedido. Informe ao cliente, de "
                "maneira agradável e empática, que não foi possível autenticá-lo desta vez e que "
                "o atendimento será encerrado. Sugira que ele confira os dados e tente novamente "
                "mais tarde."
            )
        return (
            f"CPF e/ou data de nascimento não conferem com nossa base. Restam "
            f"{tentativas_restantes} tentativa(s). Peça novamente os dois dados, com gentileza."
        )

    tools = [
        autenticar,
        make_direcionar_tool(ctx, ["credito", "entrevista", "cambio"]),
        make_encerrar_tool(ctx),
    ]

    new_messages = run_tool_loop(
        SYSTEM_PROMPT, state["messages"], tools, stop_check=lambda: ctx["handoff_pending"]
    )

    return {
        "messages": new_messages,
        "authenticated": ctx["authenticated"],
        "auth_attempts": ctx["auth_attempts"],
        "cliente": ctx["cliente"],
        "active_agent": ctx["active_agent"],
        "handoff_pending": ctx["handoff_pending"],
        "ended": ctx["ended"],
    }
