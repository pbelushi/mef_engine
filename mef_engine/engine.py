"""
Orquestrador v3. Trata os três tipos de concessão via regime contábil
(ativo financeiro / intangível / bifurcado) e incorpora o aporte ao fluxo.
Continua sendo a única fonte de cálculo.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import modules as M
from .core import MalhaTemporal, anualizar, tir_periodo, vpl
from .schema import InputMEF


@dataclass
class ResultadoMEF:
    malha: MalhaTemporal
    capex: np.ndarray
    opex: np.ndarray
    receita: np.ndarray
    aporte: np.ndarray
    impostos: dict
    fcff: np.ndarray
    tipo_concessao: str
    regime_contabil: str
    ativo_financeiro: dict | None
    taxa_ativo: float | None
    fracao_ativo_financeiro_efetiva: float
    tir_fcff_periodo: float
    tir_fcff_anual: float
    vpl_fcff: float
    financiamento: dict
    fcfe: np.ndarray
    tir_fcfe_periodo: float
    tir_fcfe_anual: float
    vpl_fcfe: float

    def resumo(self) -> dict:
        d = {
            "Tipo de concessão": self.tipo_concessao,
            "Regime contábil": self.regime_contabil,
            "Períodos": self.malha.n_periodos,
            "TIR-FCFF (período)": round(self.tir_fcff_periodo, 8),
            "TIR-FCFF anual": round(self.tir_fcff_anual, 6),
            "VPL-FCFF": round(self.vpl_fcff, 4),
            "CAPEX total": round(float(self.capex.sum()), 2),
            "Receita total": round(float(self.receita.sum()), 2),
            "Aporte total": round(float(self.aporte.sum()), 2),
            "Dívida sacada": round(float(self.financiamento["saque"].sum()), 2),
            "TIR-FCFE (período)": round(self.tir_fcfe_periodo, 8),
            "TIR-FCFE anual": round(self.tir_fcfe_anual, 6),
            "VPL-FCFE": round(self.vpl_fcfe, 4),
        }
        if self.taxa_ativo is not None:
            d["Taxa ativo IFRIC (período)"] = round(self.taxa_ativo, 8)
            d["Fração ativo financeiro (efetiva)"] = round(self.fracao_ativo_financeiro_efetiva, 4)
        return d


def calcular(inp: InputMEF) -> ResultadoMEF:
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp,
                          n_periodos=inp.timing.prazo_periodos,
                          periodo=inp.periodo)

    capex = M.vetor_capex(inp, malha)
    opex = M.vetor_opex(inp, malha)
    aporte = M.vetor_aporte(inp, malha)

    contabil = M.calcular_regime_contabil(inp, malha, capex, opex)
    receita = contabil["receita"]
    af = contabil["af"]
    taxa_ativo = contabil["taxa_ativo"]
    fracao_af_efetiva = contabil["fracao_ativo_financeiro"]

    capex_creditavel = M.vetor_capex_creditavel(inp, malha)
    opex_creditavel = M.vetor_opex_creditavel(inp, malha)
    impostos = M.vetor_impostos(inp, receita, opex, capex,
                                capex_creditavel=capex_creditavel,
                                opex_creditavel=opex_creditavel, aporte=aporte)

    # FCFF: aporte reduz o desembolso de capital próprio (recurso público
    # cobre parte do CAPEX), por isso entra como entrada de caixa no fluxo.
    fluxo = receita - opex - capex + aporte - impostos["total"]

    try:
        tir_p = tir_periodo(fluxo)
        tir_a = anualizar(tir_p, inp.periodo)
    except ValueError:
        tir_p = float("nan"); tir_a = float("nan")

    vpl_proj = vpl(inp.taxa_desconto_periodo, fluxo)

    # Financiamento: dívida sacada na construção compensa parte do CAPEX já
    # descontado do FCFF; o serviço da dívida (juros + amortização, só em
    # caixa na operação) é o custo que o equity passa a pagar por isso.
    financ = M.calcular_financiamento(inp, malha, capex)
    fluxo_fcfe = fluxo + financ["saque"] - financ["servico_divida"]
    try:
        tir_fcfe_p = tir_periodo(fluxo_fcfe)
        tir_fcfe_a = anualizar(tir_fcfe_p, inp.periodo)
    except ValueError:
        tir_fcfe_p = float("nan"); tir_fcfe_a = float("nan")
    vpl_fcfe = vpl(inp.taxa_desconto_periodo, fluxo_fcfe)

    return ResultadoMEF(
        malha=malha, capex=capex, opex=opex, receita=receita, aporte=aporte,
        impostos=impostos, fcff=fluxo,
        tipo_concessao=inp.tipo_concessao.value,
        regime_contabil=inp.regime_contabil.value,
        ativo_financeiro=af, taxa_ativo=taxa_ativo,
        fracao_ativo_financeiro_efetiva=fracao_af_efetiva,
        tir_fcff_periodo=tir_p, tir_fcff_anual=tir_a, vpl_fcff=vpl_proj,
        financiamento=financ, fcfe=fluxo_fcfe,
        tir_fcfe_periodo=tir_fcfe_p, tir_fcfe_anual=tir_fcfe_a, vpl_fcfe=vpl_fcfe,
    )
