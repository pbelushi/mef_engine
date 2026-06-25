"""
Validação da exportação Excel (v3.8): uma aba por bloco (Resumo, Fluxo de
Caixa, Ativo Financeiro, Financiamento), montada por código (sem template
.xlsx externo — ponto de extensão futuro).

Provas-chave:
  - as 4 abas aparecem quando há ativo financeiro E dívida;
  - "Ativo Financeiro" é omitida no regime intangível (sem AF);
  - "Financiamento" é omitida sem dívida (equity_pct_capex=1.0);
  - os valores nas células batem com o ResultadoMEF, não são recalculados;
  - exportar_excel salva um .xlsx válido (round-trip por disco).
"""
import os
import tempfile
from datetime import date

from mef_engine.core import Periodo, RegimeContabil, TipoConcessao
from mef_engine.engine import calcular
from mef_engine.export import exportar_excel, montar_workbook
from mef_engine.schema import (
    Aporte, BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaFixa, LinhaReceitaVolume, Timing, Tributos,
)


def _bifurcado_com_divida():
    n = 6
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 200.0)], opex=[LinhaOPEX("Opex", 5.0)],
        receitas_fixas=[LinhaReceitaFixa("CP", 30.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=2.0, volume=[40.0] * 4)],
        aporte=Aporte(valor_total=50.0),
    )
    inp = InputMEF(
        projeto="teste-export", periodo=Periodo.anual,
        tipo_concessao=TipoConcessao.patrocinada, regime_contabil=RegimeContabil.bifurcado,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2026, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08, equity_pct_capex=0.5,
                                 taxa_juros_divida_anual=0.05),
        bloco=bloco, tributos=Tributos(),
    )
    return inp, calcular(inp)


def _comum_intangivel_sem_divida():
    n = 4
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 100.0)], opex=[LinhaOPEX("Opex", 0.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=1.0, volume=[50.0] * n)],
    )
    inp = InputMEF(
        projeto="teste-export-simples", periodo=Periodo.anual,
        tipo_concessao=TipoConcessao.comum, regime_contabil=RegimeContabil.intangivel,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08, equity_pct_capex=1.0),
        bloco=bloco, tributos=Tributos(),
    )
    return inp, calcular(inp)


def test_todas_as_abas_quando_ha_af_e_divida():
    inp, res = _bifurcado_com_divida()
    wb = montar_workbook(inp, res)
    assert wb.sheetnames == ["Resumo", "Fluxo de Caixa", "Ativo Financeiro", "Financiamento"]
    print(f"  [1] Abas com AF e dívida: {wb.sheetnames}  OK")


def test_aba_ativo_financeiro_omitida_no_intangivel():
    inp, res = _comum_intangivel_sem_divida()
    wb = montar_workbook(inp, res)
    assert "Ativo Financeiro" not in wb.sheetnames
    print(f"  [2] Sem AF (intangível): abas = {wb.sheetnames}  OK")


def test_aba_financiamento_omitida_sem_divida():
    inp, res = _comum_intangivel_sem_divida()
    wb = montar_workbook(inp, res)
    assert "Financiamento" not in wb.sheetnames
    print("  [3] Sem dívida (equity_pct_capex=1.0): aba 'Financiamento' omitida  OK")


def test_valores_da_aba_fluxo_de_caixa_batem_com_resultado():
    inp, res = _bifurcado_com_divida()
    wb = montar_workbook(inp, res)
    ws = wb["Fluxo de Caixa"]
    cabecalhos = [c.value for c in ws[1]]
    col_capex = cabecalhos.index("CAPEX") + 1
    col_fcfe = cabecalhos.index("FCFE") + 1
    assert abs(ws.cell(row=2, column=col_capex).value - float(res.capex[0])) < 1e-9
    assert abs(ws.cell(row=res.malha.n_periodos + 1, column=col_fcfe).value
              - float(res.fcfe[-1])) < 1e-9
    print("  [4] Valores da aba 'Fluxo de Caixa' batem com ResultadoMEF (CAPEX[0], FCFE[-1])  OK")


def test_exportar_excel_salva_arquivo_valido():
    inp, res = _bifurcado_com_divida()
    with tempfile.TemporaryDirectory() as tmp:
        caminho = os.path.join(tmp, "mef.xlsx")
        exportar_excel(inp, res, caminho)
        assert os.path.exists(caminho)
        import openpyxl
        wb2 = openpyxl.load_workbook(caminho)
        assert wb2.sheetnames == ["Resumo", "Fluxo de Caixa", "Ativo Financeiro", "Financiamento"]
        assert wb2["Resumo"].cell(row=1, column=2).value == "teste-export"
    print("  [5] exportar_excel salva um .xlsx válido e relido confere  OK")


if __name__ == "__main__":
    print("Validação da exportação Excel\n" + "-" * 48)
    test_todas_as_abas_quando_ha_af_e_divida()
    test_aba_ativo_financeiro_omitida_no_intangivel()
    test_aba_financiamento_omitida_sem_divida()
    test_valores_da_aba_fluxo_de_caixa_batem_com_resultado()
    test_exportar_excel_salva_arquivo_valido()
    print("-" * 48 + "\nTodos os testes passaram.")
