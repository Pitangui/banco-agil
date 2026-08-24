"""Ponto de entrada do Banco Ágil.

Para a experiência completa (UI), rode:
    streamlit run app.py

Este script também oferece um modo de teste rápido via terminal:
    python main.py --cli
"""

import sys
import uuid

from langchain_core.messages import AIMessage, HumanMessage

from agents.graph import build_graph

GREETING = "Olá! Seja bem-vindo(a) ao Banco Ágil. 😊 Para começarmos, poderia me informar seu CPF?"


def estado_inicial():
    return {
        "messages": [AIMessage(content=GREETING)],
        "active_agent": "triagem",
        "handoff_pending": False,
        "authenticated": False,
        "auth_attempts": 0,
        "cliente": None,
        "ended": False,
    }


def run_cli():
    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.update_state(config, estado_inicial())

    print(f"Assistente: {GREETING}")
    while True:
        estado = graph.get_state(config).values
        if estado.get("ended"):
            print("\n[Atendimento encerrado]")
            break
        try:
            entrada = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not entrada:
            continue

        mensagens_antes = len(estado["messages"])
        graph.invoke({"messages": [HumanMessage(content=entrada)]}, config)
        novo_estado = graph.get_state(config).values
        for msg in novo_estado["messages"][mensagens_antes:]:
            if isinstance(msg, AIMessage) and msg.text:
                print(f"Assistente: {msg.text}")


def main():
    if "--cli" in sys.argv:
        run_cli()
    else:
        print("Este projeto é uma aplicação Streamlit.")
        print("Para executar a UI completa, rode:  streamlit run app.py")
        print("Para um teste rápido via terminal, rode:  python main.py --cli")


if __name__ == "__main__":
    main()
