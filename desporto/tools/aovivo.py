"""Ao vivo: os jogos a decorrer agora, para o ecrã "Ao vivo" (GET /api/aovivo no serve.py).

É o "presente" do dashboard: o passado (Última jornada) e o futuro (Próxima jornada) vêm do live.json e só mudam
quando se atualiza à mão; isto vai buscar à hora e não escreve no live.json.

- Futebol: o scoreboard da ESPN de cada competição ligada (data/competicoes.json) que tenha jogos hoje, segundo o
  live.json (assim não se pergunta às 26 competições a cada 30 s). O scoreboard já traz o resultado, o minuto e os
  acontecimentos (golos com o marcador, penáltis, vermelhos): os mesmos que o atualizar_futebol.py lê.
- Taça da Liga (se estiver ligada): a API da Liga Portugal, só quando há um jogo dela por estas horas.
- NBA: o scoreboard da ESPN da noite americana.
- F1: ainda não (ver FONTES: é aí que entra uma função nova, ex.: f1_ao_vivo()).

Cada pedido fica em cache CACHE_S segundos (a página pergunta a cada 30 s). As falhas ficam em data/fontes.json
("ESPN ao vivo", "Liga Portugal ao vivo", "ESPN NBA ao vivo"), como as dos atualizadores.

Uso à mão (mostra o que a página recebe):  python tools/aovivo.py
Para testar sem jogos a decorrer:  /api/aovivo?simular=1 (ou --simular): os jogos de ontem a fingir que estão a
decorrer, com o relógio a andar 6 minutos de jogo por cada minuto real e os golos a aparecer no minuto em que foram.
"""

import copy
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from comum import ler_dados, pedir_json, registar_fonte

import atualizar_futebol as fut   # noqa: E402  (siglas, eventos e o mapa das equipas da ESPN)
import atualizar_nba as nba       # noqa: E402
import competicoes                # noqa: E402

CACHE_S = 30
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
JANELA_ANTES = timedelta(hours=3)    # um jogo que começou há menos disto pode estar a decorrer
JANELA_DEPOIS = timedelta(hours=14)  # e os que começam até daqui a isto contam como "hoje"

_cache, _tranca = {}, threading.Lock()


def em_cache(chave, buscar):
    """O resultado de buscar(), guardado CACHE_S segundos (por chave)."""
    agora = time.time()
    with _tranca:
        c = _cache.get(chave)
        if c and agora - c[0] < CACHE_S:
            return c[1]
    valor = buscar()
    with _tranca:
        _cache[chave] = (time.time(), valor)
    return valor


def _quando(m):
    try:
        return datetime.fromisoformat(m["iso"])
    except (KeyError, TypeError, ValueError):
        return None


def competicoes_de_hoje(dados, agora):
    """[(chave, nome, liga ESPN, filtro)] das competições ligadas com algum jogo por estas horas, segundo o live.json.

    Sem horas no live.json (atualizado antes de haver "iso"), usa a janela; sem nada disso, pergunta a todas."""
    futebol = dados.get("football") or {}
    escolhidas = []
    for chave, nome, liga, _tipo, filtro in competicoes.a_buscar():
        L = futebol.get(chave)
        if not L:
            continue
        horas = [_quando(m) for m in (L.get("results") or []) + (L.get("next") or [])]
        horas = [h for h in horas if h]
        if horas:
            hoje = any(agora - JANELA_ANTES <= h <= agora + JANELA_DEPOIS for h in horas)
        else:
            j = L.get("janela") or {}
            hoje = any(v and abs(datetime.fromisoformat(v) - agora) <= JANELA_DEPOIS for v in (j.get("ultimo"), j.get("proximo")))
        if hoje:
            escolhidas.append((chave, nome, liga, filtro))
    return escolhidas


def estado_espn(e):
    """("pre" | "in" | "post", texto curto): "34'", "Intervalo", "Terminado", "20:00"..."""
    s = e["status"]
    tipo = s["type"]
    estado = tipo.get("state", "pre")
    if tipo.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED"):
        return "post", "Adiado"
    if estado == "post":
        return "post", "Terminado"
    if estado == "in":
        if tipo.get("name") == "STATUS_HALFTIME":
            return "in", "Intervalo"
        return "in", s.get("displayClock") or tipo.get("shortDetail") or "a decorrer"
    return "pre", fut.quando(e).astimezone().strftime("%H:%M")


def jogos_futebol(chave, nome, liga, filtro, equipas, dia):
    d = em_cache(f"fut:{liga}:{dia}", lambda: pedir_json(f"{ESPN}/soccer/{liga}/scoreboard?dates={dia}"))
    jogos = []
    for e in d.get("events", []):
        comp = e["competitions"][0]
        casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        if filtro and not filtro.get("todos") and not ({casa["team"]["id"], fora["team"]["id"]} & set(map(str, filtro.get("equipas") or []))):
            continue   # seleções: só as escolhidas
        estado, texto = estado_espn(e)
        lado = {casa["team"]["id"]: "h", fora["team"]["id"]: "a"}
        jogos.append({
            "id": f"espn:{e['id']}", "sport": "football", "comp": {"chave": chave, "nome": nome},
            "home": equipas.sigla(casa["team"], False), "away": equipas.sigla(fora["team"], False),
            "hs": int(casa.get("score") or 0) if estado != "pre" else None,
            "as": int(fora.get("score") or 0) if estado != "pre" else None,
            "estado": estado, "tempo": texto, "iso": fut.quando(e).astimezone().isoformat(timespec="minutes"),
            "ev": fut.eventos_do_jogo(comp, lado) if estado != "pre" else [],
        })
    return jogos


def jogos_taca_liga(dados, equipas_fut, agora):
    """A Taça da Liga vem da Liga Portugal (não está na ESPN). Só se pergunta se há um jogo dela por estas horas."""
    L = (dados.get("football") or {}).get("tl")
    if not L or not competicoes.ler().get("tl"):
        return []
    horas = [_quando(m) for m in (L.get("results") or []) + (L.get("next") or [])]
    if not any(h and agora - JANELA_ANTES <= h <= agora + timedelta(minutes=15) for h in horas):
        return []
    import atualizar_taca_liga as tl   # noqa: E402  (só quando é preciso)
    copia = copy.deepcopy(dados)
    tl_nova = em_cache("tl", lambda: tl.montar(copia, datetime.now(timezone.utc), baixar=False))
    jogos = []
    for m in (tl_nova.get("results") or []) + (tl_nova.get("next") or []):
        h = _quando(m)
        estado = "in" if m.get("live") else "post" if m.get("hs") is not None else "pre"
        if estado == "pre" and not (h and h <= agora + JANELA_DEPOIS):
            continue
        jogos.append({
            "id": f"tl:{m.get('id')}", "sport": "football", "comp": {"chave": "tl", "nome": tl_nova.get("name") or "Taça da Liga"},
            "home": m["home"], "away": m["away"], "hs": m.get("hs"), "as": m.get("as"), "estado": estado,
            "tempo": (m.get("clock") or "a decorrer") if estado == "in" else "Terminado" if estado == "post" else (h.strftime("%H:%M") if h else ""),
            "iso": m.get("iso"), "ev": m.get("ev") or [],
        })
    equipas_fut.teams.update({k: v for k, v in copia.get("teams", {}).items() if k not in equipas_fut.teams})
    return jogos


def jogos_nba(equipas, agora):
    """A noite americana: o dia de Nova Iorque (aproximado: UTC-5)."""
    dia = (agora.astimezone(timezone.utc) - timedelta(hours=5)).strftime("%Y%m%d")
    d = em_cache(f"nba:{dia}", lambda: pedir_json(f"{ESPN}/basketball/nba/scoreboard?dates={dia}"))
    jogos = []
    for e in d.get("events", []):
        comp = e["competitions"][0]
        casa = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        fora = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        tipo = e["status"]["type"]
        estado = tipo.get("state", "pre")
        texto = ("Terminado" if estado == "post" else
                 (tipo.get("shortDetail") or e["status"].get("displayClock") or "a decorrer") if estado == "in" else
                 fut.quando(e).astimezone().strftime("%H:%M"))
        jogos.append({
            "id": f"nba:{e['id']}", "sport": "nba", "comp": {"chave": "nba", "nome": "NBA"},
            "home": equipas.sigla(casa["team"]), "away": equipas.sigla(fora["team"]),
            "hs": int(casa.get("score") or 0) if estado != "pre" else None,
            "as": int(fora.get("score") or 0) if estado != "pre" else None,
            "estado": estado, "tempo": texto, "iso": fut.quando(e).astimezone().isoformat(timespec="minutes"), "ev": [],
        })
    return jogos


def proximo_do_live(dados, agora):
    """Sem jogos hoje: o próximo jogo das competições ligadas, do live.json (com a hora, se a tiver)."""
    melhor = None
    for chave, L in (dados.get("football") or {}).items():
        for m in (L.get("next") or []) + [r for r in (L.get("results") or []) if r.get("hs") is None]:
            h = _quando(m)
            if h and h > agora and (melhor is None or h < melhor[0]):
                melhor = (h, {**m, "comp": {"chave": chave, "nome": L.get("name")}, "sport": "football"})
    return melhor[1] if melhor else None


INICIO_SIMULACAO = time.time()


def simular(jogos):
    """Os jogos acabados de ontem como se estivessem a decorrer: minuto = 6 x minutos reais desde o arranque (até 95)."""
    minuto = int((time.time() - INICIO_SIMULACAO) / 10) % 100
    for j in jogos:
        if j["estado"] != "post" or j["sport"] != "football":
            continue
        def num(m):
            try:
                return int(str(m).split("+")[0])
            except ValueError:
                return 0
        ev = [e for e in j["ev"] if num(e["m"]) <= minuto]
        golos = [e for e in ev if e.get("t") in (None, "pen", "og")]
        j["hs"] = sum(1 for e in golos if (e["s"] == "h") != (e.get("t") == "og"))
        j["as"] = sum(1 for e in golos if (e["s"] == "a") != (e.get("t") == "og"))
        j["ev"], j["estado"] = ev, ("in" if minuto < 95 else "post")
        j["tempo"] = "Intervalo" if 45 < minuto < 50 else f"{minuto}'" if minuto < 95 else "Terminado"
    return jogos


def ao_vivo(seguir=(), simulado=False):
    """O que a página do Ao vivo mostra: os jogos a decorrer (e os seguidos, mesmo que já tenham acabado)."""
    agora = datetime.now().astimezone()
    if simulado:
        agora -= timedelta(days=1)
    dados = ler_dados()
    teams = dict(dados.get("teams") or {})
    equipas_fut = fut.Equipas(teams, baixar=False)
    equipas_nba = nba.Equipas(teams, baixar=False)
    dia = agora.strftime("%Y%m%d")
    jogos, falhas = [], []

    # Fontes do Ao vivo: (nome em data/fontes.json, função). A F1 entra aqui quando houver uma fonte em direto.
    hoje = competicoes_de_hoje(dados, agora)

    def futebol():
        with ThreadPoolExecutor(max_workers=6) as ex:
            futuros = {c[1]: ex.submit(jogos_futebol, *c, equipas_fut, dia) for c in hoje}
        lista, erros = [], []
        for nome, f in futuros.items():
            try:
                lista += f.result()
            except Exception as e:
                erros.append(f"{nome} ({e})")
        if erros and len(erros) == len(futuros):
            raise RuntimeError("; ".join(erros))
        return (simular(lista) if simulado else lista), erros

    FONTES = [
        ("ESPN ao vivo", futebol),
        ("Liga Portugal ao vivo", lambda: (jogos_taca_liga(dados, equipas_fut, agora), [])),
        ("ESPN NBA ao vivo", lambda: (jogos_nba(equipas_nba, agora), [])),
        # ("F1 ao vivo", f1_ao_vivo),   # quando houver uma fonte gratuita em direto
    ]
    if simulado:
        FONTES = FONTES[:1]
    for nome, buscar in FONTES:
        if simulado:   # não mistura a simulação com o registo das fontes a sério
            lista, erros = buscar()
            jogos += lista
            continue
        try:
            lista, erros = buscar()
            jogos += lista
            registar_fonte(nome, itens=sum(1 for j in lista if j["estado"] == "in"), esperado=False,
                           aviso="; ".join(erros) or None)
            falhas += [f"{nome}: {e}" for e in erros]
        except Exception as e:
            registar_fonte(nome, erro=e)
            falhas.append(f"{nome}: {e}")

    seguir = set(seguir)
    meus = {(dados.get("myTeam") or {}).get("code"), (dados.get("myTeam") or {}).get("selecao") or "PRT"}
    mostrar = [j for j in jogos if j["estado"] == "in" or j["id"] in seguir]
    for j in mostrar:
        j["meu"] = j["home"] in meus or j["away"] in meus
    # Sem jogos a decorrer: o próximo de hoje (dos scoreboards) ou, se não houver, o do live.json
    por_jogar = sorted((j for j in jogos if j["estado"] == "pre"), key=lambda j: j["iso"] or "")
    proximo = None if any(j["estado"] == "in" for j in jogos) else (por_jogar[0] if por_jogar else proximo_do_live(dados, agora))
    usados = {c for j in mostrar + ([proximo] if proximo else []) for c in (j["home"], j["away"])}
    return {
        "agora": agora.isoformat(timespec="seconds"),
        "jogos": sorted(mostrar, key=lambda j: (j["comp"]["nome"] or "", j["iso"] or "")),
        "proximo": proximo,
        "teams": {c: teams[c] for c in usados if c in teams},
        "myTeam": dados.get("myTeam"),
        "falhas": falhas,
        "competicoes": [c[1] for c in hoje],
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if a != "--simular"]
    print(json.dumps(ao_vivo(args, simulado="--simular" in sys.argv), ensure_ascii=False, indent=1))
