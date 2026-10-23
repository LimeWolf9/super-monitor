"""Vai buscar os dados reais do futebol e grava-os em data/live.json (secção "football").

Uso:
    python tools/atualizar_futebol.py            # atualiza data/live.json
    python tools/atualizar_futebol.py --mostrar  # só mostra o que gravaria
    python tools/atualizar_futebol.py --competicoes pt,en   # só estas (chaves de competicoes.py); as outras ficam

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
Taças e seleções (tipo "taca" e "selecoes" em competicoes.py): 3 pedidos por competição (os jogos dos três
meses), mais a classificação dos grupos nas seleções. A fase vem de cada jogo (season.slug: "3rd-round",
"round-of-16", "group-stage"...). Ver montar_taca().
As competições que se buscam são as escolhidas em data/competicoes.json (página /definicoes do serve.py);
as que se desligaram saem do live.json (numa atualização completa; com --competicoes só se mexe nas pedidas).
Cada competição atualizada regista a sua hora em _atualizado ("futebol:pt"), que é a que o canto do ecrã mostra
nas cenas dela; a hora "futebol" só muda numa atualização completa (ver comum.marcas).
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from comum import EMBLEMAS, LIVE, RAIZ, baixar_emblema, gravar, ler_dados, marcas, pedir, pedir_json, registar_fonte, tem_emblema
import competicoes
import emblemas_wikidata

API = "https://site.api.espn.com/apis"
URL_EMBLEMA = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/{id}.png&h=200&w=200"
INTERVALO_JORNADA = timedelta(hours=40)   # mais do que isto entre dois jogos = jornada nova

# Chave no live.json -> liga na ESPN (só as ligas; a lista toda, com as taças e as seleções, está em competicoes.py)
LIGAS = {c["chave"]: c["espn"] for c in competicoes.COMPETICOES if c["tipo"] == "liga"}
# Nome das ligas que não existiam no mock.json
NOMES_LIGAS = {c["chave"]: c["nome"] for c in competicoes.COMPETICOES if c["tipo"] == "liga"}
LOGOS_LIGAS = RAIZ / "web" / "img" / "ligas"
# Competições sem símbolo na ESPN: um ficheiro do Wikimedia Commons (livre)
SIMBOLOS_COMMONS = {"tp": "Coppa del Portogallo.svg"}   # o troféu da Taça de Portugal
# País no Wikidata dos clubes de cada taça: os emblemas que a ESPN não tem procuram-se lá (emblemas_wikidata.py)
PAIS_WIKIDATA = {"tp": "Q45", "fa": "Q145", "efl": "Q145", "cdr": "Q29", "dfb": "Q183", "cit": "Q38", "cdf": "Q142"}

# id da equipa na ESPN -> sigla. As que já existiam no mock.json foram ligadas pelo nome;
# as restantes (NOVAS) ganharam uma sigla nova. Atenção: as siglas da ESPN não servem
# (para a ESPN "SLB" é o Slovan Bratislava e "MUN" o Bayern).
EQUIPAS = {
    # Portugal
    "437": "FCP", "1929": "SLB", "2250": "SCP", "2994": "SCB", "5309": "VSC", "12698": "FAM",
    "3699": "GIL", "12216": "EST", "21581": "CPI", "3696": "MOR", "15784": "ARO", "3822": "RAV",
    "12215": "SCL", "3472": "NAC", "21610": "AMD", "21607": "ACV", "21613": "ALV", "552": "MTO",
    "21615": "SCU",
    # Seleções seguidas (as outras ficam com a sigla da ESPN)
    "482": "PRT", "205": "BRA", "202": "ARG",   # PRT: "POR" já é dos Portland Trail Blazers (NBA)
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


# Nomes da ESPN sem acentos ou compridos (clubes das taças), pelo nome da ESPN
NOMES_PT = {
    "Fatima": "Fátima", "Leca": "Leça", "Leixoes": "Leixões", "Uniao Leiria": "União de Leiria",
    "Lusitania": "Lusitânia", "Oliveira Hospital": "Oliveira do Hospital", "Vitoria Sernache": "Vitória de Sernache",
    "Vitoria Setubal": "Vitória de Setúbal", "Uniao da Serra": "União da Serra", "União Santarém": "União de Santarém",
    "Os Marialvas": "Os Marialvas", "AD Fazendense": "Fazendense", "ACDR Lamelas": "Lamelas", "SC Farense": "Farense",
    "GD Chaves": "Chaves", "FC Penafiel": "Penafiel", "Felgueiras 1932": "Felgueiras", "AD Marco 09": "Marco 09",
    "Maritimo": "Marítimo", "FC Famalicao": "Famalicão", "Vitória de Guimaraes": "Vitória de Guimarães",
}

# Nome em português das seleções (pelo nome da ESPN). As que não estiverem aqui ficam com o nome da ESPN.
NOMES_SELECOES = {
    "Portugal": "Portugal", "Spain": "Espanha", "France": "França", "Germany": "Alemanha", "England": "Inglaterra",
    "Italy": "Itália", "Netherlands": "Países Baixos", "Belgium": "Bélgica", "Croatia": "Croácia",
    "Denmark": "Dinamarca", "Norway": "Noruega", "Wales": "País de Gales", "Scotland": "Escócia",
    "Northern Ireland": "Irlanda do Norte", "Republic of Ireland": "Irlanda", "Switzerland": "Suíça",
    "Austria": "Áustria", "Czechia": "Chéquia", "Greece": "Grécia", "Serbia": "Sérvia", "Türkiye": "Turquia",
    "Poland": "Polónia", "Sweden": "Suécia", "Hungary": "Hungria", "Ukraine": "Ucrânia", "Romania": "Roménia",
    "Slovakia": "Eslováquia", "Slovenia": "Eslovénia", "Bosnia-Herzegovina": "Bósnia", "North Macedonia": "Macedónia do Norte",
    "Georgia": "Geórgia", "Albania": "Albânia", "Finland": "Finlândia", "Iceland": "Islândia", "Israel": "Israel",
    "Kosovo": "Kosovo", "Montenegro": "Montenegro", "Bulgaria": "Bulgária", "Belarus": "Bielorrússia",
    "Armenia": "Arménia", "Azerbaijan": "Azerbaijão", "Kazakhstan": "Cazaquistão", "Cyprus": "Chipre",
    "Estonia": "Estónia", "Latvia": "Letónia", "Lithuania": "Lituânia", "Luxembourg": "Luxemburgo",
    "Moldova": "Moldávia", "Malta": "Malta", "Faroe Islands": "Ilhas Faroé", "Andorra": "Andorra",
    "San Marino": "São Marino", "Liechtenstein": "Liechtenstein", "Gibraltar": "Gibraltar", "Russia": "Rússia",
    "Brazil": "Brasil", "Argentina": "Argentina", "Uruguay": "Uruguai", "Colombia": "Colômbia", "Chile": "Chile",
    "Paraguay": "Paraguai", "Peru": "Peru", "Ecuador": "Equador", "Bolivia": "Bolívia", "Venezuela": "Venezuela",
    "United States": "Estados Unidos", "USA": "Estados Unidos", "Mexico": "México", "Canada": "Canadá",
    "Japan": "Japão", "South Korea": "Coreia do Sul", "Morocco": "Marrocos", "Senegal": "Senegal",
    "Saudi Arabia": "Arábia Saudita", "Australia": "Austrália", "Egypt": "Egito", "Nigeria": "Nigéria",
    "Ivory Coast": "Costa do Marfim", "Cameroon": "Camarões", "Algeria": "Argélia", "Tunisia": "Tunísia",
    "Ghana": "Gana", "Iran": "Irão", "Qatar": "Catar", "New Zealand": "Nova Zelândia", "Cape Verde": "Cabo Verde",
    "Angola": "Angola", "Mozambique": "Moçambique", "Guinea-Bissau": "Guiné-Bissau", "Costa Rica": "Costa Rica",
    "Panama": "Panamá", "Jamaica": "Jamaica", "Haiti": "Haiti", "Uzbekistan": "Usbequistão", "Jordan": "Jordânia",
    "South Africa": "África do Sul", "DR Congo": "RD Congo", "Curacao": "Curaçau", "Curaçao": "Curaçau", "Iraq": "Iraque",
}


class Equipas:
    """Converte ids da ESPN em siglas e acrescenta a "teams" as equipas que faltam."""

    def __init__(self, teams, baixar=True):
        self.teams, self.baixar = teams, baixar
        self.novas, self.desconhecidas, self.sem_emblema = [], set(), []
        self.tranca = threading.RLock()   # as ligas correm em paralelo e partilham "teams"
        self.pedidos = set()              # emblemas já pedidos nesta atualização (uma vez por sigla)
        self.ids = {}                     # sigla -> id da ESPN (para o mapa do Wikidata)
        self.wikidata = set()             # siglas já procuradas no Wikidata nesta atualização

    def sigla(self, t, avisar=True):
        """avisar=False nas taças e nas seleções: lá aparecem muitas equipas novas (clubes amadores, seleções)."""
        with self.tranca:
            code = self._sigla(t, avisar)
            self.ids[code] = t["id"]
            baixar = self.baixar and code not in self.pedidos and not tem_emblema(code)
            self.pedidos.add(code)
        if baixar:   # fora da tranca: as outras competições não ficam à espera dos emblemas
            self.emblema(code, t)
        return code

    def _sigla(self, t, avisar):
        code = EQUIPAS.get(t["id"])
        if code is None:
            code = "".join(c for c in t.get("abbreviation", "") if c.isalpha()).upper()[:4] or f"E{t['id']}"
            if code in RESERVADOS:   # o Windows não deixa criar AUX.png, CON.png...
                code += "X"
            while code in self.teams and self.teams[code].get("_espn") != t["id"]:
                code += "X"
            if avisar and t["id"] not in self.desconhecidas:
                self.desconhecidas.add(t["id"])
                print(f"Aviso: equipa nova '{t.get('displayName')}' (id {t['id']}) ficou com a sigla {code}. "
                      f"Acrescenta-a a EQUIPAS em {Path(__file__).name}.")
        if code not in self.teams:
            c1, c2 = t.get("color"), t.get("alternateColor")
            self.teams[code] = {
                "name": NOVAS.get(code) or NOMES_PT.get(t.get("displayName")) or NOMES_SELECOES.get(t.get("displayName"))
                        or t.get("shortDisplayName") or t.get("displayName") or code,
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
        if NOMES_PT.get(t.get("displayName")) and code not in NOVAS and self.teams[code]["name"] != NOMES_PT[t["displayName"]]:
            self.teams[code] = {**self.teams[code], "name": NOMES_PT[t["displayName"]]}   # corrige os que já existiam
        if t.get("displayName") and self.teams[code].get("espnName") != t["displayName"]:
            # nome completo na ESPN (ex.: "VfB Stuttgart" para a Estugarda): serve para confirmar o clube das fotos
            self.teams[code] = {**self.teams[code], "espnName": t["displayName"]}
        return code

    def emblema(self, code, t):
        """Descarrega o emblema da ESPN (as seleções têm a bandeira noutro sítio: vem em t["logo"])."""
        logo = t.get("logo") or ""
        if logo.startswith("https://a.espncdn.com/"):
            url = f"https://a.espncdn.com/combiner/i?img={logo.removeprefix('https://a.espncdn.com')}&h=200&w=200"
        elif "logo" in t:   # a ESPN diz que não há emblema (clubes amadores): fica o círculo com a sigla
            with self.tranca:
                self.sem_emblema.append(code)
            return
        else:
            url = URL_EMBLEMA.format(id=t["id"])
        ok = baixar_emblema(code, url)
        with self.tranca:
            if ok:
                print(f"Emblema novo: {code}.png ({self.teams[code]['name']})")
            else:
                self.sem_emblema.append(code)


    def emblemas_wikidata(self, codes, pais):
        """Os emblemas que faltam (a ESPN não os tem), procurados no Wikidata. Só os que faltam, uma vez."""
        if not self.baixar or not pais:
            return
        for code in sorted(codes):
            with self.tranca:
                if code in self.wikidata or tem_emblema(code):
                    continue
                self.wikidata.add(code)
                t = self.teams.get(code, {})
                nomes = [n for n in (t.get("name"), t.get("espnName")) if n]
                chave = f"espn:{self.ids.get(code, code)}"
            if nomes and emblemas_wikidata.emblema(chave, nomes, pais, EMBLEMAS / f"{code}.png"):
                with self.tranca:
                    print(f"Emblema novo (Wikidata): {code}.png ({nomes[0]})")
                    if code in self.sem_emblema:
                        self.sem_emblema.remove(code)


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
        if atletas[0].get("id"):
            item["pid"] = atletas[0]["id"]   # id do atleta na ESPN (a cara do marcador no Ao vivo)
        ev.append(item)
    return ev


def resultado(e, equipas, avisar=True):
    comp = e["competitions"][0]
    casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    lado = {casa["team"]["id"]: "h", fora["team"]["id"]: "a"}
    return {"home": equipas.sigla(casa["team"], avisar), "away": equipas.sigla(fora["team"], avisar),
            "hs": int(casa["score"]), "as": int(fora["score"]), "ev": eventos_do_jogo(comp, lado),
            "id": e["id"],   # id do jogo na ESPN (o atualizar_onze.py vai buscar as estatísticas por aqui)
            "iso": quando(e).astimezone().isoformat(timespec="minutes")}   # quando foi (ex.: o último jogo no Início)


def jogo_da_jornada(e, equipas, avisar=True):
    """Um jogo da jornada dos resultados: acabado (resultado), a decorrer (resultado atual), adiado ou por jogar."""
    tipo = e["status"]["type"]
    if estado(e) == "fim":
        return resultado(e, equipas, avisar)
    if estado(e) == "adiado":
        return {**proximo(e, equipas, avisar), "status": "adiado", "id": e["id"]}
    if tipo.get("state") == "in":   # a decorrer: resultado e minuto da ESPN
        r = resultado(e, equipas, avisar)
        return {**r, "live": True, "clock": tipo.get("shortDetail") or e["status"].get("displayClock") or ""}
    return {**proximo(e, equipas, avisar), "id": e["id"]}


def proximo(e, equipas, avisar=True):
    comp = e["competitions"][0]
    casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    local = quando(e).astimezone()    # hora deste PC
    # "iso": o instante exato (para contagens decrescentes, ex.: o ecrã Início do MonitorHub)
    return {"home": equipas.sigla(casa["team"], avisar), "away": equipas.sigla(fora["team"], avisar),
            "when": f"{DIAS[local.weekday()]} {local:%H:%M}", "date": f"{local:%d/%m}",
            "iso": local.isoformat(timespec="minutes")}


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
    nova["tipo"], nova["janela"] = "liga", janela(eventos, agora)
    return nova


def iso(d):
    return d.isoformat(timespec="minutes") if d else None


def janela(eventos, agora):
    """Datas que decidem se a competição entra na rotação (ver competicaoAtiva em web/js/cenas/futebol.js):
    o último jogo acabado ou a decorrer e o próximo por jogar. O dashboard compara-as com a hora a que mostra."""
    feitos = [quando(e) for e in eventos if estado(e) == "fim" or e["status"]["type"].get("state") == "in"]
    por_jogar = [quando(e) for e in eventos if estado(e) == "por jogar" and quando(e) > agora]
    return {"ultimo": iso(max(feitos, default=None)), "proximo": iso(min(por_jogar, default=None))}


# ---------- Taças e seleções ----------

# Nome das fases (season.slug de cada jogo na ESPN)
FASES = {
    "round-of-16": "Oitavos de final", "quarterfinals": "Quartos de final", "semifinals": "Meias-finais",
    "final": "Final", "3rd-place-match": "Jogo do 3.º lugar", "round-of-32": "16 avos de final",
    "league-phase": "Fase de liga", "group-stage": "Fase de grupos", "relegation-playoffs": "Play-off de descida",
    "preliminary-round": "Eliminatória preliminar", "qualifying-round": "Pré-eliminatória",
    "playoff-semifinals": "Play-off · meias-finais", "playoff-finals": "Play-off · final",
    "knockout-round-playoffs": "Play-off",
}
ORDINAIS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8}
FASES_GRUPOS = {"league-phase", "group-stage"}   # aqui conta-se a jornada; nas outras, a mão (1.ª / 2.ª)
FASES_FINAIS = {"round-of-16", "quarterfinals", "semifinals", "final", "3rd-place-match"}
INTERVALO_AMIGAVEIS = timedelta(days=4)   # amigáveis: uma janela de jogos acaba com 4 dias sem jogos


def fase(e):
    return (e.get("season") or {}).get("slug") or ""


def numero_eliminatoria(slug):
    """"3rd-round" / "third-round" -> 3; None se não for uma eliminatória numerada."""
    m = re.fullmatch(r"(\d+)(?:st|nd|rd|th)-round", slug) or re.fullmatch(r"([a-z]+)-round", slug)
    if not m:
        return None
    return int(m.group(1)) if m.group(1).isdigit() else ORDINAIS.get(m.group(1))


def nome_fase(slug, confrontos):
    """Nome em português. confrontos = quantos tem a fase (8 numa eliminatória numerada = oitavos)."""
    if slug in FASES:
        return FASES[slug]
    n = numero_eliminatoria(slug)
    if n is not None:
        return "Oitavos de final" if confrontos == 8 else f"{n}.ª eliminatória"
    return "Final" if confrontos == 1 else ""


def par(e):
    return frozenset(c["team"]["id"] for c in e["competitions"][0]["competitors"])


def jogo_valido(e):
    """Fora: jogos sem as duas equipas definidas (ex.: "Vencedor do jogo 3")."""
    comp = e["competitions"][0]["competitors"]
    return len(comp) == 2 and all(c.get("team", {}).get("id") and "TBD" not in (c["team"].get("displayName") or "")
                                  for c in comp)


def com_nota(e, jogo):
    """Prolongamento e penáltis: "a.p." / "g.p. 6-5" (o desempate não entra no resultado)."""
    nome = e["status"]["type"]["name"]
    if nome == "STATUS_FINAL_PEN":
        comp = e["competitions"][0]
        casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        if casa.get("shootoutScore") is not None:
            jogo["nota"] = f"g.p. {casa['shootoutScore']}-{fora.get('shootoutScore')}"
    elif nome == "STATUS_FINAL_AET":
        jogo["nota"] = "a.p."
    return jogo


def confrontos_por_fase(eventos):
    conf = {}
    for e in eventos:
        conf.setdefault(fase(e), set()).add(par(e))
    return conf


def rondas(chave, eventos):
    """Divide os jogos em rondas, pela ordem do calendário. Devolve [(rótulo, [jogos])].

    Ronda = fase + jornada (fase de grupos: o n.º do jogo de cada equipa nessa fase) ou fase + mão
    (eliminatórias a duas mãos). Nos amigáveis não há fases: cada janela de jogos é uma ronda.
    """
    confrontos = confrontos_por_fase(eventos)
    jogos_do_par = Counter((fase(e), par(e)) for e in eventos)
    vezes, chaves = Counter(), {}
    anterior, n_janela = None, 0
    for e in eventos:
        f = fase(e)
        if chave == "amg":
            if anterior and quando(e) - anterior > INTERVALO_AMIGAVEIS:
                n_janela += 1
            anterior = quando(e)
            chaves[e["id"]] = ("", n_janela)
        elif f in FASES_GRUPOS:
            ids = [c["team"]["id"] for c in e["competitions"][0]["competitors"]]
            for i in ids:
                vezes[(f, i)] += 1
            chaves[e["id"]] = (f, max(vezes[(f, i)] for i in ids))
        else:
            vezes[(f, par(e))] += 1
            chaves[e["id"]] = (f, vezes[(f, par(e))])
    grupos = {}
    for e in eventos:
        grupos.setdefault(chaves[e["id"]], []).append(e)
    lista = []
    for (f, n), g in grupos.items():   # dict: pela ordem do primeiro jogo de cada ronda
        nome = nome_fase(f, len(confrontos.get(f, ())))
        if chave == "amg":
            rotulo = "Amigáveis"
        elif f in FASES_GRUPOS:
            rotulo = f"{nome} · Jornada {n}"
        elif n > 1 or any(jogos_do_par[(f, par(e))] > 1 for e in g):
            rotulo = f"{nome} · {n}.ª mão"
        else:
            rotulo = nome
        lista.append((rotulo, g))
    return lista


# Taças estrangeiras: a fase que equivale aos oitavos, quando a ESPN não lhe chama "round-of-16"
OITAVOS = {"fa": "fifth-round", "efl": "fourth-round"}


def fase_conta(chave, eventos):
    """Taças estrangeiras: só a partir dos oitavos. Vai pelo nome da fase e não pelo número de jogos, porque
    os três meses que se buscam podem apanhar só o fim de uma eliminatória maior."""
    if chave not in competicoes.DESDE_OITAVOS:
        return eventos
    return [e for e in eventos if fase(e) in FASES_FINAIS or fase(e) == OITAVOS.get(chave)]


def grupos_da_classificacao(liga):
    return (api(f"v2/sports/soccer/{liga}/standings").get("children")) or []


def grupos_selecoes(grupos, equipas, filtro, ids_nos_jogos):
    """Tabelas dos grupos (Liga das Nações, qualificações, fase final), se a ESPN as tiver.

    Só os grupos com alguma seleção dos jogos deste período (a ESPN pode ainda ter a tabela da edição anterior).
    Liga das Nações: só a Liga A (grupos "Group A1".."A4"), mais o grupo de Portugal se estiver noutra liga.
    """
    tabelas = []
    for g in grupos:
        entradas = list((g.get("standings") or {}).get("entries") or [])
        ids = {e["team"]["id"] for e in entradas}
        if not ids & ids_nos_jogos:
            continue
        liga_a = (g.get("name") or "").startswith("Group A")
        if not (filtro["equipas"] & ids or filtro["todos"] and (liga_a or not filtro["ligaA"])):
            continue

        def stat(e, nome):
            return next((s.get("value") for s in e["stats"] if s["name"] == nome), 0) or 0

        entradas.sort(key=lambda e: stat(e, "rank") or 999)
        tabelas.append((not filtro["equipas"] & ids, {   # Portugal (e quem mais se segue) primeiro
            "name": (g.get("name") or "").replace("Group", "Grupo"),
            "table": [{"team": equipas.sigla(e["team"], avisar=False), "j": int(stat(e, "gamesPlayed")),
                       "dg": int(stat(e, "pointDifferential")), "pts": int(stat(e, "points"))} for e in entradas],
        }))
    return [t for _, t in sorted(tabelas, key=lambda x: x[0])]


def montar_taca(chave, nome, liga, tipo, filtro, antigo, equipas, agora):
    """Taças e seleções: os resultados da ronda atual (a mais recente com um jogo acabado; aparece logo que acaba
    o primeiro jogo) e os jogos da ronda seguinte, cada um com o nome da fase ("Oitavos de final",
    "3.ª eliminatória", "Fase de liga · Jornada 4")."""
    nova = {"name": (antigo or {}).get("name") or nome, "tipo": tipo}
    eventos = [e for e in jogos(liga, agora) if jogo_valido(e)]
    grupos = grupos_da_classificacao(liga) if tipo == "selecoes" and chave != "amg" else []
    if filtro:   # seleções: só os jogos que se seguem
        liga_a = {e["team"]["id"] for g in grupos if (g.get("name") or "").startswith("Group A")
                  for e in (g.get("standings") or {}).get("entries") or []}
        eventos = [e for e in eventos if par(e) & filtro["equipas"]
                   or filtro["todos"] and (not filtro["ligaA"] or par(e) & liga_a)]
    eventos = fase_conta(chave, eventos)
    nova["janela"] = janela(eventos, agora)
    lista = rondas(chave, [e for e in eventos if estado(e) != "adiado"])
    feitos = lambda g: [e for e in g if estado(e) == "fim"]
    atual = next((i for i in range(len(lista) - 1, -1, -1) if feitos(lista[i][1])), None)
    if atual is None:
        nova["fase"], nova["results"], nova["partial"] = None, [], None
    else:
        rotulo, g = lista[atual]
        ini, fim = quando(g[0]), quando(g[-1])
        adiados = [e for e in eventos if estado(e) == "adiado" and ini <= quando(e) <= fim]
        ronda = sorted(g + adiados, key=lambda e: e["date"])
        nova["fase"] = rotulo
        nova["results"] = [com_nota(e, jogo_da_jornada(e, equipas, avisar=False)) for e in ronda]
        n = sum(1 for e in ronda if estado(e) == "fim")
        nova["partial"] = {"done": n, "total": len(ronda)} if n < len(ronda) else None
    # Próximos: os jogos por jogar da ronda seguinte que tenha jogos marcados
    por_jogar = lambda g: [e for e in g if estado(e) == "por jogar" and quando(e) > agora]
    seguinte = next(((r, por_jogar(g)) for r, g in lista[(atual + 1 if atual is not None else 0):] if por_jogar(g)),
                    (None, []))
    nova["proxFase"], nova["next"] = seguinte[0], [proximo(e, equipas, avisar=False) for e in seguinte[1]]
    if grupos:
        ids = {i for e in eventos for i in par(e)}
        nova["grupos"] = grupos_selecoes(grupos, equipas, filtro, ids)
    # Clubes sem emblema na ESPN (os amadores das taças): procura-se no Wikidata
    equipas.emblemas_wikidata({m[k] for m in nova["results"] + nova["next"] for k in ("home", "away")},
                              PAIS_WIKIDATA.get(chave))
    return nova


def logo_competicao(chave, liga):
    """Descarrega o símbolo da competição da ESPN (versão para fundo escuro) se ainda não houver nenhum."""
    if any(LOGOS_LIGAS.glob(f"{chave}.*")):
        return
    try:
        logos = (api(f"site/v2/sports/soccer/{liga}/scoreboard").get("leagues") or [{}])[0].get("logos") or []
        escuro = next((l for l in logos if "dark" in l.get("rel", [])), logos[0] if logos else None)
        url = escuro["href"] if escuro else None
        if not url and chave in SIMBOLOS_COMMONS:   # a ESPN não o tem: o do Commons
            url = emblemas_wikidata.COMMONS.format(ficheiro=SIMBOLOS_COMMONS[chave].replace(" ", "_"))
        if url:
            png = pedir(url, ua=emblemas_wikidata.USER_AGENT)
            if png.startswith(b"\x89PNG"):
                LOGOS_LIGAS.mkdir(parents=True, exist_ok=True)
                (LOGOS_LIGAS / f"{chave}.png").write_bytes(png)
    except Exception as e:   # sem símbolo: o título fica só com o nome
        print(f"Aviso: sem símbolo para {chave} ({e!r}).")


def montar(chave, nome, liga, tipo, filtro, antigo, equipas, agora, baixar):
    if baixar:
        logo_competicao(chave, liga)
    if tipo == "liga":
        nova = montar_liga(chave, antigo, equipas, agora)
        nova.setdefault("name", nome)
        return nova
    return montar_taca(chave, nome, liga, tipo, filtro, antigo, equipas, agora)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    ap.add_argument("--competicoes", help="só estas competições, separadas por vírgulas (ex.: pt,en); as outras ficam como estão")
    args = ap.parse_args()

    lista = competicoes.a_buscar()   # as escolhidas em data/competicoes.json, pela ordem da rotação
    parcial = bool(args.competicoes)
    if parcial:
        pedidas = [c.strip() for c in args.competicoes.split(",") if c.strip()]
        validas = [c[0] for c in lista]
        erradas = [c for c in pedidas if c not in validas]
        if erradas:   # desconhecida ou desligada em /definicoes (a Taça da Liga é do atualizar_taca_liga.py)
            sys.exit(f"Competições que não se buscam: {', '.join(erradas)}. Ligadas: {', '.join(validas)}.")
        lista = [c for c in lista if c[0] in pedidas]

    dados = ler_dados()
    teams = dict(dados["teams"])   # cópia: se falhar a meio, os dados originais ficam intactos
    equipas = Equipas(teams, baixar=not args.mostrar)
    agora = datetime.now(timezone.utc)
    antigo = dados.get("football") or {}
    futebol, falhas = {}, []
    # As competições são independentes: correm em paralelo, cada uma com os seus pedidos à ESPN.
    # Uma que falhe fica com os dados anteriores (se os tiver); as desligadas saem do live.json.
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros = {c[0]: ex.submit(montar, *c, antigo.get(c[0]), equipas, agora, not args.mostrar) for c in lista}
    nomes, tipos = {c[0]: c[1] for c in lista}, {c[0]: c[3] for c in lista}
    feitas = []   # as que vieram da ESPN agora (ficam com a hora de agora em _atualizado)
    for chave, f in futuros.items():
        try:
            futebol[chave] = f.result()
            feitas.append(chave)
            L = futebol[chave]
            # Uma liga tem sempre classificação; uma taça ou uma prova de seleções fica vazia entre eliminatórias
            registar_fonte(f"ESPN {nomes[chave]}", itens=sum(len(L.get(k) or []) for k in ("table", "results", "next")),
                           esperado=tipos[chave] == "liga")
        except Exception as e:   # sem rede, API em baixo, formato mudou...
            registar_fonte(f"ESPN {nomes[chave]}", erro=e)
            falhas.append(f"{chave} ({e})")
            if antigo.get(chave):
                futebol[chave] = antigo[chave]
    if parcial:   # só as pedidas mudam; as outras (e a ordem) ficam como estavam
        futebol = {**antigo, **futebol}
    elif competicoes.ler().get("tl") and antigo.get("tl"):   # a Taça da Liga é do atualizar_taca_liga.py: fica
        futebol = {**{k: v for k, v in futebol.items()}, "tl": antigo["tl"]}
        ordem = [k for k in futebol if k != "tl"]
        i = ordem.index("tp") + 1 if "tp" in ordem else len(ordem)
        futebol = {k: futebol[k] for k in ordem[:i] + ["tl"] + ordem[i:]}
    if falhas and len(falhas) == len(lista):
        sys.exit(f"Não foi possível atualizar o futebol ({'; '.join(falhas)}). O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(futebol, ensure_ascii=False, indent=2))
        return
    dados["football"], dados["teams"] = futebol, teams
    at = dados.setdefault("_atualizado", {})
    for k in [k for k in at if k.startswith("futebol:") and k[8:] not in futebol]:
        del at[k]   # de uma competição que saiu
    gravar(dados, *marcas(dados, "futebol", feitas, parcial))
    if equipas.novas:
        print(f"Equipas acrescentadas a teams: {', '.join(equipas.novas)}")
    if equipas.sem_emblema:   # nas taças há muitos clubes amadores sem emblema na ESPN: ficam com o círculo
        lista = equipas.sem_emblema
        print(f"Sem emblema: {', '.join(lista[:8])}" + (f" e mais {len(lista) - 8}" if len(lista) > 8 else ""))
    for chave, L in futebol.items():
        if parcial and chave not in feitas:
            continue
        if L.get("tipo") == "liga":
            print(f"{L['name']}: {L['round']}, {len(L['table'])} equipas, {len(L['results'])} resultados, "
                  f"{len(L['next'])} próximos jogos, {len(L['scorers'])} marcadores")
        else:
            print(f"{L['name']}: {L.get('fase') or 'sem resultados'} ({len(L['results'])} jogos), "
                  f"{L.get('proxFase') or 'sem próximos'} ({len(L['next'])} jogos)"
                  + (f", {len(L['grupos'])} grupos" if L.get("grupos") else ""))
    if falhas:
        print(f"Falharam (ficaram com os dados anteriores): {'; '.join(falhas)}")
    print(f"Futebol atualizado em {LIVE}.")


if __name__ == "__main__":
    main()
