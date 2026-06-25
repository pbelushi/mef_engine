"""
Explicação em linguagem natural do ResultadoMEF, via Gemini. Só LÊ o
resumo já calculado deterministicamente (`ResultadoMEF.resumo()`) — a IA
verbaliza números, nunca os recalcula nem os altera.
"""
from __future__ import annotations

from ..engine import ResultadoMEF
from ..schema import InputMEF
from .cliente import IAIndisponivel
from .cliente import gerar_texto as _gerar_texto_padrao


def montar_prompt_explicacao(inp: InputMEF, resultado: ResultadoMEF) -> str:
    """Prompt determinístico a partir do resumo — testável sem rede."""
    linhas = "\n".join(f"- {k}: {v}" for k, v in resultado.resumo().items())
    return (
        "Você é um analista financeiro explicando o resultado de um Modelo "
        "Econômico-Financeiro (MEF) de uma concessão/PPP brasileira para "
        "alguém não-técnico. Use SOMENTE os números abaixo (já calculados; "
        "não recalcule nada) e escreva um resumo claro em português, em "
        "3 a 5 frases, destacando viabilidade (TIR vs. taxa de desconto), "
        "estrutura de capital e qualquer ponto de atenção visível nos "
        "números.\n\n"
        f"Projeto: {inp.projeto}\n"
        f"Tipo de concessão: {resultado.tipo_concessao}\n"
        f"Regime contábil: {resultado.regime_contabil}\n"
        f"Taxa de desconto anual: {inp.capital.taxa_desconto_anual:.2%}\n\n"
        f"{linhas}"
    )


def explicar_resultado(inp: InputMEF, resultado: ResultadoMEF,
                       gerar_texto=_gerar_texto_padrao) -> str | None:
    """Gera a explicação; devolve None se a IA estiver indisponível — nunca
    levanta erro para quem só quer um resumo best-effort. `gerar_texto` é
    injetável (testes passam uma função falsa, sem rede)."""
    prompt = montar_prompt_explicacao(inp, resultado)
    try:
        return gerar_texto(prompt)
    except IAIndisponivel:
        return None
