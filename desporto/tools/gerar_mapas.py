"""Gera os mapas de base do Ao vivo (web/mapas/<regiao>.json) a partir do Natural Earth (domínio público).

Uso:  python tools/gerar_mapas.py <pasta com os .geojson do Natural Earth> [regiões, por omissão todas]

Ficheiros precisos (de https://github.com/nvkelso/natural-earth-vector/tree/master/geojson):
  ne_50m_admin_0_countries, ne_50m_lakes                       os países (vista geral)
  ne_10m_urban_areas, ne_10m_coastline, ne_10m_rivers_lake_centerlines, ne_10m_lakes,
  ne_10m_populated_places_simple                               o detalhe a meio do zoom (cidades, costa, rios)
  ne_50m_admin_1_states_provinces_lakes                        os estados dos EUA (só no mapa da América do Norte)

Os mapas guardam longitude/latitude (a projeção faz-se no browser, em web/js/mapa.js), em inteiros com
deltas para ficarem pequenos: cada linha é [lon0, lat0, dlon1, dlat1, ...] em centésimos de grau (países) ou
milésimos (detalhe). O mapa da América do Norte (NBA) só tem os países e a divisão por estados dos EUA,
sem detalhe nem cidades. Cada região é cortada à sua caixa e simplificada. Só se corre quando se quer mudar os
mapas (os .json vão no repositório). Só usa a biblioteca standard do Python.
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "web" / "mapas"

# regiao -> (centro da projeção [lon, lat], caixa (lon0, lon1, lat0, lat1)); a Europa vai até ao Cazaquistão
# (Astana, Almaty: jogos da UEFA). As caixas são as mesmas de continente() em web/js/mapa.js.
REGIOES = {
    "europa": ([10, 50], (-32, 82, 25, 72)),
    "america_norte": ([-96, 39], (-170, -48, 12, 72)),
    "america_sul": ([-60, -20], (-95, -28, -58, 15)),
}
SO_ESTADOS = {"america_norte"}   # regiões sem detalhe a meio do zoom, só com os estados dos EUA
POP_MIN = 150_000   # cidades com nome a meio do zoom


def ler(pasta, nome):
    return json.loads((pasta / f"{nome}.geojson").read_text(encoding="utf-8"))["features"]


def aneis(g):
    """Todas as linhas/anéis de uma geometria (lista de listas de [lon, lat])."""
    if not g:
        return []
    t, c = g["type"], g["coordinates"]
    if t == "LineString":
        return [c]
    if t in ("MultiLineString", "Polygon"):
        return c
    if t == "MultiPolygon":
        return [r for p in c for r in p]
    return []


def cortar_anel(anel, caixa):
    """Sutherland-Hodgman: o anel cortado ao retângulo da caixa (pode ficar vazio)."""
    x0, x1, y0, y1 = caixa
    lados = [(lambda p: p[0] >= x0, lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0]))),
             (lambda p: p[0] <= x1, lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0]))),
             (lambda p: p[1] >= y0, lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0)),
             (lambda p: p[1] <= y1, lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1))]
    pts = [tuple(p[:2]) for p in anel]
    for dentro, corte in lados:
        if not pts:
            break
        novo = []
        for i, p in enumerate(pts):
            q = pts[i - 1]
            if dentro(p):
                if not dentro(q):
                    novo.append(corte(q, p))
                novo.append(p)
            elif dentro(q):
                novo.append(corte(q, p))
        pts = novo
    return pts


def cortar_linha(linha, caixa):
    """Os pedaços da linha que ficam dentro da caixa."""
    x0, x1, y0, y1 = caixa
    pedacos, atual = [], []
    for p in linha:
        if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
            atual.append(tuple(p[:2]))
        else:
            if len(atual) > 1:
                pedacos.append(atual)
            atual = []
    if len(atual) > 1:
        pedacos.append(atual)
    return pedacos


def simplificar(pts, tol):
    """Douglas-Peucker (em graus), sem recursão."""
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
            if n2:
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / n2))
                ex, ey = ax + t * dx - px, ay + t * dy - py
            else:
                ex, ey = px - ax, py - ay
            d = ex * ex + ey * ey
            if d > pior:
                pior, k = d, i
        if k > 0 and pior > tol * tol:
            manter[k] = True
            pilha += [(a, k), (k, b)]
    return [p for p, m in zip(pts, manter) if m]


def codificar(pts, escala):
    """[lon0, lat0, dlon1, dlat1, ...] em inteiros (deltas), sem pontos repetidos."""
    saida, ant = [], None
    for lon, lat in pts:
        q = (round(lon * escala), round(lat * escala))
        if q == ant:
            continue
        saida += [q[0], q[1]] if ant is None else [q[0] - ant[0], q[1] - ant[1]]
        ant = q
    return saida


def poligonos(features, caixa, tol, escala, minimo=3):
    lista = []
    for f in features:
        for anel in aneis(f["geometry"]):
            pts = simplificar(cortar_anel(anel, caixa), tol)
            if len(pts) >= minimo:
                c = codificar(pts, escala)
                if len(c) >= 2 * minimo:
                    lista.append(c)
    return lista


def linhas(features, caixa, tol, escala):
    lista = []
    for f in features:
        for linha in aneis(f["geometry"]):
            for p in cortar_linha(linha, caixa):
                pts = simplificar(p, tol)
                if len(pts) > 1:
                    lista.append(codificar(pts, escala))
    return lista


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pasta = Path(sys.argv[1])
    paises = ler(pasta, "ne_50m_admin_0_countries")
    lagos50 = ler(pasta, "ne_50m_lakes")
    urb, costa = ler(pasta, "ne_10m_urban_areas"), ler(pasta, "ne_10m_coastline")
    rios, lagos10 = ler(pasta, "ne_10m_rivers_lake_centerlines"), ler(pasta, "ne_10m_lakes")
    sitios = ler(pasta, "ne_10m_populated_places_simple")
    estados = [f for f in ler(pasta, "ne_50m_admin_1_states_provinces_lakes") if f["properties"].get("adm0_a3") == "USA"]
    SAIDA.mkdir(parents=True, exist_ok=True)
    pedidas = sys.argv[2:] or list(REGIOES)
    for nome, (centro, caixa) in REGIOES.items():
        if nome not in pedidas:
            continue
        # os países continuam para lá da caixa (uma vista larga, ex.: Lisboa a Almaty, mostra até à China e ao Sara)
        larga = (caixa[0] - 8, caixa[1] + 25, caixa[2] - 15, caixa[3] + 6)
        mapa = {
            "_fonte": "Natural Earth (naturalearthdata.com), domínio público. Gerado por tools/gerar_mapas.py.",
            "regiao": nome, "centro": centro, "caixa": caixa,
            "paises": [{"n": f["properties"].get("ADM0_A3"), "a": a}
                       for f in paises for a in poligonos([f], larga, 0.03, 100)],
            "lagos": poligonos(lagos50, larga, 0.03, 100, 4),
        }
        if nome in SO_ESTADOS:
            mapa["estados"] = poligonos(estados, larga, 0.03, 100)
        else:
            mapa["detalhe"] = {
                "urb": poligonos(urb, caixa, 0.004, 1000, 4),
                "costa": linhas(costa, caixa, 0.004, 1000),
                "rios": linhas(rios, caixa, 0.004, 1000),
                "lagos": poligonos(lagos10, caixa, 0.004, 1000, 4),
            }
            mapa["sitios"] = sorted(({"n": f["properties"]["name"], "c": [round(v, 3) for v in f["geometry"]["coordinates"][:2]],
                                     "p": f["properties"].get("pop_max") or 0}
                                    for f in sitios
                                    if (f["properties"].get("pop_max") or 0) >= POP_MIN
                                    and caixa[0] <= f["geometry"]["coordinates"][0] <= caixa[1]
                                    and caixa[2] <= f["geometry"]["coordinates"][1] <= caixa[3]),
                                   key=lambda s: -s["p"])
        destino = SAIDA / f"{nome}.json"
        destino.write_text(json.dumps(mapa, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        extra = (f"{len(mapa['estados'])} estados" if "estados" in mapa else
                 f"{len(mapa['detalhe']['urb'])} manchas urbanas, {len(mapa['sitios'])} cidades")
        print(f"{destino.name}: {destino.stat().st_size // 1024} KB, {len(mapa['paises'])} polígonos, {extra}")


if __name__ == "__main__":
    main()
