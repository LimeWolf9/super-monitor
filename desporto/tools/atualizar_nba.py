"""Vai buscar os dados reais da NBA e grava-os em data/live.json (secção "nba").

Uso:
    python tools/atualizar_nba.py            # atualiza data/live.json
    python tools/atualizar_nba.py --mostrar  # só mostra o que gravaria

Fonte: a API pública da ESPN (site.api.espn.com), gratuita e sem chave.
- Classificação da época regular por conferência, até ao 10.º (último lugar do play-in).
- Jogos da noite passada (época regular, play-in e play-offs; a pré-época não conta).
- Jogos desta noite (os da noite americana que vem), com a hora de Portugal e o instante exato ("iso"): o ecrã
  "NBA · Esta noite" da Próxima jornada e o "Hoje no desporto" do Início do MonitorHub.
- Líderes da época em pontos, ressaltos e assistências por jogo.
- O melhor marcador da noite (box score de cada jogo), para a cena "Jogador em destaque".
Antes de a época regular começar não há classificação nem líderes: ficam a null e as cenas saem da rotação.
- Corrida ao MVP e ao Rookie do Ano: odds "futures" das casas de apostas que a ESPN publica (DraftKings),
  convertidas em probabilidade e normalizadas entre os 5 favoritos. Antes da época, a linha de cada jogador
  mostra as odds; depois, as médias da época.
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from comum import baixar_emblema, gravar, ler_dados, pedir_json, registar_fonte, tem_emblema

API = "https://site.api.espn.com/apis"
API_CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
API_STATS = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
URL_EMBLEMA = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/nba/500/{abrev}.png&h=200&w=200"
TIPOS_JOGO = {2, 3, 5}   # época regular, play-offs, play-in (1 = pré-época)

# id da equipa na ESPN -> sigla (a de "teams" e de web/img/equipas/<sigla>.png).
# Não se usam as siglas da ESPN porque algumas são diferentes (GS, NY, SA, UTAH, WSH...).
EQUIPAS = {
    "1": "ATL", "2": "BOS", "17": "BKN", "30": "CHA", "4": "CHI", "5": "CLE", "6": "DAL", "7": "DEN",
    "8": "DET", "9": "GSW", "10": "HOU", "11": "IND", "12": "LAC", "13": "LAL", "29": "MEM", "14": "MIA",
    "15": "MIL", "16": "MIN", "3": "NOP", "18": "NYK", "25": "OKC", "19": "ORL", "20": "PHI", "21": "PHX",
    "22": "POR", "23": "SAC", "24": "SAS", "28": "TOR", "26": "UTA", "27": "WAS",
}
# Sigla -> sigla da ESPN no endereço dos emblemas, quando são diferentes
EMBLEMA_ESPN = {"GSW": "gs", "NOP": "no", "NYK": "ny", "SAS": "sa", "UTA": "utah", "WAS": "wsh"}
# Equipas que não estavam no mock.json (nome curto para "teams")
NOVAS = {"BKN": "Nets", "DET": "Pistons", "LAC": "Clippers", "NOP": "Pelicans", "POR": "Trail Blazers",
         "TOR": "Raptors", "WAS": "Wizards"}

# Mercados de apostas -> chave no live.json
PREMIOS = {"Regular Season MVP": "mvp", "Rookie of the Year": "roty"}
FAVORITOS = 5

# Líderes: rótulo -> (categoria, estatística) no endpoint de estatísticas por jogador
LIDERES = {
    "Pontos": ("offensive", "avgPoints"),
    "Ressaltos": ("general", "avgRebounds"),
    "Assistências": ("offensive", "avgAssists"),
}


def api(caminho):
    return pedir_json(f"{API}/{caminho}")


class Equipas:
    def __init__(self, teams, baixar=True):
        self.teams, self.baixar, self.novas = teams, baixar, []

    def sigla(self, t):
        """t: equipa como vem da ESPN (precisa de "id"; usa "abbreviation" e cores se as tiver)."""
        tid = str(t["id"])
        code = EQUIPAS.get(tid)
        if code is None:
            code = (t.get("abbreviation") or f"N{tid}").upper()
            print(f"Aviso: equipa desconhecida '{t.get('displayName')}' (id {tid}). Acrescenta-a a EQUIPAS.")
        if code not in self.teams:
            c1, c2 = t.get("color"), t.get("alternateColor")
            self.teams[code] = {"name": NOVAS.get(code, t.get("shortDisplayName") or code),
                                "c1": f"#{c1}" if c1 else "#4b5563", "c2": f"#{c2}" if c2 else "#ffffff"}
            self.novas.append(code)
        if self.baixar and not tem_emblema(code):
            if baixar_emblema(code, URL_EMBLEMA.format(abrev=EMBLEMA_ESPN.get(code, code.lower()))):
                print(f"Emblema novo: {code}.png")
        return code


def classificacao(equipas):
    """(época, este, oeste). As conferências ficam a None se a época regular ainda não começou."""
    d = api("v2/sports/basketball/nba/standings?seasontype=2")
    epoca = d.get("season", {}).get("year")
    confs = {}
    jogos = 0
    for ch in d.get("children", []):
        def stat(e, nome):
            return next((s.get("value") for s in e["stats"] if s["name"] == nome), 0) or 0
        entradas = sorted(ch["standings"]["entries"], key=lambda e: stat(e, "playoffSeed") or 99)
        jogos += sum(int(stat(e, "wins") + stat(e, "losses")) for e in entradas)
        confs[ch["name"]] = [{"team": equipas.sigla(e["team"]), "w": int(stat(e, "wins")), "l": int(stat(e, "losses"))}
                             for e in entradas[:10]]
    if not jogos:
        return epoca, None, None
    este = next((v for k, v in confs.items() if "East" in k), None)
    oeste = next((v for k, v in confs.items() if "West" in k), None)
    return epoca, este, oeste


def lideres(epoca, equipas):
    """{"Pontos": [{name, team, v}], ...} ou None se ainda não houver estatísticas da época regular."""
    res = {}
    for rotulo, (cat, nome) in LIDERES.items():
        d = pedir_json(f"{API_STATS}?category={cat}&sort={cat}.{nome}:desc&limit=3&season={epoca}&seasontype=2")
        nomes = next((c["names"] for c in d.get("categories", []) if c["name"] == cat), [])
        lista = []
        for a in d.get("athletes", []):
            valores = next((c["totals"] for c in a["categories"] if c["name"] == cat), None)
            if not valores or nome not in nomes:
                continue
            at = a["athlete"]
            lista.append({"name": at.get("displayName"),
                          "team": equipas.sigla({"id": at.get("teamId"), "abbreviation": at.get("teamShortName")}),
                          "v": valores[nomes.index(nome)]})
        if lista:
            res[rotulo] = lista
    return res or None


def probabilidade(odd):
    """Odds americanas -> probabilidade implícita ("+250" -> 0.286, "-150" -> 0.6)."""
    v = int(odd)
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def linha_jogador(epoca, atleta_id, odd):
    """Médias da época regular ("25.0 pts · 11.5 reb · 3.1 ast"); antes da época, as odds."""
    try:
        d = pedir_json(f"{API_CORE}/seasons/{epoca}/types/2/athletes/{atleta_id}/statistics")
    except Exception:   # 404 enquanto o jogador não tiver jogos na época regular
        return f"Odds {odd}"
    v = {s["name"]: s["displayValue"] for c in d["splits"]["categories"] for s in c["stats"]}
    if not v.get("gamesPlayed") or v["gamesPlayed"] == "0":
        return f"Odds {odd}"
    return f"{v.get('avgPoints', '—')} pts · {v.get('avgRebounds', '—')} reb · {v.get('avgAssists', '—')} ast"


def premios(epoca, equipas):
    """{"mvp": [...], "roty": [...], "fonte": "DraftKings"} a partir das odds; listas vazias se não houver."""
    d = pedir_json(f"{API_CORE}/seasons/{epoca}/futures?limit=100")
    res, fonte = {}, None
    for item in d.get("items", []):
        chave = next((k for nome, k in PREMIOS.items() if nome in item.get("name", "")), None)
        if not chave or not item.get("futures"):
            continue
        mercado = item["futures"][0]
        fonte = mercado.get("provider", {}).get("name")
        apostas = [b for b in mercado.get("books", []) if b.get("athlete") and b.get("value")]
        apostas = sorted(apostas, key=lambda b: -probabilidade(b["value"]))[:FAVORITOS]
        total = sum(probabilidade(b["value"]) for b in apostas)
        lista = []

        # Os pedidos de cada jogador (ficha e médias) vão em paralelo; o resto é feito pela ordem
        def ficha(b):
            atleta = pedir_json(b["athlete"]["$ref"])
            return atleta, linha_jogador(epoca, atleta["id"], b["value"])

        with ThreadPoolExecutor(max_workers=5) as ex:
            fichas = list(ex.map(ficha, apostas))
        for b, (atleta, linha) in zip(apostas, fichas):
            equipa_ref = (atleta.get("team") or {}).get("$ref", "")
            equipa_id = equipa_ref.split("/teams/")[1].split("?")[0] if "/teams/" in equipa_ref else None
            lista.append({
                "name": atleta.get("displayName"),
                "team": equipas.sigla({"id": equipa_id}) if equipa_id else "",
                "pct": round(100 * probabilidade(b["value"]) / total),
                "line": linha,
            })
        res[chave] = lista
    return res, fonte


def noite_passada(equipas):
    """Jogos acabados da última noite americana (dia anterior em Nova Iorque) e o melhor marcador."""
    ny = datetime.now(timezone.utc) - timedelta(hours=5)   # hora de Nova Iorque, aproximada
    dia = (ny - timedelta(days=1)).strftime("%Y%m%d")
    jogos, melhor = [], None
    for e in api(f"site/v2/sports/basketball/nba/scoreboard?dates={dia}").get("events", []):
        if e["season"].get("type") not in TIPOS_JOGO or not e["status"]["type"].get("completed"):
            continue
        comp = e["competitions"][0]
        casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        jogo = {"home": equipas.sigla(casa["team"]), "away": equipas.sigla(fora["team"]),
                "hs": int(casa["score"]), "as": int(fora["score"])}
        jogos.append(jogo)
        cand = melhor_do_jogo(e["id"], jogo)
        if cand and (melhor is None or cand["pts"] > melhor["pts"]):
            melhor = cand
    return jogos, melhor


DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def esta_noite(equipas):
    """Jogos da noite americana que vem (o dia de hoje em Nova Iorque) ainda por acabar, com a hora deste PC."""
    ny = datetime.now(timezone.utc) - timedelta(hours=5)   # hora de Nova Iorque, aproximada
    jogos = []
    for e in api(f"site/v2/sports/basketball/nba/scoreboard?dates={ny:%Y%m%d}").get("events", []):
        if e["season"].get("type") not in TIPOS_JOGO or e["status"]["type"].get("completed"):
            continue
        comp = e["competitions"][0]
        casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        local = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone()
        jogos.append({"home": equipas.sigla(casa["team"]), "away": equipas.sigla(fora["team"]),
                      "when": f"{DIAS[local.weekday()]} {local:%H:%M}", "date": f"{local:%d/%m}",
                      "iso": local.isoformat(timespec="minutes")})
    return sorted(jogos, key=lambda j: j["iso"])


def melhor_do_jogo(event_id, jogo):
    """Jogador com mais pontos no box score de um jogo."""
    d = api(f"site/v2/sports/basketball/nba/summary?event={event_id}")
    melhor = None
    for lado in d.get("boxscore", {}).get("players", []):
        code = EQUIPAS.get(str(lado["team"]["id"]))
        for grupo in lado.get("statistics", []):
            chaves = grupo.get("keys", [])
            if "points" not in chaves:
                continue
            for a in grupo.get("athletes", []):
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                v = dict(zip(chaves, a["stats"]))
                try:
                    pts = int(v["points"])
                except ValueError:
                    continue
                if melhor is None or pts > melhor["pts"]:
                    casa = code == jogo["home"]
                    melhor = {"name": a["athlete"]["displayName"], "team": code,
                              "opp": jogo["away"] if casa else jogo["home"],
                              "pts": pts, "reb": int(v.get("rebounds") or 0), "ast": int(v.get("assists") or 0),
                              "min": v.get("minutes", ""), "score": f"{jogo['hs']}–{jogo['as']}",
                              "home": jogo["home"], "away": jogo["away"]}
    return melhor


def inicio_epoca_regular(epoca):
    """Data (AAAA-MM-DD, dia americano) em que começa a época regular, ou None."""
    try:
        d = pedir_json(f"{API_CORE}/seasons/{epoca}/types/2")
        return (d.get("startDate") or "")[:10] or None
    except Exception:
        return None


def montar_nba(antigo, equipas):
    epoca, este, oeste = classificacao(equipas)
    nba = dict(antigo or {})   # mantém as zonas que já existem
    nba["east"], nba["west"] = este, oeste
    nba["leaders"] = lideres(epoca, equipas) if epoca else None
    nba["lastNight"], nba["topPerformer"] = noite_passada(equipas)
    nba["tonight"] = esta_noite(equipas)
    corrida, fonte = premios(epoca, equipas) if epoca else ({}, None)
    nba["mvp"], nba["roty"] = corrida.get("mvp") or None, corrida.get("roty") or None
    nba["awardsSource"] = fonte
    nba["regularStart"] = inicio_epoca_regular(epoca) if epoca else None   # para o ecrã "Em construção"
    return nba


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    teams = dict(dados["teams"])
    equipas = Equipas(teams, baixar=not args.mostrar)
    try:
        nba = montar_nba(dados.get("nba"), equipas)
        # Fora de época (sem classificação nem jogos) é normal não vir nada: não conta como aviso
        registar_fonte("ESPN NBA", itens=len(nba.get("lastNight") or []) + len(nba.get("tonight") or []) + len((nba.get("east") or [])), esperado=False)
    except Exception as e:   # sem rede, API em baixo, formato mudou...: fica tudo como estava
        registar_fonte("ESPN NBA", erro=e)
        sys.exit(f"Não foi possível atualizar a NBA ({e}). O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(nba, ensure_ascii=False, indent=2))
        return
    dados["nba"], dados["teams"] = nba, teams
    gravar(dados, "nba")
    if equipas.novas:
        print(f"Equipas acrescentadas a teams: {', '.join(equipas.novas)}")
    print(f"NBA atualizada: classificação {'sim' if nba['east'] else 'ainda não (época por começar)'}, "
          f"líderes {'sim' if nba['leaders'] else 'ainda não'}, {len(nba['lastNight'])} jogos na noite passada, "
          f"{len(nba['tonight'])} esta noite"
          + (f", melhor marcador {nba['topPerformer']['name']} ({nba['topPerformer']['pts']} pts)" if nba["topPerformer"] else "")
          + (f", favorito a MVP {nba['mvp'][0]['name']} ({nba['mvp'][0]['pct']}%)" if nba["mvp"] else "") + ".")


if __name__ == "__main__":
    main()
