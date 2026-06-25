"""
Validação dos três tipos de concessão (v3).

Testes-chave:
  - cada tipo roda ponta a ponta com seu preset;
  - REDUÇÃO do regime bifurcado: fração=1.0 ≡ ativo financeiro puro;
    fração=0.0 ≡ intangível puro. Se a bifurcação está certa, os extremos
    coincidem com os casos puros — é o teste que prova a lógica contábil.
"""
import sys
from datetime import date

sys.path.insert(0, "/home/claude/mef_engine")

import numpy as np

from mef_engine.core import Periodo, RegimeContabil, TipoConcessao
from mef_engine.engine import calcular
from mef_engine.schema import (
    Aporte, BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaFixa, LinhaReceitaVolume, Timing, Tributos, preset_por_tipo,
)


def _base(tipo, regime, fracao=1.0, com_tarifa=False, com_fixa=False, com_aporte=False):
    anos_op = 24
    vol = [1000.0 * (1.03) ** k for k in range(anos_op)]
    bloco = BlocoSetorial(
        setor="generico",
        capex=[LinhaCAPEX("Investimento", 2000.0)],
        opex=[LinhaOPEX("Opex", 120.0)],
        receitas_fixas=[LinhaReceitaFixa("Contraprestacao", 220.0)] if com_fixa else [],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=0.16, volume=vol)] if com_tarifa else [],
        aporte=Aporte(valor_total=300.0) if com_aporte else Aporte(),
    )
    return InputMEF(
        projeto=f"{tipo.value}",
        periodo=Periodo.anual,
        tipo_concessao=tipo,
        regime_contabil=regime,
        timing=Timing(date(2024,1,1), date(2024,1,1), 25, date(2025,1,1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08),
        bloco=bloco,
        tributos=Tributos(),
        fracao_ativo_financeiro=fracao,
    )


def test_presets():
    p_comum = preset_por_tipo(TipoConcessao.comum)
    p_adm = preset_por_tipo(TipoConcessao.administrativa)
    p_pat = preset_por_tipo(TipoConcessao.patrocinada)
    assert p_comum["regime_contabil"] is RegimeContabil.intangivel
    assert p_adm["regime_contabil"] is RegimeContabil.ativo_financeiro
    assert p_pat["regime_contabil"] is RegimeContabil.bifurcado
    print("  [1] Presets por tipo de concessão  OK")


def test_comum_intangivel():
    inp = _base(TipoConcessao.comum, RegimeContabil.intangivel,
                com_tarifa=True)
    res = calcular(inp)
    assert res.taxa_ativo is None and res.ativo_financeiro is None
    assert not np.isnan(res.tir_fcff_periodo)
    print(f"  [2] Comum/intangível: TIR={res.tir_fcff_anual:.4f}, "
          f"sem ativo financeiro  OK")


def test_administrativa_ativo_financeiro():
    inp = _base(TipoConcessao.administrativa, RegimeContabil.ativo_financeiro,
                com_fixa=True, com_aporte=True)
    res = calcular(inp)
    assert res.taxa_ativo is not None and res.ativo_financeiro is not None
    assert res.aporte.sum() > 0
    print(f"  [3] Administrativa/ativo financeiro: taxa_ativo="
          f"{res.taxa_ativo:.5f}, aporte={res.aporte.sum():.0f}  OK")


def test_patrocinada_bifurcado():
    inp = _base(TipoConcessao.patrocinada, RegimeContabil.bifurcado,
                fracao=0.5, com_tarifa=True, com_fixa=True, com_aporte=True)
    res = calcular(inp)
    assert res.taxa_ativo is not None
    assert res.regime_contabil == "bifurcado"
    print("  [4] Patrocinada/bifurcado:")
    for k, v in res.resumo().items():
        print(f"        {k}: {v}")


def test_reducao_bifurcado_aos_puros():
    # fração=1.0 deve reproduzir ativo financeiro puro (mesma receita)
    inp_bif1 = _base(TipoConcessao.patrocinada, RegimeContabil.bifurcado,
                     fracao=1.0, com_fixa=True)
    inp_af = _base(TipoConcessao.administrativa, RegimeContabil.ativo_financeiro,
                   com_fixa=True)
    r_bif1 = calcular(inp_bif1)
    r_af = calcular(inp_af)
    erro_taxa = abs(r_bif1.taxa_ativo - r_af.taxa_ativo)
    assert erro_taxa < 1e-9, f"fração=1.0 não reduz a ativo financeiro: {erro_taxa}"

    # fração=0.0 deve reproduzir intangível puro (sem ativo financeiro relevante)
    inp_bif0 = _base(TipoConcessao.patrocinada, RegimeContabil.bifurcado,
                     fracao=0.0, com_tarifa=True)
    inp_int = _base(TipoConcessao.comum, RegimeContabil.intangivel,
                    com_tarifa=True)
    r_bif0 = calcular(inp_bif0)
    r_int = calcular(inp_int)
    erro_tir = abs(r_bif0.tir_fcff_periodo - r_int.tir_fcff_periodo)
    assert erro_tir < 1e-9, f"fração=0.0 não reduz a intangível: {erro_tir}"
    print(f"  [5] Redução do bifurcado: fração=1.0≡ativo fin (erro {erro_taxa:.1e}), "
          f"fração=0.0≡intangível (erro {erro_tir:.1e})  OK")


if __name__ == "__main__":
    print("Validação dos três tipos de concessão (v3)\n" + "-" * 48)
    test_presets()
    test_comum_intangivel()
    test_administrativa_ativo_financeiro()
    test_patrocinada_bifurcado()
    test_reducao_bifurcado_aos_puros()
    print("-" * 48 + "\nTodos os testes passaram.")
