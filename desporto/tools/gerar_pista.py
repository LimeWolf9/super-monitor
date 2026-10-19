"""Converte o traçado de um circuito no desenho SVG usado na cena "f1-gp". Usado pelo atualizar_f1.py.

Os traçados vêm de data/circuitos/f1-circuits.geojson (https://github.com/bacinger/f1-circuits, dados do
OpenStreetMap, licença ODbL). A ordem dos pontos segue o sentido da corrida, e o 1.º ponto é a linha de meta.
"""

import math

LARGURA = 400   # largura do viewBox do SVG (a altura sai da proporção real do circuito)
MARGEM = 14     # margem à volta do traçado, em unidades do viewBox


def para_svg(pontos):
    """Longitude/latitude -> coordenadas planas (norte para cima), ajustadas ao viewBox."""
    lon_min = min(p[0] for p in pontos); lon_max = max(p[0] for p in pontos)
    lat_min = min(p[1] for p in pontos); lat_max = max(p[1] for p in pontos)
    k = math.cos(math.radians((lat_min + lat_max) / 2))   # 1º de longitude é mais curto longe do equador
    largura_real = (lon_max - lon_min) * k
    altura_real = lat_max - lat_min
    escala = (LARGURA - 2 * MARGEM) / largura_real
    altura = altura_real * escala + 2 * MARGEM
    xy = [(MARGEM + (lon - lon_min) * k * escala, MARGEM + (lat_max - lat) * escala) for lon, lat, *_ in pontos]
    return xy, round(altura)


def gerar_de_pontos(pontos):
    """Lista de [lon, lat] (no sentido da corrida) -> desenho da pista para o live.json."""
    xy, altura = para_svg(pontos)
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in xy) + " Z"
    # Linha de meta: pequeno traço perpendicular à direcção da corrida no 1.º ponto
    (x0, y0), (x1, y1) = xy[0], xy[1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1
    px, py = -dy / n * 9, dx / n * 9
    inicio = [round(x0 - px, 1), round(y0 - py, 1), round(x0 + px, 1), round(y0 + py, 1)]
    return {"viewBox": f"0 0 {LARGURA} {altura}", "d": d, "start": inicio}

