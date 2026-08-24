"""Agente de Entrevista de Crédito: recalcula o score financeiro do cliente."""

from langchain_core.tools import tool

from agents.common import make_direcionar_tool, make_encerrar_tool, run_tool_loop
from agents.state import AgentState
from data_access import DataAccessError, atualizar_score_cliente

PESO_RENDA = 30
PESO_EMPREGO = {"formal": 300, "autonomo": 200, "desempregado": 0}
PESO_DEPENDENTES = {0: 100, 1: 80, 2: 60, "3+": 30}
PESO_DIVIDAS = {"sim": -100, "nao": 100}

SYSTEM_PROMPT = """Você é o atendente virtual do Banco Ágil (o cliente enxerga apenas um único
assistente; nunca mencione "agentes" ou transições internas).

Papel atual: entrevista financeira para recalcular o score de crédito do cliente, uma pergunta
de cada vez, de forma natural e conversacional. Colete exatamente estas informações:
1. Renda mensal (em reais).
2. Tipo de emprego: formal, autônomo ou desempregado.
3. Despesas fixas mensais (em reais).
4. Número de dependentes (0, 1, 2 ou 3 ou mais).
5. Se possui dívidas ativas (sim ou não).

Assim que tiver as cinco respostas, chame 'calcular_e_atualizar_score' com os valores coletados.
Informe o cliente do novo score de forma clara. Em seguida, sempre chame 'direcionar_para' com
"credito" para que ele receba uma nova análise de crédito com o score atualizado.

Se o cliente pedir para encerrar a conversa a qualquer momento, chame 'encerrar_atendimento'.
Seja respeitoso, objetivo e evite repetições desnecessárias.
"""


def _normalizar_tipo_emprego(valor: str) -> str:
    v = valor.strip().lower()
    v = v.replace("ô", "o").replace("ó", "o")
    if "autonomo" in v:
        return "autonomo"
    if "desemprega" in v:
        return "desempregado"
    return "formal"


def _normalizar_dependentes(valor: int):
    if valor >= 3:
        return "3+"
    return valor


def _normalizar_dividas(valor: str) -> str:
    v = valor.strip().lower()
    if v.startswith("s"):
        return "sim"
    return "nao"


def calcular_score(
    renda_mensal: float,
    tipo_emprego: str,
    despesas_fixas: float,
    num_dependentes: int,
    tem_dividas: str,
) -> int:
    emprego = _normalizar_tipo_emprego(tipo_emprego)
    dependentes = _normalizar_dependentes(num_dependentes)
    dividas = _normalizar_dividas(tem_dividas)

    score = (
        (renda_mensal / (despesas_fixas + 1)) * PESO_RENDA
        + PESO_EMPREGO[emprego]
        + PESO_DEPENDENTES[dependentes]
        + PESO_DIVIDAS[dividas]
    )
    return max(0, min(1000, round(score)))


def entrevista_node(state: AgentState) -> dict:
    cliente = state.get("cliente") or {}
    ctx = {
        "cliente": dict(cliente),
        "active_agent": state["active_agent"],
        "handoff_pending": False,
        "ended": state.get("ended", False),
    }

    @tool
    def calcular_e_atualizar_score(
        renda_mensal: float,
        tipo_emprego: str,
        despesas_fixas: float,
        num_dependentes: int,
        tem_dividas: str,
    ) -> str:
        """Calcula o novo score de crédito (0 a 1000) com base nas respostas da entrevista
        financeira e atualiza a base de clientes.

        Args:
            renda_mensal: Renda mensal do cliente, em reais.
            tipo_emprego: 'formal', 'autonomo' ou 'desempregado'.
            despesas_fixas: Despesas fixas mensais do cliente, em reais.
            num_dependentes: Número de dependentes do cliente.
            tem_dividas: 'sim' ou 'nao', indicando se o cliente possui dívidas ativas.
        """
        novo_score = calcular_score(
            renda_mensal, tipo_emprego, despesas_fixas, num_dependentes, tem_dividas
        )
        try:
            atualizar_score_cliente(ctx["cliente"].get("cpf"), novo_score)
        except DataAccessError as exc:
            return (
                f"Erro técnico ao atualizar o score: {exc} "
                "Peça desculpas ao cliente e sugira tentar novamente em instantes."
            )
        ctx["cliente"]["score"] = novo_score
        return f"Novo score calculado e atualizado com sucesso: {novo_score}."

    tools = [
        calcular_e_atualizar_score,
        make_direcionar_tool(ctx, ["credito"]),
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
