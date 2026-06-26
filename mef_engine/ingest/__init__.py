"""Ponte entre seções ingeridas e o schema do motor."""
from __future__ import annotations

from ..schema import LinhaCAPEX, LinhaOPEX
from .indexador import (
    buscar_serie_historica, montar_url, parsear_resposta,
    serie_para_taxas_acumuladas,
)
from .planilha import (
    SecaoIngerida, carregar_grade, detectar_e_ingerir, detectar_faixas,
    ingerir_arquivo_secao_unica, ingerir_secao,
)
from .receita import LinhaReceitaIngerida, ingerir_receitas_volume


def secao_para_capex(sec: SecaoIngerida, exigir_reconciliacao: bool = True):
    """Converte uma seção ingerida em linhas de CAPEX do schema.
    Se exigir_reconciliacao, recusa seções cuja soma não bate com o total.

    Itens com `curva` (ingeridos de planilha com cabeçalho de período
    reconhecido) entram com a curva convertida para FRAÇÃO do total — o
    formato que `LinhaCAPEX.curva` espera. Assume que a 1ª coluna de período
    da planilha corresponde ao período 0 da malha (início do contrato);
    ajustar as chaves depois se a obra começar em outro marco."""
    rec = sec.reconciliar()
    if exigir_reconciliacao and rec.get("ok") is False:
        raise ValueError(
            f"Seção '{sec.titulo}' não reconcilia: soma={rec['soma']:.2f} "
            f"vs total={rec['total']:.2f}. Revisar antes de ingerir.")
    linhas = []
    for i in sec.itens:
        if i.curva and i.valor:
            fracoes = {k: v / i.valor for k, v in i.curva.items()}
            linhas.append(LinhaCAPEX(nome=i.nome, valor_total=i.valor, curva=fracoes))
        else:
            linhas.append(LinhaCAPEX(nome=i.nome, valor_total=i.valor))
    return linhas


def secao_para_opex(sec: SecaoIngerida, exigir_reconciliacao: bool = True):
    """Converte uma seção ingerida em linhas de OPEX do schema. Itens com
    `curva` entram com `valor_periodo=0.0` e a curva (valor ABSOLUTO por
    período, mesma convenção de período 0 = início do contrato) — só os
    períodos lidos da planilha ficam definidos; não extrapola além do que
    foi efetivamente lido."""
    rec = sec.reconciliar()
    if exigir_reconciliacao and rec.get("ok") is False:
        raise ValueError(
            f"Seção '{sec.titulo}' não reconcilia. Revisar antes de ingerir.")
    linhas = []
    for i in sec.itens:
        if i.curva:
            linhas.append(LinhaOPEX(nome=i.nome, valor_periodo=0.0, curva=dict(i.curva)))
        else:
            linhas.append(LinhaOPEX(nome=i.nome, valor_periodo=i.valor))
    return linhas


def arquivo_para_capex(arquivo, nome_arquivo: str, exigir_reconciliacao: bool = True):
    """Lê um upload dedicado de CAPEX (arquivo inteiro = uma seção só) e
    converte direto para linhas de CAPEX do schema — atalho para a interface
    web, que substitui a digitação manual por upload de planilha."""
    sec = ingerir_arquivo_secao_unica(arquivo, nome_arquivo, titulo="CAPEX")
    return secao_para_capex(sec, exigir_reconciliacao)


def arquivo_para_opex(arquivo, nome_arquivo: str, exigir_reconciliacao: bool = True):
    """Equivalente a `arquivo_para_capex` para OPEX."""
    sec = ingerir_arquivo_secao_unica(arquivo, nome_arquivo, titulo="OPEX")
    return secao_para_opex(sec, exigir_reconciliacao)
