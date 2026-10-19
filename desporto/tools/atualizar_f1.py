"""Vai buscar os dados reais da Fórmula 1 e grava-os em data/live.json (secção "f1").

Uso:
    python tools/atualizar_f1.py            # atualiza data/live.json
    python tools/atualizar_f1.py --mostrar  # só mostra o que gravaria

Fonte: API Jolpica (https://github.com/jolpica/jolpica-f1), a continuação da antiga Ergast. Gratuita e sem chave.
O live.json tem a mesma estrutura do mock.json: na primeira vez é criado a partir do mock, e cada
atualizador (por agora só este) substitui a sua parte. O dashboard lê o live.json e, se não existir, o mock.

Também prepara os ecrãs da categoria F1 (?cat=f1), todos com dados de corridas já feitas (nada ao vivo):
- subidas/descidas no campeonato desde a corrida anterior;
- o fim de semana do próximo GP (todas as sessões) e os vencedores anteriores nesse circuito;
- o resumo da última corrida: maiores subidas, desistências e a paragem mais rápida;
- o duelo entre colegas de cada equipa (qualificação e corrida) e a evolução dos pontos do top 5;
- a estratégia de pneus da última corrida, da API OpenF1 (histórico, sem chave).
Cada uma destas partes é independente: se falhar, fica a null e esse ecrã sai da rotação (nunca se inventa).

O desenho da pista vem de data/circuitos/f1-circuits.geojson (todos os circuitos de
https://github.com/bacinger/f1-circuits, licença ODbL). Se o ficheiro não existir, é descarregado uma vez.
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import LIVE, RAIZ, gravar, ler_dados, pedir  # noqa: E402  (pausa de 0,5 s: a Jolpica pede ~4 por segundo no máximo)
from gerar_pista import gerar_de_pontos  # noqa: E402

CIRCUITOS = RAIZ / "data" / "circuitos" / "f1-circuits.geojson"
URL_CIRCUITOS = "https://raw.githubusercontent.com/bacinger/f1-circuits/master/f1-circuits.geojson"
API = "https://api.jolpi.ca/ergast/f1"
OPENF1 = "https://api.openf1.org/v1"

# constructorId da API -> sigla usada nos emblemas (web/img/equipas/<sigla>.png) e em "teams" no mock
EQUIPAS = {
    "mclaren": "MCL", "ferrari": "FER", "red_bull": "RBR", "mercedes": "MER", "aston_martin": "AMR",
    "alpine": "ALP", "haas": "HAA", "rb": "VRB", "williams": "WIL", "audi": "AUD", "sauber": "AUD",
    "cadillac": "CAD",
}

# circuitId da API -> id do traçado no f1-circuits.geojson. Se faltar, tenta pela localidade.
PISTAS = {
    "albert_park": "au-1953", "bahrain": "bh-2002", "shanghai": "cn-2004", "catalunya": "es-1991",
    "monaco": "mc-1929", "villeneuve": "ca-1978", "red_bull_ring": "at-1969", "silverstone": "gb-1948",
    "hungaroring": "hu-1986", "spa": "be-1925", "monza": "it-1922", "marina_bay": "sg-2008",
    "suzuka": "jp-1962", "americas": "us-2012", "rodriguez": "mx-1962", "interlagos": "br-1940",
    "yas_marina": "ae-2009", "imola": "it-1953", "zandvoort": "nl-1948", "jeddah": "sa-2021",
    "miami": "us-2022", "losail": "qa-2004", "baku": "az-2016", "vegas": "us-2023", "madring": "es-2026",
}

# Número de curvas (a API não tem este dado). Se faltar um circuito, aparece "—".
CURVAS = {
    "albert_park": 14, "bahrain": 15, "shanghai": 16, "catalunya": 14, "monaco": 19, "villeneuve": 14,
    "red_bull_ring": 10, "silverstone": 18, "hungaroring": 14, "spa": 19, "monza": 11, "marina_bay": 19,
    "suzuka": 18, "americas": 20, "rodriguez": 17, "interlagos": 15, "yas_marina": 16, "imola": 19,
    "zandvoort": 14, "jeddah": 27, "miami": 19, "losail": 16, "baku": 20, "vegas": 17, "madring": 22,
}

PAISES = {
    "Australia": "Austrália", "Bahrain": "Bahrein", "China": "China", "Japan": "Japão",
    "Saudi Arabia": "Arábia Saudita", "USA": "Estados Unidos", "United States": "Estados Unidos",
    "Italy": "Itália", "Monaco": "Mónaco", "Spain": "Espanha", "Canada": "Canadá", "Austria": "Áustria",
    "UK": "Reino Unido", "United Kingdom": "Reino Unido", "Belgium": "Bélgica", "Hungary": "Hungria",
    "Netherlands": "Países Baixos", "Azerbaijan": "Azerbaijão", "Singapore": "Singapura",
    "Mexico": "México", "Brazil": "Brasil", "Qatar": "Catar", "UAE": "Emirados Árabes Unidos",
}

# "Singapore Grand Prix" -> "GP de Singapura"
GPS = {
    "Australian": "da Austrália", "Chinese": "da China", "Japanese": "do Japão", "Bahrain": "do Bahrein",
    "Saudi Arabian": "da Arábia Saudita", "Miami": "de Miami", "Emilia Romagna": "da Emília-Romanha",
    "Monaco": "do Mónaco", "Spanish": "de Espanha", "Barcelona-Catalunya": "de Barcelona-Catalunha",
    "Canadian": "do Canadá", "Austrian": "da Áustria", "British": "da Grã-Bretanha", "Belgian": "da Bélgica",
    "Hungarian": "da Hungria", "Dutch": "dos Países Baixos", "Italian": "de Itália",
    "Azerbaijan": "do Azerbaijão", "Singapore": "de Singapura", "United States": "dos Estados Unidos",
    "Mexico City": "da Cidade do México", "São Paulo": "de São Paulo", "Las Vegas": "de Las Vegas",
    "Qatar": "do Catar", "Abu Dhabi": "de Abu Dhabi",
}


def api(caminho):
    return json.loads(pedir(f"{API}/{caminho}"))["MRData"]


def nome_gp(race_name):
    base = race_name.removesuffix(" Grand Prix")
    return f"GP {GPS[base]}" if base in GPS else f"GP {base}"


def sigla(constructor_id):
    if constructor_id not in EQUIPAS:
        print(f"Aviso: equipa nova '{constructor_id}'. Acrescenta-a a EQUIPAS em {Path(__file__).name}.")
    return EQUIPAS.get(constructor_id, constructor_id[:3].upper())


def pontos(valor):
    p = float(valor)
    return int(p) if p.is_integer() else p


def instante(corrida):
    """Data/hora da corrida em ISO (UTC). Sem hora definida, assume meio-dia."""
    return f"{corrida['date']}T{corrida.get('time', '12:00:00Z')}"


def classificacoes():
    pil = api("current/driverStandings.json")["StandingsTable"]["StandingsLists"]
    con = api("current/constructorStandings.json")["StandingsTable"]["StandingsLists"]
    pilotos = [{
        "name": f"{d['Driver']['givenName']} {d['Driver']['familyName']}",
        "team": sigla(d["Constructors"][-1]["constructorId"]),   # a última equipa da época
        "pts": pontos(d["points"]),
    } for d in (pil[0]["DriverStandings"] if pil else [])]
    construtores = [{"team": sigla(c["Constructor"]["constructorId"]), "pts": pontos(c["points"])}
                    for c in (con[0]["ConstructorStandings"] if con else [])]
    return pilotos, construtores


def calendario(epoca):
    return api(f"{epoca}.json?limit=100")["RaceTable"]["Races"]


def tracados():
    if not CIRCUITOS.exists():
        print("A descarregar os traçados dos circuitos (só da primeira vez)...")
        CIRCUITOS.write_bytes(pedir(URL_CIRCUITOS))
    return json.loads(CIRCUITOS.read_text(encoding="utf-8"))["features"]


def tracado(circuito, features):
    """Procura o traçado do circuito: primeiro pelo id conhecido, depois pela localidade."""
    alvo = PISTAS.get(circuito["circuitId"])
    local = circuito["Location"]["locality"].lower()
    for f in features:
        p = f["properties"]
        if p["id"] == alvo or (not alvo and p["Location"].lower() == local):
            return f
    return None


def proxima_corrida(corrida, features):
    c = corrida["Circuit"]
    prox = {
        "name": nome_gp(corrida["raceName"]),
        "circuit": c["Location"]["locality"],
        "country": PAISES.get(c["Location"]["country"], c["Location"]["country"]),
        "date": instante(corrida),
        "laps": "—", "length": "—", "turns": CURVAS.get(c["circuitId"], "—"),
    }
    f = tracado(c, features)
    if f is None:
        print(f"Aviso: não há traçado para '{c['circuitId']}' ({c['circuitName']}). Fica sem desenho da pista.")
        prox["track"] = None
        return prox
    metros = f["properties"]["length"]
    prox["length"] = f"{metros / 1000:.2f} km".replace(".", ",")
    # Regra da F1: o menor número de voltas que passa os 305 km (o Mónaco é a exceção, ~260 km).
    prox["laps"] = 78 if c["circuitId"] == "monaco" else math.ceil(305_000 / metros)
    prox["track"] = gerar_de_pontos(f["geometry"]["coordinates"])
    return prox


def ultima_corrida(corrida):
    res = api(f"{corrida['season']}/{corrida['round']}/results.json")["RaceTable"]["Races"]
    if not res:
        return None
    resultados = res[0]["Results"]

    def tempo(r):
        if "Time" not in r:
            return r["status"]                       # ex.: "+1 Lap"
        t = r["Time"]["time"]
        if r["position"] == "1" or ":" in t:
            return t                                 # tempo total, ou "+1:02.345"
        return f"+{float(t.lstrip('+')):.1f}s"       # "+2.400" -> "+2.4s"

    podio = [{
        "pos": int(r["position"]),
        "name": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
        "team": sigla(r["Constructor"]["constructorId"]),
        "time": tempo(r),
    } for r in resultados[:3]]
    mais_rapida = next((r for r in resultados if r.get("FastestLap", {}).get("rank") == "1"), None)
    return {
        "name": nome_gp(corrida["raceName"]),
        "circuit": corrida["Circuit"]["Location"]["locality"],
        "podium": podio,
        "fastest": (f"Volta mais rápida: {mais_rapida['Driver']['familyName']}, {mais_rapida['FastestLap']['Time']['time']}"
                    if mais_rapida else ""),
    }


# ---------- Ecrãs da categoria F1 ----------

SESSOES = [("FirstPractice", "Treino livre 1"), ("SecondPractice", "Treino livre 2"), ("ThirdPractice", "Treino livre 3"),
           ("SprintQualifying", "Qualificação sprint"), ("Sprint", "Sprint"), ("Qualifying", "Qualificação")]


def todos(caminho, chave):
    """Junta as páginas de uma lista da Jolpica (máximo 100 por pedido)."""
    corridas, offset = {}, 0
    while True:
        d = api(f"{caminho}.json?limit=100&offset={offset}")
        for r in d["RaceTable"]["Races"]:   # uma corrida pode vir partida entre duas páginas
            corridas.setdefault(r["round"], {**r, chave: []})[chave].extend(r.get(chave, []))
        offset += 100
        if offset >= int(d["total"]):
            return [corridas[k] for k in sorted(corridas, key=int)]


def variacoes(pilotos, construtores, epoca, ronda):
    """Posição de cada piloto/equipa antes da última corrida (para as setas ▲▼)."""
    if ronda < 2:
        return
    pil = api(f"{epoca}/{ronda - 1}/driverStandings.json")["StandingsTable"]["StandingsLists"]
    con = api(f"{epoca}/{ronda - 1}/constructorStandings.json")["StandingsTable"]["StandingsLists"]
    antes_p = {f"{d['Driver']['givenName']} {d['Driver']['familyName']}": int(d["position"])
               for d in (pil[0]["DriverStandings"] if pil else [])}
    antes_c = {sigla(c["Constructor"]["constructorId"]): int(c["position"])
               for c in (con[0]["ConstructorStandings"] if con else [])}
    for i, p in enumerate(pilotos, 1):
        p["chg"] = antes_p[p["name"]] - i if p["name"] in antes_p else 0
    for i, c in enumerate(construtores, 1):
        c["chg"] = antes_c[c["team"]] - i if c["team"] in antes_c else 0


def fim_de_semana(corrida):
    """Todas as sessões do próximo GP (ISO, UTC: a cena mostra-as na hora de Lisboa) e os últimos vencedores ali."""
    sessoes = [{"name": nome, "date": instante(corrida[k])} for k, nome in SESSOES if k in corrida]
    sessoes.append({"name": "Corrida", "date": instante(corrida)})
    sessoes.sort(key=lambda x: x["date"])
    circuito = corrida["Circuit"]["circuitId"]
    total = int(api(f"circuits/{circuito}/results/1.json?limit=1")["total"])
    venc = api(f"circuits/{circuito}/results/1.json?limit=5&offset={max(0, total - 5)}")["RaceTable"]["Races"]
    vencedores = [{"year": int(r["season"]),
                   "name": f"{r['Results'][0]['Driver']['givenName']} {r['Results'][0]['Driver']['familyName']}",
                   "team": EQUIPAS.get(r["Results"][0]["Constructor"]["constructorId"]),
                   "teamName": r["Results"][0]["Constructor"]["name"]} for r in reversed(venc)]
    return {"name": nome_gp(corrida["raceName"]), "sessions": sessoes, "winners": vencedores}


def resumo_extra(corrida):
    """Maiores subidas (grelha -> final), desistências e a paragem mais rápida (tempo na via das boxes)."""
    res = api(f"{corrida['season']}/{corrida['round']}/results.json")["RaceTable"]["Races"][0]["Results"]
    nome = lambda r: f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
    classificados = [r for r in res if r["status"] == "Finished" or r["status"].startswith("+") or r["status"] == "Lapped"]
    subidas = sorted(({"name": nome(r), "team": sigla(r["Constructor"]["constructorId"]), "grid": int(r["grid"]),
                       "pos": int(r["position"]), "gain": int(r["grid"]) - int(r["position"])}
                      for r in classificados if int(r["grid"]) > 0), key=lambda x: -x["gain"])
    desistencias = [{"name": nome(r), "team": sigla(r["Constructor"]["constructorId"]), "status": r["status"],
                     "laps": int(r["laps"])} for r in res if r not in classificados]
    paragens = api(f"{corrida['season']}/{corrida['round']}/pitstops.json?limit=100")["RaceTable"]["Races"]
    rapida = None
    if paragens:
        pilotos = {r["Driver"]["driverId"]: r for r in res}
        validas = [x for x in paragens[0]["PitStops"] if x.get("duration", "").replace(".", "").isdigit()]
        if validas:
            x = min(validas, key=lambda x: float(x["duration"]))
            r = pilotos.get(x["driverId"])
            rapida = {"name": nome(r) if r else x["driverId"], "team": sigla(r["Constructor"]["constructorId"]) if r else None,
                      "time": x["duration"], "lap": int(x["lap"])}
    return {"gains": [x for x in subidas if x["gain"] > 0][:3], "dnfs": desistencias, "fastestPit": rapida}


def duelos_e_evolucao(epoca, construtores):
    """Duelo entre colegas (qualificação e corrida) e pontos acumulados ronda a ronda (top 5)."""
    corridas = todos(f"{epoca}/results", "Results")
    qualis = todos(f"{epoca}/qualifying", "QualifyingResults")
    sprints = {r["round"]: r for r in todos(f"{epoca}/sprint", "SprintResults")}
    nome = lambda d: f"{d['givenName']} {d['familyName']}"

    # Duelos: dentro de cada equipa, os dois pilotos com mais corridas por ela
    corridas_por = {}
    for r in corridas:
        for x in r["Results"]:
            corridas_por.setdefault(sigla(x["Constructor"]["constructorId"]), {}).setdefault(nome(x["Driver"]), 0)
            corridas_por[sigla(x["Constructor"]["constructorId"])][nome(x["Driver"])] += 1

    def contar(lista, chave, equipa, a, b):
        ga = gb = 0
        for r in lista:
            pos = {nome(x["Driver"]): int(x["position"]) for x in r[chave]
                   if sigla(x["Constructor"]["constructorId"]) == equipa}
            if a in pos and b in pos:
                ga += pos[a] < pos[b]
                gb += pos[b] < pos[a]
        return ga, gb

    pontos_pil = {}
    for r in corridas:
        for x in r["Results"]:
            pontos_pil[nome(x["Driver"])] = pontos_pil.get(nome(x["Driver"]), 0) + float(x["points"])
    for r in sprints.values():
        for x in r["SprintResults"]:
            pontos_pil[nome(x["Driver"])] = pontos_pil.get(nome(x["Driver"]), 0) + float(x["points"])

    duelos = []
    for c in construtores:
        dupla = sorted(corridas_por.get(c["team"], {}).items(), key=lambda kv: -kv[1])[:2]
        if len(dupla) < 2:
            continue
        a, b = dupla[0][0], dupla[1][0]
        qa, qb = contar(qualis, "QualifyingResults", c["team"], a, b)
        ra, rb = contar(corridas, "Results", c["team"], a, b)
        dois = [{"name": a, "q": qa, "r": ra, "pts": pontos(pontos_pil.get(a, 0))},
                {"name": b, "q": qb, "r": rb, "pts": pontos(pontos_pil.get(b, 0))}]
        duelos.append({"team": c["team"], "drivers": sorted(dois, key=lambda x: -x["pts"])})   # o de mais pontos primeiro

    # Evolução: pontos acumulados depois de cada ronda (corrida + sprint dessa ronda)
    acumulado, series = {}, {}
    rondas = []
    for r in corridas:
        for x in r["Results"] + sprints.get(r["round"], {}).get("SprintResults", []):
            acumulado[nome(x["Driver"])] = acumulado.get(nome(x["Driver"]), 0) + float(x["points"])
        rondas.append(int(r["round"]))
        for n, v in acumulado.items():
            series.setdefault(n, {})[int(r["round"])] = v
    return duelos, {"rounds": rondas, "series": series}


def estrategia(corrida, resultados_ultima):
    """Stints de pneus da última corrida (OpenF1). None se a OpenF1 não tiver essa corrida."""
    sessoes = json.loads(pedir(f"{OPENF1}/sessions?year={corrida['season']}&session_name=Race"))
    sessao = next((x for x in sessoes if x["date_start"][:10] == corrida["date"]), None)
    if not sessao:
        return None
    sk = sessao["session_key"]
    stints = json.loads(pedir(f"{OPENF1}/stints?session_key={sk}"))
    pilotos = {d["driver_number"]: d for d in json.loads(pedir(f"{OPENF1}/drivers?session_key={sk}"))}
    if not isinstance(stints, list) or not stints:
        return None
    por_numero = {}
    for st in stints:
        if st.get("lap_end") is None:
            continue
        por_numero.setdefault(st["driver_number"], []).append(
            {"c": (st.get("compound") or "UNKNOWN").upper(), "from": st["lap_start"], "to": st["lap_end"]})
    linhas = []
    for r in resultados_ultima:   # pela ordem de chegada
        num = int(r["number"])
        if num not in por_numero:
            continue
        linhas.append({"code": r["Driver"].get("code") or pilotos.get(num, {}).get("name_acronym", "?"),
                       "name": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                       "team": sigla(r["Constructor"]["constructorId"]), "pos": r["positionText"],
                       "stints": sorted(por_numero[num], key=lambda x: x["from"])})
    if not linhas:
        return None
    return {"name": nome_gp(corrida["raceName"]), "laps": max(x["to"] for l in linhas for x in l["stints"]),
            "drivers": linhas}


def parte(nome, funcao):
    """Corre uma parte opcional: se falhar, avisa e devolve None (esse ecrã sai da rotação)."""
    try:
        return funcao()
    except Exception as e:
        print(f"Aviso: F1, {nome}: {e!r}")
        return None


def montar_f1(antigo):
    agora = datetime.now(timezone.utc)
    pilotos, construtores = classificacoes()
    corridas = calendario("current")
    epoca = int(corridas[0]["season"]) if corridas else agora.year
    quando = lambda r: datetime.fromisoformat(instante(r).replace("Z", "+00:00"))
    passadas = [r for r in corridas if quando(r) <= agora]
    futuras = [r for r in corridas if quando(r) > agora] or calendario(epoca + 1)   # fim de época: calendário seguinte

    f1 = dict(antigo)
    # Mantém a cara de quem já estava na lista (o atualizar_fotos.py só corre depois)
    caras = {(p["name"], p["team"]): p.get("photo") for p in antigo.get("drivers", []) if p.get("photo")}
    for p in pilotos:
        if (p["name"], p["team"]) in caras:
            p["photo"] = caras[(p["name"], p["team"])]
    f1["drivers"], f1["constructors"] = pilotos, construtores
    if futuras:
        f1["next"] = proxima_corrida(futuras[0], tracados())
    if passadas:
        f1["last"] = ultima_corrida(passadas[-1]) or antigo.get("last")

    # Ecrãs da categoria F1: cada um à parte
    ultima = passadas[-1] if passadas else None
    if ultima:
        parte("variações", lambda: variacoes(pilotos, construtores, ultima["season"], int(ultima["round"])))
    f1["weekend"] = parte("fim de semana", lambda: fim_de_semana(futuras[0])) if futuras else None
    f1["summary"] = parte("resumo", lambda: resumo_extra(ultima)) if ultima else None
    duelos = parte("duelos", lambda: duelos_e_evolucao(epoca, construtores))
    f1["h2h"], evolucao = duelos if duelos else (None, None)
    if evolucao:
        top5 = [p["name"] for p in pilotos[:5]]
        f1["evolution"] = {"rounds": evolucao["rounds"],
                           "series": [{"name": n, "team": next(p["team"] for p in pilotos if p["name"] == n),
                                       "pts": [pontos(evolucao["series"].get(n, {}).get(r, 0)) for r in evolucao["rounds"]]}
                                      for n in top5]}
    else:
        f1["evolution"] = None
    if ultima:
        res = api(f"{ultima['season']}/{ultima['round']}/results.json")["RaceTable"]["Races"]
        f1["stints"] = parte("estratégia (OpenF1)", lambda: estrategia(ultima, res[0]["Results"])) if res else None
    else:
        f1["stints"] = None
    return f1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    try:
        dados["f1"] = montar_f1(dados["f1"])
    except Exception as e:   # sem rede, API em baixo, formato mudou...: fica tudo como estava
        sys.exit(f"Não foi possível atualizar a F1 ({e}). O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(dados["f1"], ensure_ascii=False, indent=2))
        return
    gravar(dados, "f1")
    n = dados["f1"].get("next", {})
    print(f"F1 atualizada em {LIVE}: {len(dados['f1']['drivers'])} pilotos, próxima corrida {n.get('name')} ({n.get('date')}).")


if __name__ == "__main__":
    main()
