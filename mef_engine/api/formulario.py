"""
Schema Pydantic do formulário web/API — NA BORDA, separado das dataclasses
internas do motor (schema.py), que ficam intocadas (já validadas por toda a
suíte de testes). `FormularioMEF` valida o input simplificado de beta
(financiamento, indexação, módulo fiscal completo e bifurcação por linha
ficam fora desta v1 — usam os defaults/presets do motor) e converte para um
`InputMEF` de verdade via `para_input_mef()`.

`FormularioMEF.model_json_schema()` gera o JSON Schema que o roadmap pedia
(item "schema em Pydantic") — é o que a interface web usa para montar o
formulário a partir de um único lugar de verdade.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

from ..core import Periodo, TipoConcessao
from ..schema import (
    BlocoSetorial, EstruturaCapital, InputMEF, LinhaCAPEX, LinhaOPEX,
    LinhaReceitaFixa, LinhaReceitaVolume, Timing, preset_por_tipo,
)


class LinhaCapexForm(BaseModel):
    nome: str
    valor_total: float = Field(gt=0)


class LinhaOpexForm(BaseModel):
    nome: str
    valor_periodo: float = Field(ge=0)


class LinhaReceitaFixaForm(BaseModel):
    nome: str
    valor_periodo: float = Field(ge=0)


class LinhaReceitaVolumeForm(BaseModel):
    nome: str
    tarifa: float = Field(gt=0)
    volume_periodo: float = Field(gt=0, description="Volume constante por período (simplificação do MVP)")
    crescimento_anual_pct: float = Field(0.0, ge=-1, description="Crescimento do volume a cada período")


class FormularioMEF(BaseModel):
    """Versão simplificada do InputMEF para o beta: cobre só os inputs
    essenciais (tipo de concessão, timing, CAPEX/OPEX/receita, taxa de
    desconto). Financiamento, indexação, módulo fiscal completo e
    bifurcação por linha usam os defaults do motor — não aparecem aqui."""
    projeto: str = Field(min_length=1)
    tipo_concessao: TipoConcessao
    periodo: Periodo = Periodo.anual
    data_base: date
    inicio_ppp: date
    prazo_periodos: int = Field(gt=0)
    inicio_operacao: date
    taxa_desconto_anual: float = Field(ge=0, le=1)
    capex: list[LinhaCapexForm] = Field(default_factory=list)
    opex: list[LinhaOpexForm] = Field(default_factory=list)
    receitas_fixas: list[LinhaReceitaFixaForm] = Field(default_factory=list)
    receitas_volume: list[LinhaReceitaVolumeForm] = Field(default_factory=list)

    @field_validator("inicio_operacao")
    @classmethod
    def _operacao_apos_ppp(cls, v, info):
        inicio_ppp = info.data.get("inicio_ppp")
        if inicio_ppp is not None and v < inicio_ppp:
            raise ValueError("inicio_operacao não pode ser anterior a inicio_ppp")
        return v

    def para_input_mef(self) -> InputMEF:
        """Converte para um InputMEF de verdade, aplicando o preset do tipo
        de concessão (regime contábil, fração ativo financeiro) — o usuário
        do formulário simplificado não escolhe isso diretamente."""
        preset = preset_por_tipo(self.tipo_concessao)
        timing = Timing(self.data_base, self.inicio_ppp, self.prazo_periodos,
                        self.inicio_operacao)
        # equity_pct_capex=1.0: sem financiamento nesta v1 do formulário
        # (fica disponível só editando o InputMEF programaticamente depois).
        capital = EstruturaCapital(taxa_desconto_anual=self.taxa_desconto_anual,
                                   equity_pct_capex=1.0)
        bloco = BlocoSetorial(
            capex=[LinhaCAPEX(nome=c.nome, valor_total=c.valor_total) for c in self.capex],
            opex=[LinhaOPEX(nome=o.nome, valor_periodo=o.valor_periodo) for o in self.opex],
            receitas_fixas=[LinhaReceitaFixa(nome=r.nome, valor_periodo=r.valor_periodo)
                            for r in self.receitas_fixas],
            receitas_volume=[
                LinhaReceitaVolume(
                    nome=r.nome, tarifa=r.tarifa,
                    volume=[r.volume_periodo * (1 + r.crescimento_anual_pct) ** k
                           for k in range(self.prazo_periodos)],
                )
                for r in self.receitas_volume
            ],
        )
        return InputMEF(
            projeto=self.projeto, periodo=self.periodo,
            tipo_concessao=self.tipo_concessao,
            regime_contabil=preset["regime_contabil"], timing=timing,
            capital=capital, bloco=bloco,
            fracao_ativo_financeiro=preset.get("fracao_ativo_financeiro"),
        )
