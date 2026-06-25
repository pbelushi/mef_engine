"""
Validação do módulo fiscal completo (v3.4): crédito sobre CAPEX/OPEX, real
vs. presumido (com presunção por atividade), compensação de prejuízo,
tratamento do aporte, e o alternador regime atual (PIS/COFINS/ISS) vs.
pós-reforma (CBS/IBS por atividade econômica).
"""
import numpy as np

from mef_engine.core import AtividadeEconomica, RegimeTributario
from mef_engine.modules import aplicar_compensacao_prejuizo, vetor_impostos
from mef_engine.schema import RegimeLucro, Tributos, preset_por_atividade


def test_preset_por_atividade_saude_e_outras():
    saude = preset_por_atividade(AtividadeEconomica.saude_hospitalar)
    outras = preset_por_atividade(AtividadeEconomica.outras)
    assert saude == {"redutor_cbs_ibs": 0.60, "presuncao_irpj": 0.08, "presuncao_csll": 0.12}
    assert outras == {"redutor_cbs_ibs": 0.0, "presuncao_irpj": 0.32, "presuncao_csll": 0.32}
    print("  [1] Preset por atividade: saúde com redução e presunção específicas, "
          "outras = padrão  OK")


def test_aliquota_indireta_atual_inclui_iss():
    trib = Tributos()  # regime_tributario=atual por default
    assert abs(trib.aliquota_indireta - (trib.pis + trib.cofins + trib.iss)) < 1e-12
    print(f"  [2] Alíquota indireta (atual) inclui ISS: {trib.aliquota_indireta:.4f}  OK")


def test_aliquota_indireta_reforma_aplica_redutor_por_atividade():
    cheia = Tributos(regime_tributario=RegimeTributario.reforma,
                     atividade_economica=AtividadeEconomica.outras)
    reduzida = Tributos(regime_tributario=RegimeTributario.reforma,
                        atividade_economica=AtividadeEconomica.saude_hospitalar)
    assert abs(cheia.aliquota_indireta - cheia.aliquota_referencia_cbs_ibs) < 1e-12
    assert abs(reduzida.aliquota_indireta - cheia.aliquota_referencia_cbs_ibs * 0.40) < 1e-12
    print(f"  [3] Reforma: outras={cheia.aliquota_indireta:.4f} (cheia), "
          f"saúde={reduzida.aliquota_indireta:.4f} (60% de redução)  OK")


def test_credito_reduz_indiretos():
    trib = Tributos(regime_tributario=RegimeTributario.atual)
    receita = np.array([1000.0, 1000.0])
    opex = np.array([0.0, 0.0])
    capex = np.array([0.0, 0.0])
    capex_creditavel = np.array([500.0, 0.0])
    class _Fake:  # evita montar um InputMEF completo só para este teste unitário
        tributos = trib
    sem_credito = vetor_impostos(_Fake(), receita, opex, capex)
    com_credito = vetor_impostos(_Fake(), receita, opex, capex,
                                 capex_creditavel=capex_creditavel)
    esperado_credito_p0 = 500.0 * trib.aliquota_credito_insumos
    assert abs(com_credito["creditos"][0] - esperado_credito_p0) < 1e-9
    assert com_credito["indiretos"][0] < sem_credito["indiretos"][0]
    assert np.isclose(com_credito["indiretos"][1], sem_credito["indiretos"][1])  # sem crédito no período 1
    print(f"  [4] Crédito sobre CAPEX reduz indiretos: {sem_credito['indiretos'][0]:.2f} -> "
          f"{com_credito['indiretos'][0]:.2f}  OK")


def test_compensacao_prejuizo_trava_30pct():
    lucro = np.array([-100.0, 200.0, 200.0])
    r = aplicar_compensacao_prejuizo(lucro, trava=0.30)
    # t0: prejuízo 100, base 0, saldo acumulado 100
    # t1: compensável = min(100, 200*0.30=60) = 60 -> base=140, saldo=40
    # t2: compensável = min(40, 200*0.30=60) = 40 -> base=160, saldo=0
    assert np.allclose(r["base_tributavel"], [0.0, 140.0, 160.0])
    assert np.allclose(r["saldo_prejuizo_acumulado"], [100.0, 40.0, 0.0])
    print("  [5] Compensação de prejuízo: trava de 30% respeitada período a período  OK")


def test_presumido_usa_presuncao_por_atividade():
    receita = np.array([1000.0])
    opex = np.array([0.0])
    capex = np.array([0.0])

    class _Fake:
        pass

    trib_saude = Tributos(regime_lucro=RegimeLucro.presumido,
                          atividade_economica=AtividadeEconomica.saude_hospitalar,
                          credito_pis_cofins=False)
    trib_outras = Tributos(regime_lucro=RegimeLucro.presumido,
                           atividade_economica=AtividadeEconomica.outras,
                           credito_pis_cofins=False)
    f_saude = _Fake(); f_saude.tributos = trib_saude
    f_outras = _Fake(); f_outras.tributos = trib_outras

    r_saude = vetor_impostos(f_saude, receita, opex, capex, depreciacao=np.zeros(1))
    r_outras = vetor_impostos(f_outras, receita, opex, capex, depreciacao=np.zeros(1))

    esperado_saude = 1000.0 * 0.08 * (trib_saude.irpj + trib_saude.irpj_adicional) + 1000.0 * 0.12 * trib_saude.csll
    esperado_outras = 1000.0 * 0.32 * (trib_outras.irpj + trib_outras.irpj_adicional) + 1000.0 * 0.32 * trib_outras.csll
    assert abs(r_saude["ir_csll"][0] - esperado_saude) < 1e-9
    assert abs(r_outras["ir_csll"][0] - esperado_outras) < 1e-9
    assert r_saude["ir_csll"][0] < r_outras["ir_csll"][0]
    print(f"  [6] Presumido por atividade: saúde paga menos IR/CSLL que outras "
          f"({r_saude['ir_csll'][0]:.2f} vs {r_outras['ir_csll'][0]:.2f})  OK")


def test_aporte_nao_tributavel_por_default():
    receita = np.array([1000.0])
    opex = np.array([0.0])
    capex = np.array([0.0])
    aporte = np.array([500.0])

    class _Fake:
        pass

    trib_default = Tributos(credito_pis_cofins=False)
    trib_tributavel = Tributos(credito_pis_cofins=False, aporte_tributavel=True)
    f1 = _Fake(); f1.tributos = trib_default
    f2 = _Fake(); f2.tributos = trib_tributavel

    r1 = vetor_impostos(f1, receita, opex, capex, depreciacao=np.zeros(1), aporte=aporte)
    r2 = vetor_impostos(f2, receita, opex, capex, depreciacao=np.zeros(1), aporte=aporte)
    assert np.isclose(r1["indiretos"][0], 1000.0 * trib_default.aliquota_indireta)
    assert np.isclose(r2["indiretos"][0], 1500.0 * trib_tributavel.aliquota_indireta)
    print(f"  [7] Aporte não tributável por default ({r1['indiretos'][0]:.2f}); "
          f"com a flag ligada, base cresce ({r2['indiretos'][0]:.2f})  OK")


if __name__ == "__main__":
    print("Validação do módulo fiscal (crédito, presumido, prejuízo, reforma)\n" + "-" * 48)
    test_preset_por_atividade_saude_e_outras()
    test_aliquota_indireta_atual_inclui_iss()
    test_aliquota_indireta_reforma_aplica_redutor_por_atividade()
    test_credito_reduz_indiretos()
    test_compensacao_prejuizo_trava_30pct()
    test_presumido_usa_presuncao_por_atividade()
    test_aporte_nao_tributavel_por_default()
    print("-" * 48 + "\nTodos os testes passaram.")
