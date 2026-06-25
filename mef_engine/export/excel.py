"""
Exportação dos resultados do MEF para Excel, por blocos (Resumo, Fluxo de
Caixa, Ativo Financeiro, Financiamento) — uma aba por bloco. Mesma filosofia
da ingestão (uma seção, uma responsabilidade), no sentido contrário: do
motor para a planilha.

Estrutura montada por código, não um template .xlsx externo — ponto de
extensão natural para, no futuro, preencher um template fornecido pelo
usuário em vez de gerar o layout do zero.
"""
from __future__ import annotations

import numpy as np
import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from ..engine import ResultadoMEF
from ..schema import InputMEF

FONTE_CABECALHO = Font(bold=True)
FORMATO_NUMERO = "#,##0.00"


def _nativo(v):
    """numpy scalar (np.float64 etc.) -> tipo Python nativo; openpyxl não
    lida bem com tipos numpy."""
    return v.item() if isinstance(v, np.generic) else v


def _aba_resumo(wb, inp: InputMEF, resultado: ResultadoMEF):
    ws = wb.create_sheet("Resumo")
    linhas = [
        ("Projeto", inp.projeto),
        ("Tipo de concessão", resultado.tipo_concessao),
        ("Regime contábil", resultado.regime_contabil),
        ("Periodicidade", inp.periodo.value),
    ]
    linhas += list(resultado.resumo().items())
    for r, (chave, valor) in enumerate(linhas, start=1):
        ws.cell(row=r, column=1, value=chave).font = FONTE_CABECALHO
        valor = _nativo(valor)
        cel = ws.cell(row=r, column=2, value=valor)
        if isinstance(valor, (int, float)):
            cel.number_format = FORMATO_NUMERO
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 20
    return ws


def _escrever_tabela(ws, cabecalhos: list, colunas: list):
    """`colunas` = lista de sequências (mesmo tamanho). Escreve o cabeçalho
    na linha 1 e uma linha por período a partir da linha 2."""
    for c, titulo in enumerate(cabecalhos, start=1):
        ws.cell(row=1, column=c, value=titulo).font = FONTE_CABECALHO
    n = len(colunas[0])
    for t in range(n):
        for c, vetor in enumerate(colunas, start=1):
            valor = _nativo(vetor[t])
            cel = ws.cell(row=t + 2, column=c, value=valor)
            if isinstance(valor, (int, float)):
                cel.number_format = FORMATO_NUMERO
    for c in range(1, len(cabecalhos) + 1):
        ws.column_dimensions[get_column_letter(c)].width = 16


def _aba_fluxo_de_caixa(wb, resultado: ResultadoMEF):
    n = resultado.malha.n_periodos
    ws = wb.create_sheet("Fluxo de Caixa")
    _escrever_tabela(ws,
        ["Período", "Data", "CAPEX", "OPEX", "Receita", "Indiretos",
         "IR/CSLL", "Aporte", "FCFF", "FCFE"],
        [list(range(1, n + 1)), resultado.malha.datas_inicio, resultado.capex,
         resultado.opex, resultado.receita, resultado.impostos["indiretos"],
         resultado.impostos["ir_csll"], resultado.aporte, resultado.fcff,
         resultado.fcfe])
    return ws


def _aba_ativo_financeiro(wb, resultado: ResultadoMEF):
    af = resultado.ativo_financeiro
    if af is None:
        return None
    n = resultado.malha.n_periodos
    ws = wb.create_sheet("Ativo Financeiro")
    _escrever_tabela(ws,
        ["Período", "Data", "AF Inicial", "Receita Financeira", "AF Final"],
        [list(range(1, n + 1)), resultado.malha.datas_inicio, af["af_inicial"],
         af["receita_financeira"], af["af_final"]])
    return ws


def _aba_financiamento(wb, resultado: ResultadoMEF):
    fin = resultado.financiamento
    if float(fin["saque"].sum()) == 0.0 and float(fin["servico_divida"].sum()) == 0.0:
        return None  # sem dívida: aba sem informação útil, omitida
    n = resultado.malha.n_periodos
    ws = wb.create_sheet("Financiamento")
    _escrever_tabela(ws,
        ["Período", "Data", "Saque", "Saldo Inicial", "Juros", "Amortização",
         "Serviço da Dívida", "Saldo Final"],
        [list(range(1, n + 1)), resultado.malha.datas_inicio, fin["saque"],
         fin["saldo_inicial"], fin["juros"], fin["amortizacao"],
         fin["servico_divida"], fin["saldo_final"]])
    return ws


def montar_workbook(inp: InputMEF, resultado: ResultadoMEF) -> openpyxl.Workbook:
    """Monta o workbook em memória, sem salvar — separado de `exportar_excel`
    para testar células direto, sem round-trip por disco."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove a aba default vazia
    _aba_resumo(wb, inp, resultado)
    _aba_fluxo_de_caixa(wb, resultado)
    _aba_ativo_financeiro(wb, resultado)
    _aba_financiamento(wb, resultado)
    return wb


def exportar_excel(inp: InputMEF, resultado: ResultadoMEF, caminho: str) -> None:
    """Exporta os resultados do MEF para um .xlsx, uma aba por bloco:
    Resumo, Fluxo de Caixa, Ativo Financeiro (só se o regime tiver ativo
    financeiro) e Financiamento (só se houver dívida)."""
    montar_workbook(inp, resultado).save(caminho)
