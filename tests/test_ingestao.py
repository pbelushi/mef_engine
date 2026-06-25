"""
Validação do parser de ingestão contra o MEF real do HOPE.

Prova que o parser, sem assumir formato de coluna, (1) identifica os itens de
CAPEX, (2) detecta a linha de total por palavra-chave, e (3) RECONCILIA a soma
dos itens contra o total declarado pelo próprio modelo — a checagem de qualidade
que dá confiança de que leu o bloco certo.
"""
import sys
sys.path.insert(0, "/home/claude/mef_engine")

from mef_engine.ingest.planilha import detectar_e_ingerir

HOPE = "/mnt/user-data/uploads/9_10_2_MODELO_ECONÔMICO-FINANCEIRO.xlsx"


def test_capex_complexo_hospitalar_reconcilia():
    # Seção 5.2.1: itens de CAPEX do Complexo Hospitalar + linha de total (r147)
    secs = detectar_e_ingerir(HOPE, "Painel de Controle",
                              [(134, 147, "CAPEX Complexo Hospitalar")])
    sec = secs[0]
    rec = sec.reconciliar()
    print(f"  [1] CAPEX Complexo Hospitalar:")
    print(f"        itens lidos: {len(sec.itens)}")
    print(f"        soma itens:  {sec.soma_itens:,.2f}")
    print(f"        total decl.: {sec.total_declarado:,.2f}")
    print(f"        reconcilia:  {rec['ok']} (erro_rel={rec['erro_rel']:.2e})")
    assert sec.total_declarado is not None, "linha de total não detectada"
    assert len(sec.itens) >= 8, "poucos itens lidos"
    assert rec["ok"], f"soma não bate com total: {rec}"


def test_capex_lacen_reconcilia():
    secs = detectar_e_ingerir(HOPE, "Painel de Controle",
                              [(151, 164, "CAPEX LACEN")])
    sec = secs[0]
    rec = sec.reconciliar()
    print(f"  [2] CAPEX LACEN:")
    print(f"        itens lidos: {len(sec.itens)}")
    print(f"        soma itens:  {sec.soma_itens:,.2f}")
    print(f"        total decl.: {sec.total_declarado:,.2f}")
    print(f"        reconcilia:  {rec['ok']} (erro_rel={rec['erro_rel']:.2e})")
    assert rec["ok"], f"soma não bate: {rec}"


def test_deteccao_total_funciona():
    # Garante que a ancoragem no total não confunde item com total
    secs = detectar_e_ingerir(HOPE, "Painel de Controle",
                              [(134, 147, "CAPEX CH")])
    sec = secs[0]
    # o total não pode estar entre os itens
    nomes = [i.nome.lower() for i in sec.itens]
    assert not any("total" in n for n in nomes), "total vazou para itens"
    assert sec.linha_total == 147, f"linha de total errada: {sec.linha_total}"
    print(f"  [3] Ancoragem no total: linha {sec.linha_total}, "
          f"sem vazamento para itens  OK")


if __name__ == "__main__":
    print("Validação da ingestão CAPEX/OPEX vs HOPE\n" + "-" * 46)
    test_capex_complexo_hospitalar_reconcilia()
    test_capex_lacen_reconcilia()
    test_deteccao_total_funciona()
    print("-" * 46 + "\nTodos os testes passaram.")
