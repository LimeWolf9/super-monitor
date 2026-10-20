"""As competições de futebol que o dashboard segue, e a escolha de cada uma (data/competicoes.json).

- COMPETICOES: todas as que se podem escolher, pela ordem da rotação, com o grupo da página /definicoes,
  a liga na ESPN e o tipo:
    liga      tabela, resultados da jornada, próximos jogos, marcadores e 11 (o comportamento de sempre)
    taca      eliminatórias: um ecrã com os resultados da fase e os jogos seguintes
    selecoes  jogos de seleções (como as taças, e com as tabelas dos grupos quando a ESPN as tem)
    fonte     uma fonte das notícias (não é uma competição; só se liga e desliga)
  espn=None: não há fonte grátis e sem chave (aparece na página de definições, mas não se pode ligar).
  espn="ligaportugal": a Taça da Liga, que vem da API do site da Liga Portugal (tools/atualizar_taca_liga.py) e
  não do atualizar_futebol.py. Vem desligada (os termos da Liga Portugal só permitem uso pessoal).
- ler() devolve {chave: True/False}: o que está no ficheiro, e o valor por defeito (POR_DEFEITO) no que faltar.
- gravar() guarda a escolha (escrita atómica).

As seleções não são uma competição só: "Portugal", "Brasil" e "Argentina" escolhem equipas, e as competições
de seleções (Liga das Nações, qualificações, Mundial, Europeu) escolhem todos os jogos. Ver FONTES_SELECOES.
Só usa a biblioteca standard do Python.
"""

import json
from pathlib import Path

FICHEIRO = Path(__file__).resolve().parent.parent / "data" / "competicoes.json"

# (chave, nome, grupo, liga na ESPN, tipo, ligada por defeito, nota para a página de definições)
_LISTA = [
    ("pt",   "Liga Portugal",            "Portugal",   "por.1",               "liga", True, ""),
    ("tp",   "Taça de Portugal",         "Portugal",   "por.taca.portugal",   "taca", True, ""),
    ("tl",   "Taça da Liga",             "Portugal",   "ligaportugal",        "taca", False, "API do site da Liga Portugal: uso pessoal"),
    ("stp",  "Supertaça",                "Portugal",   None,                  "taca", True, "sem fonte grátis"),
    ("en",   "Premier League",           "Inglaterra", "eng.1",               "liga", True, ""),
    ("fa",   "Taça de Inglaterra",       "Inglaterra", "eng.fa",              "taca", True, "a partir dos oitavos"),
    ("efl",  "Taça da Liga inglesa",     "Inglaterra", "eng.league_cup",      "taca", True, "a partir dos oitavos"),
    ("es",   "La Liga",                  "Espanha",    "esp.1",               "liga", True, ""),
    ("cdr",  "Taça do Rei",              "Espanha",    "esp.copa_del_rey",    "taca", True, "a partir dos oitavos"),
    ("de",   "Bundesliga",               "Alemanha",   "ger.1",               "liga", True, ""),
    ("dfb",  "Taça da Alemanha",         "Alemanha",   "ger.dfb_pokal",       "taca", True, "a partir dos oitavos"),
    ("it",   "Serie A",                  "Itália",     "ita.1",               "liga", True, ""),
    ("cit",  "Taça de Itália",           "Itália",     "ita.coppa_italia",    "taca", True, "a partir dos oitavos"),
    ("fr",   "Ligue 1",                  "França",     "fra.1",               "liga", True, ""),
    ("cdf",  "Taça de França",           "França",     "fra.coupe_de_france", "taca", True, "a partir dos oitavos"),
    ("ucl",  "Liga dos Campeões",        "Europa",     "uefa.champions",      "liga", True, ""),
    ("uel",  "Liga Europa",              "Europa",     "uefa.europa",         "liga", True, ""),
    ("uecl", "Liga Conferência",         "Europa",     "uefa.europa.conf",    "liga", True, ""),
    ("usc",  "Supertaça Europeia",       "Europa",     "uefa.super_cup",      "taca", True, ""),
    ("por",  "Portugal",                 "Seleções",   None,                  "equipa", True, "todos os jogos, com os amigáveis"),
    ("bra",  "Brasil",                   "Seleções",   None,                  "equipa", True, "jogos oficiais"),
    ("arg",  "Argentina",                "Seleções",   None,                  "equipa", True, "jogos oficiais"),
    ("unl",  "Liga das Nações",          "Seleções",   "uefa.nations",        "selecoes", True, "Liga A"),
    ("wcq",  "Qualificação do Mundial",  "Seleções",   "fifa.worldq.uefa",    "selecoes", True, "Europa"),
    ("euq",  "Qualificação do Europeu",  "Seleções",   "uefa.euroq",          "selecoes", True, ""),
    ("wc",   "Mundial",                  "Seleções",   "fifa.world",          "selecoes", True, "fase final, todos os jogos"),
    ("euro", "Europeu",                  "Seleções",   "uefa.euro",           "selecoes", True, "fase final, todos os jogos"),
    # Fontes das notícias (tools/atualizar_noticias.py): não são competições, só se ligam e desligam
    ("n_record",      "Record",       "Notícias", None, "fonte", True, "Liga Portugal"),
    ("n_espn",        "ESPN",         "Notícias", None, "fonte", True, "em inglês, por competição"),
    ("n_abola",       "A Bola",       "Notícias", None, "fonte", True, "só os títulos"),
    ("n_maisfutebol", "Maisfutebol",  "Notícias", None, "fonte", True, ""),
    ("n_bbc",         "BBC Sport",    "Notícias", None, "fonte", True, "em inglês"),
    ("n_marca",       "Marca",        "Notícias", None, "fonte", True, "em espanhol, LaLiga"),
    ("n_ojogo",       "O Jogo",       "Notícias", None, "fonte", False, "o site proíbe o acesso automático"),
]
COMPETICOES = [dict(zip(("chave", "nome", "grupo", "espn", "tipo", "omissao", "nota"), c)) for c in _LISTA]
POR_CHAVE = {c["chave"]: c for c in COMPETICOES}
POR_DEFEITO = {c["chave"]: c["omissao"] for c in COMPETICOES
               if c["espn"] or c["tipo"] == "equipa" or (c["tipo"] == "fonte" and c["chave"] != "n_ojogo")}

# Taças estrangeiras: só a partir dos oitavos (ver fase_conta em atualizar_futebol.py)
DESDE_OITAVOS = {"fa", "efl", "cdr", "dfb", "cit", "cdf"}

# Seleções escolhidas por equipa: id da seleção na ESPN
SELECOES = {"por": "482", "bra": "205", "arg": "202"}

# Ecrãs de seleções: chave no live.json -> (nome, liga na ESPN, competição que liga todos os jogos ou None,
# seleções que entram mesmo sem isso, só Liga A?). Portugal entra em todas (com os amigáveis); o Brasil e a
# Argentina só nas oficiais.
FONTES_SELECOES = [
    ("unl",  "Liga das Nações",          "uefa.nations",         "unl",  ("por",),              True),
    ("wcq",  "Qualificação do Mundial",  "fifa.worldq.uefa",     "wcq",  ("por",),              False),
    ("euq",  "Qualificação do Europeu",  "uefa.euroq",           "euq",  ("por",),              False),
    ("wc",   "Mundial",                  "fifa.world",           "wc",   ("por", "bra", "arg"), False),
    ("euro", "Europeu",                  "uefa.euro",            "euro", ("por",),              False),
    ("ca",   "Copa América",             "conmebol.america",     None,   ("bra", "arg"),        False),
    ("wcqs", "Qualificação do Mundial · América do Sul", "fifa.worldq.conmebol", None, ("bra", "arg"), False),
    ("amg",  "Amigáveis",                "fifa.friendly",        None,   ("por",),              False),
]


def ler():
    """{chave: ligada?} com o valor por defeito no que o ficheiro não tiver (ou se não existir / estiver estragado)."""
    try:
        escolha = json.loads(FICHEIRO.read_text(encoding="utf-8")).get("ligadas", {})
    except (OSError, ValueError, AttributeError):
        escolha = {}
    return {k: bool(escolha.get(k, v)) for k, v in POR_DEFEITO.items()}


def gravar(escolha):
    """Grava só as chaves conhecidas. Devolve a escolha gravada."""
    limpa = {k: bool(escolha.get(k, v)) for k, v in POR_DEFEITO.items()}
    dados = {"_nota": "Escolhido em http://<pc>:8000/definicoes. Entra na próxima atualização.", "ligadas": limpa}
    tmp = FICHEIRO.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FICHEIRO)
    return limpa


def a_buscar(escolha=None):
    """O que o atualizador do futebol tem de ir buscar, pela ordem da rotação.

    Devolve [(chave, nome, liga ESPN, tipo, filtro)], com filtro = None (todos os jogos) ou
    {"equipas": {ids ESPN}, "ligaA": bool} para as seleções.
    """
    escolha = escolha or ler()
    lista = [(c["chave"], c["nome"], c["espn"], c["tipo"], None) for c in COMPETICOES
             if c["tipo"] in ("liga", "taca") and c["espn"] and c["espn"] != "ligaportugal" and escolha.get(c["chave"])]
    for chave, nome, espn, liga_toda, equipas, so_liga_a in FONTES_SELECOES:
        todos = bool(liga_toda and escolha.get(liga_toda))
        ids = {SELECOES[e] for e in equipas if escolha.get(e)}
        if todos:
            lista.append((chave, nome, espn, "selecoes", {"todos": True, "ligaA": so_liga_a, "equipas": ids}))
        elif ids:
            lista.append((chave, nome, espn, "selecoes", {"todos": False, "ligaA": False, "equipas": ids}))
    return lista
