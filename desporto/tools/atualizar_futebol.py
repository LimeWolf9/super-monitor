"""Vai buscar os dados reais do futebol e grava-os em data/live.json (secção "football").

Uso:
    python tools/atualizar_futebol.py            # atualiza data/live.json
    python tools/atualizar_futebol.py --mostrar  # só mostra o que gravaria

Fonte: a API pública da ESPN (site.api.espn.com), gratuita e sem chave. Não é oficial nem documentada:
se um dia mudar de formato, o script falha e o live.json fica como estava.
Por competição faz 5 pedidos: classificação, marcadores e os jogos do mês anterior, do atual e do seguinte
(a API só aceita um dia ou um mês de cada vez). Os jogos já trazem golos, penáltis, autogolos e vermelhos.

A ESPN não diz a jornada de cada jogo. Por isso os jogos são agrupados pelas datas: um intervalo de mais de
40 h entre jogos separa duas jornadas. A "última jornada" é o último grupo com os jogos todos terminados e os
"próximos jogos" são os do grupo seguinte. O número da jornada é o número de jogos que a maioria das equipas leva.

Equipas: o id da ESPN passa a sigla pelo mapa EQUIPAS (as siglas de "teams" e de web/img/equipas/<sigla>.png).
Uma equipa que ainda não esteja em "teams" é acrescentada com as cores da ESPN, e o emblema que faltar é
descarregado da ESPN. Um id que não esteja em EQUIPAS dá um aviso.
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from comum import LIVE, baixar_emblema, gravar, ler_dados, pedir_json, tem_emblema

API = "https://site.api.espn.com/apis"
URL_EMBLEMA = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/{id}.png&h=200&w=200"
INTERVALO_JORNADA = timedelta(hours=40)   # mais do que isto entre dois jogos = jornada nova

# Chave no live.json -> liga na ESPN
LIGAS = {
    "pt": "por.1", "en": "eng.1", "es": "esp.1",
    "ucl": "uefa.champions", "uel": "uefa.europa", "uecl": "uefa.europa.conf",
    # Só aparecem com ?cat=futebol (ver construirCenas em scenes.js)
    "de": "ger.1", "fr": "fra.1", "it": "ita.1",
}
# Nome das ligas que não existiam no mock.json
NOMES_LIGAS = {"de": "Bundesliga", "fr": "Ligue 1", "it": "Serie A"}

# id da equipa na ESPN -> sigla. As que já existiam no mock.json foram ligadas pelo nome;
# as restantes (NOVAS) ganharam uma sigla nova. Atenção: as siglas da ESPN não servem
# (para a ESPN "SLB" é o Slovan Bratislava e "MUN" o Bayern).
EQUIPAS = {
    # Portugal
    "437": "FCP", "1929": "SLB", "2250": "SCP", "2994": "SCB", "5309": "VSC", "12698": "FAM",
    "3699": "GIL", "12216": "EST", "21581": "CPI", "3696": "MOR", "15784": "ARO", "3822": "RAV",
    "12215": "SCL", "3472": "NAC", "21610": "AMD", "21607": "ACV", "21613": "ALV", "552": "MTO",
    "21615": "SCU",
    # Inglaterra
    "382": "MCI", "359": "ARS", "364": "LIV", "363": "CHE", "367": "TOT", "361": "NEW", "360": "MUN",
    "362": "AVL", "331": "BHA", "368": "EVE", "370": "FUL", "384": "CRY", "337": "BRE", "349": "BOU",
    "393": "NFO", "357": "LEE", "366": "SUN", "306": "HUL", "373": "IPS", "388": "COV",
    # Espanha
    "86": "RMA", "83": "BAR", "1068": "ATM", "102": "VIL", "93": "ATH", "244": "BET", "89": "RSO",
    "243": "SEV", "94": "VAL", "85": "CEL", "97": "OSA", "2922": "GET", "101": "RAY", "88": "ESP",
    "96": "ALA", "1538": "LEV", "3751": "ELC", "90": "DEP", "87": "RAC", "99": "MLG",
    # Resto da Europa
    "132": "BAY", "160": "PSG", "110": "INT", "124": "BVB", "114": "NAP", "104": "ROM", "167": "LYO",
    "436": "FEN", "139": "AJX", "443": "PAO", "3362": "CFC", "131": "B04", "111": "JUV", "105": "ATA",
    "174": "MON", "176": "MAR", "148": "PSV", "570": "BRU", "5807": "USG", "432": "GAL", "435": "OLY",
    "909": "COP", "494": "PRA", "2980": "BOD", "2528": "KAI", "22281": "PAF", "142": "FEY", "256": "CLT",
    "572": "MID", "166": "LIL", "887": "AEK", "2990": "LEC", "11505": "JAG", "617": "OMO",
    "134": "VFB", "493": "SHK", "2572": "COM", "175": "RCL", "11420": "RBL", "21922": "SAB",
    "510": "VIK", "4411": "LAS", "521": "SBR", "433": "SPP", "1895": "BES", "622": "FTC", "1010": "OFI",
    "2790": "SLZ", "597": "DZG", "13083": "HBS", "169": "REN", "3746": "STG", "441": "AND",
    "987": "LSK", "140": "AZA", "490": "LVS", "103": "ACM", "7911": "TSG", "20024": "ARA",
    "11706": "PLZ", "147": "NEC", "7853": "AGF", "20710": "BBL", "620": "BRN", "10834": "CSK",
    "21943": "EGN", "126": "SCF", "3611": "GNT", "489": "HAJ", "262": "HOM", "20025": "IBE",
    "20703": "IDE", "7922": "JAB", "20028": "ZAL", "8169": "KUP", "17856": "LRI", "7672": "LUG",
    "20301": "MJA", "3101": "FCN", "2290": "CZV", "19246": "RIG", "936": "STV", "3024": "THU",
    "997": "TRA", "152": "TWE", "8089": "UCR",
    # Alemanha
    "125": "SGE", "3841": "FCA", "137": "SVW", "2950": "M05", "10388": "ELV", "122": "KOE", "127": "HSV",
    "133": "S04", "3307": "PAD", "598": "FCU", "268": "BMG",
    # França
    "2502": "NIC", "6851": "PFC", "6997": "B29", "273": "LOR", "180": "STR", "7868": "ANG", "2697": "LMA",
    "179": "TFC", "172": "AJA", "170": "TRY", "3236": "LHA",
    # Itália
    "109": "FIO", "112": "LAZ", "2925": "CAG", "4057": "FRO", "3997": "USS", "239": "TRN", "113": "USL",
    "107": "BOL", "118": "UDI", "4007": "MZA", "3263": "GEN", "115": "PAR", "17530": "VEN",
}

# Nome curto das equipas que não estavam no mock.json (para "teams")
NOVAS = {
    "ACV": "Académico Viseu", "ALV": "Alverca", "MTO": "Marítimo", "SCU": "Torreense",
    "HUL": "Hull City", "IPS": "Ipswich", "COV": "Coventry",
    "DEP": "Deportivo", "RAC": "Racing", "MLG": "Málaga",
    "VFB": "Estugarda", "SHK": "Shakhtar", "COM": "Como", "RCL": "Lens", "RBL": "Leipzig",
    "SAB": "Sabah", "VIK": "Viking", "LAS": "LASK", "SBR": "Slovan Bratislava", "SPP": "Sparta Praga",
    "BES": "Besiktas", "FTC": "Ferencváros", "OFI": "OFI Creta", "SLZ": "Salzburgo",
    "DZG": "Dínamo Zagreb", "HBS": "Hapoel Be'er Sheva", "REN": "Rennes", "STG": "Sturm Graz",
    "AND": "Anderlecht", "LSK": "Lillestrøm", "AZA": "AZ Alkmaar", "LVS": "Levski Sófia",
    "ACM": "Milan", "TSG": "Hoffenheim", "ARA": "Ararat-Arménia", "PLZ": "Viktoria Plzeň",
    "NEC": "NEC Nijmegen", "AGF": "Aarhus", "BBL": "Borac Banja Luka", "BRN": "Brann",
    "CSK": "CSKA Sófia", "EGN": "Egnatia", "SCF": "Friburgo", "GNT": "Gent", "HAJ": "Hajduk Split",
    "HOM": "Hearts", "IBE": "Iberia 1999", "IDE": "Inter d'Escaldes", "JAB": "Jablonec",
    "ZAL": "Žalgiris", "KUP": "KuPS", "LRI": "Lincoln Red Imps", "LUG": "Lugano", "MJA": "Mjällby",
    "FCN": "Nordsjælland", "CZV": "Estrela Vermelha", "RIG": "Riga", "STV": "Sint-Truiden",
    "THU": "Thun", "TRA": "Trabzonspor", "TWE": "Twente", "UCR": "U. Craiova",
    "FCA": "Augsburgo", "SVW": "Werder Bremen", "M05": "Mainz", "ELV": "Elversberg", "KOE": "Colónia",
    "HSV": "Hamburgo", "S04": "Schalke 04", "PAD": "Paderborn", "FCU": "Union Berlim", "BMG": "Gladbach",
    "PFC": "Paris FC", "B29": "Brest", "LOR": "Lorient", "STR": "Estrasburgo", "ANG": "Angers", "LMA": "Le Mans",
    "TFC": "Toulouse", "AJA": "Auxerre", "TRY": "Troyes", "LHA": "Le Havre",
    "LAZ": "Lazio", "CAG": "Cagliari", "FRO": "Frosinone", "USS": "Sassuolo", "TRN": "Torino", "USL": "Lecce",
    "BOL": "Bolonha", "UDI": "Udinese", "MZA": "Monza", "GEN": "Génova", "PAR": "Parma", "VEN": "Veneza",
}

# Nomes de ficheiro proibidos no Windows: nenhuma sigla pode ser um destes (o emblema é <sigla>.png)
RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
COR_NEUTRA = "#4b5563"


def api(caminho):
    return pedir_json(f"{API}/{caminho}")


class Equipas:
    """Converte ids da ESPN em siglas e acrescenta a "teams" as equipas que faltam."""

    def __init__(self, teams, baixar=True):
        self.teams, self.baixar = teams, baixar
        self.novas, self.desconhecidas, self.sem_emblema = [], set(), []
        self.tranca = threading.RLock()   # as ligas correm em paralelo e partilham "teams"

    def sigla(self, t):
        with self.tranca:
            return self._sigla(t)

    def _sigla(self, t):
        code = EQUIPAS.get(t["id"])
        if code is None:
            code = "".join(c for c in t.get("abbreviation", "") if c.isalpha()).upper()[:4] or f"E{t['id']}"
            if code in RESERVADOS:   # o Windows não deixa criar AUX.png, CON.png...
                code += "X"
            while code in self.teams and self.teams[code].get("_espn") != t["id"]:
                code += "X"
            if t["id"] not in self.desconhecidas:
                self.desconhecidas.add(t["id"])
                print(f"Aviso: equipa nova '{t.get('displayName')}' (id {t['id']}) ficou com a sigla {code}. "
                      f"Acrescenta-a a EQUIPAS em {Path(__file__).name}.")
        if code not in self.teams:
            c1, c2 = t.get("color"), t.get("alternateColor")
            self.teams[code] = {
                "name": NOVAS.get(code, t.get("shortDisplayName") or t.get("displayName") or code),
                "c1": f"#{c1}" if c1 and c1 != "000000" else COR_NEUTRA,
                "c2": f"#{c2}" if c2 and c2 != c1 else "#ffffff",
            }
            if t["id"] not in EQUIPAS:
                self.teams[code]["_espn"] = t["id"]
            self.novas.append(code)
        elif self.teams[code].get("c1") == COR_NEUTRA and t.get("color") and t["color"] != "000000":
            # a classificação não traz cores; os jogos trazem, e corrigem a cor neutra
            self.teams[code] = {**self.teams[code], "c1": f"#{t['color']}",
                                "c2": f"#{t['alternateColor']}" if t.get("alternateColor") not in (None, t["color"]) else "#ffffff"}
        if t.get("displayName") and self.teams[code].get("espnName") != t["displayName"]:
            # nome completo na ESPN (ex.: "VfB Stuttgart" para a Estugarda): serve para confirmar o clube das fotos
            self.teams[code] = {**self.teams[code], "espnName": t["displayName"]}
        self.emblema(code, t["id"])
        return code

    def emblema(self, code, espn_id):
        """Descarrega o emblema da ESPN se ainda não houver nenhum para esta sigla."""
        if not self.baixar or code in self.sem_emblema or tem_emblema(code):
            return
        if baixar_emblema(code, URL_EMBLEMA.format(id=espn_id)):
            print(f"Emblema novo: {code}.png ({self.teams[code]['name']})")
        else:
            self.sem_emblema.append(code)


def classificacao(liga, equipas):
    d = api(f"v2/sports/soccer/{liga}/standings")
    grupos = d.get("children") or []
    if not grupos:
        raise RuntimeError(f"{liga}: sem classificação")
    entradas = grupos[0]["standings"]["entries"]   # ligas e fase de liga das taças: um só grupo

    def stat(e, nome):
        return next((s.get("value") for s in e["stats"] if s["name"] == nome), 0) or 0

    entradas.sort(key=lambda e: stat(e, "rank") or 999)
    # gf (golos marcados) não aparece na tabela: serve para as comparações das curiosidades
    return [{"team": equipas.sigla(e["team"]), "j": int(stat(e, "gamesPlayed")), "pts": int(stat(e, "points")),
             "gf": int(stat(e, "pointsFor"))} for e in entradas]


def marcadores(liga, equipas, n=3):
    d = api(f"site/v2/sports/soccer/{liga}/statistics")
    golos = next((s for s in d.get("stats", []) if s["name"] == "goalsLeaders"), {"leaders": []})
    lista = []
    for l in golos["leaders"][:n]:
        a = l["athlete"]
        team = a.get("team") or {}
        lista.append({
            "id": a.get("id"),   # id do atleta na ESPN (serve para a foto, em atualizar_fotos.py)
            "name": a.get("displayName") or a.get("shortName"),
            "team": equipas.sigla(team) if team.get("id") else "",
            "goals": int(l["value"]),
        })
    return lista


def meses(agora):
    """AAAAMM do mês anterior, do atual e do seguinte."""
    ant = agora.replace(day=1) - timedelta(days=1)
    seg = (agora.replace(day=28) + timedelta(days=4)).replace(day=1)
    return [m.strftime("%Y%m") for m in (ant, agora, seg)]


def jogos(liga, agora):
    vistos = {}
    for mes in meses(agora):
        for e in api(f"site/v2/sports/soccer/{liga}/scoreboard?dates={mes}").get("events", []):
            vistos[e["id"]] = e
    return sorted(vistos.values(), key=lambda e: e["date"])


def quando(e):
    return datetime.fromisoformat(e["date"].replace("Z", "+00:00"))


def estado(e):
    tipo = e["status"]["type"]
    if tipo.get("completed"):
        return "fim"
    if tipo["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED"):
        return "adiado"
    return "por jogar"   # agendado ou a decorrer


def jornadas(eventos, por_jornada):
    """Agrupa os jogos pelas datas. Os grupos muito pequenos (jogos em atraso) ficam de fora."""
    grupos, atual = [], []
    for e in eventos:
        if estado(e) == "adiado":
            continue
        if atual and quando(e) - quando(atual[-1]) > INTERVALO_JORNADA:
            grupos.append(atual)
            atual = []
        atual.append(e)
    if atual:
        grupos.append(atual)
    return [g for g in grupos if len(g) >= max(2, por_jornada // 3)]


def uma_por_equipa(eventos, maximo, do_fim=False):
    """Se duas jornadas ficaram coladas (ex.: segunda e terça), fica só com um jogo por equipa."""
    escolhidos, usadas = [], set()
    for e in (reversed(eventos) if do_fim else eventos):
        ids = {c["team"]["id"] for c in e["competitions"][0]["competitors"]}
        if ids & usadas:
            continue
        usadas |= ids
        escolhidos.append(e)
        if len(escolhidos) == maximo:
            break
    return sorted(escolhidos, key=lambda e: e["date"])


def nome_curto(nome):
    """Nome para os eventos, como no mock: "Vinícius Júnior" -> "V. Júnior". Nomes curtos ficam como estão."""
    partes = nome.split()
    if len(nome) <= 12 or len(partes) < 2 or partes[0].endswith("."):
        return nome
    return f"{partes[0][0]}. {' '.join(partes[1:])}"


def minuto(detalhe):
    m = detalhe["clock"]["displayValue"].replace("'", "")    # "90'+2'" -> "90+2"
    return int(m) if m.isdigit() else m


def eventos_do_jogo(comp, lado):
    """Golos, penáltis (marcados e falhados), autogolos e vermelhos. Os amarelos e os penáltis do desempate ficam de fora."""
    ev = []
    for d in comp.get("details", []):
        if d.get("shootout"):
            continue
        if d.get("scoringPlay"):
            t = "og" if d.get("ownGoal") else "pen" if d.get("penaltyKick") else None
        elif d.get("penaltyKick"):
            t = "pen_miss"
        elif d.get("redCard"):
            t = "red"
        else:
            continue
        atletas = d.get("athletesInvolved") or [{}]
        item = {"m": minuto(d), "s": lado.get(d.get("team", {}).get("id"), "h"),
                "p": nome_curto(atletas[0].get("shortName") or atletas[0].get("displayName") or "?")}
        if t:
            item["t"] = t
        ev.append(item)
    return ev


def resultado(e, equipas):
    comp = e["competitions"][0]
    casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    lado = {casa["team"]["id"]: "h", fora["team"]["id"]: "a"}
    return {"home": equipas.sigla(casa["team"]), "away": equipas.sigla(fora["team"]),
            "hs": int(casa["score"]), "as": int(fora["score"]), "ev": eventos_do_jogo(comp, lado),
            "id": e["id"]}   # id do jogo na ESPN (o atualizar_onze.py vai buscar as estatísticas por aqui)


def jogo_da_jornada(e, equipas):
    """Um jogo da jornada dos resultados: acabado (resultado), a decorrer (resultado atual), adiado ou por jogar."""
    tipo = e["status"]["type"]
    if estado(e) == "fim":
        return resultado(e, equipas)
    if estado(e) == "adiado":
        return {**proximo(e, equipas), "status": "adiado", "id": e["id"]}
    if tipo.get("state") == "in":   # a decorrer: resultado e minuto da ESPN
        r = resultado(e, equipas)
        return {**r, "live": True, "clock": tipo.get("shortDetail") or e["status"].get("displayClock") or ""}
    return {**proximo(e, equipas), "id": e["id"]}


def proximo(e, equipas):
    comp = e["competitions"][0]
    casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    local = quando(e).astimezone()    # hora deste PC
    return {"home": equipas.sigla(casa["team"]), "away": equipas.sigla(fora["team"]),
            "when": f"{DIAS[local.weekday()]} {local:%H:%M}", "date": f"{local:%d/%m}"}


def montar_liga(chave, antigo, equipas, agora):
    liga = LIGAS[chave]
    nova = dict(antigo or {})   # mantém o nome e as zonas que já existem
    nova.setdefault("name", NOMES_LIGAS.get(chave, chave))
    nova["table"] = classificacao(liga, equipas)
    por_jornada = max(1, len(nova["table"]) // 2)
    jogados = Counter(r["j"] for r in nova["table"] if r["j"])
    nova["round"] = f"Jornada {jogados.most_common(1)[0][0]}" if jogados else "Ainda sem jogos"
    nova["scorers"] = marcadores(liga, equipas)
    # Mantém a cara de quem já estava na lista (o atualizar_fotos.py só corre depois e só trata os novos);
    # sem isto, as caras desapareciam entre a atualização do futebol e a das fotos.
    caras = {(s["name"], s["team"]): s.get("photo") for s in (antigo or {}).get("scorers", []) if s.get("photo")}
    for s in nova["scorers"]:
        if (s["name"], s["team"]) in caras:
            s["photo"] = caras[(s["name"], s["team"])]

    eventos = jogos(liga, agora)
    grupos = jornadas(eventos, por_jornada)
    terminados = lambda g: [e for e in g if estado(e) == "fim"]
    # Jornada dos resultados: a mais recente com pelo menos metade dos jogos acabados. Assim uma jornada que
    # acaba à segunda (ex.: Premier League de sábado a segunda) já aparece no domingo, só com os jogos feitos,
    # em vez de ficar a mostrar a anterior até o último jogo acabar.
    # Jornada dos resultados: a mais recente com pelo menos um jogo acabado. Mostra-se a jornada toda: os jogos
    # acabados com o resultado, os que estão a decorrer com o resultado atual, os que faltam com o dia e a hora
    # e os adiados como "adiado".
    atual = next((i for i in range(len(grupos) - 1, -1, -1) if terminados(grupos[i])), None)
    ids_atual = set()
    if atual is None:
        nova["results"], nova["partial"] = [], None
    else:
        g = grupos[atual]
        ini, fim = quando(g[0]), quando(g[-1])
        # os adiados não entram nos grupos (jornadas()); voltam aqui se eram desta jornada
        adiados = [e for e in eventos if estado(e) == "adiado" and ini <= quando(e) <= fim]
        jornada = sorted(uma_por_equipa(g, por_jornada) + adiados, key=lambda e: e["date"])
        ids_atual = {e["id"] for e in jornada}
        nova["results"] = [jogo_da_jornada(e, equipas) for e in jornada]
        feitos = sum(1 for e in jornada if estado(e) == "fim")
        # jornada ainda em curso: "9 de 10 jogos" no subtítulo dos resultados
        nova["partial"] = {"done": feitos, "total": len(jornada)} if feitos < len(jornada) else None
    # Próximos jogos: tudo o que está por jogar até ao fim da jornada seguinte, menos o que já aparece nos resultados
    # (a jornada em curso). Inclui os jogos em atraso isolados (ex.: um Gil Vicente-Braga a meio da semana).
    depois = grupos[(atual + 1 if atual is not None else 0):]
    limite = max(quando(e) for e in depois[0]) if depois else agora + timedelta(days=8)
    por_jogar = sorted((e for e in eventos if estado(e) == "por jogar" and quando(e) <= limite
                        and e["id"] not in ids_atual and quando(e) > agora), key=lambda e: e["date"])
    nova["next"] = [proximo(e, equipas) for e in por_jogar]
    # Rótulo: só se diz "Jornada N" quando os próximos jogos são todos da jornada seguinte
    da_seguinte = {e["id"] for e in depois[0]} if depois else set()
    nova["nextMixed"] = any(e["id"] not in da_seguinte for e in por_jogar)
    return nova


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    teams = dict(dados["teams"])   # cópia: se falhar a meio, os dados originais ficam intactos
    equipas = Equipas(teams, baixar=not args.mostrar)
    agora = datetime.now(timezone.utc)
    futebol = dict(dados["football"])
    try:
        # As ligas são independentes: correm em paralelo (5 de cada vez), cada uma com os seus pedidos à ESPN
        with ThreadPoolExecutor(max_workers=5) as ex:
            futuros = {k: ex.submit(montar_liga, k, futebol.get(k), equipas, agora) for k in LIGAS}
            for chave, f in futuros.items():
                futebol[chave] = f.result()
    except Exception as e:   # sem rede, API em baixo, formato mudou...: fica tudo como estava
        sys.exit(f"Não foi possível atualizar o futebol ({e}). O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(futebol, ensure_ascii=False, indent=2))
        return
    dados["football"], dados["teams"] = futebol, teams
    gravar(dados, "futebol")
    if equipas.novas:
        print(f"Equipas acrescentadas a teams: {', '.join(equipas.novas)}")
    if equipas.sem_emblema:
        print(f"Sem emblema: {', '.join(equipas.sem_emblema)}")
    for chave in LIGAS:
        L = futebol[chave]
        print(f"{L['name']}: {L['round']}, {len(L['table'])} equipas, {len(L['results'])} resultados, "
              f"{len(L['next'])} próximos jogos, {len(L['scorers'])} marcadores")
    print(f"Futebol atualizado em {LIVE}.")


if __name__ == "__main__":
    main()
