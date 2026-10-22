"""Prepara o mapa do Ao vivo: os estádios dos jogos dos próximos 30 dias que ainda faltam (o passo "Estádios").

Uso:
    python tools/atualizar_estadios.py           # os jogos de hoje até daqui a 30 dias
    python tools/atualizar_estadios.py --ontem   # também os de ontem (são os que o ?simular=1 mostra)
    python tools/atualizar_estadios.py --seco    # só diz o que falta, sem descarregar nada

1. A lista: os estádios dos jogos dos próximos DIAS dias de cada competição ligada (data/competicoes.json) e da
   NBA, dos calendários da ESPN (o jogo mais próximo primeiro).
2. Compara-a com data/estadios.json e data/estadios_osm/ (estadios.em_falta): falta um estádio sem coordenadas, um
   de futebol sem o ficheiro do OSM, ou um marcado com refazer.
3. Só se faltar algum se descarrega (estadios.preparar): as coordenadas (Wikidata) e, no futebol, o OpenStreetMap
   (Overpass), com as regras do --todos: no máximo OSM_POR_DIA por dia, a vaga no /api/status, para ao fim de 3
   estádios seguidos com erro de rede e o Overpass fica 24 h em pausa. Para de começar estádios ao fim de MAX_S.
4. Sem nada em falta não se liga à Wikidata nem ao Overpass (nem ao /api/status): "Estádios: 0 em falta, sem
   ligação ao OSM".
O que fica a faltar vai para data/estadios_em_falta.json (a página /definicoes mostra-o). Não mexe no live.json.
Só usa a biblioteca standard do Python.
"""

import sys
import time
from datetime import datetime, timedelta

from comum import pedir_json, registar_fonte

import competicoes   # noqa: E402
import estadios      # noqa: E402

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
DIAS = 30
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
    lista, a_fazer = estadios.em_falta([(v, desporto) for _quando, v, desporto in sorted(todos, key=lambda x: x[0])])
    if not a_fazer:
        estadios.gravar_em_falta(lista, DIAS)
        registar_fonte("Estádios (Wikidata, OpenStreetMap)", itens=0, esperado=False, aviso="; ".join(erros) or None)
        print(f"Estádios: {len(lista)} dos próximos {DIAS} dias, 0 em falta, sem ligação ao OSM.")
        return
    print(f"Estádios: {len(lista)} dos próximos {DIAS} dias, {len(a_fazer)} em falta: "
          + ", ".join(e["nome"] for e, _f in a_fazer[:10]) + (" ..." if len(a_fazer) > 10 else ""), flush=True)
    if "--seco" in sys.argv:
        estadios.gravar_em_falta(lista, DIAS)
        return
    novos, faltam, parou = estadios.preparar(a_fazer, mostrar=lambda t: print(t, flush=True), ate=time.time() + MAX_S)
    estadios.gravar_em_falta(lista, DIAS)
    registar_fonte("Estádios (Wikidata, OpenStreetMap)", itens=novos, esperado=False,
                   aviso="; ".join(([f"{faltam} estádios por fazer"] if faltam else []) + ([parou] if parou else []) + erros) or None)
    print(f"Estádios: {len(lista) - len(a_fazer)} já em cache, {novos} novos, {faltam} por fazer"
          + (f" ({parou})" if parou else "") + ".")

if __name__ == "__main__":
    main()
