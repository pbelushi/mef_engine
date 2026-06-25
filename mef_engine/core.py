"""
Núcleo numérico do motor: malha temporal + funções financeiras determinísticas.

MUDANÇA v2 (após o MEF de saneamento): a malha deixa de ser mensal-fixa. O
HOPE projeta em meses (~360); o saneamento projeta em anos (25). O período
agora é um parâmetro. Toda a matemática (VPL, TIR por root-finding) é
indiferente ao período — opera sobre vetores e uma taxa-por-período.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

import numpy as np
from dateutil.relativedelta import relativedelta
from scipy.optimize import brentq


class Periodo(str, Enum):
    mensal = "mensal"
    anual = "anual"

    @property
    def meses(self) -> int:
        return 1 if self is Periodo.mensal else 12

    @property
    def por_ano(self) -> int:
        return 12 if self is Periodo.mensal else 1


class TipoConcessao(str, Enum):
    """Tipos da Lei 8.987/95 (comum) e 11.079/04 (PPP administrativa/patrocinada)."""
    comum = "comum"                  # 100% tarifa, risco de demanda no privado
    administrativa = "administrativa"  # 100% recursos públicos (aporte + CP)
    patrocinada = "patrocinada"      # tarifa + recursos públicos


class RegimeContabil(str, Enum):
    ativo_financeiro = "ativo_financeiro"  # IFRIC 12 — contraprestação garantida
    intangivel = "intangivel"              # risco de demanda no concessionário
    bifurcado = "bifurcado"                # parte garantida + parte com risco


class TipoIndexador(str, Enum):
    """Índices de inflação disponíveis para reajuste contratual (tarifa/
    contraprestação). Lista fechada por ora; IPCA é o default no schema."""
    ipca = "IPCA"
    ipca15 = "IPCA-15"
    igpm = "IGP-M"
    inpc = "INPC"
    incc_di = "INCC-DI"


class RegimeTributario(str, Enum):
    """Tributação sobre o consumo: legislação vigente (PIS/COFINS/ISS) ou o
    regime final pós-reforma tributária (CBS/IBS, Lei Complementar 214/2025),
    já sem a transição gradual até 2033. Não afeta IRPJ/CSLL nem lucro
    real/presumido — a reforma reestrutura só os tributos sobre consumo."""
    atual = "atual"
    reforma = "reforma"


class AtividadeEconomica(str, Enum):
    """Atividade econômica da concessão. Alimenta dois presets independentes
    em `preset_por_atividade` (schema.py): o redutor de alíquota do CBS/IBS
    na reforma, e o percentual de presunção de lucro no regime presumido.
    Lista fechada nos setores típicos de concessão/PPP; `outras` é o
    fallback sem benefício."""
    educacao = "educacao"
    saude_hospitalar = "saude_hospitalar"
    rodovias = "rodovias"
    energia_eletrica = "energia_eletrica"
    saneamento = "saneamento"
    transporte_publico_coletivo = "transporte_publico_coletivo"
    parques = "parques"
    destinacao_residuos_solidos = "destinacao_residuos_solidos"
    producao_vacinas = "producao_vacinas"
    iluminacao_publica = "iluminacao_publica"
    outras = "outras"


@dataclass
class MalhaTemporal:
    """Sequência de períodos do contrato. Período mensal OU anual."""
    inicio: date
    n_periodos: int
    periodo: Periodo = Periodo.mensal

    @property
    def datas_inicio(self) -> list[date]:
        passo = self.periodo.meses
        return [self.inicio + relativedelta(months=passo * i)
                for i in range(self.n_periodos)]

    def indice_da_data(self, d: date) -> int:
        """Índice do período que contém a data d (0-based); -1 se anterior."""
        if d < self.inicio:
            return -1
        passo = self.periodo.meses
        datas = self.datas_inicio
        for i, m in enumerate(datas):
            prox = m + relativedelta(months=passo)
            if m <= d < prox:
                return i
        return self.n_periodos - 1


def vpl(taxa_periodo: float, fluxos: np.ndarray) -> float:
    """VPL de fluxos, descontando à taxa-por-período a partir do período 0."""
    t = np.arange(len(fluxos))
    return float(np.sum(fluxos / (1 + taxa_periodo) ** t))


def tir_periodo(fluxos: np.ndarray, lo: float = -0.99, hi: float = 1.0) -> float:
    """TIR por período (mensal ou anual conforme a malha). Brent + checagem de
    troca de sinal — sem raiz, reporta erro em vez de devolver número errado."""
    f = lambda r: vpl(r, fluxos)
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        raise ValueError(
            "TIR sem raiz no intervalo: fluxo não troca de sinal "
            f"(VPL({lo:.2f})={flo:.2e}, VPL({hi:.2f})={fhi:.2e})"
        )
    return float(brentq(f, lo, hi, xtol=1e-12, maxiter=200))


def anualizar(taxa_periodo: float, periodo: Periodo) -> float:
    """Converte taxa-por-período em taxa anual efetiva."""
    return (1 + taxa_periodo) ** periodo.por_ano - 1


def ponto_fixo(f, x0: float = 0.0, tol: float = 1e-12, max_iter: int = 200) -> float:
    """Resolve x = f(x) por iteração direta. Usado para a circularidade
    funding↔juros (juros sobre saldo médio dependem do próprio saldo, que
    inclui os juros do período). f deve ser uma contração (|f'| < 1) nas
    taxas de juros usuais — converge geometricamente. Sem convergência em
    max_iter, levanta erro em vez de devolver um número não confiável
    (mesma postura de tir_periodo)."""
    x = x0
    for _ in range(max_iter):
        x_novo = f(x)
        if abs(x_novo - x) < tol:
            return x_novo
        x = x_novo
    raise ValueError(f"Ponto fixo não convergiu em {max_iter} iterações "
                     f"(último delta={abs(x_novo - x):.2e})")
