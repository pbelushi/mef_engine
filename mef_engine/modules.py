"""
Módulos de cálculo puros, alinhados à malha por período (mensal OU anual).

MUDANÇA v2: receita por volume×tarifa; regime contábil como duas estratégias
(ativo financeiro IFRIC 12 vs. tarifário/caixa); impostos com IR/CSLL sobre
lucro além de PIS/COFINS sobre receita. A mecânica do IFRIC permanece a
derivada e validada contra o HOPE.
"""
from __future__ import annotations

import numpy as np

from .core import MalhaTemporal, ponto_fixo, tir_periodo
from .schema import InputMEF, RegimeContabil, RegimeLucro, preset_por_atividade


# --- Vetores de base --------------------------------------------------------
def vetor_capex(inp: InputMEF, malha: MalhaTemporal) -> np.ndarray:
    v = np.zeros(malha.n_periodos)
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    for linha in inp.bloco.capex:
        if linha.curva:
            for k, frac in linha.curva.items():
                if 0 <= k < malha.n_periodos:
                    v[k] += linha.valor_total * frac
        else:
            janela = max(idx_op, 1)
            v[:janela] += linha.valor_total / janela
    return v


def vetor_opex(inp: InputMEF, malha: MalhaTemporal) -> np.ndarray:
    """Valor constante de cada linha a partir de `periodo_inicio`, com os
    períodos em `linha.curva` (se houver) SOBREPONDO esse valor — não
    somando. Curva vazia (default) reproduz exatamente o comportamento
    anterior (valor constante)."""
    v = np.zeros(malha.n_periodos)
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    for linha in inp.bloco.opex:
        contrib = np.zeros(malha.n_periodos)
        ini = idx_op + linha.periodo_inicio
        if 0 <= ini < malha.n_periodos:
            contrib[ini:] = linha.valor_periodo
        for t, valor in linha.curva.items():
            if 0 <= t < malha.n_periodos:
                contrib[t] = valor
        v += contrib
    return v


def vetor_capex_creditavel(inp: InputMEF, malha: MalhaTemporal) -> np.ndarray:
    """Mesma distribuição de `vetor_capex`, só somando linhas com
    `credita_pis_cofins=True` — a base do crédito sobre insumos."""
    v = np.zeros(malha.n_periodos)
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    for linha in inp.bloco.capex:
        if not linha.credita_pis_cofins:
            continue
        if linha.curva:
            for k, frac in linha.curva.items():
                if 0 <= k < malha.n_periodos:
                    v[k] += linha.valor_total * frac
        else:
            janela = max(idx_op, 1)
            v[:janela] += linha.valor_total / janela
    return v


def vetor_opex_creditavel(inp: InputMEF, malha: MalhaTemporal) -> np.ndarray:
    """Mesma distribuição de `vetor_opex`, só somando linhas com
    `credita_pis_cofins=True` — a base do crédito sobre insumos."""
    v = np.zeros(malha.n_periodos)
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    for linha in inp.bloco.opex:
        if not linha.credita_pis_cofins:
            continue
        ini = idx_op + linha.periodo_inicio
        if 0 <= ini < malha.n_periodos:
            v[ini:] += linha.valor_periodo
    return v


def vetor_fator_reajuste(inp: InputMEF, malha: MalhaTemporal) -> np.ndarray:
    """Fator de reajuste acumulado por período, a partir de
    `inp.indexacao.taxas_acumuladas` (uma taxa por aniversário de reajuste).
    Mantém o fator constante entre reajustes — igual à prática contratual: a
    tarifa só muda na data de reajuste, não período a período. Sem taxas
    informadas, devolve fator neutro (1.0), preservando o comportamento do
    motor antes deste campo existir."""
    idx = inp.indexacao
    n = malha.n_periodos
    fator = np.ones(n)
    if not idx.taxas_acumuladas:
        return fator
    meses_por_periodo = malha.periodo.meses
    passo = max(1, idx.periodicidade_meses // meses_por_periodo)
    defasagem_meses = (idx.defasagem_meses if idx.defasagem_meses is not None
                       else idx.periodicidade_meses)
    defasagem = defasagem_meses // meses_por_periodo
    acumulado = 1.0
    i_taxa = 0
    for t in range(n):
        if t >= defasagem and (t - defasagem) % passo == 0 and i_taxa < len(idx.taxas_acumuladas):
            acumulado *= (1 + idx.taxas_acumuladas[i_taxa])
            i_taxa += 1
        fator[t] = acumulado
    return fator


def vetor_receita(inp: InputMEF, malha: MalhaTemporal) -> np.ndarray:
    """Receita de caixa total: linhas fixas + linhas volume×tarifa, ambas
    sujeitas a reajuste pelo indexador conforme `inp.indexacao`."""
    v = np.zeros(malha.n_periodos)
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    fator = vetor_fator_reajuste(inp, malha)
    idxc = inp.indexacao
    for linha in inp.bloco.receitas_fixas:
        ini = idx_op + linha.periodo_inicio
        if 0 <= ini < malha.n_periodos:
            f = fator[ini:] if idxc.aplica_contraprestacao else 1.0
            v[ini:] += linha.valor_periodo * f
    for linha in inp.bloco.receitas_volume:
        ini = idx_op + linha.periodo_inicio
        vol = linha.volume
        for k, q in enumerate(vol):
            p = ini + k
            if 0 <= p < malha.n_periodos:
                tarifa = linha.tarifa * fator[p] if idxc.aplica_tarifa else linha.tarifa
                v[p] += q * tarifa
    return v


# --- Regime contábil: IFRIC 12 (ativo financeiro) ---------------------------
def taxa_ativo_ifric(capex, opex, contraprestacao) -> float:
    """Taxa implícita do ativo financeiro: zera o fluxo construção/operação
    contra a contraprestação. Validada contra o HOPE (~1,29%/mês)."""
    fluxo = contraprestacao - capex - opex
    return tir_periodo(fluxo)


def rolar_ativo_financeiro(capex, opex, contraprestacao, taxa) -> dict:
    """AF_final = AF_ini + Constr + Oper - Contrapr + RecFin;
    RecFin = AF_ini*taxa; AF_ini(t)=AF_final(t-1). Validado contra o HOPE."""
    n = len(capex)
    af_ini = np.zeros(n); af_fim = np.zeros(n); rec_fin = np.zeros(n)
    saldo = 0.0
    for t in range(n):
        af_ini[t] = saldo
        rec_fin[t] = saldo * taxa
        saldo = saldo + capex[t] + opex[t] - contraprestacao[t] + rec_fin[t]
        af_fim[t] = saldo
    return {"af_inicial": af_ini, "af_final": af_fim, "receita_financeira": rec_fin}


# --- Impostos -----------------------------------------------------------
def aplicar_compensacao_prejuizo(lucro: np.ndarray, trava: float = 0.30) -> dict:
    """Compensação de prejuízos fiscais (Lei 9.065/95): prejuízo acumulado
    de períodos anteriores reduz a base tributável do período corrente em
    até `trava` (30%) do lucro positivo do período — nunca zera a base por
    completo de uma vez. O restante do prejuízo fica acumulado, sem prazo de
    prescrição. Substitui o floor ingênuo `max(lucro, 0)`, que esquecia
    prejuízos de períodos anteriores."""
    n = len(lucro)
    base_tributavel = np.zeros(n)
    saldo_acumulado = np.zeros(n)
    saldo = 0.0
    for t in range(n):
        l = lucro[t]
        if l <= 0:
            saldo += -l
            base_tributavel[t] = 0.0
        else:
            compensavel = min(saldo, l * trava)
            base_tributavel[t] = l - compensavel
            saldo -= compensavel
        saldo_acumulado[t] = saldo
    return {"base_tributavel": base_tributavel, "saldo_prejuizo_acumulado": saldo_acumulado}


def vetor_impostos(inp: InputMEF, receita, opex, capex, depreciacao=None,
                   capex_creditavel=None, opex_creditavel=None,
                   aporte=None) -> dict:
    """Indiretos (PIS/COFINS/ISS no regime atual, ou CBS/IBS na reforma,
    ambos via `Tributos.aliquota_indireta`) líquidos do crédito sobre
    CAPEX/OPEX creditável, mais IR/CSLL sobre o lucro tributável.

    Lucro real: base = lucro contábil após compensação de prejuízo (ou o
    floor simples `max(lucro,0)` se `compensacao_prejuizo=False`), mesma
    base para IRPJ e CSLL. Lucro presumido: bases diferentes por tributo,
    como percentual da receita bruta definido por `preset_por_atividade`
    (ex.: serviços hospitalares têm presunção menor que o padrão).

    Proxy de lucro = receita - opex - depreciação - indiretos. Sem
    depreciação informada, usa CAPEX linear pelo prazo como proxy.

    Aporte público não compõe a base tributável por padrão
    (`aporte_tributavel=False`) — é ingresso de capital, não receita
    operacional; ligar a flag só se o contrato específico tributar o aporte.
    """
    trib = inp.tributos
    n = len(capex)
    if capex_creditavel is None:
        capex_creditavel = np.zeros(n)
    if opex_creditavel is None:
        opex_creditavel = np.zeros(n)
    if aporte is None:
        aporte = np.zeros(n)

    receita_tributavel = receita + (aporte if trib.aporte_tributavel else 0.0)
    indiretos_brutos = receita_tributavel * trib.aliquota_indireta
    creditos = ((capex_creditavel + opex_creditavel) * trib.aliquota_credito_insumos
               if trib.credito_pis_cofins else np.zeros(n))
    indiretos = np.maximum(indiretos_brutos - creditos, 0.0)

    if depreciacao is None:
        depreciacao = np.full(n, capex.sum() / n)
    lucro = receita_tributavel - opex - depreciacao - indiretos

    if trib.regime_lucro is RegimeLucro.presumido:
        preset_at = preset_por_atividade(trib.atividade_economica)
        base_irpj = receita_tributavel * preset_at["presuncao_irpj"]
        base_csll = receita_tributavel * preset_at["presuncao_csll"]
    else:
        if trib.compensacao_prejuizo:
            base_irpj = base_csll = aplicar_compensacao_prejuizo(
                lucro, trib.trava_compensacao_prejuizo)["base_tributavel"]
        else:
            base_irpj = base_csll = np.maximum(lucro, 0.0)

    ir_csll = (np.zeros(n) if not trib.aplica_ir_csll else
              base_irpj * (trib.irpj + trib.irpj_adicional) + base_csll * trib.csll)
    return {"indiretos": indiretos, "creditos": creditos, "ir_csll": ir_csll,
            "total": indiretos + ir_csll}


# --- FCFF -------------------------------------------------------------------
def fcff(capex, opex, receita, impostos_total) -> np.ndarray:
    return receita - opex - capex - impostos_total


# --- Aporte e regime bifurcado (v3) ----------------------------------------
def vetor_aporte(inp, malha) -> "np.ndarray":
    """Aporte público distribuído por período (curva ou linear até operação)."""
    v = np.zeros(malha.n_periodos)
    ap = inp.bloco.aporte
    if not ap or ap.valor_total == 0:
        return v
    if ap.curva:
        for k, frac in ap.curva.items():
            if 0 <= k < malha.n_periodos:
                v[k] += ap.valor_total * frac
    else:
        idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
        janela = max(idx_op, 1)
        v[:janela] += ap.valor_total / janela
    return v


def separar_receita_por_regime(inp, malha):
    """Separa a receita em duas parcelas conforme o regime contábil, LINHA A
    LINHA: cada `LinhaReceitaFixa`/`LinhaReceitaVolume` tem seu próprio
    `fracao_garantida` — a parte dela que conta como GARANTIDA (ativo
    financeiro) vs. com RISCO de demanda (intangível). Defaults preservam o
    comportamento anterior à bifurcação por linha (fixa=1.0, volume=0.0):
    receita fixa 100% garantida, tarifa 100% risco, a menos que a linha
    declare outra coisa (p.ex. tarifa com mínimo garantido parcial)."""
    garantida = np.zeros(malha.n_periodos)
    risco = np.zeros(malha.n_periodos)
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    fator = vetor_fator_reajuste(inp, malha)
    idxc = inp.indexacao
    for linha in inp.bloco.receitas_fixas:
        ini = idx_op + linha.periodo_inicio
        if 0 <= ini < malha.n_periodos:
            f_reaj = fator[ini:] if idxc.aplica_contraprestacao else 1.0
            valor = linha.valor_periodo * f_reaj
            garantida[ini:] += valor * linha.fracao_garantida
            risco[ini:] += valor * (1 - linha.fracao_garantida)
    for linha in inp.bloco.receitas_volume:
        ini = idx_op + linha.periodo_inicio
        for k, q in enumerate(linha.volume):
            p = ini + k
            if 0 <= p < malha.n_periodos:
                tarifa = linha.tarifa * fator[p] if idxc.aplica_tarifa else linha.tarifa
                valor = q * tarifa
                garantida[p] += valor * linha.fracao_garantida
                risco[p] += valor * (1 - linha.fracao_garantida)
    return {"garantida": garantida, "risco_demanda": risco}


def calcular_regime_contabil(inp, malha, capex, opex):
    """Aplica o regime contábil. Retorna a receita reconhecida e, quando há
    ativo financeiro, sua rolagem. No bifurcado, divide o CAPEX entre os dois
    regimes pela fração de ativo financeiro e rola apenas a parcela
    correspondente. Essa fração vem de `inp.fracao_ativo_financeiro` se
    definida; senão, é derivada da mistura de receita (garantida / total) —
    contabilmente mais correto, já que o ativo financeiro fica dimensionado
    exatamente pela parcela de CAPEX remunerada pelo canal garantido."""
    from .core import RegimeContabil
    rec = separar_receita_por_regime(inp, malha)
    regime = inp.regime_contabil
    af = None
    taxa = None

    if regime is RegimeContabil.intangivel:
        # Sem ativo financeiro; receita reconhecida em caixa (tarifa).
        receita_caixa = rec["garantida"] + rec["risco_demanda"]
        return {"receita": receita_caixa, "af": None, "taxa_ativo": None,
                "capex_af": np.zeros_like(capex), "fracao_ativo_financeiro": 0.0}

    if regime is RegimeContabil.ativo_financeiro:
        contrap = rec["garantida"] + rec["risco_demanda"]
        taxa = taxa_ativo_ifric(capex, opex, contrap)
        af = rolar_ativo_financeiro(capex, opex, contrap, taxa)
        return {"receita": contrap, "af": af, "taxa_ativo": taxa,
                "capex_af": capex, "fracao_ativo_financeiro": 1.0}

    # bifurcado: parcela garantida -> ativo financeiro; risco -> intangível
    f = inp.fracao_ativo_financeiro
    if f is None:
        total = float(rec["garantida"].sum() + rec["risco_demanda"].sum())
        f = float(rec["garantida"].sum() / total) if total else 0.0
    capex_af = capex * f
    opex_af = opex * f
    contrap_af = rec["garantida"]
    taxa = taxa_ativo_ifric(capex_af, opex_af, contrap_af)
    af = rolar_ativo_financeiro(capex_af, opex_af, contrap_af, taxa)
    # Receita total de caixa = contraprestação + tarifa (ambas entram no FCFF)
    receita_caixa = rec["garantida"] + rec["risco_demanda"]
    return {"receita": receita_caixa, "af": af, "taxa_ativo": taxa,
            "capex_af": capex_af, "fracao_ativo_financeiro": f}


# --- Financiamento (v3.3): dívida com circularidade funding↔juros ----------
def calcular_financiamento(inp: InputMEF, malha: MalhaTemporal, capex) -> dict:
    """Cronograma da dívida que financia `1 - equity_pct_capex` do CAPEX.

    Construção (t < início da operação): a dívida é sacada pari-passu com o
    CAPEX; os juros do período incidem sobre o saldo MÉDIO (abertura + saque
    + juros do próprio período) e são capitalizados (sem caixa) — é a
    circularidade funding↔juros do roadmap, resolvida por `ponto_fixo`
    (linear, converge geometricamente à razão taxa/2).

    Operação (t >= início da operação): sem novos saques, então sem
    circularidade — juros sobre saldo de ABERTURA (exato) + amortização SAC
    constante ao longo de `prazo_amortizacao_periodos` (default: até o fim
    do contrato).
    """
    cap = inp.capital
    n = malha.n_periodos
    idx_op = malha.indice_da_data(inp.timing.inicio_operacao)
    taxa = (1 + cap.taxa_juros_divida_anual) ** (1 / malha.periodo.por_ano) - 1
    saque = capex * (1 - cap.equity_pct_capex)

    saldo_ini = np.zeros(n); saldo_fim = np.zeros(n)
    juros = np.zeros(n); amortizacao = np.zeros(n)
    saldo = 0.0
    amort_periodo = 0.0
    fim_amortizacao = idx_op
    for t in range(n):
        saldo_ini[t] = saldo
        if t < idx_op:
            base = 2 * saldo_ini[t] + saque[t]
            juros[t] = ponto_fixo(lambda j: taxa / 2 * (base + j))
            saldo = saldo_ini[t] + saque[t] + juros[t]
        else:
            if t == idx_op:
                prazo = cap.prazo_amortizacao_periodos or (n - idx_op)
                prazo = max(1, min(prazo, n - idx_op))
                amort_periodo = saldo_ini[t] / prazo
                fim_amortizacao = idx_op + prazo
            juros[t] = saldo_ini[t] * taxa
            amortizacao[t] = min(amort_periodo, saldo_ini[t]) if t < fim_amortizacao else 0.0
            saldo = saldo_ini[t] - amortizacao[t]
        saldo_fim[t] = saldo

    periodos = np.arange(n)
    servico_divida = np.where(periodos >= idx_op, juros + amortizacao, 0.0)
    return {"saque": saque, "saldo_inicial": saldo_ini, "saldo_final": saldo_fim,
            "juros": juros, "amortizacao": amortizacao,
            "servico_divida": servico_divida}
