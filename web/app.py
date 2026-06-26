"""
Interface web do Motor MEF (beta) — Streamlit.

Camada de borda: só monta o formulário (via o schema Pydantic
`FormularioMEF`), chama o motor (`engine.calcular`, determinístico, sem rede)
e oferece export Excel + explicação opcional por IA (Gemini, com fallback
gracioso se a chave não estiver configurada). Nenhuma lógica de cálculo mora
aqui — só orquestração de UI.
"""
from __future__ import annotations

import csv
import io
import os
import sys
from datetime import date

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mef_engine.api.formulario import FormularioMEF
from mef_engine.core import TipoConcessao
from mef_engine.engine import calcular
from mef_engine.export import exportar_excel
from mef_engine.ia.cliente import chave_configurada
from mef_engine.ia.explicacao import explicar_resultado
from mef_engine.ingest import (
    arquivo_para_capex, arquivo_para_opex, ingerir_receitas_volume,
)

TIPOS_PLANILHA = ["csv", "xls", "xlsx"]


def _csv_bytes(linhas: list[list]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(linhas)
    return buf.getvalue().encode("utf-8-sig")


def _modelo_capex() -> bytes:
    return _csv_bytes([["Item", "Valor"], ["Obra 1", 1000], ["Obra 2", 500],
                       ["Total", 1500]])


def _modelo_opex() -> bytes:
    return _csv_bytes([["Item", "Valor por período"], ["Custo 1", 10],
                       ["Custo 2", 5], ["Total", 15]])


def _modelo_receita() -> bytes:
    return _csv_bytes([["Nome", "Tarifa", "Volume por período", "Crescimento anual (%)"],
                       ["Tarifa 1", 1.0, 100, 0]])


def _upload_capex_opex(label: str, key: str, modelo: bytes, nome_modelo: str,
                       conversor, campo_valor: str) -> list[dict]:
    """Upload + parsing de uma planilha de CAPEX/OPEX (item, valor, linha de
    Total opcional p/ reconciliação automática) — substitui a digitação
    manual linha a linha. `campo_valor` é 'valor_total' (CAPEX) ou
    'valor_periodo' (OPEX): o nome do dataclass do schema não muda, só o
    rótulo do campo que o formulário simplificado espera."""
    st.caption("Planilha com itens em linhas e, opcionalmente, uma linha "
              "'Total' para conferência automática da soma.")
    st.download_button(f"Baixar modelo ({nome_modelo})", data=modelo,
                       file_name=nome_modelo, mime="text/csv", key=f"{key}_modelo")
    arquivo = st.file_uploader(label, type=TIPOS_PLANILHA, key=key)
    if arquivo is None:
        return []
    try:
        linhas = conversor(arquivo, arquivo.name)
    except Exception as e:
        st.error(f"Erro ao ler planilha: {e}")
        return []
    st.success(f"{len(linhas)} itens lidos de '{arquivo.name}'.")
    return [{"nome": l.nome, campo_valor: getattr(l, campo_valor)} for l in linhas]


def _upload_receita() -> list[dict]:
    st.caption("Planilha com colunas Nome, Tarifa, Volume por período e, "
              "opcionalmente, Crescimento anual (%).")
    st.download_button("Baixar modelo (receita)", data=_modelo_receita(),
                       file_name="modelo_receita.csv", mime="text/csv",
                       key="receita_modelo")
    arquivo = st.file_uploader("Planilha de receita (tarifa × volume)",
                               type=TIPOS_PLANILHA, key="upload_receita")
    if arquivo is None:
        return []
    try:
        linhas = ingerir_receitas_volume(arquivo, arquivo.name)
    except Exception as e:
        st.error(f"Erro ao ler planilha: {e}")
        return []
    st.success(f"{len(linhas)} linhas de receita lidas de '{arquivo.name}'.")
    return [{"nome": r.nome, "tarifa": r.tarifa, "volume_periodo": r.volume_periodo,
             "crescimento_anual_pct": r.crescimento_anual_pct} for r in linhas]


st.set_page_config(page_title="Motor MEF — Beta", layout="wide")


def _checar_senha() -> bool:
    """Gate simples por senha compartilhada (beta-teste). APP_PASSWORD vem do
    .env (mesmo mecanismo dotenv da camada de IA) ou de st.secrets — não é
    controle de acesso forte, só evita que a URL fique 100% pública."""
    from mef_engine.ia.cliente import _carregar_dotenv
    _carregar_dotenv()
    try:
        senha_secrets = st.secrets.get("APP_PASSWORD")
    except Exception:
        senha_secrets = None  # sem secrets.toml configurado: tudo bem, usa só o .env
    senha_esperada = os.environ.get("APP_PASSWORD") or senha_secrets
    if not senha_esperada:
        st.warning("APP_PASSWORD não configurada — acesso liberado sem senha "
                    "(defina APP_PASSWORD no .env antes de publicar o beta).")
        return True
    if st.session_state.get("autenticado"):
        return True
    senha = st.text_input("Senha de acesso (beta)", type="password")
    if senha and senha == senha_esperada:
        st.session_state["autenticado"] = True
        st.rerun()
    elif senha:
        st.error("Senha incorreta.")
    return False


def _formulario_sidebar() -> FormularioMEF | None:
    st.sidebar.header("Dados do projeto")
    projeto = st.sidebar.text_input("Nome do projeto", "Minha concessão")
    tipo = st.sidebar.selectbox(
        "Tipo de concessão", list(TipoConcessao),
        format_func=lambda t: t.value.capitalize())
    data_base = st.sidebar.date_input("Data-base", date.today())
    inicio_ppp = st.sidebar.date_input("Início da PPP/concessão", date.today())
    prazo_periodos = st.sidebar.number_input("Prazo (anos)", min_value=1, value=20)
    inicio_operacao = st.sidebar.date_input("Início da operação", date.today())
    taxa_desconto = st.sidebar.number_input(
        "Taxa de desconto anual (%)", min_value=0.0, value=8.0, step=0.5) / 100

    st.subheader("CAPEX")
    capex = _upload_capex_opex(
        "Planilha de CAPEX", "upload_capex", _modelo_capex(), "modelo_capex.csv",
        arquivo_para_capex, "valor_total")

    st.subheader("OPEX")
    opex = _upload_capex_opex(
        "Planilha de OPEX", "upload_opex", _modelo_opex(), "modelo_opex.csv",
        arquivo_para_opex, "valor_periodo")

    st.subheader("Receita tarifária (volume × tarifa)")
    receitas_volume = _upload_receita()

    st.subheader("Contraprestação pública (valor fixo por período)")
    n_receita_fixa = st.number_input("Número de linhas de contraprestação", min_value=0,
                                     value=0, key="n_receita_fixa")
    receitas_fixas = []
    for i in range(n_receita_fixa):
        c1, c2 = st.columns(2)
        nome = c1.text_input(f"Nome contraprestação {i+1}", f"Contraprestação {i+1}",
                             key=f"rf_nome_{i}")
        valor = c2.number_input(f"Valor por período {i+1}", min_value=0.0, value=10.0,
                                key=f"rf_valor_{i}")
        receitas_fixas.append({"nome": nome, "valor_periodo": valor})

    try:
        return FormularioMEF(
            projeto=projeto, tipo_concessao=tipo, data_base=data_base,
            inicio_ppp=inicio_ppp, prazo_periodos=int(prazo_periodos),
            inicio_operacao=inicio_operacao, taxa_desconto_anual=taxa_desconto,
            capex=capex, opex=opex, receitas_fixas=receitas_fixas,
            receitas_volume=receitas_volume,
        )
    except Exception as e:
        st.sidebar.error(f"Formulário inválido: {e}")
        return None


def main():
    st.title("Motor MEF — Beta")
    st.caption("Modelo Econômico-Financeiro de concessões/PPP — protótipo de teste.")

    if not _checar_senha():
        return

    form = _formulario_sidebar()
    if form is None:
        return

    if st.button("Calcular", type="primary"):
        inp = form.para_input_mef()
        resultado = calcular(inp)
        st.session_state["inp"] = inp
        st.session_state["resultado"] = resultado

    if "resultado" not in st.session_state:
        st.info("Preencha o formulário na barra lateral e clique em Calcular.")
        return

    inp = st.session_state["inp"]
    resultado = st.session_state["resultado"]

    st.subheader("Resumo")
    st.table({"Indicador": list(resultado.resumo().keys()),
             "Valor": [str(v) for v in resultado.resumo().values()]})

    buffer = io.BytesIO()
    from mef_engine.export.excel import montar_workbook
    montar_workbook(inp, resultado).save(buffer)
    st.download_button("Baixar Excel", data=buffer.getvalue(),
                       file_name=f"{inp.projeto}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("Explicação por IA (opcional)")
    if not chave_configurada():
        st.caption("IA indisponível (GOOGLE_API_KEY não configurada) — siga sem ela, "
                   "o resultado acima já está completo.")
    elif st.button("Explicar com IA"):
        with st.spinner("Gerando explicação..."):
            texto = explicar_resultado(inp, resultado)
        if texto:
            st.write(texto)
        else:
            st.caption("IA indisponível agora — siga sem ela.")


if __name__ == "__main__":
    main()
