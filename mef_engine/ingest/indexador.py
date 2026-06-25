"""
Busca da série histórica do indexador na API pública do Banco Central (SGS).

Mesma fronteira da ingestão de planilhas: dados externos ficam fora do núcleo
de cálculo. O motor nunca decide o que é "verdade" sobre a inflação — só
recebe a série já buscada (ou informada manualmente) e, no próximo incremento,
aplica o reajuste sobre ela.

A busca em rede (`buscar_serie_historica`) é separada da montagem de URL e do
parsing da resposta, para que a lógica de mapeamento/parsing seja testável
sem depender de rede.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime

from ..core import TipoIndexador

# Códigos das séries no SGS (Sistema Gerenciador de Séries Temporais do BCB),
# variação % mensal de cada índice.
CODIGO_SGS = {
    TipoIndexador.ipca: 433,
    TipoIndexador.ipca15: 7478,
    TipoIndexador.igpm: 189,
    TipoIndexador.inpc: 188,
    TipoIndexador.incc_di: 192,
}

URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


def montar_url(indice: TipoIndexador, data_inicial: date, data_final: date) -> str:
    codigo = CODIGO_SGS[indice]
    return (f"{URL_SGS.format(codigo=codigo)}?formato=json"
            f"&dataInicial={data_inicial.strftime('%d/%m/%Y')}"
            f"&dataFinal={data_final.strftime('%d/%m/%Y')}")


def parsear_resposta(corpo: str) -> list[tuple[date, float]]:
    """Converte o JSON do SGS (`[{"data": "01/01/2024", "valor": "0.42"}, ...]`)
    em pares (data, fração decimal). O SGS reporta variação em %, por isso a
    divisão por 100 (0,42% -> 0.0042)."""
    registros = json.loads(corpo)
    return [(datetime.strptime(r["data"], "%d/%m/%Y").date(), float(r["valor"]) / 100.0)
            for r in registros]


def buscar_serie_historica(indice: TipoIndexador, data_inicial: date,
                           data_final: date, timeout: float = 10.0
                           ) -> list[tuple[date, float]]:
    """Consulta a série histórica mensal do índice (variação % a.m., como
    fração decimal) na API do Banco Central. Levanta erro em vez de devolver
    série incompleta silenciosamente — mesma postura da reconciliação de
    planilhas."""
    url = montar_url(indice, data_inicial, data_final)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        corpo = resp.read().decode("utf-8")
    return parsear_resposta(corpo)


def serie_para_taxas_acumuladas(serie: list[tuple[date, float]],
                                meses_por_grupo: int = 12) -> list[float]:
    """Agrupa a série mensal bruta (de `buscar_serie_historica`) em taxas
    acumuladas por janela de `meses_por_grupo` meses, na ordem cronológica —
    o formato que `Indexacao.taxas_acumuladas` espera (uma taxa por
    aniversário de reajuste). Grupo final incompleto é descartado: só entra
    reajuste com o ciclo de variação completo."""
    taxas = []
    for i in range(0, len(serie) - meses_por_grupo + 1, meses_por_grupo):
        acumulado = 1.0
        for _, variacao in serie[i:i + meses_por_grupo]:
            acumulado *= (1 + variacao)
        taxas.append(acumulado - 1.0)
    return taxas
