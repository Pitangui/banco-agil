"""Camada de acesso a dados (CSV) com tratamento de erros.

Todas as leituras/escritas de clientes.csv, score_limite.csv e
solicitacoes_aumento_limite.csv passam por aqui. Erros de IO são
logados em data/erros.log e relançados como DataAccessError, para
que os agentes possam responder ao cliente de forma amigável em vez
de quebrar a conversa.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from config import CLIENTES_CSV, ERROS_LOG, SCORE_LIMITE_CSV, SOLICITACOES_CSV

logging.basicConfig(
    filename=str(ERROS_LOG),
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("banco_agil.data_access")


class DataAccessError(Exception):
    """Erro de acesso a dados (CSV indisponível, corrompido, etc.)."""


def _log_and_raise(operacao: str, exc: Exception) -> None:
    logger.error("Falha em %s: %s", operacao, exc)
    raise DataAccessError(
        f"Não foi possível concluir a operação '{operacao}' no momento."
    ) from exc


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def normalizar_data(valor: str) -> Optional[str]:
    """Normaliza datas em formatos comuns para DD/MM/AAAA. Retorna None se inválida."""
    valor = (valor or "").strip()
    formatos = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"]
    for fmt in formatos:
        try:
            return datetime.strptime(valor, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return None


def _ler_clientes() -> pd.DataFrame:
    try:
        return pd.read_csv(CLIENTES_CSV, dtype={"cpf": str, "data_nascimento": str})
    except (FileNotFoundError, pd.errors.EmptyDataError, PermissionError) as exc:
        _log_and_raise("leitura de clientes.csv", exc)


def _cliente_row_to_dict(row: pd.Series) -> dict:
    return {
        "cpf": str(row["cpf"]),
        "nome": str(row["nome"]),
        "data_nascimento": str(row["data_nascimento"]),
        "limite_credito": float(row["limite_credito"]),
        "score": int(row["score"]),
    }


def autenticar_cliente(cpf: str, data_nascimento: str) -> Optional[dict]:
    """Retorna os dados do cliente se cpf + data de nascimento baterem, senão None."""
    cpf_norm = somente_digitos(cpf)
    data_norm = normalizar_data(data_nascimento)
    if not cpf_norm or not data_norm:
        return None

    df = _ler_clientes()
    df["_cpf_norm"] = df["cpf"].apply(somente_digitos)
    match = df[(df["_cpf_norm"] == cpf_norm) & (df["data_nascimento"] == data_norm)]
    if match.empty:
        return None
    return _cliente_row_to_dict(match.iloc[0])


def obter_cliente(cpf: str) -> Optional[dict]:
    cpf_norm = somente_digitos(cpf)
    df = _ler_clientes()
    df["_cpf_norm"] = df["cpf"].apply(somente_digitos)
    match = df[df["_cpf_norm"] == cpf_norm]
    if match.empty:
        return None
    return _cliente_row_to_dict(match.iloc[0])


def obter_limite_maximo_por_score(score: int) -> float:
    try:
        df = pd.read_csv(SCORE_LIMITE_CSV)
    except (FileNotFoundError, pd.errors.EmptyDataError, PermissionError) as exc:
        _log_and_raise("leitura de score_limite.csv", exc)

    faixa = df[(df["score_min"] <= score) & (score <= df["score_max"])]
    if faixa.empty:
        # score fora de todas as faixas cadastradas: usa a mais conservadora
        return float(df["limite_maximo_permitido"].min())
    return float(faixa.iloc[0]["limite_maximo_permitido"])


def registrar_solicitacao_aumento(
    cpf: str, limite_atual: float, novo_limite: float, status: str
) -> None:
    linha = pd.DataFrame(
        [
            {
                "cpf_cliente": somente_digitos(cpf),
                "data_hora_solicitacao": datetime.now(timezone.utc).isoformat(),
                "limite_atual": limite_atual,
                "novo_limite_solicitado": novo_limite,
                "status_pedido": status,
            }
        ]
    )
    try:
        linha.to_csv(
            SOLICITACOES_CSV,
            mode="a",
            header=not SOLICITACOES_CSV.exists() or SOLICITACOES_CSV.stat().st_size == 0,
            index=False,
        )
    except (PermissionError, OSError) as exc:
        _log_and_raise("registro de solicitação de aumento de limite", exc)


def atualizar_limite_cliente(cpf: str, novo_limite: float) -> None:
    _atualizar_campo_cliente(cpf, "limite_credito", novo_limite)


def atualizar_score_cliente(cpf: str, novo_score: int) -> None:
    _atualizar_campo_cliente(cpf, "score", novo_score)


def _atualizar_campo_cliente(cpf: str, campo: str, valor) -> None:
    cpf_norm = somente_digitos(cpf)
    df = _ler_clientes()
    df["_cpf_norm"] = df["cpf"].apply(somente_digitos)
    idx = df.index[df["_cpf_norm"] == cpf_norm]
    if len(idx) == 0:
        raise DataAccessError(f"Cliente com CPF {cpf} não encontrado para atualização.")
    df.loc[idx, campo] = valor
    df = df.drop(columns=["_cpf_norm"])
    try:
        df.to_csv(CLIENTES_CSV, index=False)
    except (PermissionError, OSError) as exc:
        _log_and_raise(f"atualização de {campo} em clientes.csv", exc)
