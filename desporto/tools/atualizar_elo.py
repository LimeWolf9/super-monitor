"""Vai buscar o Elo dos clubes ao ClubElo e grava-o em data/live.json (secção "elo").

Uso:
    python tools/atualizar_elo.py            # atualiza data/live.json
    python tools/atualizar_elo.py --mostrar  # só mostra o que gravaria

Fontes (grátis, sem chave; o ClubElo não tem robots.txt):
- Ranking: a API do ClubElo (http://api.clubelo.com/AAAA-MM-DD, um CSV com Rank,Club,Country,Level,Elo,From,To).
  Quando a API está em baixo (acontece), a página https://clubelo.com/Ranking, que tem o mesmo ranking.
- Previsões dos jogos (1X2): a API das previsões foi desativada pelo ClubElo; ficam as da página
  https://clubelo.com/Fixtures (só os jogos dos próximos dias de algumas ligas). Os outros jogos são calculados no
  dashboard a partir do Elo (probabilidades() em web/js/cenas/futebol.js).

Grava:
    elo.data         dia do ranking
    elo.fonte        "API" ou "página Ranking"
    elo.ranking      top 10 da Europa, mais os clubes portugueses (posição, nome, país, Elo, sigla se a conhecermos)
    elo.porSigla     sigla -> Elo, das equipas que aparecem no dashboard (para as probabilidades dos próximos jogos)
    elo.previsoes    "CASA-FORA" (siglas) -> [p1, pX, p2] em %, as previsões do ClubElo
Os nomes do ClubElo ("Man City", "Porto") ligam-se às siglas pelos nomes das equipas no live.json, só dentro do
mesmo país; os que não batem certo vão em NOMES (nome do ClubElo -> sigla).
Só usa a biblioteca standard do Python.
"""

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone

from comum import gravar, ler_dados, pedir, registar_fonte

API = "http://api.clubelo.com/{dia}"
PAGINA_RANKING = "https://clubelo.com/Ranking"
PAGINA_JOGOS = "https://clubelo.com/Fixtures"
EUROPA = {"ENG", "ESP", "GER", "ITA", "FRA", "POR", "NED", "BEL", "TUR", "SCO", "AUT", "SUI", "GRE", "CZE", "DEN",
          "NOR", "SWE", "UKR", "CRO", "SRB", "POL", "RUS", "ISR", "CYP", "HUN", "ROM", "BUL", "SVK", "SLO", "AZE",
          "KAZ", "BLR", "IRL", "NIR", "WAL", "FIN", "ISL", "MOL", "ALB", "BIH", "MKD", "MNE", "KOS", "LUX", "MLT",
          "GEO", "ARM", "LAT", "LIT", "EST", "FAR", "AND", "SMR", "GIB", "LIE"}
TOP = 10
# País do ClubElo -> competições do live.json com equipas desse país (para ligar os nomes)
PAIS_COMPETICOES = {"POR": ["pt", "tp", "tl"], "ENG": ["en", "fa", "efl"], "ESP": ["es", "cdr"], "GER": ["de", "dfb"],
                    "ITA": ["it", "cit"], "FRA": ["fr", "cdf"]}
EUROPEIAS = ["ucl", "uel", "uecl"]
# Nomes do ClubElo que não batem certo com os das equipas (nome do ClubElo -> sigla)
NOMES = {
    "Porto": "FCP", "Benfica": "SLB", "Sporting": "SCP", "Braga": "SCB", "Guimaraes": "VSC", "Famalicao": "FAM",
    "Estrela": "AMD", "Casa Pia": "CPI", "Santa Clara": "SCL", "Alverca": "ALV", "Tondela": "CDT", "Nacional": "NAC",
    "Man City": "MCI", "Man United": "MUN", "Forest": "NFO", "Wolves": "WOL", "Spurs": "TOT", "Tottenham": "TOT",
    "Atletico": "ATM", "Real Madrid": "RMA", "Barcelona": "BAR", "Bilbao": "ATH", "Sociedad": "RSO", "Betis": "BET",
    "Celta": "CEL", "Rayo Vallecano": "RAY", "Espanyol": "ESP", "Bayern": "BAY", "Dortmund": "BVB",
    "Bayern München": "BAY", "Leverkusen": "B04", "Frankfurt": "SGE", "Gladbach": "BMG", "Koeln": "KOE", "Stuttgart": "VFB", "Leipzig": "RBL",
    "Hoffenheim": "TSG", "Freiburg": "SCF", "Mainz": "M05", "Werder": "SVW", "Union Berlin": "FCU",
    "Inter": "INT", "Milan": "ACM", "Juventus": "JUV", "Napoli": "NAP", "Roma": "ROM", "Lazio": "LAZ",
    "Atalanta": "ATA", "Fiorentina": "FIO", "Paris SG": "PSG", "Marseille": "MAR", "Lyon": "LYO", "Monaco": "MON",
    "Lille": "LIL", "Lens": "RCL", "Rennes": "REN", "Nice": "NIC", "Brest": "B29", "Strasbourg": "STR",
    "PSV": "PSV", "Ajax": "AJX", "Feyenoord": "FEY", "Brugge": "BRU", "Galatasaray": "GAL", "Fenerbahce": "FEN",
    "Ac Viseu": "ACV", "Viseu": "ACV", "Maritimo": "MTO", "Koeln": "KOE", "Köln": "KOE", "Schalke": "S04",
    "Hamburg": "HSV", "Augsburg": "FCA", "Hull": "HUL", "Depor": "DEP", "Racing Santander": "RAC",
    "Olympiakos": "OLY", "Alkmaar": "AZA", "Nijmegen": "NEC", "Sparta Praha": "SPP", "Levski": "LVS",
    "Hajduk": "HAJ", "Crvena Zvezda": "CZV", "Craiova": "UCR", "Pafos": "PAF", "Kairat": "KAI", "Gent": "GNT",
    "St Gillis": "USG", "Sint-Truiden": "STV", "Midtjylland": "MID", "Celtic": "CLT", "Rangers": "RAN",
}


def normalizar(nome):
    nome = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", nome)


def ranking_api(dia):
    texto = pedir(API.format(dia=dia), pausa=0).decode("utf-8")
    linhas = list(csv.DictReader(io.StringIO(texto)))
    if not linhas:
        raise RuntimeError("API sem dados")
    return [{"rank": int(l["Rank"]) if l["Rank"].isdigit() else None, "club": l["Club"], "country": l["Country"],
             "elo": round(float(l["Elo"]))} for l in linhas], "API"


LINHA = re.compile(r'<a href="/([A-Z]{3})"><img[^>]*></a>\s*<span class="min481"><small>\s*(\d+)\s*</small></span>\s*'
                   r'<a href="/([^"]+)"><span class="NonAst">[^<]*</span><span class="Ast">([^<]*)</span></a></td>'
                   r'<td class="r">(\d+)</td>')


# O resto do ranking vem num array de JavaScript, com o nome partido: "Colegiales de Mun<span>ro</span>"
LINHA_JS = re.compile(r'alt="([A-Z]{3})"[^>]*></a> <small> (\d+) </small><a href="/([^"]+)">([^<]*)'
                      r"(?:<span class=\"min481\">([^<]*)</span>)?</a></td>', '(\d+)'")


def ranking_pagina():
    pagina = pedir(PAGINA_RANKING).decode("utf-8", "replace")
    lista = [{"rank": int(r), "club": nome, "country": pais, "elo": int(elo), "slug": slug}
             for pais, r, slug, nome, elo in LINHA.findall(pagina)]
    vistos = {c["slug"] for c in lista}
    lista += [{"rank": int(r), "club": (n1 + n2).strip(), "country": pais, "elo": int(elo), "slug": slug}
              for pais, r, slug, n1, n2, elo in LINHA_JS.findall(pagina) if slug not in vistos]
    if len(lista) < 50:
        raise RuntimeError("a página do ranking mudou de formato")
    return sorted(lista, key=lambda c: c["rank"]), "página Ranking"


EQUIPA = re.compile(r'<a href="/([^"/]+)">(?:<span[^>]*>[^<]*</span>)+</a>')
PCT = re.compile(r'<span class="min1081">([\d.]+)</span>')


def previsoes_pagina():
    """[(slug casa, slug fora, [p1, pX, p2])] da página dos jogos."""
    pagina = pedir(PAGINA_JOGOS).decode("utf-8", "replace")
    res = []
    for bloco in pagina.split("data-live-status-game-id=")[1:]:
        equipas = list(EQUIPA.finditer(bloco))
        if len(equipas) < 2:
            continue
        a, b = equipas[0], equipas[1]
        antes = PCT.findall(bloco[a.end():b.start()])
        depois = PCT.findall(bloco[b.end():])
        if len(antes) >= 2 and depois:
            res.append((a.group(1), b.group(1), [float(antes[0]), float(antes[1]), float(depois[0])]))
    return res


def siglas_por_nome(dados):
    """(país do ClubElo, nome normalizado) -> sigla, das equipas das competições do live.json."""
    futebol, teams = dados.get("football") or {}, dados.get("teams") or {}
    codes = lambda chave: {r["team"] for r in (futebol.get(chave) or {}).get("table", [])} | \
        {m[k] for m in (futebol.get(chave) or {}).get("results", []) + (futebol.get(chave) or {}).get("next", [])
         for k in ("home", "away") if m.get(k)}
    mapa = {}
    for pais, chaves in PAIS_COMPETICOES.items():
        for c in set().union(*(codes(k) for k in chaves)):
            for n in (teams.get(c, {}).get("name"), teams.get(c, {}).get("espnName")):
                if n:
                    mapa.setdefault((pais, normalizar(n)), c)
    europeias = set().union(*(codes(k) for k in EUROPEIAS))
    for c in europeias:
        for n in (teams.get(c, {}).get("name"), teams.get(c, {}).get("espnName")):
            if n:
                mapa.setdefault(("*", normalizar(n)), c)
    return mapa, set(teams)


def sigla(clube, pais, mapa, existentes):
    if pais in EUROPA and clube in NOMES and NOMES[clube] in existentes:   # ("Nacional" também há no Uruguai)
        return NOMES[clube]
    n = normalizar(clube)
    return mapa.get((pais, n)) or mapa.get(("*", n))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    erros = []
    try:
        lista, fonte = ranking_api(dia)
        registar_fonte("ClubElo API", itens=len(lista))
    except Exception as e:   # a API do ClubElo vai abaixo de vez em quando: fica a página do ranking
        erros.append(f"API ({e})")
        try:
            lista, fonte = ranking_pagina()
            registar_fonte("ClubElo API", aviso=f"{e}; usou-se a página do ranking")   # há dados: não é uma falha
            registar_fonte("ClubElo página", itens=len(lista))
        except Exception as e2:
            registar_fonte("ClubElo API", erro=e)
            registar_fonte("ClubElo página", erro=e2)
            sys.exit(f"Não foi possível atualizar o ClubElo (API: {e}; página: {e2}). O live.json não foi alterado.")
    mapa, existentes = siglas_por_nome(dados)
    for c in lista:
        c["sigla"] = sigla(c["club"], c["country"], mapa, existentes)
    europa = [c for c in lista if c["country"] in EUROPA]
    europa.sort(key=lambda c: -c["elo"])
    for i, c in enumerate(europa, 1):
        c["posEuropa"] = i
    ranking = [c for c in europa[:TOP]] + [c for c in europa[TOP:] if c["country"] == "POR"][:8]
    por_sigla = {c["sigla"]: c["elo"] for c in lista if c.get("sigla")}
    previsoes = {}
    try:
        slug_sigla = {c["slug"]: c["sigla"] for c in lista if c.get("slug") and c.get("sigla")}
        if not slug_sigla:   # a API não dá os "slugs" das páginas: vão-se buscar ao ranking da página
            slug_sigla = {c["slug"]: sigla(c["club"], c["country"], mapa, existentes) for c in ranking_pagina()[0]}
        for casa, fora, p in previsoes_pagina():
            if slug_sigla.get(casa) and slug_sigla.get(fora):
                previsoes[f"{slug_sigla[casa]}-{slug_sigla[fora]}"] = p
        registar_fonte("ClubElo previsões", itens=len(previsoes), esperado=False)
    except Exception as e:   # sem previsões: o dashboard calcula-as a partir do Elo
        registar_fonte("ClubElo previsões", erro=e)
        erros.append(f"previsões ({e})")
    elo = {"data": dia, "fonte": fonte,
           "ranking": [{k: c.get(k) for k in ("posEuropa", "rank", "club", "country", "elo", "sigla")} for c in ranking],
           "porSigla": por_sigla, "previsoes": previsoes}
    if args.mostrar:
        print(json.dumps(elo, ensure_ascii=False, indent=2))
        return
    dados["elo"] = elo
    gravar(dados, "elo")
    print(f"ClubElo ({fonte}): {len(lista)} clubes, {len(por_sigla)} com sigla, {len(previsoes)} previsões."
          + (f" Avisos: {'; '.join(erros)}." if erros else ""))


if __name__ == "__main__":
    main()
