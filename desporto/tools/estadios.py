"""Estádios e pavilhões dos jogos do Ao vivo: onde ficam (para o mapa) e as ruas à volta (para o zoom dos golos).

- O estádio de cada jogo vem da ESPN (competitions[0].venue: id, nome, cidade, país), no mesmo scoreboard que o
  aovivo.py já lê.
- As coordenadas vêm da Wikidata (pesquisa pelo nome, propriedade P625), confirmadas pela cidade (a menos de
  80 km da cidade, que também se procura na Wikidata). Sem estádio, fica a cidade. Guardam-se em
  data/estadios.json (cache local, fora do git), pela chave do estádio na ESPN. Um estádio que ficou só na cidade
  aparece no registo e na página /definicoes ("⚠ só cidade"); corrige-se à mão em tools/estadios_correcoes.json.
- Correções à mão (tools/estadios_correcoes.json, no git): as coordenadas verificadas à mão de um estádio (pela
  chave), lidas antes do cache e nunca substituídas pela Wikidata nem pela cidade (ver ler()).
- Futebol: o OpenStreetMap à volta do estádio, pelo Overpass (ruas num raio de 2,5 km mais as estradas grandes
  até 8 km, linhas de comboio e metro, água, parques, prédios a 250 m, o estádio e o relvado), já simplificado
  e em inteiros (ver osm_compacto), em data/estadios_osm/<chave>.json (cache local, fora do git; dados ODbL,
  "© OpenStreetMap"). O relvado dá o centro e o ângulo do desenho do estádio no zoom.
- Pedidos com calma: um de cada vez (uma só thread de fundo), com pausa entre eles e um User-Agent próprio (com o
  link do projeto). No máximo OSM_POR_DIA descarregamentos do OSM por dia (contados em data/estadios_osm_dia.json).
  Um estádio que não se encontrou só se procura outra vez no dia seguinte; um erro de rede, ao fim de 15 minutos.

Quem chama:
- aovivo.py: info(venue) a cada pergunta; o que falta (coordenadas, OSM de um jogo de futebol a decorrer) vai
  para a fila de fundo (pedir_em_fundo).
- atualizar_estadios.py (na atualização à mão): os estádios dos jogos dos próximos 7 dias que ainda não estão
  em cache (preparar).

Uso à mão:  python tools/estadios.py "Estádio do Dragão" Porto Portugal   (procura e mostra, sem gravar)
            python tools/estadios.py --todos   (prepara de uma vez todos os estádios da época: ver todos())
            pythonw tools/estadios.py --retomar   (o mesmo, só se não acabou nem está a correr: a tarefa agendada)
            python tools/estadios.py --refazer 10409   (o OSM desse estádio volta a descarregar-se no próximo --retomar)
            pythonw tools/estadios.py --testar Riazor   (só o OSM desse estádio; se vier, segue como o --retomar)
            python tools/estadios.py --testar Riazor --seco   (só mostra o que faria, sem pedidos)
            python tools/estadios.py --corrigir  (aplica já tools/estadios_correcoes.json e marca-os com --refazer)
Só usa a biblioteca standard do Python.
"""

import json
import math
import queue
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from comum import RAIZ

CACHE = RAIZ / "data" / "estadios.json"
CORRECOES = RAIZ / "tools" / "estadios_correcoes.json"   # {chave: {"nome", "lat", "lon", "nota"}}, à mão
PASTA_OSM = RAIZ / "data" / "estadios_osm"
# o Overpass e a Wikidata pedem um User-Agent que diga quem é e como contactar: o link do projeto (nada privado)
UA = "SuperMonitor/1.0 (+https://github.com/LimeWolf9/super-monitor)"
WIKIDATA = "https://www.wikidata.org/w/api.php"
# Overpass: o servidor principal e, se não responder, outros servidores públicos (por esta ordem)
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
OVERPASS_LEITURA_S = 200     # s à espera da resposta (a consulta pede [timeout:180] ao servidor)
OVERPASS_DE_PARTE_S = 10 * 60   # um servidor que falhou (sem ligação, tempo esgotado, 5xx) fica de parte 10 minutos
OVERPASS_VEZ_MAX_S = 180     # o /api/status diz quando há vaga para o nosso IP: espera-se até isto, senão fica de parte
OVERPASS_SEGUIDOS = 3        # --todos: tantos estádios seguidos com erro de rede no Overpass e a fase B para
PAUSA = 2.0                  # segundos entre pedidos (Wikidata e Overpass)
REPETIR_S = 86400            # um estádio que não se encontrou só se procura outra vez no dia seguinte
REPETIR_ERRO_S = 15 * 60     # um erro de rede (ex.: Overpass ocupado) repete-se ao fim de 15 minutos
MAX_CIDADE_KM = 80           # o estádio da Wikidata tem de ficar a menos disto da cidade
RAIO_RUAS = 2500             # m: ruas, linhas, água, parques
RAIO_ESTRADAS = 8000         # m: auto-estradas e estradas principais (para o meio do zoom)
RAIO_PREDIOS = 250           # m (consulta mais leve; chega para o zoom no estádio)
RAIO_PEQUENO = (1200, 6000)  # m (ruas, estradas): quando a consulta normal esgota o tempo
PERTO_SEM_NOME_M = 300       # um estádio do OSM sem o nome do da ESPN só conta se estiver a menos disto
OSM_POR_DIA = 40             # descarregamentos do OSM (buscar_osm) por dia, no máximo: o Overpass é partilhado
CONTADOR_OSM = RAIZ / "data" / "estadios_osm_dia.json"   # {"dia": "AAAA-MM-DD", "n": quantos hoje}
E = 100_000                 # o OSM grava-se em 1/100 000 de grau (~1 m)

_tranca = threading.Lock()   # data/estadios.json (o servidor tem várias threads)


# ------------------------------------------------------------ cache

def correcoes():
    try:
        return json.loads(CORRECOES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ler():
    """O cache, com as correções à mão por cima: um estádio corrigido fica com as coordenadas da correção (fonte
    "manual"; o OSM pode depois pô-lo no centro do relvado). Uma correção nova ou mudada marca o OSM para refazer."""
    try:
        tudo = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tudo = {}
    for c, k in correcoes().items():
        g = tudo.get(c, {})
        if g.get("corrigido") != [k["lat"], k["lon"]]:
            tudo[c] = {**g, "nome": g.get("nome") or k.get("nome"), "lat": k["lat"], "lon": k["lon"], "fonte": "manual",
                       "corrigido": [k["lat"], k["lon"]], "afinar": False, "refazer": True, "falhou": None, "erro": None}
    return tudo


def _gravar_entrada(chave, valor):
    with _tranca:
        tudo = ler()
        tudo[chave] = {**tudo.get(chave, {}), **valor}
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(tudo, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(CACHE)
        return tudo[chave]


def chave(venue):
    """A chave do estádio: o id da ESPN ou, sem ele, o nome simplificado."""
    if venue.get("id"):
        return str(venue["id"])
    return "n-" + "-".join(simples(venue.get("fullName") or "")) or None


def simples(texto):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", texto).split()


def ficheiro_osm(c):
    return PASTA_OSM / f"{c}.json"


def info(venue, desporto="football"):
    """O que a página precisa do estádio de um jogo (venue = o da ESPN), com o que já houver em cache.

    {"id", "nome", "cidade", "pais", "lat", "lon", "osm"} (lat/lon None se ainda não se sabe; osm = há o ficheiro
    do OpenStreetMap). Não faz pedidos: o que falta pede-se com pedir_em_fundo()."""
    if not venue or not venue.get("fullName"):
        return None
    c = chave(venue)
    morada = venue.get("address") or {}
    guardado = ler().get(c, {})
    return {
        "id": c, "nome": venue["fullName"], "cidade": morada.get("city"), "pais": morada.get("country") or morada.get("state"),
        "lat": guardado.get("lat"), "lon": guardado.get("lon"), "fonte": guardado.get("fonte"),
        "osm": desporto == "football" and ficheiro_osm(c).exists(),
    }


# ------------------------------------------------------------ pedidos

_ultimo = [0.0]


def _pedir(url, dados=None, tentativas=3, timeout=180):
    """GET (ou POST com dados) com pausa entre pedidos; respeita o 429 / Retry-After."""
    for n in range(tentativas):
        espera = _ultimo[0] + PAUSA - time.time()
        if espera > 0:
            time.sleep(espera)
        pedido = urllib.request.Request(url, data=dados, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or n == tentativas - 1:
                raise
            time.sleep(min(60, int(e.headers.get("Retry-After") or 10 * (n + 1))))
        finally:
            _ultimo[0] = time.time()


def _wikidata(texto, lingua="en"):
    """[(qid, rótulo, descrição, lat, lon, tipos P31, população (0 se não tem))] dos resultados com coordenadas."""
    d = _pedir(f"{WIKIDATA}?" + urllib.parse.urlencode({"action": "wbsearchentities", "search": texto, "language": lingua,
                                                         "uselang": lingua, "type": "item", "limit": 8, "format": "json"}))
    ids = [x["id"] for x in d.get("search", [])]
    if not ids:
        return []
    ent = _pedir(f"{WIKIDATA}?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids),
                                                           "props": "claims|labels|descriptions", "languages": "en", "format": "json"}))["entities"]
    lista = []
    for i in ids:
        claims = ent.get(i, {}).get("claims", {})
        coord = next((c["mainsnak"].get("datavalue", {}).get("value") for c in claims.get("P625", [])
                      if c["mainsnak"].get("datavalue")), None)
        if not coord:
            continue
        tipos = {c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P31", [])}
        pop = max((float(c["mainsnak"]["datavalue"]["value"].get("amount", 0)) for c in claims.get("P1082", [])
                   if c["mainsnak"].get("datavalue")), default=0)
        lista.append((i, ent[i].get("labels", {}).get("en", {}).get("value", ""), ent[i].get("descriptions", {}).get("en", {}).get("value", ""),
                      coord["latitude"], coord["longitude"], tipos, pop or ("P1082" in claims)))
    return lista


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, a)))


PAISES = {"Q6256", "Q3624078", "Q7275", "Q35657", "Q3024240"}   # país, estado soberano, estado dos EUA, ...
LOCAL = ("stadium", "arena", "venue", "ground", "field", "park", "dome", "center", "centre", "estadio", "stadion", "coliseum")


# Na NBA a morada da ESPN só traz o estado ou a província (ex.: "DC", "NC", "ON"): o que procurar na Wikidata
ESTADOS = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
    "CT": "connecticut", "DE": "delaware", "DC": "washington, d.c.|district of columbia", "FL": "florida",
    "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan",
    "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island",
    "SC": "south carolina", "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
    "ON": "ontario", "QC": "quebec", "BC": "british columbia",
}
CANADA = {"ON", "QC", "BC"}
# a descrição da Wikidata às vezes só traz o adjetivo ("French commune and city in Haute-Garonne")
ADJETIVOS = {"France": "french", "Spain": "spanish", "Germany": "german", "Italy": "italian", "Portugal": "portuguese",
             "Netherlands": "dutch", "Belgium": "belgian", "England": "english", "Scotland": "scottish", "Wales": "welsh",
             "Turkey": "turkish", "Greece": "greek", "Austria": "austrian", "Switzerland": "swiss", "Poland": "polish"}


def cidade(nome, pais):
    """(lat, lon) da cidade, pela Wikidata: dos resultados com população que não sejam um país, os que têm o país
    (ou o estado: "DC", "NC"...) no rótulo ou na descrição; destes, o de mais população (Washington DC e não
    Washington NC; Gillingham do Kent e não a do Dorset)."""
    if not nome:
        return None
    resultados = [r for r in _wikidata(nome) if not (r[5] & PAISES)]
    lista = [r for r in resultados if r[6]]
    if pais:
        if pais in ESTADOS:
            termos = [ESTADOS[pais].split("|"), ["canada" if pais in CANADA else "united states"]]
        else:
            termos = [[pais.lower(), ADJETIVOS.get(pais, pais.lower())]
                      + (["united kingdom"] if pais in ("England", "Scotland", "Wales") else [])]
        # com população primeiro; senão um sem população mas no país (o "East London" de Londres não tem)
        for t in termos:
            no_pais = ([r for r in lista if any(x in f"{r[1]} {r[2]}".lower() for x in t)]
                       or [r for r in resultados if any(x in f"{r[1]} {r[2]}".lower() for x in t)])
            if no_pais:
                lista = no_pais
                break
    lista.sort(key=lambda r: -float(r[6]))
    return (lista[0][3], lista[0][4]) if lista else None


def coordenadas(nome, nome_cidade, pais):
    """(lat, lon, fonte) do estádio: Wikidata confirmada pela cidade; sem estádio, a cidade; None se nada."""
    perto = cidade(nome_cidade, pais)
    tentativas = [nome, re.sub(r"\s*\(.*?\)", "", nome)]
    if nome_cidade and nome_cidade.lower() not in nome.lower():
        tentativas.append(f"{nome} {nome_cidade}")
    vistos = set()
    for t in tentativas:
        if t in vistos:
            continue
        vistos.add(t)
        for qid, rotulo, desc, lat, lon, tipos, populacao in _wikidata(t):
            if populacao or tipos & PAISES:
                continue   # é uma cidade ou um país com o mesmo nome
            if perto and km(lat, lon, *perto) > MAX_CIDADE_KM:
                continue   # um homónimo noutro sítio (ex.: há dois estádios Diego Armando Maradona)
            if not any(p in desc.lower() or p in rotulo.lower() for p in LOCAL) and not perto:
                continue
            return lat, lon, f"wikidata:{qid}"
    return (perto[0], perto[1], "cidade") if perto else None


# ------------------------------------------------------------ OpenStreetMap

_de_parte = {}   # servidor do Overpass -> quando falhou


def _esperar_vez(url):
    """Pergunta ao /api/status do servidor se o nosso IP tem vaga ("2 slots available now." ou "Slot available after:
    ..., in 37 seconds."). Espera pela vaga se for pouco; se for muito, ou se o status não responder em 20 s (o
    servidor está em baixo ou a recusar o nosso IP), sobe um erro e o servidor fica de parte sem se gastarem os
    200 s da consulta. Um servidor sem /api/status (responde, mas noutro formato) segue em frente."""
    pedido = urllib.request.Request(url.replace("/interpreter", "/status"), headers={"User-Agent": UA})
    with urllib.request.urlopen(pedido, timeout=20) as r:
        estado = r.read().decode("utf-8", "replace")
    if "available now" in estado or "Rate limit: 0" in estado:
        return
    esperas = [int(x) for x in re.findall(r"in (\d+) seconds", estado)]
    if not esperas:
        return
    if min(esperas) > OVERPASS_VEZ_MAX_S:
        raise TimeoutError(f"sem vaga no Overpass antes de {min(esperas)} s")
    time.sleep(min(esperas) + 2)


def _overpass(consulta):
    """Pergunta aos servidores do Overpass, por ordem. Um que falhou (sem ligação, tempo esgotado, 5xx) fica de
    parte OVERPASS_DE_PARTE_S, para não se esperar por ele em cada estádio. Se nenhum responder, sobe o erro (de
    preferência o TimeoutError, que leva buscar_osm a tentar com um raio menor); o estádio repete-se mais tarde."""
    dados = urllib.parse.urlencode({"data": consulta}).encode()
    erros = []
    for url in OVERPASS:
        if time.time() - _de_parte.get(url, 0) < OVERPASS_DE_PARTE_S:
            continue
        try:
            _esperar_vez(url)
            return _pedir(url, dados, tentativas=2, timeout=OVERPASS_LEITURA_S)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504):
                raise   # a consulta está mal: outro servidor diria o mesmo
            erros.append(e)
        except OSError as e:   # URLError, TimeoutError, ConnectionResetError...
            erros.append(e)
        _de_parte[url] = time.time()
        print(f"Aviso: Overpass {url} ({erros[-1]}); fica de parte {OVERPASS_DE_PARTE_S // 60} min")
    if not erros:
        raise ConnectionError(f"nenhum servidor do Overpass respondeu nos últimos {OVERPASS_DE_PARTE_S // 60} min")
    raise next((e for e in erros if isinstance(e, TimeoutError)), erros[-1])


def _centro(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _parecido(a, b):
    """Quantas palavras (com mais de 2 letras) os dois nomes têm em comum."""
    genericas = {"stadium", "estadio", "stadio", "stade", "stadion", "arena", "the", "de", "do", "da", "del"}
    pa = {w for w in simples(a) if len(w) > 2} - genericas
    pb = {w for w in simples(b) if len(w) > 2} - genericas
    return len(pa & pb)


def _nomes(tags):
    return " ".join(v for k, v in tags.items() if k.startswith(("name", "alt_name", "official_name", "old_name")))


def afinar(nome, lat, lon, raio):
    """O estádio no OSM com o nome mais parecido num raio: (lat, lon) do centro, ou None. Sem nenhum com o nome,
    só o mais perto se estiver a menos de PERTO_SEM_NOME_M (o Stadio dei Marmi fica a 250 m do Olimpico). Também
    contam os contornos com nome e sport=soccer sem leisure (o Olimpico, no OSM, não tem leisure=stadium)."""
    d = _overpass(f'[out:json][timeout:90];(nwr(around:{raio},{lat},{lon})[leisure=stadium];'
                  f'nwr(around:{min(raio, 1500)},{lat},{lon})[name][sport~"soccer|football"][!leisure];);out center tags;')
    melhor = None
    for e in d.get("elements", []):
        c = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        if not c:
            continue
        nota = (_parecido(nome, _nomes(e.get("tags", {}))), -km(lat, lon, c["lat"], c["lon"]))
        if nota[0] == 0 and "leisure" not in e.get("tags", {}):
            continue
        if melhor is None or nota > melhor[0]:
            melhor = (nota, (c["lat"], c["lon"]))
    if melhor and (melhor[0][0] > 0 or -melhor[0][1] * 1000 < PERTO_SEM_NOME_M):
        return melhor[1]
    return None


RUAS = {"motorway": "maior", "trunk": "maior", "primary": "maior", "motorway_link": "media", "trunk_link": "media",
        "primary_link": "media", "secondary": "media", "secondary_link": "media", "tertiary": "media",
        "tertiary_link": "media", "residential": "menor", "living_street": "menor", "unclassified": "menor",
        "pedestrian": "menor"}
FECHADAS = {"agua", "parque", "edif", "estadio"}   # camadas de polígonos (o resto são linhas)


def _consulta(lat, lon, pequeno=False):
    ruas, estradas = RAIO_PEQUENO if pequeno else (RAIO_RUAS, RAIO_ESTRADAS)
    r = f"{ruas},{lat},{lon}"
    return f"""[out:json][timeout:180];
(
  way(around:{r})[highway~"^(motorway|trunk|primary|secondary|tertiary|residential|living_street|unclassified|pedestrian)(_link)?$"];
  way(around:{estradas},{lat},{lon})[highway~"^(motorway|trunk|primary)$"];
  way(around:{r})[railway~"^(rail|light_rail|subway|tram)$"];
  way(around:{r})[natural=water];
  relation(around:{r})[natural=water];
  way(around:{r})[waterway~"^(river|canal)$"];
  way(around:{r})[leisure=park];
  way(around:{RAIO_PREDIOS},{lat},{lon})[building];
  nwr(around:800,{lat},{lon})[leisure=stadium];
  way(around:800,{lat},{lon})[name][sport~"soccer|football"][!leisure];
  way(around:800,{lat},{lon})[leisure=pitch];
);
out geom qt;"""


def _juntar(pedacos):
    """Junta as linhas de uma relação (água) em anéis, pelas pontas."""
    pedacos = [list(p) for p in pedacos if len(p) > 1]
    aneis = []
    while pedacos:
        anel = pedacos.pop()
        mudou = True
        while mudou and anel[0] != anel[-1]:
            mudou = False
            for i, p in enumerate(pedacos):
                if p[0] == anel[-1]:
                    anel += p[1:]
                elif p[-1] == anel[-1]:
                    anel += p[-2::-1]
                elif p[-1] == anel[0]:
                    anel = p[:-1] + anel
                elif p[0] == anel[0]:
                    anel = p[:0:-1] + anel
                else:
                    continue
                pedacos.pop(i)
                mudou = True
                break
        aneis.append(anel)
    return aneis


def _simplificar(pts, tol):
    """Douglas-Peucker em metros (pts em metros locais)."""
    if len(pts) < 3:
        return pts
    manter = [False] * len(pts)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pts) - 1)]
    while pilha:
        a, b = pilha.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        n2 = dx * dx + dy * dy
        pior, k = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / n2)) if n2 else 0
            d = (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2
            if d > pior:
                pior, k = d, i
        if k > 0 and pior > tol * tol:
            manter[k] = True
            pilha += [(a, k), (k, b)]
    return [p for p, m in zip(pts, manter) if m]


def _eixo(pts):
    """Eixo maior de um polígono (metros): (centro, vetor unitário, comprimento, largura)."""
    cx, cy = _centro(pts)
    sxx = sum((x - cx) ** 2 for x, _ in pts)
    syy = sum((y - cy) ** 2 for _, y in pts)
    sxy = sum((x - cx) * (y - cy) for x, y in pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    u = (math.cos(ang), math.sin(ang))
    ao_longo = [(x - cx) * u[0] + (y - cy) * u[1] for x, y in pts]
    ao_lado = [-(x - cx) * u[1] + (y - cy) * u[0] for x, y in pts]
    return (cx, cy), u, max(ao_longo) - min(ao_longo), max(ao_lado) - min(ao_lado)


def _dentro(p, anel):
    x, y = p
    sim = False
    for i in range(len(anel)):
        (x1, y1), (x2, y2) = anel[i - 1], anel[i]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            sim = not sim
    return sim


def osm_compacto(d, lat0, lon0, nome=""):
    """A resposta do Overpass -> o ficheiro guardado.

    {"centro": [lon, lat], "e": 100000, "camadas": {agua, parque, edif, rio, ferro, metro, menor, media, maior,
     estadio: [[dlon, dlat, ...], ...]}, "campo": {"c", "a", "b": [lon, lat], "larg": m} | None}
    Cada linha começa em relação ao centro e segue em deltas, em 1/100 000 de grau. Os pontos a mais de ~3 km
    (ou 16 km, nas estradas grandes) cortam-se; as linhas simplificam-se (1,5 m perto, 15 m longe)."""
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    m = lambda g: [((n["lon"] - lon0) * kx, (n["lat"] - lat0) * ky) for n in g if n]
    camadas = {k: [] for k in ["agua", "parque", "edif", "rio", "ferro", "metro", "menor", "media", "maior", "estadio"]}
    estadios, campos = [], []

    def por(k, pts, limite=3200):
        fechado = k in FECHADAS
        if fechado:
            if not pts or all(math.hypot(*p) > limite for p in pts):
                return
            pedacos = [pts]
        else:   # as linhas cortam-se onde saem do raio
            pedacos, atual = [], []
            for p in pts:
                if math.hypot(*p) <= limite:
                    atual.append(p)
                else:
                    if len(atual) > 1:
                        pedacos.append(atual)
                    atual = []
            if len(atual) > 1:
                pedacos.append(atual)
        for p in pedacos:
            tol = 1.5 if math.hypot(*_centro(p)) < 600 else 4 if math.hypot(*_centro(p)) < limite else 15
            s = _simplificar(p, tol)
            if len(s) >= (3 if fechado else 2):
                camadas[k].append(s)

    for e in d.get("elements", []):
        t = e.get("tags", {})
        if e["type"] == "relation":
            pedacos = [m(mb["geometry"]) for mb in e.get("members", []) if mb.get("geometry")]
            aneis = [a for a in _juntar([[(round(x, 2), round(y, 2)) for x, y in p] for p in pedacos]) if len(a) > 3]
            if t.get("natural") == "water":
                for a in aneis:
                    por("agua", a)
            elif t.get("leisure") == "stadium":
                estadios += [(t, a) for a in aneis]
            continue
        g = e.get("geometry")
        if not g:
            continue
        pts = m(g)
        if "highway" in t:
            k = RUAS.get(t["highway"])
            if k:
                por(k, pts, 16000 if k == "maior" else 3200)
        elif t.get("railway") == "rail":
            por("ferro", pts)
        elif t.get("railway") in ("light_rail", "subway", "tram"):
            por("metro", pts)
        elif t.get("natural") == "water":
            por("agua", pts)
        elif "waterway" in t:
            por("rio", pts)
        elif t.get("leisure") == "park":
            por("parque", pts)
        elif t.get("leisure") == "stadium":
            estadios.append((t, pts))
        elif t.get("leisure") == "pitch":
            campos.append((t, pts))
        else:
            if "leisure" not in t and "sport" in t and _parecido(nome, _nomes(t)) and len(pts) > 3:
                estadios.append((t, pts))   # o contorno com o nome do estádio, sem leisure=stadium (o Olimpico)
            if "building" in t:
                por("edif", pts)

    # O estádio: o do nome mais parecido; sem nenhum com o nome, o que tem o ponto procurado lá dentro, senão o
    # mais perto (a menos de PERTO_SEM_NOME_M: um vizinho como o Stadio dei Marmi não serve)
    nota = lambda s: (_parecido(nome, _nomes(s[0])), -math.hypot(*_centro(s[1])))
    estadio = max(estadios, key=nota, default=None)
    if estadio and nota(estadio)[0] == 0:
        com_ponto = [s for s in estadios if _dentro((0, 0), s[1])]
        estadio = com_ponto[0] if com_ponto else estadio if -nota(estadio)[1] < PERTO_SEM_NOME_M else None
    if estadio:
        por("estadio", estadio[1])

    # O relvado: um de futebol dentro do estádio (o maior); senão o maior dos mais perto do centro do estádio (ou do
    # ponto procurado), a menos de 300 m
    def area(pts):
        return abs(sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))) / 2
    def de_futebol(t):
        return not t.get("sport") or bool({"soccer", "football"} & {s.strip() for s in t["sport"].split(";")})
    futebol = [c for c in campos if de_futebol(c[0]) and len(c[1]) >= 4]
    dentro = [c for c in futebol if estadio and _dentro(_centro(c[1]), estadio[1])]
    if dentro:
        relvado = max(dentro, key=lambda c: area(c[1]))[1]
    else:
        ox, oy = _centro(estadio[1]) if estadio else (0, 0)
        dist = lambda c: math.hypot(_centro(c[1])[0] - ox, _centro(c[1])[1] - oy)
        # nunca o relvado de dentro de outro estádio (o Jean-Bouin, de râguebi, ficava com o do Parc des Princes)
        perto = [c for c in futebol if dist(c) < 300 and area(c[1]) > 4000
                 and not any(s is not estadio and _dentro(_centro(c[1]), s[1]) for s in estadios)]
        relvado = min(perto, key=lambda c: (round(dist(c) / 50), -area(c[1])))[1] if perto else None
    campo = None
    base = relvado or (estadio[1] if estadio else None)
    if base:
        (cx, cy), u, comp, larg = _eixo(base)
        if not relvado:
            comp, larg = 105, 68
        meio = comp / 2
        geo = lambda x, y: [round(lon0 + x / kx, 6), round(lat0 + y / ky, 6)]
        campo = {"c": geo(cx, cy), "a": geo(cx - u[0] * meio, cy - u[1] * meio), "b": geo(cx + u[0] * meio, cy + u[1] * meio),
                 "larg": round(larg, 1), "relvado": bool(relvado)}

    def codificar(pts):
        saida, ant = [], (0, 0)
        for x, y in pts:
            q = (round(x / kx * E), round(y / ky * E))
            if q == ant and saida:
                continue
            saida += [q[0] - ant[0], q[1] - ant[1]]
            ant = q
        return saida

    return {
        "_fonte": "© OpenStreetMap contributors, ODbL (openstreetmap.org/copyright). Gerado por tools/estadios.py.",
        "centro": [round(lon0, 6), round(lat0, 6)], "e": E,
        "camadas": {k: [codificar(p) for p in v] for k, v in camadas.items()},
        "campo": campo,
    }


class LimiteDiario(Exception):
    """Já se fizeram OSM_POR_DIA descarregamentos do OSM hoje: o resto fica para amanhã."""


_tranca_contador = threading.Lock()


def _contar_osm():
    """Conta mais um descarregamento do OSM hoje; se já se chegou a OSM_POR_DIA, sobe LimiteDiario (sem contar)."""
    hoje = time.strftime("%Y-%m-%d")
    with _tranca_contador:
        try:
            d = json.loads(CONTADOR_OSM.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        n = d.get("n", 0) if d.get("dia") == hoje else 0
        if n >= OSM_POR_DIA:
            raise LimiteDiario(f"limite de {OSM_POR_DIA} descarregamentos do OSM por dia atingido ({hoje})")
        CONTADOR_OSM.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONTADOR_OSM.with_suffix(".tmp")
        tmp.write_text(json.dumps({"dia": hoje, "n": n + 1}), encoding="utf-8")
        tmp.replace(CONTADOR_OSM)


def buscar_osm(c, lat, lon, nome):
    """Descarrega e grava o OSM à volta do estádio. Devolve o campo (centro e eixo do relvado) ou None. Se a consulta
    esgotar o tempo, tenta logo com um raio menor (RAIO_PEQUENO), e esse estádio passa a ir sempre com ele."""
    pequeno = ler().get(c, {}).get("pequeno")
    _contar_osm()
    try:
        d = _overpass(_consulta(lat, lon, pequeno))
    except TimeoutError:
        if pequeno:
            raise
        _gravar_entrada(c, {"pequeno": True})
        print(f"Aviso: {nome}: a consulta esgotou o tempo; outra vez com o raio menor")
        d = _overpass(_consulta(lat, lon, True))
    compacto = osm_compacto(d, lat, lon, nome)
    PASTA_OSM.mkdir(parents=True, exist_ok=True)
    destino = ficheiro_osm(c)
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps(compacto, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(destino)
    return compacto["campo"]


# ------------------------------------------------------------ resolver um estádio (coordenadas e, no futebol, OSM)

def falhou_ha_pouco(guardado):
    espera = REPETIR_ERRO_S if guardado.get("erro") else REPETIR_S
    return bool(guardado.get("falhou")) and time.time() - guardado["falhou"] < espera


def resolver(e, com_osm):
    """e = info() de um estádio. Procura o que falta e grava em data/estadios.json. Devolve a entrada gravada."""
    c = e["id"]
    guardado = ler().get(c, {})
    agora = time.time()
    if falhou_ha_pouco(guardado):
        return guardado
    try:
        if guardado.get("lat") is None:
            achado = coordenadas(e["nome"], e.get("cidade"), e.get("pais"))
            if not achado:
                return _gravar_entrada(c, {"nome": e["nome"], "cidade": e.get("cidade"), "pais": e.get("pais"), "falhou": agora, "erro": None})
            lat, lon, fonte = achado
            if fonte == "cidade":
                print(f"⚠ só cidade: {e['nome']} ({e.get('cidade')}, {e.get('pais')}), chave {c}: corrigir à mão em "
                      "tools/estadios_correcoes.json", flush=True)
            # já fica no mapa, mesmo que o resto (Overpass) falhe
            guardado = _gravar_entrada(c, {"nome": e["nome"], "cidade": e.get("cidade"), "pais": e.get("pais"), "afinar": True,
                                           "lat": round(lat, 6), "lon": round(lon, 6), "fonte": fonte, "falhou": None, "erro": None, "t": agora})
        if com_osm and guardado.get("afinar", True) and "+osm" not in (guardado.get("fonte") or ""):
            # o ponto exato do estádio no OSM (a cidade fica a quilómetros; a Wikidata às vezes a centenas de metros)
            cidade_so = guardado.get("fonte") == "cidade"
            fino = afinar(e["nome"], guardado["lat"], guardado["lon"], 15000 if cidade_so else 1500)
            novo = {"afinar": False}
            if fino:
                novo.update(lat=round(fino[0], 6), lon=round(fino[1], 6), fonte=guardado["fonte"] + "+osm")
            guardado = _gravar_entrada(c, novo)
        if com_osm and (not ficheiro_osm(c).exists() or guardado.get("refazer")) and "cidade" != guardado.get("fonte"):
            campo = buscar_osm(c, guardado["lat"], guardado["lon"], e["nome"])
            novo = {"osm_t": agora, "falhou": None, "erro": None, "refazer": None}
            if campo:   # o ponto do mapa passa a ser o centro do relvado
                novo.update(lon=campo["c"][0], lat=campo["c"][1])
            guardado = _gravar_entrada(c, novo)
        return guardado
    except LimiteDiario:
        raise   # não é um erro do estádio: fica como estava, para amanhã
    except Exception as ex:
        print(f"Aviso: estádio {e['nome']}: {ex!r}")
        return _gravar_entrada(c, {"nome": e["nome"], "cidade": e.get("cidade"), "pais": e.get("pais"), "falhou": agora, "erro": str(ex)[:200]})


# Fila de fundo: um pedido de cada vez, para não abusar da Wikidata e do Overpass. Primeiro as coordenadas de
# todos (Wikidata, rápido: chegam para o mapa), só depois o OSM, um de cada vez (Overpass, ~1 minuto cada)
_fila, _na_fila = queue.PriorityQueue(), set()
_ordem = iter(range(10 ** 12))   # desempate na fila (por ordem de chegada)
_trabalhador = []


def _trabalhar():
    time.sleep(1)   # deixa chegar os outros jogos do mesmo pedido, para as coordenadas irem antes do primeiro OSM
    while True:
        fase, _, e, com_osm = _fila.get()
        try:
            if fase == 0 and com_osm:
                # só as coordenadas; o OSM volta à fila, atrás das coordenadas dos outros
                if resolver(e, False).get("lat") is not None:
                    _fila.put((1, next(_ordem), e, True))
                    continue
            resolver(e, com_osm)
        except Exception:
            pass
        _na_fila.discard(e["id"])


def falta(e, com_osm):
    """Ainda falta alguma coisa a este estádio (e não falhou há pouco)?"""
    guardado = ler().get(e["id"], {})
    if falhou_ha_pouco(guardado):
        return False
    if guardado.get("lat") is None:
        return True
    if com_osm and guardado.get("refazer"):
        return True
    return com_osm and not e.get("osm") and (guardado.get("fonte") != "cidade" or guardado.get("afinar", True))


def pedir_em_fundo(e, com_osm):
    """Põe o estádio na fila de fundo (se ainda faltar alguma coisa e não estiver já lá)."""
    if not e or e["id"] in _na_fila or not falta(e, com_osm):
        return
    if not _trabalhador:
        _trabalhador.append(threading.Thread(target=_trabalhar, daemon=True, name="estadios"))
        _trabalhador[0].start()
    _na_fila.add(e["id"])
    _fila.put((0 if ler().get(e["id"], {}).get("lat") is None else 1, next(_ordem), e, com_osm))


def preparar(venues, mostrar=print):
    """Resolve já (na thread de quem chama) os estádios que faltam. venues = [(venue da ESPN, desporto)].
    Devolve (quantos já estavam, quantos se resolveram, quantos falharam)."""
    ja, novos, falhas = 0, 0, 0
    vistos = set()
    for v, desporto in venues:
        e = info(v, desporto)
        if not e or e["id"] in vistos:
            continue
        vistos.add(e["id"])
        com_osm = desporto == "football"
        if not falta(e, com_osm):
            ja += 1
            continue
        mostrar(f"Estádio: {e['nome']} ({e.get('cidade') or '?'})")
        r = resolver(e, com_osm)
        if r.get("lat") is not None and (not com_osm or ficheiro_osm(e["id"]).exists() or r.get("fonte") == "cidade"):
            novos += 1
        else:
            falhas += 1
    return ja, novos, falhas


# ------------------------------------------------------------ todos de uma vez (--todos)

PROGRESSO = RAIZ / "data" / "estadios_todos.json"   # o progresso, no formato do data/atualizacao.json
MESES = 8                    # os jogos de hoje até ao fim da época (os estádios de todas as equipas)
PAUSA_TODOS = 30.0           # Overpass (fase B): mais calma do que no resto, são centenas de pedidos seguidos
PAUSA_WIKIDATA = 1.0         # Wikidata (fase A): ~1 pedido por segundo chega (cada estádio são ~4 pedidos)
REGISTO = RAIZ / "data" / "estadios_todos.log"    # o que o --todos escreve (pela página /definicoes ou à mão)
TRANCA_TODOS = RAIZ / "data" / "estadios_todos.lock"
TRANCA_VELHA_S = 120         # a tranca toca-se a cada 20 s: mais velha do que isto é de um --todos que morreu
RONDAS = 4                   # voltas aos que deram erro de rede (cada uma ao fim de REPETIR_ERRO_S)


def _todos_venues(mostrar):
    """[(data do 1.º jogo, venue, desporto)] de todos os jogos marcados nas competições ligadas e na NBA, dos
    próximos MESES meses (os scoreboards da ESPN de cada mês). As ligas dão os estádios de todas as equipas; as
    taças e as seleções, os dos jogos já marcados. Cada estádio uma só vez, pelo jogo mais próximo."""
    from datetime import datetime, timedelta
    import atualizar_estadios
    import competicoes
    hoje = datetime.now()
    ate = hoje + timedelta(days=31 * MESES)
    fontes = [(f"soccer/{liga}", nome, filtro) for _c, nome, liga, _t, filtro in competicoes.a_buscar()]
    fontes.append(("basketball/nba", "NBA", None))
    todos = []
    for caminho, nome, filtro in fontes:
        # venues() pede os meses das duas pontas; aqui pede-se mês a mês
        mes, n = hoje, 0
        while mes <= ate:
            fim = min(ate, (mes.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1))
            try:
                lista = atualizar_estadios.venues(caminho, mes, fim, filtro)
                todos += lista
                n += len(lista)
            except Exception as e:
                mostrar(f"Aviso: {nome} {mes:%Y-%m}: {e}")
            mes = fim + timedelta(days=1)
        mostrar(f"{nome}: {n} jogos")
    vistos, lista = set(), []
    for quando, v, desporto in sorted(todos, key=lambda x: x[0]):
        c = chave(v)
        if c and c not in vistos:
            vistos.add(c)
            lista.append((quando, v, desporto))
    return lista


def _poligonos_estadio(c):
    """Os contornos do estádio (camada "estadio") do ficheiro do OSM de c, em [(lon, lat), ...]."""
    try:
        d = json.loads(ficheiro_osm(c).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lon0, lat0 = d["centro"]
    aneis = []
    for linha in d["camadas"].get("estadio", []):
        x = y = 0
        anel = []
        for k in range(0, len(linha) - 1, 2):
            x, y = x + linha[k], y + linha[k + 1]
            anel.append((lon0 + x / d["e"], lat0 + y / d["e"]))
        if len(anel) >= 3:
            aneis.append(anel)
    return aneis


def duplicados(futebol, mostrar):
    """Só mostra (não apaga nem junta) os estádios que parecem o mesmo com chaves da ESPN diferentes: o ponto de um
    cai dentro do contorno do estádio (leisure=stadium) do outro. A distância não chega: o Parc des Princes e o
    Jean-Bouin estão a ~250 m, Dens Park e Tannadice (Dundee) a ~100 m."""
    tudo = ler()
    com = [e for e in futebol if ficheiro_osm(e["id"]).exists() and tudo.get(e["id"], {}).get("lat") is not None]
    aneis = {e["id"]: _poligonos_estadio(e["id"]) for e in com}
    n = 0
    for a in com:
        ga = tudo[a["id"]]
        for b in com:
            gb = tudo[b["id"]]
            if (a["id"] < b["id"] and km(ga["lat"], ga["lon"], gb["lat"], gb["lon"]) < 1.5
                    and (any(_dentro((ga["lon"], ga["lat"]), x) for x in aneis[b["id"]])
                         or any(_dentro((gb["lon"], gb["lat"]), x) for x in aneis[a["id"]]))):
                n += 1
                mostrar(f"Talvez o mesmo estádio: {a['nome']} ({a['id']}) e {b['nome']} ({b['id']})")
    mostrar(f"Duplicados prováveis: {n} (só listados, nada se apagou)")


def todos_a_correr():
    """Há um --todos a correr (aqui ou noutro processo)? Pela tranca, que ele toca a cada 20 s."""
    try:
        return time.time() - TRANCA_TODOS.stat().st_mtime < TRANCA_VELHA_S
    except OSError:
        return False


def estado_todos(linhas=12):
    """Para a página /definicoes: o progresso (data/estadios_todos.json), se está mesmo a correr, e o fim do registo."""
    try:
        estado = json.loads(PROGRESSO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        estado = {"estado": None}
    try:
        with open(REGISTO, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - 8000))
            fim = f.read().decode("utf-8", "replace").splitlines()[-linhas:]
    except OSError:
        fim = []
    vivo = todos_a_correr()
    if estado.get("estado") == "a correr" and not vivo:
        estado["estado"] = "parado"   # o processo morreu a meio (ex.: o PC desligou): continua com --todos
    so_cidade = sorted(f"{v.get('nome')} ({v.get('cidade') or '?'})" for v in ler().values() if v.get("fonte") == "cidade")
    return {**estado, "a_correr": vivo, "registo": fim, "so_cidade": so_cidade}


def todos():
    """Prepara já todos os estádios da época, para o mapa nunca ter de esperar.

    Fase A: as coordenadas (Wikidata) de todos os que faltam. Fase B: o OSM (Overpass, ~1 minuto cada) de todos os
    estádios de futebol que faltam, um de cada vez, o do jogo mais próximo primeiro. Grava depois de cada estádio:
    se parar a meio, volta a correr e continua onde ficou. Os erros de rede repetem-se ao fim de 15 minutos
    (RONDAS vezes); um estádio que não se encontrou fica para o dia seguinte (como no resto). O progresso fica em
    data/estadios_todos.json; a tranca (data/estadios_todos.lock) impede dois ao mesmo tempo."""
    if todos_a_correr():
        print("Já há um --todos a correr (data/estadios_todos.lock).")
        return
    TRANCA_TODOS.write_text(str(time.time()), encoding="utf-8")
    vivo = threading.Event()

    def tocar():   # a tranca é o sinal de que está vivo (a página /definicoes e o botão "Continuar" leem-na)
        while not vivo.wait(20):
            TRANCA_TODOS.touch()
    threading.Thread(target=tocar, daemon=True).start()
    try:
        _todos()
    finally:
        vivo.set()
        TRANCA_TODOS.unlink(missing_ok=True)


def _todos():
    t0 = time.time()
    estado = {"estado": "a correr", "fase": "lista", "passo": "Estádios: lista", "feitos": 0, "total": 0, "decorrido_s": 0,
              "estimativa_s": None, "inicio_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "terminado_em": None, "erro": None}

    def gravar_progresso(**mudar):
        estado.update(mudar, decorrido_s=round(time.time() - t0, 1))
        tmp = PROGRESSO.with_suffix(".tmp")
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(PROGRESSO)

    def mostrar(texto):
        print(f"{time.strftime('%H:%M:%S')} {texto}", flush=True)

    gravar_progresso()
    try:
        _fases(gravar_progresso, mostrar, t0)
    except Exception as ex:
        mostrar(f"Erro: {ex!r} (corre outra vez --todos para continuar)")
        gravar_progresso(estado="erro", erro=str(ex)[:200], terminado_em=time.strftime("%Y-%m-%dT%H:%M:%S"))
        raise


def _fases(gravar_progresso, mostrar, t0):
    global PAUSA
    lista = _todos_venues(mostrar)
    estadios_ = [(quando, info(v, d), d) for quando, v, d in lista]
    estadios_ = [(q, e, d) for q, e, d in estadios_ if e]
    futebol = [(q, e) for q, e, d in estadios_ if d == "football"]
    mostrar(f"{len(estadios_)} estádios ({len(futebol)} de futebol, {len(estadios_) - len(futebol)} da NBA)")

    # Fase A: só as coordenadas
    a_fazer = [e for _q, e, _d in estadios_ if ler().get(e["id"], {}).get("lat") is None]
    mostrar(f"Fase A: coordenadas de {len(a_fazer)} estádios (os outros já estão)")
    PAUSA = PAUSA_WIKIDATA
    sem_osm = sum(1 for _q, e in futebol if not ficheiro_osm(e["id"]).exists())
    t1 = time.time()
    for i, e in enumerate(a_fazer, 1):
        media = (time.time() - t1) / (i - 1) if i > 1 else 6
        gravar_progresso(fase="A", passo=f"Coordenadas: {e['nome']}", feitos=i - 1, total=len(a_fazer),
                         estimativa_s=round(time.time() - t0 + media * (len(a_fazer) - i + 1) + 65 * sem_osm))
        r = resolver(e, False)
        mostrar(f"A {i}/{len(a_fazer)} {e['nome']} ({e.get('cidade') or '?'}): "
                + (f"{r['lat']}, {r['lon']} ({r.get('fonte')})" + (" ⚠ só cidade" if r.get("fonte") == "cidade" else "")
                   if r.get("lat") is not None else f"sem coordenadas {r.get('erro') or ''}"))
    com = sum(1 for _q, e, _d in estadios_ if ler().get(e["id"], {}).get("lat") is not None)
    mostrar(f"Fase A feita: {com}/{len(estadios_)} com coordenadas")

    # Fase B: o OSM, o do jogo mais próximo primeiro (a lista já vem por data)
    PAUSA = max(PAUSA, PAUSA_TODOS)
    limite = False
    for ronda in range(RONDAS):
        a_fazer = [e for _q, e in futebol if falta({**e, "osm": ficheiro_osm(e["id"]).exists()}, True)
                   and ler().get(e["id"], {}).get("lat") is not None]
        if not a_fazer:
            break
        if ronda:   # 15, 30, 60 minutos
            espera = REPETIR_ERRO_S * 2 ** (ronda - 1)
            mostrar(f"Ronda {ronda + 1}: {len(a_fazer)} com erro de rede; a esperar {espera // 60} minutos")
            gravar_progresso(passo=f"À espera {espera // 60} min para repetir {len(a_fazer)} com erro de rede")
            time.sleep(espera + 5)
        mostrar(f"Fase B: OpenStreetMap de {len(a_fazer)} estádios (~1 minuto cada)")
        t1 = time.time()
        seguidos = 0
        for i, e in enumerate(a_fazer, 1):
            media = (time.time() - t1) / (i - 1) if i > 1 else 60
            gravar_progresso(fase="B", passo=f"OpenStreetMap: {e['nome']}", feitos=i - 1, total=len(a_fazer),
                             estimativa_s=round(time.time() - t0 + media * (len(a_fazer) - i + 1)))
            try:
                r = resolver(e, True)
            except LimiteDiario as ex:
                mostrar(f"Limite diário: {ex}; paro a fase B, o resto fica para amanhã")
                limite = True
                break
            ok = ficheiro_osm(e["id"]).exists()
            mostrar(f"B {i}/{len(a_fazer)} {e['nome']}: " + ("ok" if ok else f"sem OSM ({r.get('fonte')}) {r.get('erro') or ''}"))
            seguidos = 0 if ok or not r.get("erro") else seguidos + 1
            if seguidos >= OVERPASS_SEGUIDOS:
                # o Overpass não responde (em baixo, ou a recusar o nosso IP): continuar só gastava pedidos e tempo
                mostrar(f"Overpass sem resposta em {seguidos} estádios seguidos: paro a fase B (ver /api/status do Overpass)")
                break
        if seguidos >= OVERPASS_SEGUIDOS or limite:
            break
        time.sleep(1)
        # os que deram erro voltam a ser tentados; os outros (não encontrados, só a cidade) ficam
        if not any(ler().get(e["id"], {}).get("erro") for e in a_fazer):
            break

    osm = sum(1 for _q, e in futebol if ficheiro_osm(e["id"]).exists())
    com = sum(1 for _q, e, _d in estadios_ if ler().get(e["id"], {}).get("lat") is not None)
    fim = f"{com}/{len(estadios_)} com coordenadas, {osm}/{len(futebol)} de futebol com OpenStreetMap"
    # os que ainda têm erro de rede não ficam esquecidos: "incompleto" (e não "ok") faz a tarefa agendada
    # (--retomar, de 30 em 30 minutos) voltar a tentá-los
    com_erro = sum(1 for _q, e in futebol if ler().get(e["id"], {}).get("erro"))
    erro = f"{com_erro} estádios com erro de rede (Overpass); a tarefa agendada repete" if com_erro else None
    if limite:   # os que ficaram por fazer também não ficam esquecidos
        erro = f"limite de {OSM_POR_DIA} descarregamentos do OSM por dia atingido; o resto fica para amanhã"
    gravar_progresso(estado="incompleto" if com_erro or limite else "ok", fase="fim", passo=fim, terminado_em=time.strftime("%Y-%m-%dT%H:%M:%S"),
                     feitos=osm, total=len(futebol), erro=erro)
    mostrar("Feito: " + fim + (f" ({erro})" if erro else ""))
    duplicados([e for _q, e in futebol], mostrar)


def testar(nome, seco=False):
    """Um só estádio de futebol já em cache (pelo nome ou pela chave), com as regras do --todos (User-Agent, raios,
    vaga no /api/status, PAUSA_TODOS, OSM_POR_DIA). Se o OSM vier, segue com um --todos (os que faltam, como um
    --retomar); se não, para e diz que o bloqueio continua. Tudo no registo e no progresso (a página /definicoes).
    seco: só mostra o que faria, sem pedidos nem gravar nada."""
    global PAUSA

    def mostrar(texto):
        print(f"{time.strftime('%H:%M:%S')} {texto}", flush=True)

    tudo = ler()
    c = nome if nome in tudo else next((k for k, v in tudo.items() if simples(v.get("nome")) == simples(nome)), None)
    if not c or tudo[c].get("lat") is None:
        mostrar(f"Teste: {nome} não está em data/estadios.json com coordenadas; nada feito")
        return False
    g = tudo[c]
    e = {"id": c, "nome": g.get("nome") or nome, "cidade": g.get("cidade"), "pais": g.get("pais")}
    if seco:
        mostrar(f"Teste (a seco): {e['nome']} ({c}) em {g['lat']}, {g['lon']}; raios {RAIO_RUAS}/{RAIO_ESTRADAS}/"
                f"{RAIO_PREDIOS} m{' (pequeno)' if g.get('pequeno') else ''}; pausa {PAUSA_TODOS:.0f} s; "
                f"{OSM_POR_DIA}/dia; consulta de {len(_consulta(g['lat'], g['lon'], g.get('pequeno')))} caracteres; "
                f"servidores {', '.join(OVERPASS)}; UA {UA}")
        return True
    if todos_a_correr():
        mostrar("Teste: já há um --todos a correr (data/estadios_todos.lock); nada feito")
        return False
    t0 = time.time()
    estado = {"estado": "a correr", "fase": "teste", "passo": f"Teste: OpenStreetMap de {e['nome']}", "feitos": 0, "total": 1,
              "decorrido_s": 0, "estimativa_s": 120, "inicio_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "terminado_em": None, "erro": None}
    tmp = PROGRESSO.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PROGRESSO)
    mostrar(f"Teste: OpenStreetMap só de {e['nome']} ({c})")
    PAUSA = max(PAUSA, PAUSA_TODOS)
    _gravar_entrada(c, {"refazer": True, "falhou": None, "erro": None})   # descarrega mesmo que já houvesse
    try:
        r = resolver(e, True)
    except LimiteDiario as ex:
        r = {"erro": str(ex)}
    ok = ficheiro_osm(c).exists() and not r.get("refazer")
    if ok:
        mostrar(f"Teste: {e['nome']} ok ({time.time() - t0:.0f} s); o Overpass responde. Segue o resto (como o --retomar)")
        return True
    fim = f"Teste: {e['nome']} falhou ({r.get('erro') or 'sem OSM'}): o bloqueio do Overpass continua; paro aqui"
    mostrar(fim)
    estado.update(estado="erro", fase="fim", passo=fim, erro=fim[:200], decorrido_s=round(time.time() - t0, 1),
                  terminado_em=time.strftime("%Y-%m-%dT%H:%M:%S"))
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PROGRESSO)
    return False


if __name__ == "__main__":
    if sys.stdout:   # com pythonw (a tarefa agendada) não há consola
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:] == ["--todos"]:
        todos()
        sys.exit()
    if sys.argv[1:] == ["--retomar"]:
        # pela tarefa agendada do Windows (pythonw, sem consola): só se o --todos não está a correr e não acabou (ou
        # acabou mas ainda há estádios com erro de rede ou marcados com --refazer)
        try:
            acabou = json.loads(PROGRESSO.read_text(encoding="utf-8")).get("estado") == "ok"
        except (OSError, ValueError):
            acabou = False
        pendentes = [c for c, v in ler().items() if v.get("refazer") or v.get("erro") and (
            v.get("lat") is None or not ficheiro_osm(c).exists())]
        acabou = acabou and not pendentes
        if acabou or todos_a_correr():
            sys.exit()
        sys.stdout = sys.stderr = open(REGISTO, "a", encoding="utf-8", buffering=1)
        print(f"{time.strftime('%H:%M:%S')} Retomado pela tarefa agendada", flush=True)
        todos()
        sys.exit()
    if sys.argv[1:2] == ["--testar"] and len(sys.argv) > 2:
        # pela tarefa agendada "(teste Riazor)": um estádio só; se o OSM vier, um --todos com os que faltam
        seco = "--seco" in sys.argv
        nome = " ".join(a for a in sys.argv[2:] if a != "--seco")
        if not seco:
            sys.stdout = sys.stderr = open(REGISTO, "a", encoding="utf-8", buffering=1)
        if testar(nome, seco) and not seco:
            todos()
        sys.exit()
    if sys.argv[1:] == ["--corrigir"]:
        # grava já no cache as correções à mão novas ou mudadas (o ler() põe-nas por cima e marca-as para o OSM
        # se descarregar outra vez, no ponto certo, no próximo --todos / --retomar)
        mudou = [c for c, v in ler().items() if c in correcoes() and v.get("refazer")]
        for c in mudou:
            _gravar_entrada(c, {})
        print(f"Correções no cache, OSM a refazer: {', '.join(mudou) or 'nenhuma'}")
        sys.exit()
    if sys.argv[1:2] == ["--refazer"]:
        # marca estádios (pela chave) para o OSM se descarregar outra vez no próximo --todos / --retomar
        for c in sys.argv[2:]:
            _gravar_entrada(c, {"refazer": True, "falhou": None, "erro": None})
        print(f"Marcados para refazer: {', '.join(sys.argv[2:]) or 'nenhum'}")
        sys.exit()
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    nome, cid, pais = (sys.argv[1:] + [None, None])[:3]
    print(coordenadas(nome, cid, pais))
