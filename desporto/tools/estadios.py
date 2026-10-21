"""Estádios e pavilhões dos jogos do Ao vivo: onde ficam (para o mapa) e as ruas à volta (para o zoom dos golos).

- O estádio de cada jogo vem da ESPN (competitions[0].venue: id, nome, cidade, país), no mesmo scoreboard que o
  aovivo.py já lê.
- As coordenadas vêm da Wikidata (pesquisa pelo nome, propriedade P625), confirmadas pela cidade (a menos de
  80 km da cidade, que também se procura na Wikidata). Sem estádio, fica a cidade. Guardam-se em
  data/estadios.json (cache local, fora do git), pela chave do estádio na ESPN.
- Futebol: o OpenStreetMap à volta do estádio, pelo Overpass (ruas num raio de 2,5 km mais as estradas grandes
  até 15 km, linhas de comboio e metro, água, parques, prédios a 350 m, o estádio e o relvado), já simplificado
  e em inteiros (ver osm_compacto), em data/estadios_osm/<chave>.json (cache local, fora do git; dados ODbL,
  "© OpenStreetMap"). O relvado dá o centro e o ângulo do desenho do estádio no zoom.
- Pedidos com calma: um de cada vez (uma só thread de fundo), com pausa entre eles e um User-Agent próprio.
  Um estádio que não se encontrou só se procura outra vez no dia seguinte; um erro de rede, ao fim de 15 minutos.

Quem chama:
- aovivo.py: info(venue) a cada pergunta; o que falta (coordenadas, OSM de um jogo de futebol a decorrer) vai
  para a fila de fundo (pedir_em_fundo).
- atualizar_estadios.py (na atualização à mão): os estádios dos jogos dos próximos 7 dias que ainda não estão
  em cache (preparar).

Uso à mão:  python tools/estadios.py "Estádio do Dragão" Porto Portugal   (procura e mostra, sem gravar)
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

from comum import RAIZ, USER_AGENT

CACHE = RAIZ / "data" / "estadios.json"
PASTA_OSM = RAIZ / "data" / "estadios_osm"
UA = f"{USER_AGENT} estadios.py (mapa do Ao vivo; um pedido de cada vez)"
WIKIDATA = "https://www.wikidata.org/w/api.php"
# Overpass: o servidor principal e, se estiver ocupado (502/504), outro servidor público
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
PAUSA = 2.0                  # segundos entre pedidos (Wikidata e Overpass)
REPETIR_S = 86400            # um estádio que não se encontrou só se procura outra vez no dia seguinte
REPETIR_ERRO_S = 15 * 60     # um erro de rede (ex.: Overpass ocupado) repete-se ao fim de 15 minutos
MAX_CIDADE_KM = 80           # o estádio da Wikidata tem de ficar a menos disto da cidade
RAIO_RUAS = 2500             # m: ruas, linhas, água, parques
RAIO_ESTRADAS = 15000        # m: auto-estradas e estradas principais (para o meio do zoom)
RAIO_PREDIOS = 350           # m
E = 100_000                  # o OSM grava-se em 1/100 000 de grau (~1 m)

_tranca = threading.Lock()   # data/estadios.json (o servidor tem várias threads)


# ------------------------------------------------------------ cache

def ler():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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


def _pedir(url, dados=None, tentativas=3):
    """GET (ou POST com dados) com pausa entre pedidos; respeita o 429 / Retry-After."""
    for n in range(tentativas):
        espera = _ultimo[0] + PAUSA - time.time()
        if espera > 0:
            time.sleep(espera)
        pedido = urllib.request.Request(url, data=dados, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or n == tentativas - 1:
                raise
            time.sleep(min(60, int(e.headers.get("Retry-After") or 10 * (n + 1))))
        finally:
            _ultimo[0] = time.time()


def _wikidata(texto, lingua="en"):
    """[(qid, rótulo, descrição, lat, lon, tipos P31, tem população)] dos resultados com coordenadas."""
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
        lista.append((i, ent[i].get("labels", {}).get("en", {}).get("value", ""), ent[i].get("descriptions", {}).get("en", {}).get("value", ""),
                      coord["latitude"], coord["longitude"], tipos, "P1082" in claims))
    return lista


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, a)))


PAISES = {"Q6256", "Q3624078", "Q7275", "Q35657", "Q3024240"}   # país, estado soberano, estado dos EUA, ...
LOCAL = ("stadium", "arena", "venue", "ground", "field", "park", "dome", "center", "centre", "estadio", "stadion", "coliseum")


def cidade(nome, pais):
    """(lat, lon) da cidade, pela Wikidata: o primeiro resultado com população que não seja um país
    (de preferência com o país na descrição)."""
    if not nome:
        return None
    lista = [r for r in _wikidata(nome) if r[6] and not (r[5] & PAISES)]
    if pais:
        no_pais = [r for r in lista if pais.lower() in r[2].lower() or (pais == "England" and "united kingdom" in r[2].lower())]
        lista = no_pais or lista
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

def _overpass(consulta):
    dados = urllib.parse.urlencode({"data": consulta}).encode()
    for i, url in enumerate(OVERPASS):
        try:
            return _pedir(url, dados, tentativas=2)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if i == len(OVERPASS) - 1:
                raise
            print(f"Aviso: Overpass {url} ({e}); a tentar outro servidor")


def _centro(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _parecido(a, b):
    """Quantas palavras (com mais de 2 letras) os dois nomes têm em comum."""
    genericas = {"stadium", "estadio", "stadio", "stade", "stadion", "arena", "the", "de", "do", "da", "del"}
    pa = {w for w in simples(a) if len(w) > 2} - genericas
    pb = {w for w in simples(b) if len(w) > 2} - genericas
    return len(pa & pb)


def afinar(nome, lat, lon, raio):
    """O estádio no OSM com o nome mais parecido (ou o mais perto) num raio: (lat, lon) do centro, ou None."""
    d = _overpass(f'[out:json][timeout:60];nwr(around:{raio},{lat},{lon})[leisure=stadium];out center tags;')
    melhor = None
    for e in d.get("elements", []):
        c = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        if not c:
            continue
        nomes = " ".join(v for k, v in e.get("tags", {}).items() if k.startswith(("name", "alt_name", "official_name", "old_name")))
        nota = (_parecido(nome, nomes), -km(lat, lon, c["lat"], c["lon"]))
        if melhor is None or nota > melhor[0]:
            melhor = (nota, (c["lat"], c["lon"]))
    if melhor and (melhor[0][0] > 0 or -melhor[0][1] < 1.0):   # o nome bate certo, ou está a menos de 1 km
        return melhor[1]
    return None


RUAS = {"motorway": "maior", "trunk": "maior", "primary": "maior", "motorway_link": "media", "trunk_link": "media",
        "primary_link": "media", "secondary": "media", "secondary_link": "media", "tertiary": "media",
        "tertiary_link": "media", "residential": "menor", "living_street": "menor", "unclassified": "menor",
        "pedestrian": "menor"}
FECHADAS = {"agua", "parque", "edif", "estadio"}   # camadas de polígonos (o resto são linhas)


def _consulta(lat, lon):
    r = f"{RAIO_RUAS},{lat},{lon}"
    return f"""[out:json][timeout:150];
(
  way(around:{r})[highway~"^(motorway|trunk|primary|secondary|tertiary|residential|living_street|unclassified|pedestrian)(_link)?$"];
  way(around:{RAIO_ESTRADAS},{lat},{lon})[highway~"^(motorway|trunk|primary)$"];
  way(around:{r})[railway~"^(rail|light_rail|subway|tram)$"];
  way(around:{r})[natural=water];
  relation(around:{r})[natural=water];
  way(around:{r})[waterway~"^(river|canal)$"];
  way(around:{r})[leisure=park];
  way(around:{RAIO_PREDIOS},{lat},{lon})[building];
  nwr(around:800,{lat},{lon})[leisure=stadium];
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
        elif "building" in t:
            por("edif", pts)

    # O estádio: o do nome mais parecido, senão o mais perto do ponto procurado
    estadio = max(estadios, key=lambda s: (_parecido(nome, s[0].get("name", "")), -math.hypot(*_centro(s[1]))), default=None)
    if estadio:
        por("estadio", estadio[1])
    # O relvado: um de futebol dentro do estádio (o maior); senão o de futebol mais perto, a menos de 300 m
    def area(pts):
        return abs(sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))) / 2
    futebol = [c for c in campos if c[0].get("sport") in ("soccer", "football", None) and len(c[1]) >= 4]
    dentro = [c for c in futebol if estadio and _dentro(_centro(c[1]), estadio[1])]
    if dentro:
        relvado = max(dentro, key=lambda c: area(c[1]))[1]
    else:
        perto = [c for c in futebol if math.hypot(*_centro(c[1])) < 300 and area(c[1]) > 4000]
        relvado = min(perto, key=lambda c: math.hypot(*_centro(c[1])))[1] if perto else None
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


def buscar_osm(c, lat, lon, nome):
    """Descarrega e grava o OSM à volta do estádio. Devolve o campo (centro e eixo do relvado) ou None."""
    d = _overpass(_consulta(lat, lon))
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
        if com_osm and not ficheiro_osm(c).exists() and "cidade" != guardado.get("fonte"):
            campo = buscar_osm(c, guardado["lat"], guardado["lon"], e["nome"])
            if campo:   # o ponto do mapa passa a ser o centro do relvado
                guardado = _gravar_entrada(c, {"lon": campo["c"][0], "lat": campo["c"][1], "osm_t": agora, "falhou": None, "erro": None})
        return guardado
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    nome, cid, pais = (sys.argv[1:] + [None, None])[:3]
    print(coordenadas(nome, cid, pais))
