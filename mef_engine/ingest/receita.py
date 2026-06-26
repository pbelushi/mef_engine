"""
Ingestão de receita tarifária (volume × tarifa) a partir de planilha
dedicada — upload separado de CAPEX/OPEX na interface web.

Diferente do CAPEX/OPEX (`planilha.py`), aqui não há linha de total para
ancorar a reconciliação: cada linha já é um item independente. A checagem de
qualidade é o CABEÇALHO — exige colunas reconhecíveis de nome/tarifa/volume;
sem isso, falha de forma visível em vez de ingerir dado incompleto (mesma
postura do resto do módulo de ingestão).
"""
from __future__ import annotations

from dataclasses import dataclass

from .planilha import _norm, carregar_grade

_ALIASES = {
    "nome": ("nome", "item", "descricao"),
    "tarifa": ("tarifa",),
    "volume_periodo": ("volume",),
    "crescimento_anual_pct": ("crescimento",),
}
_CAMPOS_OBRIGATORIOS = {"nome", "tarifa", "volume_periodo"}


@dataclass
class LinhaReceitaIngerida:
    nome: str
    tarifa: float
    volume_periodo: float
    crescimento_anual_pct: float = 0.0


def _mapear_cabecalho(linha: list) -> dict[str, int]:
    """Mapeia nome do campo -> índice de coluna (0-based) por correspondência
    de substring no rótulo normalizado do cabeçalho."""
    mapa: dict[str, int] = {}
    for c, valor in enumerate(linha):
        nv = _norm(valor) if isinstance(valor, str) else ""
        for campo, aliases in _ALIASES.items():
            if campo not in mapa and any(a in nv for a in aliases):
                mapa[campo] = c
    return mapa


def ingerir_receitas_volume(arquivo, nome_arquivo: str) -> list[LinhaReceitaIngerida]:
    """Lê um upload dedicado de receita (tarifa × volume): procura a primeira
    linha cujo cabeçalho tenha colunas reconhecíveis de nome/tarifa/volume
    (crescimento é opcional, default 0%) e lê as linhas abaixo dela.
    Levanta `ValueError` se nenhuma linha de cabeçalho for encontrada."""
    ws = carregar_grade(arquivo, nome_arquivo)
    cabecalho = None
    mapa: dict[str, int] = {}
    for r in range(1, ws.max_row + 1):
        linha = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        if all(v is None for v in linha):
            continue
        candidato = _mapear_cabecalho(linha)
        if _CAMPOS_OBRIGATORIOS <= candidato.keys():
            cabecalho, mapa = r, candidato
            break
    if cabecalho is None:
        raise ValueError(
            "Cabeçalho não encontrado: a planilha de receita precisa de "
            "colunas reconhecíveis como nome, tarifa e volume.")

    linhas = []
    for r in range(cabecalho + 1, ws.max_row + 1):
        valores = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        if all(v is None for v in valores):
            continue
        nome = valores[mapa["nome"]] if mapa["nome"] < len(valores) else None
        tarifa = valores[mapa["tarifa"]] if mapa["tarifa"] < len(valores) else None
        volume = valores[mapa["volume_periodo"]] if mapa["volume_periodo"] < len(valores) else None
        if (not isinstance(nome, str) or not isinstance(tarifa, (int, float))
                or not isinstance(volume, (int, float))):
            continue
        crescimento = 0.0
        idx_cresc = mapa.get("crescimento_anual_pct")
        if idx_cresc is not None and idx_cresc < len(valores):
            v = valores[idx_cresc]
            if isinstance(v, (int, float)):
                crescimento = float(v)
        linhas.append(LinhaReceitaIngerida(
            nome=nome.strip(), tarifa=float(tarifa), volume_periodo=float(volume),
            crescimento_anual_pct=crescimento))
    return linhas
