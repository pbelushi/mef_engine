"""
Validação do financiamento com circularidade funding↔juros (v3.3).

Provas-chave:
  - ponto_fixo (core.py) converge para a contração linear esperada e
    levanta erro quando a função não é contração;
  - juros de construção (saldo médio, capitalizados) batem com a fórmula
    fechada da recorrência linear — o ponto fixo está resolvendo a
    circularidade certa;
  - amortização SAC zera o saldo exatamente no fim do prazo;
  - REDUÇÃO ao caso sem dívida: equity_pct_capex=1.0 (100% equity) não saca
    nada e o FCFE coincide EXATAMENTE com o FCFF (erro 0.0) — mesmo padrão
    de prova usado para o regime bifurcado em test_concessoes.py.
"""
from datetime import date

import numpy as np

from mef_engine.core import MalhaTemporal, Periodo, RegimeContabil, TipoConcessao, ponto_fixo
from mef_engine.engine import calcular
from mef_engine.modules import calcular_financiamento
from mef_engine.schema import (
    BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaVolume, Timing, Tributos,
)


def _base(equity_pct=0.5, taxa_juros_anual=0.05, prazo_amortizacao=None):
    n = 8
    bloco = BlocoSetorial(
        setor="generico",
        capex=[LinhaCAPEX("Investimento", 1000.0)],
        opex=[LinhaOPEX("Opex", 30.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=0.5, volume=[1000.0] * n)],
    )
    return InputMEF(
        projeto="teste-financiamento",
        periodo=Periodo.anual,
        tipo_concessao=TipoConcessao.comum,
        regime_contabil=RegimeContabil.intangivel,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2026, 1, 1)),  # 2 anos de construção
        capital=EstruturaCapital(taxa_desconto_anual=0.08, equity_pct_capex=equity_pct,
                                 taxa_juros_divida_anual=taxa_juros_anual,
                                 prazo_amortizacao_periodos=prazo_amortizacao),
        bloco=bloco,
        tributos=Tributos(),
    )


def test_ponto_fixo_converge_e_detecta_nao_contracao():
    # x = 3 + 0.4*x  ->  x* = 3 / (1 - 0.4) = 5.0
    x = ponto_fixo(lambda x: 3 + 0.4 * x)
    assert abs(x - 5.0) < 1e-10
    try:
        ponto_fixo(lambda x: 1 + 2 * x, max_iter=50)
        assert False, "deveria levantar erro: 2x não é contração"
    except ValueError:
        pass
    print("  [1] ponto_fixo: converge na contração e detecta divergência  OK")


def test_juros_construcao_bate_com_formula_fechada():
    inp = _base(equity_pct=0.5, taxa_juros_anual=0.05)
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=8, periodo=Periodo.anual)
    capex = np.array([500.0, 500.0, 0, 0, 0, 0, 0, 0])  # 2 períodos de construção
    financ = calcular_financiamento(inp, malha, capex)

    taxa = 0.05
    saldo = 0.0
    esperado = []
    for saque in financ["saque"][:2]:
        juros = (taxa / 2 * (2 * saldo + saque)) / (1 - taxa / 2)
        saldo = saldo + saque + juros
        esperado.append(saldo)
    assert np.allclose(financ["saldo_final"][:2], esperado), (financ["saldo_final"][:2], esperado)
    assert np.all(financ["servico_divida"][:2] == 0), "juros de construção não podem ser caixa"
    print(f"  [2] Juros de construção (saldo médio/ponto fixo) batem com fórmula fechada: "
          f"saldo pós-construção={financ['saldo_final'][1]:.4f}  OK")


def test_amortizacao_sac_zera_saldo_no_fim_do_prazo():
    inp = _base(equity_pct=0.5, taxa_juros_anual=0.05)  # prazo_amortizacao=None -> até o fim do contrato
    res = calcular(inp)
    financ = res.financiamento
    assert financ["saldo_final"][-1] < 1e-6, financ["saldo_final"][-1]
    assert np.isclose(financ["amortizacao"].sum(), financ["saldo_inicial"][2])  # saldo no início da operação
    print(f"  [3] Amortização SAC: saldo final={financ['saldo_final'][-1]:.2e} "
          f"(zera no fim do prazo)  OK")


def test_sem_divida_fcfe_igual_fcff():
    res = calcular(_base(equity_pct=1.0, taxa_juros_anual=0.05))  # 100% equity, sem dívida
    assert np.all(res.financiamento["saque"] == 0)
    assert np.all(res.financiamento["servico_divida"] == 0)
    erro = float(np.max(np.abs(res.fcfe - res.fcff)))
    assert erro < 1e-9, f"sem dívida, FCFE deveria ser idêntico ao FCFF: erro={erro}"
    assert abs(res.tir_fcfe_periodo - res.tir_fcff_periodo) < 1e-9
    print(f"  [4] Redução ao caso sem dívida: FCFE≡FCFF (erro {erro:.1e})  OK")


def test_engine_com_divida_dificulta_capex_do_equity():
    sem_divida = calcular(_base(equity_pct=1.0, taxa_juros_anual=0.05))
    com_divida = calcular(_base(equity_pct=0.5, taxa_juros_anual=0.05))
    # Construção: dívida financia metade do CAPEX -> equity desembolsa menos caixa.
    assert com_divida.fcfe[0] > sem_divida.fcfe[0]
    assert com_divida.financiamento["saque"].sum() > 0
    print("  [5] Engine: dívida reduz o desembolso de equity na construção  OK")


if __name__ == "__main__":
    print("Validação do financiamento (ponto fixo + FCFE)\n" + "-" * 48)
    test_ponto_fixo_converge_e_detecta_nao_contracao()
    test_juros_construcao_bate_com_formula_fechada()
    test_amortizacao_sac_zera_saldo_no_fim_do_prazo()
    test_sem_divida_fcfe_igual_fcff()
    test_engine_com_divida_dificulta_capex_do_equity()
    print("-" * 48 + "\nTodos os testes passaram.")
