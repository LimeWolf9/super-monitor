"""Prepara o mapa do Ao vivo: os estádios dos jogos dos próximos 7 dias que ainda não estão em cache.

Uso:
    python tools/atualizar_estadios.py           # os jogos de hoje até daqui a 7 dias
    python tools/atualizar_estadios.py --ontem   # também os de ontem (são os que o ?simular=1 mostra)

Para cada competição ligada (data/competicoes.json) e para a NBA, lê o scoreboard da ESPN dos próximos dias e
passa os estádios ao tools/estadios.py: coordenadas (Wikidata) e, no futebol, o OpenStreetMap à volta
(Overpass). Um pedido de cada vez, com pausa; o Overpass demora ~1 minuto por estádio, por isso cada
atualização para de começar estádios novos ao fim de MAX_S segundos (os que ficarem, faz-se na seguinte ou,
num jogo a decorrer, em fundo pelo Ao vivo). Não mexe no live.json.
Só usa a biblioteca standard do Python.
"""

import sys
import time
from datetime import datetime, timedelta

from comum import pedir_json, registar_fonte

import competicoes   # noqa: E402
import estadios      # noqa: E402

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
DIAS = 7
MAX_S = 7 * 60   # o atualizar_tudo.py desiste de um passo ao fim de 10 minutos


def venues(caminho, de, ate, filtro=None):
    """[(data, venue, desporto)] dos jogos do scoreboard da ESPN entre as duas datas.

    A ESPN não aceita intervalos de datas, mas aceita o mês inteiro (dates=AAAAMM): pede-se cada mês e filtra-se."""
    meses = sorted({f"{de:%Y%m}", f"{ate:%Y%m}"})
    eventos = [e for mes in meses for e in pedir_json(f"{ESPN}/{caminho}/scoreboard?dates={mes}&limit=500").get("events", [])]
    lista = []
    for e in eventos:
        if not f"{de:%Y-%m-%d}" <= (e.get("date") or "")[:10] <= f"{ate:%Y-%m-%d}":
            continue
        comp = e["competitions"][0]
        if filtro and not filtro.get("todos"):
            ids = {c["team"]["id"] for c in comp["competitors"]}
            if not ids & set(map(str, filtro.get("equipas") or [])):
                continue
        if comp.get("venue"):
            lista.append((e.get("date") or "", comp["venue"], "nba" if caminho.startswith("basketball") else "football"))
    return lista


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    hoje = datetime.now()
    de = hoje - timedelta(days=1) if "--ontem" in sys.argv else hoje
    ate = hoje + timedelta(days=DIAS)
    todos, erros = [], []
    fontes = [(f"soccer/{liga}", nome, filtro) for _c, nome, liga, _t, filtro in competicoes.a_buscar()]
    fontes.append(("basketball/nba", "NBA", None))
    for caminho, nome, filtro in fontes:
        try:
            todos += venues(caminho, de, ate, filtro)
        except Exception as e:
            erros.append(f"{nome} ({e})")
    # Os jogos mais próximos primeiro, e cada estádio uma só vez
    vistos, lista = set(), []
    for _quando, v, desporto in sorted(todos, key=lambda x: x[0]):
        c = estadios.chave(v)
        if c not in vistos:
            vistos.add(c)
            lista.append((v, desporto))
    t0 = time.time()
    ja = novos = falhas = 0
    for v in lista:
        if time.time() - t0 > MAX_S:
            print("Tempo esgotado: os estádios que faltam ficam para a próxima atualização.")
            break
        a, b, c = estadios.preparar([v])
        ja, novos, falhas = ja + a, novos + b, falhas + c
    registar_fonte("Estádios (Wikidata, OpenStreetMap)", itens=novos, esperado=False,
                   aviso=f"{falhas} estádios sem coordenadas" if falhas else ("; ".join(erros) or None))
    print(f"Estádios: {ja} já em cache, {novos} novos, {falhas} sem dados.")


if __name__ == "__main__":
    main()
