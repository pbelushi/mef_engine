"""
Schema de inputs do MEF (protótipo em dataclasses; vira Pydantic em produção).

MUDANÇA v3 (três tipos de concessão):
  - TipoConcessao (comum / administrativa / patrocinada) como PRESET editável;
  - regime contábil agora inclui 'intangivel' e 'bifurcado';
  - Aporte como elemento de primeira classe (recurso público p/ investimento);
  - preset_por_tipo() deriva defaults sensatos a partir do tipo, sem travar nada.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum

from .core import (
    AtividadeEconomica, Periodo, RegimeContabil, RegimeTributario,
    TipoConcessao, TipoIndexador,
)


class RegimeLucro(str, Enum):
    real = "real"
    presumido = "presumido"


@dataclass
class Timing:
    data_base: date
    inicio_ppp: date
    prazo_periodos: int
    inicio_operacao: date

    def __post_init__(self):
        if self.prazo_periodos <= 0:
            raise ValueError("prazo_periodos deve ser > 0")
        if self.inicio_operacao < self.inicio_ppp:
            raise ValueError("inicio_operacao anterior ao inicio_ppp")


@dataclass
class Tributos:
    """Módulo fiscal: regime de lucro (real/presumido), regime tributário
    sobre o consumo (`atual`: PIS/COFINS/ISS; `reforma`: CBS/IBS — LC
    214/2025, regime final pós-transição, sem o calendário 2026-2033),
    crédito sobre insumos, compensação de prejuízo fiscal e tratamento do
    aporte público.

    `atividade_economica` alimenta dois presets independentes em
    `preset_por_atividade`: o redutor de alíquota no regime pós-reforma, e o
    percentual de presunção de lucro no regime presumido — este último não é
    afetado pela reforma, que só reestrutura tributos sobre consumo.
    """
    regime_lucro: RegimeLucro = RegimeLucro.real
    regime_tributario: RegimeTributario = RegimeTributario.atual
    atividade_economica: AtividadeEconomica = AtividadeEconomica.outras
    credito_pis_cofins: bool = True
    pis: float = 0.0165
    cofins: float = 0.076
    iss: float = 0.05
    irpj: float = 0.15
    irpj_adicional: float = 0.10
    csll: float = 0.09
    aplica_ir_csll: bool = True
    # Alíquota de referência combinada CBS+IBS no regime pós-reforma (preset
    # ilustrativo dos estudos oficiais; calibração final é do Comitê Gestor
    # do IBS — editar conforme a melhor estimativa disponível).
    aliquota_referencia_cbs_ibs: float = 0.265
    # Compensação de prejuízo fiscal (Lei 9.065/95): só se aplica no lucro
    # real — no presumido a base é um % da receita, não há "prejuízo".
    compensacao_prejuizo: bool = True
    trava_compensacao_prejuizo: float = 0.30
    # Aporte público (investimento) não é receita operacional tributável por
    # padrão. Ligar só se a estrutura específica do contrato tributar o aporte.
    aporte_tributavel: bool = False

    @property
    def aliquota_indireta(self) -> float:
        """Alíquota sobre a receita bruta, antes de créditos, no regime
        tributário selecionado."""
        if self.regime_tributario is RegimeTributario.reforma:
            redutor = preset_por_atividade(self.atividade_economica)["redutor_cbs_ibs"]
            return self.aliquota_referencia_cbs_ibs * (1 - redutor)
        return self.pis + self.cofins + self.iss

    @property
    def aliquota_credito_insumos(self) -> float:
        """Alíquota para o crédito sobre CAPEX/OPEX creditável. Na reforma,
        crédito amplo (não-cumulatividade plena) à mesma alíquota efetiva da
        saída; hoje, só PIS/COFINS geram crédito (ISS é cumulativo)."""
        if self.regime_tributario is RegimeTributario.reforma:
            return self.aliquota_indireta
        return self.pis + self.cofins

    @property
    def aliquota_ir_csll(self) -> float:
        if not self.aplica_ir_csll:
            return 0.0
        return self.irpj + self.irpj_adicional + self.csll


@dataclass
class EstruturaCapital:
    taxa_desconto_anual: float = 0.0
    equity_pct_capex: float = 0.10
    # Financiamento: dívida = capex * (1 - equity_pct_capex), sacada
    # pari-passu com o desembolso do CAPEX.
    taxa_juros_divida_anual: float = 0.0
    # None = amortiza do início da operação até o fim do contrato (SAC).
    prazo_amortizacao_periodos: int | None = None


@dataclass
class Indexacao:
    """Índice de reajuste contratual, escolhido de uma lista fechada
    (`TipoIndexador`), e os parâmetros para aplicá-lo a tarifa/contraprestação.

    `taxas_acumuladas` é a taxa acumulada de CADA reajuste, na ordem
    cronológica (ex.: IPCA acumulado nos últimos 12 meses, uma entrada por
    aniversário de reajuste) — não a série mensal bruta. Para converter a
    série mensal buscada via `mef_engine.ingest.indexador.buscar_serie_historica`
    para esse formato, usar `serie_para_taxas_acumuladas`. Lista vazia
    (default) = sem reajuste, comportamento idêntico ao motor antes deste
    campo existir.

    `defasagem_meses=None` (default) aplica o 1º reajuste só após um ciclo
    completo (`periodicidade_meses`) — ex.: reajuste anual começa a valer no
    aniversário de 12 meses, não no período inicial do contrato.
    """
    indice: TipoIndexador = TipoIndexador.ipca
    aplica_tarifa: bool = True
    aplica_contraprestacao: bool = True
    periodicidade_meses: int = 12
    defasagem_meses: int | None = None
    taxas_acumuladas: list = field(default_factory=list)


# --- Linhas genéricas -------------------------------------------------------
@dataclass
class LinhaCAPEX:
    nome: str
    valor_total: float
    curva: dict = field(default_factory=dict)
    credita_pis_cofins: bool = True


@dataclass
class LinhaOPEX:
    """`curva` (período absoluto da malha -> valor) SOBREPÕE `valor_periodo`
    nos períodos que declarar; os demais continuam usando `valor_periodo` a
    partir de `periodo_inicio`. Default vazio = comportamento anterior à
    curva (valor constante). Útil para OPEX que varia (ex.: ramp-up nos
    primeiros anos) ou ingerida de planilha com colunas por período."""
    nome: str
    valor_periodo: float
    periodo_inicio: int = 0
    credita_pis_cofins: bool = True
    curva: dict = field(default_factory=dict)


@dataclass
class LinhaReceitaFixa:
    """Contraprestação pública / valor fixo por período. `fracao_garantida`
    (default 1.0) é a parcela desta linha reconhecida como ativo financeiro
    no regime bifurcado — o restante vira intangível (risco de demanda),
    útil p.ex. quando parte da contraprestação é performance-at-risk."""
    nome: str
    valor_periodo: float
    periodo_inicio: int = 0
    fracao_garantida: float = 1.0


@dataclass
class LinhaReceitaVolume:
    """Receita tarifária = volume × tarifa. `fracao_garantida` (default 0.0)
    é a parcela desta linha reconhecida como ativo financeiro no regime
    bifurcado — o restante fica com risco de demanda (intangível), útil
    p.ex. para uma tarifa com mínimo garantido parcial."""
    nome: str
    tarifa: float
    volume: list = field(default_factory=list)
    periodo_inicio: int = 0
    fracao_garantida: float = 0.0


@dataclass
class Aporte:
    """Recurso público para investimento (aporte). Distribuído por período."""
    valor_total: float = 0.0
    curva: dict = field(default_factory=dict)   # periodo_rel -> fracao


@dataclass
class BlocoSetorial:
    setor: str = "generico"
    receitas_fixas: list = field(default_factory=list)
    receitas_volume: list = field(default_factory=list)
    opex: list = field(default_factory=list)
    capex: list = field(default_factory=list)
    aporte: Aporte = field(default_factory=Aporte)


@dataclass
class InputMEF:
    projeto: str
    periodo: Periodo
    tipo_concessao: TipoConcessao
    regime_contabil: RegimeContabil
    timing: Timing
    capital: EstruturaCapital
    bloco: BlocoSetorial
    tributos: Tributos = field(default_factory=Tributos)
    indexacao: Indexacao = field(default_factory=Indexacao)
    # Override do CAPEX/OPEX alocado ao sub-regime de ativo financeiro no
    # bifurcado (1.0 = tudo garantido = ativo_financeiro; 0.0 = tudo risco =
    # intangível). None (default) = deriva da média ponderada de
    # `fracao_garantida` das linhas de receita (ver
    # `modules.calcular_regime_contabil`) — contabilmente mais correto, já
    # que o ativo financeiro fica dimensionado exatamente pela parcela de
    # CAPEX remunerada pelo canal garantido. Definir explicitamente sobrepõe
    # a derivação.
    fracao_ativo_financeiro: float | None = None

    @property
    def capex_total(self) -> float:
        return sum(l.valor_total for l in self.bloco.capex)

    @property
    def taxa_desconto_periodo(self) -> float:
        por_ano = self.periodo.por_ano
        return (1 + self.capital.taxa_desconto_anual) ** (1 / por_ano) - 1


# --- PRESET por tipo de concessão (editável depois) -------------------------
def preset_por_tipo(tipo: TipoConcessao) -> dict:
    """Defaults sensatos derivados do tipo. Retorna dict que o app aplica como
    ponto de partida — o usuário edita livremente depois (decisão de design:
    'tipo como preset, mas tudo editável')."""
    if tipo is TipoConcessao.comum:
        return {
            "regime_contabil": RegimeContabil.intangivel,
            "fracao_ativo_financeiro": 0.0,
            "permite_receita_volume": True,
            "permite_receita_fixa": False,
            "permite_aporte": False,
            "nota": "Risco de demanda no concessionário; receita 100% tarifária.",
        }
    if tipo is TipoConcessao.administrativa:
        return {
            "regime_contabil": RegimeContabil.ativo_financeiro,
            "fracao_ativo_financeiro": 1.0,
            "permite_receita_volume": False,
            "permite_receita_fixa": True,
            "permite_aporte": True,
            "nota": "Receita 100% pública (aporte + contraprestação); IFRIC 12.",
        }
    # patrocinada
    return {
        "regime_contabil": RegimeContabil.bifurcado,
        # None = deriva da mistura de receita (fracao_garantida por linha);
        # editar para um float fixo só se quiser sobrepor a derivação.
        "fracao_ativo_financeiro": None,
        "permite_receita_volume": True,
        "permite_receita_fixa": True,
        "permite_aporte": True,
        "nota": "Tarifa + recursos públicos; bifurcação ativo financeiro/intangível.",
    }


# --- PRESET por atividade econômica (editável depois) -----------------------
def preset_por_atividade(atividade: AtividadeEconomica) -> dict:
    """Dois presets independentes por atividade: (a) `redutor_cbs_ibs` — % de
    redução da alíquota de referência no regime pós-reforma (LC 214/2025,
    Art. 9º, regime final); (b) `presuncao_irpj`/`presuncao_csll` — % da
    receita bruta usado como base no lucro presumido (Lei 9.249/95, art.
    15/20), válido independente do regime tributário (a reforma não altera
    IRPJ/CSLL).

    ATENÇÃO — marcados como PLACEHOLDER os valores onde a regulamentação
    ainda depende do Comitê Gestor do IBS, ou o benefício depende de
    enquadramento específico (ex.: serviços hospitalares só têm presunção
    reduzida se organizados como sociedade empresária e atenderem requisitos
    da ANVISA). Preset editável: confirme antes de uso real e sobrescreva
    livremente — nada aqui trava o `InputMEF`.
    """
    padrao = {"redutor_cbs_ibs": 0.0, "presuncao_irpj": 0.32, "presuncao_csll": 0.32}
    presets = {
        AtividadeEconomica.educacao: {
            **padrao, "redutor_cbs_ibs": 0.60,  # Art. 9º, I — serviços de educação
        },
        AtividadeEconomica.saude_hospitalar: {
            # Art. 9º, I — serviços de saúde; presunção 8%/12% exige
            # enquadramento como serviço hospitalar (Lei 9.249/95, art. 15
            # §1º III "a") — confirmar requisitos da ANVISA.
            "redutor_cbs_ibs": 0.60, "presuncao_irpj": 0.08, "presuncao_csll": 0.12,
        },
        AtividadeEconomica.transporte_publico_coletivo: {
            # PLACEHOLDER: transporte público coletivo urbano/semiurbano/
            # metropolitano — confirmar se o caso concreto se qualifica para
            # alíquota zero. Presunção conservadora em 32%/32% (a regra de
            # "demais serviços de transporte" pode reduzir IRPJ a 16% —
            # confirmar enquadramento).
            **padrao, "redutor_cbs_ibs": 1.00,
        },
        AtividadeEconomica.rodovias: dict(padrao),                        # PLACEHOLDER
        AtividadeEconomica.energia_eletrica: dict(padrao),                # PLACEHOLDER
        AtividadeEconomica.saneamento: dict(padrao),                      # PLACEHOLDER
        AtividadeEconomica.parques: dict(padrao),                         # PLACEHOLDER
        AtividadeEconomica.destinacao_residuos_solidos: dict(padrao),     # PLACEHOLDER
        AtividadeEconomica.producao_vacinas: dict(padrao),                # PLACEHOLDER
        AtividadeEconomica.iluminacao_publica: dict(padrao),              # PLACEHOLDER
        AtividadeEconomica.outras: dict(padrao),
    }
    return presets[atividade]
