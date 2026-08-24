"""Agente de Câmbio: consulta de cotação de moedas em tempo real."""

import logging

import requests
from langchain_core.tools import tool

from agents.common import make_direcionar_tool, make_encerrar_tool, run_tool_loop
from agents.state import AgentState
from config import ERROS_LOG

logging.basicConfig(
    filename=str(ERROS_LOG),
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("banco_agil.agents.cambio")

AWESOMEAPI_URL = "https://economia.awesomeapi.com.br/json/last/{par}"

MOEDAS = {
    "dolar": "USD",
    "dólar": "USD",
    "usd": "USD",
    "euro": "EUR",
    "eur": "EUR",
    "libra": "GBP",
    "libra esterlina": "GBP",
    "gbp": "GBP",
    "peso argentino": "ARS",
    "ars": "ARS",
    "iene": "JPY",
    "jpy": "JPY",
    "franco suico": "CHF",
    "franco suiço": "CHF",
    "chf": "CHF",
    "bitcoin": "BTC",
    "btc": "BTC",
}

SYSTEM_PROMPT = """Você é o atendente virtual do Banco Ágil (o cliente enxerga apenas um único
assistente; nunca mencione "agentes" ou transições internas).

Papel atual: consulta de cotação de moedas, para um cliente já autenticado.

Responsabilidades:
1. Identifique qual moeda o cliente deseja consultar (padrão: dólar, se ele não especificar).
2. Chame 'consultar_cotacao' com o nome da moeda.
3. Apresente a cotação de forma clara e amigável, e encerre esse assunto especificamente com uma
   mensagem simpática, perguntando se pode ajudar em algo mais.
4. Se o cliente mencionar outro assunto (ex: crédito) ou não quiser mais nada, chame
   'direcionar_para' com "triagem" para identificar o próximo passo.
5. Se o cliente pedir para encerrar a conversa a qualquer momento, chame 'encerrar_atendimento'.

Seja respeitoso, objetivo e evite repetições desnecessárias.
"""


def _resolver_codigo_moeda(moeda: str) -> str:
    chave = moeda.strip().lower()
    if chave in MOEDAS:
        return MOEDAS[chave]
    if len(chave) == 3 and chave.isalpha():
        return chave.upper()
    return ""


def cambio_node(state: AgentState) -> dict:
    ctx = {
        "active_agent": state["active_agent"],
        "handoff_pending": False,
        "ended": state.get("ended", False),
    }

    @tool
    def consultar_cotacao(moeda: str) -> str:
        """Consulta a cotação atual de uma moeda em relação ao Real (BRL) em uma API externa.

        Args:
            moeda: Nome ou código da moeda desejada (ex: 'dólar', 'euro', 'USD').
        """
        codigo = _resolver_codigo_moeda(moeda)
        if not codigo:
            return (
                f"Não reconheci a moeda '{moeda}'. Peça ao cliente para informar o nome usual "
                "(ex: dólar, euro, libra) ou o código de 3 letras (ex: USD)."
            )

        par = f"{codigo}-BRL"
        try:
            resposta = requests.get(AWESOMEAPI_URL.format(par=par), timeout=5)
            resposta.raise_for_status()
            dados = resposta.json()
            info = dados[f"{codigo}BRL"]
            return (
                f"Cotação atual: 1 {codigo} = R$ {float(info['bid']):.4f} "
                f"(compra) / R$ {float(info['ask']):.4f} (venda)."
            )
        except (requests.exceptions.RequestException, KeyError, ValueError) as exc:
            logger.error("Falha ao consultar cotação para %s: %s", par, exc)
            return (
                "O serviço de cotação de moedas está indisponível no momento. Peça desculpas ao "
                "cliente e sugira tentar novamente em instantes."
            )

    tools = [
        consultar_cotacao,
        make_direcionar_tool(ctx, ["triagem"]),
        make_encerrar_tool(ctx),
    ]

    new_messages = run_tool_loop(
        SYSTEM_PROMPT, state["messages"], tools, stop_check=lambda: ctx["handoff_pending"]
    )

    return {
        "messages": new_messages,
        "active_agent": ctx["active_agent"],
        "handoff_pending": ctx["handoff_pending"],
        "ended": ctx["ended"],
    }
