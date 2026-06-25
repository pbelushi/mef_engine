"""
Validação das camadas de IA na borda (v3.9): parsing assistido e
explicação, via Gemini (Google AI). Nada aqui chama a API real — a IA é
sempre injetável (`gerar_texto`), então os testes verificam a ORQUESTRAÇÃO
(prompt montado, resposta parseada, fallback gracioso) sem rede, sem chave,
sem custo.

Provas-chave:
  - sem GOOGLE_API_KEY, a IA fica indisponível (IAIndisponivel), nunca
    derruba quem chamou;
  - explicar_resultado só verbaliza o resumo já calculado (não recalcula
    nada) e devolve None de forma graciosa se a IA falhar;
  - parsing assistido só é chamado quando a heurística não acha nada, e a
    sugestão da IA passa pela MESMA reconciliação que qualquer faixa —
    uma sugestão que não bate com o total ainda é rejeitada.
"""
import os
from datetime import date

from mef_engine.core import Periodo, RegimeContabil, TipoConcessao
from mef_engine.engine import calcular
from mef_engine.ia.cliente import IAIndisponivel, chave_configurada, gerar_texto
from mef_engine.ia.explicacao import explicar_resultado, montar_prompt_explicacao
from mef_engine.ia.parsing import (
    detectar_e_ingerir_com_ia_fallback, montar_prompt_parsing,
    parsear_resposta_parsing, sugerir_faixas,
)
from mef_engine.ingest import secao_para_capex
from mef_engine.schema import (
    BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaVolume, Timing, Tributos,
)


def _sem_google_api_key():
    """Contexto: garante GOOGLE_API_KEY ausente, restaura no final. Também
    trava `_carregar_dotenv` para não recarregar a chave de um .env real do
    repositório (este projeto tem um .env de beta-teste) — o teste precisa
    ser determinístico independente de haver ou não um .env na máquina."""
    import mef_engine.ia.cliente as cliente
    class _Ctx:
        def __enter__(self):
            self.anterior = os.environ.pop("GOOGLE_API_KEY", None)
            self.flag_anterior = cliente._DOTENV_CARREGADO
            cliente._DOTENV_CARREGADO = True
        def __exit__(self, *a):
            if self.anterior is not None:
                os.environ["GOOGLE_API_KEY"] = self.anterior
            cliente._DOTENV_CARREGADO = self.flag_anterior
    return _Ctx()


def test_sem_chave_ia_fica_indisponivel():
    with _sem_google_api_key():
        assert chave_configurada() is False
        try:
            gerar_texto("qualquer prompt")
            assert False, "deveria levantar IAIndisponivel sem chave"
        except IAIndisponivel:
            pass
    print("  [1] Sem GOOGLE_API_KEY: chave_configurada()=False, gerar_texto levanta IAIndisponivel  OK")


def _resultado_exemplo():
    n = 5
    bloco = BlocoSetorial(
        capex=[LinhaCAPEX("Obra", 200.0)], opex=[LinhaOPEX("Opex", 5.0)],
        receitas_volume=[LinhaReceitaVolume("Tarifa", tarifa=2.0, volume=[40.0] * n)],
    )
    inp = InputMEF(
        projeto="teste-ia", periodo=Periodo.anual, tipo_concessao=TipoConcessao.comum,
        regime_contabil=RegimeContabil.intangivel,
        timing=Timing(date(2024, 1, 1), date(2024, 1, 1), n, date(2024, 1, 1)),
        capital=EstruturaCapital(taxa_desconto_anual=0.08), bloco=bloco,
        tributos=Tributos(),
    )
    return inp, calcular(inp)


def test_montar_prompt_explicacao_contem_numeros_do_resumo():
    inp, res = _resultado_exemplo()
    prompt = montar_prompt_explicacao(inp, res)
    assert "teste-ia" in prompt
    assert f"{round(res.tir_fcff_anual, 6)}" in prompt
    assert "não recalcule nada" in prompt
    print("  [2] Prompt de explicação contém projeto e números do resumo (não os recalcula)  OK")


def test_explicar_resultado_usa_gerar_texto_injetado():
    inp, res = _resultado_exemplo()
    chamadas = []

    def gerar_texto_falso(prompt, modelo="x"):
        chamadas.append(prompt)
        return "Resumo gerado pela IA falsa."

    texto = explicar_resultado(inp, res, gerar_texto=gerar_texto_falso)
    assert texto == "Resumo gerado pela IA falsa."
    assert len(chamadas) == 1
    print("  [3] explicar_resultado usa a função de IA injetada (sem rede)  OK")


def test_explicar_resultado_retorna_none_quando_ia_indisponivel():
    inp, res = _resultado_exemplo()

    def gerar_texto_falha(prompt, modelo="x"):
        raise IAIndisponivel("simulado")

    assert explicar_resultado(inp, res, gerar_texto=gerar_texto_falha) is None
    print("  [4] explicar_resultado devolve None (gracioso) quando a IA falha  OK")


def test_parsear_resposta_parsing_ignora_linhas_mal_formadas():
    texto = "3|5|CAPEX Complexo Hospitalar\nlinha sem pipes\n10|12|CAPEX LACEN\nx|y|sem numero"
    faixas = parsear_resposta_parsing(texto)
    assert faixas == [(3, 5, "CAPEX Complexo Hospitalar"), (10, 12, "CAPEX LACEN")]
    print(f"  [5] parsear_resposta_parsing extrai faixas válidas e ignora o resto: {faixas}  OK")


def _planilha_sem_cabecalho_detectavel():
    """Itens SEM rótulo de seção (a heurística de cabeçalho não acha nada
    aqui) — força o fallback de IA."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Obra", 1000.0])
    ws.append(["Equipamentos", 500.0])
    ws.append(["Total", 1500.0])
    return wb


def test_montar_prompt_parsing_contem_linhas_da_planilha():
    wb = _planilha_sem_cabecalho_detectavel()
    prompt = montar_prompt_parsing(wb.active)
    assert "Obra" in prompt and "1000" in prompt
    print("  [6] Prompt de parsing contém o dump das linhas da planilha  OK")


def test_sugerir_faixas_usa_gerar_texto_injetado():
    wb = _planilha_sem_cabecalho_detectavel()

    def gerar_texto_falso(prompt, modelo="x"):
        return "1|3|CAPEX Obra"

    faixas = sugerir_faixas(wb.active, gerar_texto=gerar_texto_falso)
    assert faixas == [(1, 3, "CAPEX Obra")]
    print(f"  [7] sugerir_faixas usa a IA injetada: {faixas}  OK")


def test_fallback_so_chama_ia_quando_heuristica_vazia():
    import tempfile
    wb = _planilha_sem_cabecalho_detectavel()  # sem cabeçalho -> heurística vazia
    chamadas = []

    def gerar_texto_falso(prompt, modelo="x"):
        chamadas.append(1)
        return "1|3|CAPEX Obra"

    with tempfile.TemporaryDirectory() as tmp:
        caminho = os.path.join(tmp, "x.xlsx")
        wb.save(caminho)
        secs = detectar_e_ingerir_com_ia_fallback(
            caminho, wb.active.title, gerar_texto=gerar_texto_falso)
    assert len(chamadas) == 1  # IA chamada exatamente 1 vez (heurística não achou nada)
    assert len(secs) == 1
    assert secs[0].reconciliar()["ok"]
    print("  [8] Fallback: IA só é chamada quando a heurística não acha faixa, e a "
          "seção sugerida reconcilia  OK")


def test_sugestao_da_ia_que_nao_reconcilia_ainda_e_rejeitada():
    """Mesmo via IA, uma faixa cuja soma não bate com o total é recusada na
    ponte para o schema — a IA não tem atalho para a checagem de qualidade."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Obra", 1000.0])
    ws.append(["Equipamentos", 500.0])
    ws.append(["Total", 9999.0])  # não bate com 1000+500

    def gerar_texto_falso(prompt, modelo="x"):
        return "1|3|CAPEX Obra"

    faixas = sugerir_faixas(ws, gerar_texto=gerar_texto_falso)
    from mef_engine.ingest.planilha import ingerir_secao
    sec = ingerir_secao(ws, *faixas[0][:2], faixas[0][2])
    try:
        secao_para_capex(sec)
        assert False, "deveria recusar: soma não bate com o total"
    except ValueError:
        pass
    print("  [9] Sugestão da IA que não reconcilia é recusada do mesmo jeito  OK")


if __name__ == "__main__":
    print("Validação das camadas de IA (parsing assistido + explicação)\n" + "-" * 48)
    test_sem_chave_ia_fica_indisponivel()
    test_montar_prompt_explicacao_contem_numeros_do_resumo()
    test_explicar_resultado_usa_gerar_texto_injetado()
    test_explicar_resultado_retorna_none_quando_ia_indisponivel()
    test_parsear_resposta_parsing_ignora_linhas_mal_formadas()
    test_montar_prompt_parsing_contem_linhas_da_planilha()
    test_sugerir_faixas_usa_gerar_texto_injetado()
    test_fallback_so_chama_ia_quando_heuristica_vazia()
    test_sugestao_da_ia_que_nao_reconcilia_ainda_e_rejeitada()
    print("-" * 48 + "\nTodos os testes passaram.")
