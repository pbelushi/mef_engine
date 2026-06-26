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
    planilha.py    ingestão de CAPEX/OPEX em .xlsx/.xls/.csv (faixas
                   auto-detectadas por cabeçalho + curvas de desembolso por
                   coluna de período); `carregar_grade` unifica os 3 formatos
                   numa única interface de leitura por célula; `ingerir_
                   arquivo_secao_unica` trata um upload dedicado (1 arquivo =
                   1 bloco) sem precisar detectar limites de seção
    receita.py     ingestão de receita tarifária (tarifa × volume) de planilha
                   dedicada, por cabeçalho de colunas (sem total para ancorar)
    indexador.py   busca de série histórica de inflação na API do BCB (SGS)
  export/
    excel.py       exportação para .xlsx com fórmulas vivas, em alto nível
                   (Capa/Painel de Controle/Premissas/Projeções/Financiamento/
                   Ativo Financeiro/Resultados) — todo valor derivado é
                   fórmula auditável no Excel, não número pré-calculado
  ia/
    cliente.py     wrapper do Gemini (Google AI) — única porta de saída para IA
    explicacao.py  resumo em linguagem natural do ResultadoMEF
    parsing.py     fallback de IA para detecção de faixas (heurística falhou)
  api/
    formulario.py  FormularioMEF (Pydantic) — schema simplificado de borda para a
                   interface web, com para_input_mef() e model_json_schema()
web/
  app.py       interface Streamlit do beta: senha compartilhada, upload de
               planilha (.csv/.xls/.xlsx) para CAPEX/OPEX/receita com modelo
               para baixar, Calcular, download do Excel (fórmulas vivas),
               explicação opcional por IA
Dockerfile     imagem para Cloud Run (Streamlit, porta via $PORT)
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
  test_export_excel.py        exportação Excel: abas, omissão condicional, fórmulas
                               vivas + recálculo (pacote opcional `formulas`) vs. motor
  test_ia.py                  camadas de IA: orquestração sem rede (IA injetável)
  test_formulario.py          schema Pydantic do formulário: validação, preset, JSON Schema
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

## Exportação Excel com fórmulas vivas (v3.8 → v3.12)

`mef_engine/export/excel.py` exporta o `ResultadoMEF` para `.xlsx` numa
estrutura em alto nível equivalente à de um MEF profissional comum — Capa /
Painel de Controle / Premissas / Projeções / Financiamento / Ativo
Financeiro / Resultados — sem nenhuma referência a projeto, cor ou layout de
terceiros: é uma organização genérica, não a cópia de um modelo específico.
Abas sem conteúdo útil continuam omitidas (Financiamento só com dívida
sacada; Ativo Financeiro só fora do regime intangível), não geradas vazias.

A mudança central da v3.12: **todo valor DERIVADO entra como FÓRMULA do
Excel**, não como o número já calculado pelo motor — impostos (indiretos,
créditos, IR/CSLL com compensação de prejuízo ou lucro presumido),
FCFF/FCFE, rolagem do ativo financeiro (com a taxa implícita via `=IRR(...)`
direto na planilha), cronograma de dívida (saque/saldo/juros/amortização
SAC) e os indicadores do Painel de Controle (TIR/VPL via `IRR`/`NPV`, totais
via `SUM`) — tudo recalculável abrindo o `.xlsx`, igual a um MEF de mercado.
Só a aba **Projeções** (CAPEX/OPEX/receita já distribuídos por período a
partir das linhas de entrada — curva de desembolso, indexação) entra como
valor: é o cronograma resolvido, equivalente a uma aba de premissas/
operacional, não ao bloco de resultado.

Mecanismo: a classe `_Premissas` guarda o endereço de cada célula escrita
(`ref[nome]`) para que fórmulas em outras abas referenciem por NOME, nunca
por número de linha hardcoded. Um ponto técnico que vale registrar: a
fórmula fechada do juro de construção (deriva-se algebricamente o ponto fixo
`juros = taxa/2*(2*saldo+saque+juros)` para uma expressão sem o termo `juros`
do lado direito, eliminando a circularidade que o motor resolve em Python via
`ponto_fixo`) e a célula auxiliar de amortização SAC por período referenciam
a LINHA ESPECÍFICA do início da operação (`idx_op`, já conhecida em tempo de
geração) — um `INDEX` sobre a faixa inteira criaria dependência circular
TEXTUAL (mesmo sem ser circular em valor), porque linhas posteriores da
mesma coluna dependem, por tabela, da própria célula auxiliar.

`montar_workbook(inp, resultado)` monta o workbook em memória, separado de
`exportar_excel(inp, resultado, caminho)` (que só chama `.save`) — mesma
assinatura pública de antes da v3.12, `web/app.py` não precisou mudar.

Validação (`tests/test_export_excel.py`): confere a estrutura (abas
certas presentes/omitidas, "Projeções" traz valor e "Resultados"/"Painel de
Controle" trazem fórmula) e, se o pacote opcional `formulas` estiver
instalado (`pip install formulas` — não é dependência do projeto, só de
teste), RECALCULA as fórmulas geradas e confere contra o `ResultadoMEF` em 5
cenários (bifurcado+dívida, intangível sem dívida, ativo financeiro puro,
lucro presumido, sem compensação de prejuízo) — a prova de que a fórmula
está certa, não só presente.

## Camadas de IA na borda (v3.9) — parsing assistido e explicação

`mef_engine/ia/` usa o Gemini (Google AI, pacote `google-genai`) para duas
funcionalidades, ambas estritamente de borda — `core.py`/`modules.py`/
`engine.py` não importam nada deste pacote, e nada aqui altera um número já
calculado deterministicamente:

  - **Explicação** (`explicar_resultado`): verbaliza em português o
    `ResultadoMEF.resumo()` já calculado — não recebe os fluxos brutos, não
    recalcula nada, só explica os números prontos.
  - **Parsing assistido** (`detectar_e_ingerir_com_ia_fallback`): só chama a
    IA quando `detectar_faixas` (heurística) não acha NENHUMA seção. A
    sugestão da IA passa pela MESMA `ingerir_secao` — e portanto a mesma
    reconciliação soma-vs-total — que qualquer faixa manual ou heurística;
    uma sugestão que não bate com o total ainda é recusada.

Em ambos os casos, a função que de fato chama a IA (`gerar_texto`) é
injetável — os testes (`tests/test_ia.py`) verificam prompt, parsing da
resposta e fallback gracioso sem nenhuma chamada de rede real. Sem
`GOOGLE_API_KEY` configurada (ou sem o SDK instalado, ou se a chamada
falhar), a IA fica indisponível (`IAIndisponivel`) e quem chamou decide o
fallback — nunca uma dependência dura do motor.

### Configuração

Dependência opcional, em `requirements-ia.txt` (`google-genai` +
`python-dotenv`): `pip install -r requirements-ia.txt`. A chave do Gemini
Developer API (gerada em aistudio.google.com/apikey) vai num `.env` na raiz
do projeto — copie `.env.example`, preencha `GOOGLE_API_KEY` e nunca
commite o `.env` real (já está no `.gitignore`); `cliente.py` carrega esse
arquivo automaticamente via `python-dotenv`.

**Nota de segurança (beta com chave compartilhada)**: se uma única chave for
distribuída a vários beta-testers (em vez de cada um gerar a própria),
configure um limite de gasto/cota nessa chave no Google AI Studio/Cloud
Console antes de distribuir — qualquer um com acesso ao `.env` local pode
extrair a chave; o limite de gasto é o que reduz o estrago se isso acontecer.

## Schema Pydantic + interface web + Cloud Run (v3.10)

Último item do roadmap original. Decisão de design: o schema Pydantic vive
NA BORDA (`mef_engine/api/formulario.py`), não substitui as dataclasses do
motor (`schema.py`) — mesma filosofia já usada para IA e ingestão. `core.py`/
`modules.py`/`engine.py` continuam sem saber que o Pydantic existe.

  - **`FormularioMEF`**: versão simplificada do `InputMEF` para o beta —
    projeto, tipo de concessão, timing, taxa de desconto e linhas de
    CAPEX/OPEX/receita. Deliberadamente NÃO expõe financiamento, indexação,
    módulo fiscal completo ou bifurcação por linha nesta v1 (ficam nos
    defaults do motor); reduzir o formulário a um MVP testável valeu mais que
    cobrir 100% do `InputMEF` de uma vez.
  - **`para_input_mef()`**: converte o formulário simplificado num `InputMEF`
    de verdade, aplicando `preset_por_tipo` (regime contábil, fração ativo
    financeiro) automaticamente — o beta-tester não escolhe isso diretamente.
  - **`FormularioMEF.model_json_schema()`**: gera o JSON Schema do roadmap —
    contrato único entre o formulário e qualquer cliente futuro (web atual,
    eventual API depois).
  - **`web/app.py`** (Streamlit): gate por senha única compartilhada
    (`APP_PASSWORD`, mesmo mecanismo `.env`/dotenv da chave de IA — vazio =
    acesso liberado, com aviso), formulário na barra lateral espelhando o
    `FormularioMEF`, botão Calcular, tabela de `resumo()`, download do Excel
    (`export.exportar_excel`) e botão opcional "Explicar com IA" (oculto se
    `GOOGLE_API_KEY` não estiver configurada).
  - **`Dockerfile`**: imagem `python:3.12-slim` com as três camadas de
    requirements (`requirements.txt`, `-ia`, `-web`), porta via `$PORT`
    (convenção Cloud Run) com default 8501 para execução local.

Testado com `streamlit.testing.v1.AppTest` (execução headless do script,
sem servidor real) e com o servidor de desenvolvimento (`streamlit run`,
verificado via HTTP): formulário sem erros, fluxo completo até o resultado,
gate de senha (recusa senha errada, libera com a correta) e geração do Excel
— sem exceções em nenhum caso. Um bug real foi encontrado e corrigido nesse
processo: `st.secrets.get(...)` levanta exceção quando não existe nenhum
`secrets.toml` no projeto (caso normal fora do Streamlit Community Cloud) —
corrigido para tratar a ausência de secrets como "sem senha via secrets",
sem derrubar o app.

Prova de corretude (teste [5] em test_formulario.py): `para_input_mef()` +
`engine.calcular()` produz exatamente o mesmo resultado (erro 0.0) que montar
o `InputMEF` equivalente à mão — a camada Pydantic não introduz nem perde
nenhuma informação na conversão.

### Rodando localmente

```bash
pip install -r requirements.txt -r requirements-ia.txt -r requirements-web.txt
streamlit run web/app.py
```

### Deploy no Google Cloud Run (manual — não automatizado por este projeto)

```bash
gcloud run deploy motor-mef --source . --region <sua-regiao> \
  --set-env-vars APP_PASSWORD=<senha-do-beta> \
  --set-env-vars GOOGLE_API_KEY=<chave-compartilhada>
```

**Nota de segurança**: a chave do Gemini é compartilhada entre os
beta-testers (decisão já tomada, ver seção de IA acima) — antes de
publicar a URL do Cloud Run, configure um limite de gasto/cota nessa chave
no Google AI Studio/Cloud Console, já que o app passa a ser acessível por
qualquer pessoa com o link + senha.

## Upload de planilha no formulário web (v3.11)

Teste do protótipo mostrou a digitação manual linha a linha (CAPEX, OPEX,
receita por volume) como o principal ponto de atrito de UX. Substituída por
upload de planilha (`.csv`, `.xls` ou `.xlsx`) em três campos independentes,
cada um com botão "baixar modelo" e mensagem de sucesso/erro — a
contraprestação pública (receita fixa) continua manual, não foi pedida.

  - **CAPEX/OPEX**: reaproveita o parser heurístico de `ingest/planilha.py`
    (mesma filosofia de ancorar na linha de total e RECONCILIAR soma dos
    itens vs. total declarado), generalizado para `.csv`/`.xls` além de
    `.xlsx` via `carregar_grade` — um adaptador (`_GradeLista`) que expõe a
    mesma interface de leitura por célula de uma worksheet openpyxl sobre uma
    lista de listas, alimentada por `csv` (delimitador `,`/`;` detectado por
    amostragem, números BR como `1.234,56` reconhecidos) ou `xlrd` (`.xls`).
    `ingerir_arquivo_secao_unica` trata o arquivo inteiro como UMA seção só
    (o upload já é dedicado a um bloco, não precisa detectar limites de
    seção como `detectar_faixas`); `arquivo_para_capex`/`arquivo_para_opex`
    (`ingest/__init__.py`) são o atalho usado pela interface web.
  - **Receita (tarifa × volume)**: sem linha de total para ancorar, então o
    módulo novo `ingest/receita.py` usa o CABEÇALHO de colunas (nome/tarifa/
    volume/crescimento, por correspondência de substring normalizada) como
    checagem de qualidade — falha de forma visível se as 3 colunas
    obrigatórias não forem reconhecidas, em vez de ingerir dado incompleto.

Dependência nova: `xlrd>=2.0` (`requirements.txt`), só usada para `.xls` (o
formato antigo do Excel; `.xlsx` continua via `openpyxl`).

Validado por simulação de upload via `streamlit.testing.v1.AppTest`
(CSV em formato BR e internacional, e um caso de reconciliação falhando de
propósito) e por smoke test direto das funções de ingestão.

## Próximos incrementos

Roadmap original do protótipo concluído. Possíveis próximos passos,
dependendo do retorno do beta:

  - Cobrir no formulário web os campos hoje só editáveis via `InputMEF`
    direto (financiamento, indexação, módulo fiscal completo, bifurcação por
    linha) — expandir `FormularioMEF` ou expor um modo "avançado".
  - Persistência de cenários (salvar/recuperar um `FormularioMEF` preenchido).
  - Autenticação por usuário (hoje é uma senha única compartilhada, adequada
    só para o beta).

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
python3 tests/test_ia.py
python3 tests/test_formulario.py
```

## Sequência recomendada até a nuvem (concluída)

Ingestão → schema Pydantic → interface que reflete o schema → Cloud Run. O
deploy em si (`gcloud run deploy`) é manual — depende das credenciais GCP do
usuário, não é executado por este repositório.
