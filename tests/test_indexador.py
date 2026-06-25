"""
Validação do campo de indexador (schema), da aplicação do reajuste no motor,
e do parser da API do BCB (SGS).

Não chama rede: a busca real (`buscar_serie_historica`) é só urllib + duas
funções puras (`montar_url`, `parsear_resposta`), testadas isoladamente.
"""
from datetime import date

import numpy as np

from mef_engine.core import MalhaTemporal, Periodo, RegimeContabil, TipoConcessao, TipoIndexador
from mef_engine.engine import calcular
from mef_engine.ingest.indexador import (
    CODIGO_SGS, montar_url, parsear_resposta, serie_para_taxas_acumuladas,
)
from mef_engine.modules import vetor_fator_reajuste
from mef_engine.schema import (
    Aporte, BlocoSetorial, EstruturaCapital, Indexacao, InputMEF, LinhaCAPEX,
    LinhaOPEX, LinhaReceitaFixa, LinhaReceitaVolume, Timing, Tributos,
)


def test_default_e_lista_fechada():
    assert Indexacao().indice is TipoIndexador.ipca
    assert set(CODIGO_SGS) == {
        TipoIndexador.ipca, TipoIndexador.ipca15, TipoIndexador.igpm,
        TipoIndexador.inpc, TipoIndexador.incc_di,
    }
    print("  [1] Default IPCA + lista fechada de índices  OK")


def test_input_mef_usa_indexacao_default():
    campos = InputMEF.__dataclass_fields__
    assert campos["indexacao"].default_factory().indice is TipoIndexador.ipca
    print("  [2] InputMEF.indexacao default = IPCA  OK")


def test_montar_url_usa_codigo_sgs_certo():
    url = montar_url(TipoIndexador.igpm, date(2023, 1, 1), date(2023, 12, 31))
    assert f"bcdata.sgs.{CODIGO_SGS[TipoIndexador.igpm]}" in url
    assert "dataInicial=01/01/2023" in url and "dataFinal=31/12/2023" in url
    print("  [3] URL do SGS com código/datas corretos  OK")


def test_parsear_resposta_converte_percentual_para_fracao():
    corpo = '[{"data": "01/01/2024", "valor": "0.42"}, {"data": "01/02/2024", "valor": "0.83"}]'
    serie = parsear_resposta(corpo)
    assert serie[0] == (date(2024, 1, 1), 0.0042)
    assert serie[1] == (date(2024, 2, 1), 0.0083)
    print("  [4] Parsing do SGS: % a.m. -> fração decimal  OK")


def _base(periodo, indexacao):
    n = 5
    bloco = BlocoSetorial(
        setor="generico",
        capex=[LinhaCAPEX("Investimento", 1000.0)],
        opex=[LinhaOPEX("Opex", 50.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=0.16, volume=[1000.0] * n)],
    )
    return InputMEF(
        projeto="teste-indexador",
        periodo=periodo,
        tipo_concessao=TipoConcessao.comum,
        regime_contabil=RegimeContabil.intangivel,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08),
        bloco=bloco,
        tributos=Tributos(),
        indexacao=indexacao,
    )


def test_vetor_fator_reajuste_anual_aplica_a_partir_do_1o_aniversario():
    inp = _base(Periodo.anual, Indexacao(taxas_acumuladas=[0.05, 0.04, 0.03]))
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=5, periodo=Periodo.anual)
    fator = vetor_fator_reajuste(inp, malha)
    esperado = [1.0, 1.05, 1.05 * 1.04, 1.05 * 1.04 * 1.03, 1.05 * 1.04 * 1.03]
    assert np.allclose(fator, esperado), fator
    print("  [5] Fator de reajuste anual: 1º aniversário em t=1, mantém após esgotar taxas  OK")


def test_sem_taxas_fator_neutro_compat_com_motor_anterior():
    inp = _base(Periodo.anual, Indexacao())  # taxas_acumuladas=[] (default)
    malha = MalhaTemporal(inicio=inp.timing.inicio_ppp, n_periodos=5, periodo=Periodo.anual)
    fator = vetor_fator_reajuste(inp, malha)
    assert np.array_equal(fator, np.ones(5))
    print("  [6] Sem taxas_acumuladas: fator neutro (compatibilidade com motor anterior)  OK")


def test_serie_para_taxas_acumuladas_agrupa_12_meses():
    serie = [(date(2023, m, 1), 0.01) for m in range(1, 13)] + [(date(2024, 1, 1), 0.5)]
    taxas = serie_para_taxas_acumuladas(serie, meses_por_grupo=12)
    assert len(taxas) == 1  # grupo de 13 meses: só o 1º grupo de 12 fecha; o resto é descartado
    esperado = 1.01 ** 12 - 1
    assert abs(taxas[0] - esperado) < 1e-12
    print(f"  [7] Agrupamento mensal->anual: {taxas[0]:.4%} (grupo incompleto descartado)  OK")


def test_engine_aplica_reajuste_na_tarifa():
    sem_reajuste = calcular(_base(Periodo.anual, Indexacao(taxas_acumuladas=[])))
    com_reajuste = calcular(_base(Periodo.anual, Indexacao(taxas_acumuladas=[0.10, 0.10, 0.10])))
    assert np.isclose(sem_reajuste.receita[0], com_reajuste.receita[0])  # 1º período: sem reajuste ainda
    assert np.isclose(com_reajuste.receita[1], sem_reajuste.receita[1] * 1.10)  # 1º reajuste no aniversário
    assert com_reajuste.receita.sum() > sem_reajuste.receita.sum()
    print("  [8] Engine: receita reajustada bate com fator esperado a partir do 1º aniversário  OK")


if __name__ == "__main__":
    print("Validação do indexador (schema + reajuste no motor + parser SGS)\n" + "-" * 48)
    test_default_e_lista_fechada()
    test_input_mef_usa_indexacao_default()
    test_montar_url_usa_codigo_sgs_certo()
    test_parsear_resposta_converte_percentual_para_fracao()
    test_vetor_fator_reajuste_anual_aplica_a_partir_do_1o_aniversario()
    test_sem_taxas_fator_neutro_compat_com_motor_anterior()
    test_serie_para_taxas_acumuladas_agrupa_12_meses()
    test_engine_aplica_reajuste_na_tarifa()
    print("-" * 48 + "\nTodos os testes passaram.")
