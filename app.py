"""UI Streamlit do Banco Ágil — chat único que, por trás, orquestra os 4 agentes especializados."""

import uuid

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agents.graph import build_graph

GREETING = "Olá! Seja bem-vindo(a) ao Banco Ágil. 😊 Para começarmos, poderia me informar seu CPF?"

st.set_page_config(page_title="Banco Ágil", page_icon="🏦")


@st.cache_resource
def get_graph():
    return build_graph()


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


def iniciar_sessao():
    graph = get_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph.update_state(config, estado_inicial())
    st.session_state.thread_id = thread_id
    st.session_state.config = config


if "thread_id" not in st.session_state:
    iniciar_sessao()

st.title("🏦 Banco Ágil")
st.caption("Atendimento inteligente — crédito, entrevista financeira e câmbio em uma só conversa.")

graph = get_graph()
config = st.session_state.config
estado_atual = graph.get_state(config).values
mensagens = estado_atual.get("messages", [])
encerrado = estado_atual.get("ended", False)

for msg in mensagens:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.markdown(msg.content)
    elif isinstance(msg, AIMessage) and msg.text:
        with st.chat_message("assistant"):
            st.markdown(msg.text)

if encerrado:
    st.info("Atendimento encerrado. Obrigado por escolher o Banco Ágil!")
    if st.button("Iniciar novo atendimento"):
        iniciar_sessao()
        st.rerun()
else:
    entrada = st.chat_input("Digite sua mensagem...")
    if entrada:
        with st.chat_message("user"):
            st.markdown(entrada)
        with st.spinner("Digitando..."):
            graph.invoke({"messages": [HumanMessage(content=entrada)]}, config)
        st.rerun()
