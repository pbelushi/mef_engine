"""
Validação da bifurcação por linha de receita (v3.5).

Antes, a separação garantida/risco era binária por TIPO de linha (fixa=100%
garantida, volume=100% risco) e um `fracao_ativo_financeiro` global, livre,
controlava o CAPEX/OPEX. Agora cada linha declara seu próprio
`fracao_garantida` (ex.: tarifa com mínimo garantido parcial), e
`fracao_ativo_financeiro` (None por default) é DERIVADO da mistura de
receita resultante — a menos que o usuário sobreponha explicitamente.

Provas-chave:
  - defaults (fixa=1.0, volume=0.0) preservam o comportamento anterior;
  - linha com fração parcial divide proporcionalmente entre os dois baldes;
  - a derivação do CAPEX/OPEX bate com garantida/(garantida+risco);
  - override explícito de fracao_ativo_financeiro tem precedência;
  - nos extremos (100% garantida ou 100% risco), a derivação reproduz
    exatamente os regimes puros — mesmo padrão de prova já usado para a
    redução do bifurcado em test_concessoes.py.
"""
from datetime import date

import numpy as np

from mef_engine.core import MalhaTemporal, Periodo, RegimeContabil, TipoConcessao
from mef_engine.engine import calcular
from mef_engine.modules import calcular_regime_contabil, separar_receita_por_regime
from mef_engine.schema import (
    BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaFixa, LinhaReceitaVolume, Timing, Tributos,
)


def _base(bloco, fracao_af=None):
    n = 6
    return InputMEF(
        projeto="teste-bifurcacao-receita",
        periodo=Periodo.anual,
        tipo_concessao=TipoConcessao.patrocinada,
        regime_contabil=RegimeContabil.bifurcado,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08),
        bloco=bloco,
        tributos=Tributos(),
        fracao_ativo_financeiro=fracao_af,
    )


def test_defaults_preservam_comportamento_anterior():
    n = 4
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 100.0)], opex=[LinhaOPEX("Opex", 0.0)],
        receitas_fixas=[LinhaReceitaFixa("CP", 50.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=1.0, volume=[10.0] * n)],
    )
    inp = _base(bloco)
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=n, periodo=Periodo.anual)
    rec = separar_receita_por_regime(inp, malha)
    assert np.allclose(rec["garantida"], 50.0)     # 100% da linha fixa
    assert np.allclose(rec["risco_demanda"], 10.0)  # 100% da linha de tarifa
    print("  [1] Defaults (fixa=1.0, volume=0.0) preservam a separação binária anterior  OK")


def test_linha_com_fracao_parcial_divide_proporcionalmente():
    n = 4
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 100.0)], opex=[LinhaOPEX("Opex", 0.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa com mínimo garantido",
                                            tarifa=1.0, volume=[10.0] * n,
                                            fracao_garantida=0.4)],
    )
    inp = _base(bloco)
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=n, periodo=Periodo.anual)
    rec = separar_receita_por_regime(inp, malha)
    assert np.allclose(rec["garantida"], 10.0 * 0.4)
    assert np.allclose(rec["risco_demanda"], 10.0 * 0.6)
    print("  [2] Tarifa com mínimo garantido parcial (40%) divide 40/60 entre os dois baldes  OK")


def _base_com_construcao(bloco, fracao_af=None):
    # 2 anos de construção (capex concentrado aí) + 4 de operação, p/ ter um
    # fluxo do ativo financeiro com troca de sinal (TIR computável).
    n = 6
    return InputMEF(
        projeto="teste-bifurcacao-receita-construcao",
        periodo=Periodo.anual,
        tipo_concessao=TipoConcessao.patrocinada,
        regime_contabil=RegimeContabil.bifurcado,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2026, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08),
        bloco=bloco,
        tributos=Tributos(),
        fracao_ativo_financeiro=fracao_af,
    ), n


def test_derivacao_automatica_bate_com_mistura_de_receita():
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 100.0)], opex=[LinhaOPEX("Opex", 0.0)],
        receitas_fixas=[LinhaReceitaFixa("CP", 30.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=1.0, volume=[70.0] * 4)],
    )
    inp, n = _base_com_construcao(bloco, fracao_af=None)
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=n, periodo=Periodo.anual)
    capex = np.array([50.0, 50.0, 0.0, 0.0, 0.0, 0.0])  # construção nos 2 primeiros anos
    opex = np.zeros(n)
    contabil = calcular_regime_contabil(inp, malha, capex, opex)
    esperado = 30.0 / (30.0 + 70.0)  # garantida / total, nos períodos de operação
    assert abs(contabil["fracao_ativo_financeiro"] - esperado) < 1e-12
    assert np.allclose(contabil["capex_af"], capex * esperado)
    print(f"  [3] Fração derivada = garantida/total = {esperado:.4f}, "
          f"CAPEX-AF consistente  OK")


def test_override_explicito_tem_precedencia():
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 100.0)], opex=[LinhaOPEX("Opex", 0.0)],
        receitas_fixas=[LinhaReceitaFixa("CP", 30.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=1.0, volume=[70.0] * 4)],
    )
    inp, n = _base_com_construcao(bloco, fracao_af=0.9)  # ignora a mistura (que daria 0.30)
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=n, periodo=Periodo.anual)
    capex = np.array([50.0, 50.0, 0.0, 0.0, 0.0, 0.0])
    opex = np.zeros(n)
    contabil = calcular_regime_contabil(inp, malha, capex, opex)
    assert contabil["fracao_ativo_financeiro"] == 0.9
    print("  [4] Override explícito de fracao_ativo_financeiro sobrepõe a derivação  OK")


def test_extremos_da_derivacao_reproduzem_regimes_puros():
    n = 6  # tem que bater com o n interno de _base()
    vol = [10.0 * 1.02 ** k for k in range(n)]

    # 100% garantida (só receita fixa) -> derivação dá f=1.0 -> ativo financeiro puro
    bloco_garantida = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 200.0)], opex=[LinhaOPEX("Opex", 5.0)],
        receitas_fixas=[LinhaReceitaFixa("CP", 80.0)],
    )
    res_bif_garantida = calcular(_base(bloco_garantida))
    res_af_puro = calcular(InputMEF(
        projeto="af-puro", periodo=Periodo.anual, tipo_concessao=TipoConcessao.administrativa,
        regime_contabil=RegimeContabil.ativo_financeiro,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08), bloco=bloco_garantida,
        tributos=Tributos(),
    ))
    erro_af = abs(res_bif_garantida.taxa_ativo - res_af_puro.taxa_ativo)
    assert erro_af < 1e-9, erro_af

    # 100% risco (só tarifa, fracao_garantida=0.0 default) -> f=0.0 -> intangível puro
    bloco_risco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 200.0)], opex=[LinhaOPEX("Opex", 5.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=2.0, volume=vol)],
    )
    res_bif_risco = calcular(_base(bloco_risco))
    res_int_puro = calcular(InputMEF(
        projeto="intangivel-puro", periodo=Periodo.anual, tipo_concessao=TipoConcessao.comum,
        regime_contabil=RegimeContabil.intangivel,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08), bloco=bloco_risco,
        tributos=Tributos(),
    ))
    erro_tir = abs(res_bif_risco.tir_fcff_periodo - res_int_puro.tir_fcff_periodo)
    assert erro_tir < 1e-9, erro_tir
    print(f"  [5] Extremos da derivação ≡ regimes puros: garantida (erro {erro_af:.1e}), "
          f"risco (erro {erro_tir:.1e})  OK")


if __name__ == "__main__":
    print("Validação da bifurcação por linha de receita\n" + "-" * 48)
    test_defaults_preservam_comportamento_anterior()
    test_linha_com_fracao_parcial_divide_proporcionalmente()
    test_derivacao_automatica_bate_com_mistura_de_receita()
    test_override_explicito_tem_precedencia()
    test_extremos_da_derivacao_reproduzem_regimes_puros()
    print("-" * 48 + "\nTodos os testes passaram.")
