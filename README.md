# Motor MEF — Protótipo v3

Núcleo determinístico de cálculo para Modelos Econômico-Financeiros de PPP e
concessões. Cobre os três tipos da legislação brasileira, dois setores reais
(saúde/HOPE e saneamento/VDR), duas granularidades (mensal/anual) e três
regimes contábeis. IA fica nas bordas (parsing, explicação), nunca no cálculo.

## Os três tipos de concessão (Lei 8.987/95 e 11.079/04)

O tipo não é um parâmetro isolado — é a combinação de fontes de receita, da
qual decorre o regime contábil. Tratado como PRESET editável (`preset_por_tipo`):

| Tipo            | Receita                  | Regime contábil default | Exemplo |
|-----------------|--------------------------|-------------------------|---------|
| Comum (8.987)   | 100% tarifária           | intangível              | —       |
| Administrativa  | 100% pública (CP+aporte) | ativo financeiro IFRIC  | HOPE    |
| Patrocinada     | tarifa + recursos públ.  | bifurcado               | VDR     |

O preset configura defaults sensatos; o usuário edita tudo depois (regime,
fração de bifurcação, fontes de receita, aporte).

## A novidade real do v3: regime BIFURCADO

Na patrocinada, parte da receita é contraprestação garantida (vira ativo
financeiro, IFRIC 12) e parte é tarifa com risco de demanda (vira intangível).
O motor divide CAPEX/OPEX pela `fracao_ativo_financeiro` e rola o ativo
financeiro só sobre a parcela garantida.

Prova de corretude (teste [5] em test_concessoes.py): o bifurcado se REDUZ
EXATAMENTE aos casos puros nos extremos — fração=1.0 ≡ ativo financeiro puro
(erro 0.0), fração=0.0 ≡ intangível puro (erro 0.0). Não é uma terceira lógica
ad hoc; é a interpolação correta entre os dois regimes.

## Validação (tudo passa)

`tests/test_validacao.py` — núcleo + dois setores reais:
  1. Solver TIR controlado (VPL ~1e-13)
  2. IFRIC 12 vs. HOPE (receita financeira, erro <1)
  3. TIR anual vs. saneamento (7,941% vs. 7,920% do painel)
  4. HOPE-like IFRIC mensal (rolagem do ativo fecha)
  5. Saneamento-like patrocinada/bifurcado anual

`tests/test_concessoes.py` — os três tipos:
  1. Presets por tipo
  2. Comum/intangível
  3. Administrativa/ativo financeiro (com aporte)
  4. Patrocinada/bifurcado
  5. Redução do bifurcado aos puros (erro 0.0)

```bash
python3 tests/test_validacao.py
python3 tests/test_concessoes.py
```

## Estrutura

```
mef_engine/
  core.py      Periodo, TipoConcessao, RegimeContabil, TipoIndexador, RegimeTributario,
               AtividadeEconomica + MalhaTemporal + TIR/VPL + ponto_fixo
  schema.py    Inputs + Aporte + Indexacao + EstruturaCapital (financiamento) +
               Tributos (fiscal completo) + preset_por_tipo + preset_por_atividade
  modules.py   CAPEX/OPEX/receita + reajuste + IFRIC 12 + bifurcação por linha de
               receita + impostos (crédito, presumido, compensação de prejuízo) +
               financiamento (FCFE)
  engine.py    Orquestrador dos 3 tipos + aporte + financiamento no fluxo (FCFF e FCFE)
  ingest/
    planilha.py    ingestão de CAPEX/OPEX (faixas auto-detectadas por cabeçalho +
                   curvas de desembolso por coluna de período)
    indexador.py   busca de série histórica de inflação na API do BCB (SGS)
  export/
    excel.py       exportação para .xlsx, uma aba por bloco (Resumo, Fluxo de
                   Caixa, Ativo Financeiro, Financiamento)
tests/
  test_validacao.py           núcleo + setores reais
  test_concessoes.py          três tipos de concessão
  test_ingestao.py            ingestão de planilhas vs. HOPE
  test_indexador.py           indexador: schema, reajuste no motor, parser SGS
  test_financiamento.py       financiamento: ponto fixo, dívida/FCFE
  test_fiscal.py              módulo fiscal: crédito, presumido, prejuízo, reforma
  test_bifurcacao_receita.py  bifurcação por linha de receita: derivação, extremos
  test_deteccao_faixas.py     detecção automática de faixas por cabeçalho
  test_curva_desembolso.py    ingestão de CAPEX/OPEX com curva de desembolso
  test_export_excel.py        exportação Excel: abas, omissão condicional, valores
```

## Indexação por inflação (v3.2) — reajuste de tarifa/contraprestação

O indexador é um campo do usuário: `Indexacao.indice`, escolhido de uma lista
fechada (`TipoIndexador`: IPCA, IPCA-15, IGP-M, INPC, INCC-DI), com **IPCA
pré-selecionado**. `aplica_tarifa`/`aplica_contraprestacao` controlam quais
receitas são reajustadas; `periodicidade_meses` (default 12, anual) e
`defasagem_meses` controlam o ciclo — o 1º reajuste só vale a partir do
aniversário completo, não no período inicial do contrato.

O reajuste em si é aplicado por `vetor_fator_reajuste` (modules.py): função
pura, sem rede, que acumula `Indexacao.taxas_acumuladas` (uma taxa por
aniversário de reajuste) e mantém o fator constante entre reajustes — igual à
prática contratual. Lista de taxas vazia (default) = fator neutro, idêntico
ao comportamento do motor antes deste campo existir.

A série histórica do índice pode ser obtida na API pública do Banco Central
(SGS) via `ingest/indexador.py`:
  - `buscar_serie_historica` consulta a série mensal bruta por índice/data
    (mesma fronteira de dados externos da ingestão de planilhas — fora do
    núcleo de cálculo);
  - `serie_para_taxas_acumuladas` agrupa a série mensal em taxas acumuladas
    por ciclo de reajuste (ex.: 12 meses), no formato que `Indexacao` espera.

Validado em `tests/test_indexador.py`: defaults, fator de reajuste anual
(1º aniversário, manutenção do fator após esgotar as taxas), neutralidade sem
taxas (compatibilidade retroativa), agrupamento mensal→anual, e o efeito
ponta a ponta no `engine.calcular`.

## Financiamento (v3.3) — circularidade funding↔juros

A dívida financia `1 - equity_pct_capex` do CAPEX (`EstruturaCapital`), sacada
pari-passu com o desembolso do CAPEX. Dois regimes de juros, conforme a fase:

  - **Construção** (antes do início da operação): juros incidem sobre o
    saldo MÉDIO do período (abertura + saque + juros do próprio período) e
    são capitalizados (sem caixa) — essa dependência circular é a
    "circularidade funding↔juros" do roadmap, resolvida por `ponto_fixo`
    (core.py): a recorrência é linear, então converge geometricamente
    (razão `taxa/2`) em poucas iterações.
  - **Operação**: sem novos saques, logo sem circularidade — juros sobre
    saldo de ABERTURA (exato) + amortização SAC constante até
    `prazo_amortizacao_periodos` (default: até o fim do contrato).

O FCFF não muda. O financiamento gera um fluxo novo, **FCFE** (equity):
`FCFE = FCFF + saque_dívida - serviço_dívida`, com TIR/VPL-FCFE próprios em
`ResultadoMEF`.

Prova de corretude (teste [4] em test_financiamento.py): com
`equity_pct_capex=1.0` (100% equity, sem dívida), nada é sacado e o FCFE
coincide EXATAMENTE com o FCFF (erro 0.0) — mesmo padrão de prova da redução
do regime bifurcado aos casos puros.

## Módulo fiscal completo (v3.4) — crédito, presumido, prejuízo, reforma tributária

`Tributos` cobre os quatro itens do roadmap original num só módulo
(`vetor_impostos`, modules.py):

  - **Crédito sobre CAPEX/OPEX**: linhas marcadas `credita_pis_cofins=True`
    (`LinhaCAPEX`/`LinhaOPEX`) entram em `vetor_capex_creditavel`/
    `vetor_opex_creditavel` e abatem o indireto devido, à alíquota de
    `aliquota_credito_insumos`.
  - **Real vs. presumido** (`RegimeLucro`): no real, a base é o lucro
    contábil após compensação de prejuízo; no presumido, a base é um % da
    receita bruta — e esse percentual varia por atividade (ver abaixo).
  - **Compensação de prejuízo** (`aplicar_compensacao_prejuizo`): prejuízo
    acumulado reduz a base tributável do período em até 30% do lucro
    positivo (trava da Lei 9.065/95) — substitui o floor ingênuo
    `max(lucro,0)` que esquecia prejuízos de períodos anteriores.
  - **Aporte público**: não compõe a base tributável por padrão
    (`aporte_tributavel=False`) — é ingresso de capital, não receita
    operacional; editável se o contrato específico tributar o aporte.

### Atual vs. reforma tributária, por atividade econômica

`Tributos.regime_tributario` alterna entre `atual` (PIS+COFINS+ISS) e
`reforma` (CBS/IBS — LC 214/2025, regime final pós-transição, sem o
calendário 2026-2033). `Tributos.atividade_economica` (lista fechada:
educação, saúde/hospitalar, rodovias, energia elétrica, saneamento,
transporte público coletivo, parques, destinação de resíduos sólidos,
produção de vacinas, iluminação pública, outras) alimenta dois presets
independentes em `preset_por_atividade`:

  - o **redutor de alíquota do CBS/IBS** na reforma (ex.: saúde e educação
    têm 60% de redução, Art. 9º da LC 214/2025);
  - o **percentual de presunção de lucro** (IRPJ/CSLL) no presumido — não
    afetado pela reforma, que só reestrutura tributos sobre consumo (ex.:
    serviços hospitalares têm presunção 8%/12% em vez do padrão 32%/32%).

**Atenção**: só saúde/hospitalar e educação têm base legal direta e estável
hoje. As demais atividades estão marcadas como PLACEHOLDER no código
(redutor 0%, presunção padrão) porque dependem de regulamentação do Comitê
Gestor do IBS ainda em curso, ou de enquadramento fiscal específico a
confirmar caso a caso — preset editável, não é posição jurídica.

## Bifurcação por linha de receita (v3.5)

Antes, a separação garantida/risco era binária por TIPO de linha (fixa =
100% garantida, volume = 100% risco) e um `fracao_ativo_financeiro` global
controlava o CAPEX/OPEX, dissociado da receita. Agora cada linha
(`LinhaReceitaFixa`/`LinhaReceitaVolume`) declara seu próprio
`fracao_garantida` (defaults 1.0 e 0.0 — preservam o comportamento anterior),
útil p.ex. para uma tarifa com mínimo garantido parcial ou uma
contraprestação com parcela de performance em risco.

`InputMEF.fracao_ativo_financeiro` passa a ser `None` por default (inclusive
no preset da patrocinada): nesse caso, `calcular_regime_contabil`
(modules.py) DERIVA a fração de CAPEX/OPEX alocada ao ativo financeiro como
`garantida / (garantida + risco)`, a partir da mistura de receita resultante
— contabilmente mais correto, já que o ativo financeiro fica dimensionado
exatamente pela parcela de CAPEX remunerada pelo canal garantido. Definir o
campo explicitamente continua disponível como override, com precedência
sobre a derivação.

Prova de corretude (teste [5] em test_bifurcacao_receita.py): nos extremos
(receita 100% garantida ou 100% risco), a derivação automática reproduz
EXATAMENTE os regimes puros (erro 0.0) — mesmo padrão de prova já usado para
a redução do bifurcado em test_concessoes.py.

## Detecção automática de faixas de seção (v3.6)

Antes, `detectar_e_ingerir` exigia as faixas (ini, fim, título) explícitas.
Agora, sem faixas informadas, `detectar_faixas` (planilha.py) varre a aba e
acha os cabeçalhos por heurística: candidata é uma linha com rótulo de
texto e SEM valor numérico — o que distingue um título de seção de uma
linha de item (rótulo + valor, sempre). Cada candidata só é aceita como
seção real se a faixa resultante render itens E uma linha de total para
ancorar; senão é descartada como ruído (nota, título de página, parâmetro
solto) — mesma filosofia de "ancorar no total" já usada na reconciliação.
Informar faixas explicitamente continua funcionando exatamente como antes
(bypassa a detecção).

## Curvas de desembolso na ingestão (v3.7)

Decisão deliberadamente conservadora: uma linha de item com múltiplos
valores numéricos só é lida como CURVA de desembolso (valores por período)
se houver um cabeçalho de período reconhecido — `detectar_cabecalho_periodos`
exige ≥2 colunas com "Ano N"/"Mês N"/"Período N" ou anos absolutos, em
sequência estritamente crescente e passo constante — imediatamente acima da
faixa. Sem esse cabeçalho, múltiplos números na mesma linha continuam sendo
lidos como antes (só o 1º valor): podem ser a mesma cifra em unidades
diferentes (R$ mil vs. R$), não uma curva — confundir as duas coisas seria
ingerir dado financeiro silenciosamente errado, o que este módulo existe
para evitar.

Com cabeçalho detectado, `secao_para_capex` converte a curva absoluta lida
em FRAÇÃO do total (formato que `LinhaCAPEX.curva` espera); `secao_para_opex`
entra com `valor_periodo=0.0` e a curva em valores absolutos — só os
períodos efetivamente lidos da planilha ficam definidos, sem extrapolar.
Em ambos, assume-se que a 1ª coluna de período da planilha é o período 0 da
malha (início do contrato); ajustar as chaves depois se necessário.

`LinhaOPEX` ganhou o campo `curva` (período absoluto -> valor, SOBREPONDO
`valor_periodo` nesses períodos) — útil também fora da ingestão, p.ex. para
um OPEX com ramp-up nos primeiros anos. Curva vazia (default) reproduz
exatamente o `vetor_opex` anterior a esta mudança.

## Exportação Excel (v3.8)

`mef_engine/export/excel.py` exporta o `ResultadoMEF` para `.xlsx`, uma aba
por bloco: Resumo (indicadores de `resumo()` + metadados do projeto), Fluxo
de Caixa (CAPEX/OPEX/receita/impostos/FCFF/FCFE período a período), Ativo
Financeiro (só quando o regime contábil tem AF) e Financiamento (só quando
há dívida sacada ou serviço de dívida) — abas sem conteúdo útil são
omitidas, não geradas vazias.

`montar_workbook(inp, resultado)` monta o workbook em memória, separado de
`exportar_excel(inp, resultado, caminho)` (que só chama `.save`) — permite
testar valores de célula sem round-trip por disco. Estrutura montada por
código, não um template `.xlsx` externo (não havia um disponível); ponto de
extensão natural para preencher um template fornecido pelo usuário depois.

## Próximos incrementos (em ordem de risco)

1. Camadas de IA de parsing/explicação (na borda, nunca no cálculo).
2. Schema em Pydantic (gera JSON Schema do formulário/CSV) → interface web → cloud.

## Alvos de validação por setor

- HOPE (saúde, administrativa, IFRIC mensal): TIR-FCFF 10,13%/ano
- VDR (saneamento, patrocinada, anual): TIR-FCFF 7,92%/ano

## Camada de ingestão (v3.1) — planilhas variadas, ancoradas no total

`mef_engine/ingest/` lê CAPEX/OPEX de planilhas SEM formato fixo:
  - descobre coluna de rótulos e de valores por varredura (não assume A, B...);
  - detecta a linha de total/soma por palavra-chave;
  - RECONCILIA soma dos itens vs. total declarado — recusa se não bater.

Validado contra o HOPE (`tests/test_ingestao.py`): CAPEX Complexo Hospitalar
(12 itens, reconcilia com erro 0.0) e LACEN (erro ~1e-16). A ponte
`secao_para_capex/opex` converte seções reconciliadas em linhas do schema.

```bash
python3 tests/test_ingestao.py
python3 tests/test_indexador.py
python3 tests/test_financiamento.py
python3 tests/test_fiscal.py
python3 tests/test_bifurcacao_receita.py
python3 tests/test_deteccao_faixas.py
python3 tests/test_curva_desembolso.py
python3 tests/test_export_excel.py
```

## Sequência recomendada até a nuvem

Ingestão (feito) → schema Pydantic → interface que reflete o schema →
Google Cloud quando houver produto testável ponta a ponta. Deploy antes de
existir caminho de entrada de dados daria um endpoint que ninguém sabe usar.
