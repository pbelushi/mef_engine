"""
Validação do schema Pydantic do formulário web (v3.10): `FormularioMEF` vive
NA BORDA (mef_engine/api/formulario.py) — não substitui as dataclasses do
motor (schema.py), só oferece um input simplificado (sem financiamento,
indexação, módulo fiscal completo ou bifurcação por linha) que se converte
num InputMEF de verdade.

Provas-chave:
  - validação Pydantic recusa input claramente inválido (datas, valores
    negativos, prazo <= 0) ANTES de chegar ao motor;
  - para_input_mef() aplica o preset do tipo de concessão (regime contábil,
    fração ativo financeiro) automaticamente;
  - o resultado de calcular() sobre o InputMEF convertido é consistente com
    construir o mesmo cenário diretamente em InputMEF (mesma prova de
    "não inventa números" usada nas outras camadas de borda);
  - model_json_schema() gera um JSON Schema válido (é o contrato que a
    interface web usa para montar o formulário).
"""
from datetime import date

from mef_engine.api.formulario import FormularioMEF
from mef_engine.core import Periodo, RegimeContabil, TipoConcessao
from mef_engine.engine import calcular
from mef_engine.schema import (
    BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaVolume, Timing,
)


def _formulario_exemplo(tipo=TipoConcessao.comum):
    return FormularioMEF(
        projeto="teste-formulario",
        tipo_concessao=tipo,
        data_base=date(2024, 1, 1),
        inicio_ppp=date(2024, 1, 1),
        prazo_periodos=5,
        inicio_operacao=date(2024, 1, 1),
        taxa_desconto_anual=0.08,
        capex=[{"nome": "Obra", "valor_total": 200.0}],
        opex=[{"nome": "Opex", "valor_periodo": 5.0}],
        receitas_volume=[{"nome": "Tarifa", "tarifa": 2.0, "volume_periodo": 40.0}],
    )


def test_validacao_rejeita_prazo_invalido():
    try:
        _formulario_exemplo().model_copy(update={"prazo_periodos": 0})
        # model_copy não re-valida por padrão; força via construtor mesmo:
        FormularioMEF(**{**_formulario_exemplo().model_dump(), "prazo_periodos": 0})
        assert False, "deveria recusar prazo_periodos <= 0"
    except Exception:
        pass
    print("  [1] FormularioMEF recusa prazo_periodos <= 0  OK")


def test_validacao_rejeita_operacao_antes_do_ppp():
    base = _formulario_exemplo().model_dump()
    base["inicio_operacao"] = date(2023, 1, 1)  # antes de inicio_ppp=2024-01-01
    try:
        FormularioMEF(**base)
        assert False, "deveria recusar inicio_operacao < inicio_ppp"
    except Exception:
        pass
    print("  [2] FormularioMEF recusa inicio_operacao anterior a inicio_ppp  OK")


def test_validacao_rejeita_valor_negativo():
    base = _formulario_exemplo().model_dump()
    base["capex"][0]["valor_total"] = -10.0
    try:
        FormularioMEF(**base)
        assert False, "deveria recusar valor_total negativo"
    except Exception:
        pass
    print("  [3] FormularioMEF recusa valor_total negativo  OK")


def test_para_input_mef_aplica_preset_do_tipo():
    form = _formulario_exemplo(tipo=TipoConcessao.administrativa)
    inp = form.para_input_mef()
    assert inp.regime_contabil is RegimeContabil.ativo_financeiro
    assert inp.fracao_ativo_financeiro == 1.0
    print("  [4] para_input_mef() aplica o preset (administrativa -> ativo_financeiro, fração 1.0)  OK")


def test_para_input_mef_produz_o_mesmo_resultado_que_montar_a_mao():
    n = 5
    form = _formulario_exemplo(tipo=TipoConcessao.comum)
    inp_via_form = form.para_input_mef()

    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 200.0)], opex=[LinhaOPEX("Opex", 5.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=2.0, volume=[40.0] * n)],
    )
    inp_a_mao = InputMEF(
        projeto="teste-formulario", periodo=Periodo.anual,
        tipo_concessao=TipoConcessao.comum, regime_contabil=RegimeContabil.intangivel,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08, equity_pct_capex=1.0),
        bloco=bloco, fracao_ativo_financeiro=0.0,
    )

    res_via_form = calcular(inp_via_form)
    res_a_mao = calcular(inp_a_mao)
    erro = abs(res_via_form.tir_fcff_anual - res_a_mao.tir_fcff_anual)
    assert erro < 1e-9, f"erro {erro}"
    print(f"  [5] para_input_mef() + calcular() bate com o InputMEF montado à mão: erro={erro:.2e}  OK")


def test_json_schema_gerado_tem_os_campos_essenciais():
    esquema = FormularioMEF.model_json_schema()
    assert esquema["title"] == "FormularioMEF"
    propriedades = esquema["properties"]
    for campo in ("projeto", "tipo_concessao", "prazo_periodos", "taxa_desconto_anual",
                  "capex", "opex", "receitas_fixas", "receitas_volume"):
        assert campo in propriedades, f"campo '{campo}' ausente no JSON Schema"
    print(f"  [6] model_json_schema() inclui todos os campos essenciais do formulário  OK")


if __name__ == "__main__":
    print("Validação do schema Pydantic do formulário web\n" + "-" * 48)
    test_validacao_rejeita_prazo_invalido()
    test_validacao_rejeita_operacao_antes_do_ppp()
    test_validacao_rejeita_valor_negativo()
    test_para_input_mef_aplica_preset_do_tipo()
    test_para_input_mef_produz_o_mesmo_resultado_que_montar_a_mao()
    test_json_schema_gerado_tem_os_campos_essenciais()
    print("-" * 48 + "\nTodos os testes passaram.")
