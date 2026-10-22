"""Ao vivo: os jogos a decorrer agora, para o ecrã "Ao vivo" (GET /api/aovivo no serve.py).

É o "presente" do dashboard: o passado (Última jornada) e o futuro (Próxima jornada) vêm do live.json e só mudam
quando se atualiza à mão; isto vai buscar à hora e não escreve no live.json.

- Futebol: o scoreboard da ESPN de cada competição ligada (data/competicoes.json) que tenha jogos hoje, segundo o
  live.json (assim não se pergunta às 26 competições a cada 30 s). O scoreboard já traz o resultado, o minuto e os
  acontecimentos (golos com o marcador, penáltis, vermelhos): os mesmos que o atualizar_futebol.py lê.
- Taça da Liga (se estiver ligada): a API da Liga Portugal, só quando há um jogo dela por estas horas.
- NBA: o scoreboard da ESPN da noite americana.
- Aquecimento: os jogos por começar entram na lista AQUECIMENTO (10 min) antes da hora, sem resultado, e passam a
  "in" quando a ESPN os der como começados (um atrasado fica em aquecimento até lá; adiado/cancelado sai).
- F1: ainda não (ver FONTES: é aí que entra uma função nova, ex.: f1_ao_vivo()).

Cada jogo traz o estádio ("estadio": nome, cidade, coordenadas, se já há o OpenStreetMap à volta), para o mapa do
acompanhamento (ver tools/estadios.py). Só se lê o que já está em cache (data/estadios.json, data/estadios_osm/):
o Ao vivo nunca pede nem descarrega um estádio. Os estádios preparam-se antes (o passo "Estádios" da atualização,
estadios.py --todos). Sem coordenadas, o jogo fica só no cartão; sem o OSM, fica no mapa mas sem o zoom das ruas.
A cara de quem marcou: cara() (GET /api/aovivo/cara), da cache das fotos, do facepack ou da ESPN.

Cada pedido fica em cache CACHE_S segundos (a página pergunta a cada 30 s). As falhas ficam em data/fontes.json
("ESPN ao vivo", "Liga Portugal ao vivo", "ESPN NBA ao vivo"), como as dos atualizadores.

Uso à mão (mostra o que a página recebe):  python tools/aovivo.py
Para testar sem jogos a decorrer:  /api/aovivo?simular=1&desde=<s> (ou --simular): os jogos de ontem (futebol e
NBA) a fingir que estão a decorrer. desde = segundos desde que a página abriu: o relógio começa no minuto 55 e anda
um minuto de jogo a cada 2 s, com os golos a aparecer no minuto em que foram. Aos 10 s entra um golo inventado num
jogo seguido (&golo=<sigla> escolhe a equipa; por omissão, a casa do primeiro jogo seguido com o OSM do estádio).
&aquecimento=<siglas>: os jogos dessas equipas ficam em "Aquecimento" (por omissão, o primeiro jogo de futebol) e
começam aos AQUECIMENTO_SIM_S segundos, do minuto 1. &semruas=<siglas> e &semestadio=<siglas> (separadas por vírgulas): os jogos dessas equipas como se o estádio ainda
não tivesse o OSM / as coordenadas (para ver o Ao vivo sem o zoom e só com o cartão, sem tocar no cache).
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
import estadios                   # noqa: E402  (onde fica cada estádio, para o mapa)
import f1_direto                  # noqa: E402  (a F1 em direto: um item da lista durante as sessões)

CACHE_S = 30
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
JANELA_ANTES = timedelta(hours=3)    # um jogo que começou há menos disto pode estar a decorrer
JANELA_DEPOIS = timedelta(hours=14)  # e os que começam até daqui a isto contam como "hoje"
AQUECIMENTO = timedelta(minutes=10)  # um jogo por começar entra na lista este tempo antes da hora ("Aquecimento")
AQUECIMENTO_SIM_S = 40               # simulação: o jogo em aquecimento começa ao fim disto (segundos)
CANCELADOS = ("STATUS_POSTPONED", "STATUS_CANCELED")   # adiados/cancelados: saem da lista

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
        ev = fut.eventos_do_jogo(comp, lado) if estado != "pre" else []
        nomes = {a.get("id"): a.get("displayName") for d in comp.get("details", []) for a in d.get("athletesInvolved") or []}
        for x in ev:   # o nome completo (é o da cache das fotos e do facepack)
            if nomes.get(x.get("pid")):
                x["pn"] = nomes[x["pid"]]
        jogos.append({
            "id": f"espn:{e['id']}", "sport": "football", "comp": {"chave": chave, "nome": nome},
            "home": equipas.sigla(casa["team"], False), "away": equipas.sigla(fora["team"], False),
            "hs": int(casa.get("score") or 0) if estado != "pre" else None,
            "as": int(fora.get("score") or 0) if estado != "pre" else None,
            "estado": estado, "tempo": texto, "iso": fut.quando(e).astimezone().isoformat(timespec="minutes"),
            "ev": ev, "estadio": estadios.info(comp.get("venue"), "football"),
            "cancelado": e["status"]["type"].get("name") in CANCELADOS,
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
            "estadio": estadios.info(comp.get("venue"), "nba"), "cancelado": tipo.get("name") in CANCELADOS,
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


def _num(m):
    try:
        return int(str(m).split("+")[0])
    except ValueError:
        return 0


def aquecer(j, inicio):
    """Este jogo por começar passa a "Aquecimento" (começa às <inicio>)."""
    j.update(estado="aquecimento", tempo=f"Aquecimento · {inicio.strftime('%H:%M')}", hs=None, ev=[],
             iso=inicio.isoformat(timespec="seconds"))
    j["as"] = None


def simular(jogos, desde, seguir=(), golo=None, aquecimento=()):
    """Os jogos de ontem como se estivessem a decorrer (ver o início do ficheiro). desde = segundos desde que a página abriu.

    Aquecimento: os jogos das equipas em <aquecimento> (por omissão, o primeiro jogo de futebol jogado) ficam em
    "Aquecimento" até desde = AQUECIMENTO_SIM_S, com a hora de início daqui a esse tempo; depois começam no minuto 1."""
    minuto = min(95, 55 + int(desde / 2))
    jogados = [j for j in jogos if j["estado"] != "pre"]
    if aquecimento:
        aquecer_ids = {j["id"] for j in jogados if {j["home"], j["away"]} & set(aquecimento)}
    else:
        bola = sorted((j for j in jogados if j["sport"] == "football"), key=lambda j: (j["comp"]["nome"] or "", j["iso"] or ""))
        aquecer_ids = {bola[0]["id"]} if bola else set()
    falta = AQUECIMENTO_SIM_S - desde
    inicio = datetime.now().astimezone() + timedelta(seconds=falta)
    for j in jogos:
        if j["id"] not in aquecer_ids:
            continue
        if falta > 0:
            aquecer(j, inicio)
        elif j["sport"] == "football":   # já começou: do minuto 1, com os golos de ontem a aparecer no minuto deles
            m = 1 + int(-falta / 2)
            j["ev"] = [e for e in j["ev"] if _num(e["m"]) <= m]
            j["estado"], j["tempo"], j["aq_m"] = "in", f"{m}'", m
    for j in jogos:
        if j["sport"] != "football" or j["estado"] in ("pre", "aquecimento") or "aq_m" in j:
            continue
        j["ev"] = [e for e in j["ev"] if _num(e["m"]) <= minuto]
        j["estado"], j["tempo"] = ("in", f"{minuto}'") if minuto < 95 else ("post", "Terminado")
    # O golo inventado, aos 10 s: num jogo seguido (o da equipa pedida ou o primeiro com o OSM do estádio)
    seguidos = [j for j in jogos if j["sport"] == "football" and j["estado"] == "in" and j["id"] in seguir]
    alvo = next((j for j in seguidos if golo in (j["home"], j["away"])), None) or \
        next((j for j in seguidos if (j.get("estadio") or {}).get("osm")), None) or (seguidos[0] if seguidos else None)
    if alvo and desde >= 10:
        lado = "a" if golo and golo == alvo["away"] else "h"
        # sempre o mesmo marcador (um dos que já tinham marcado antes do minuto 55), para não parecer outro golo
        quem = next((e for e in reversed(alvo["ev"]) if e["s"] == lado and e.get("t") in (None, "pen") and e.get("pid")
                     and _num(e["m"]) <= 55), None)
        alvo["ev"].append({"m": 60, "s": lado, "p": quem["p"] if quem else "Golo simulado",
                           **({"pid": quem["pid"], "pn": quem.get("pn")} if quem else {})})
    for j in jogos:
        j.pop("aq_m", None)
        if j["sport"] == "football" and j["estado"] not in ("pre", "aquecimento"):
            golos = [e for e in j["ev"] if e.get("t") in (None, "pen", "og")]
            j["hs"] = sum(1 for e in golos if (e["s"] == "h") != (e.get("t") == "og"))
            j["as"] = sum(1 for e in golos if (e["s"] == "a") != (e.get("t") == "og"))
    # NBA: os resultados a crescer até ao final de ontem (ou até um final inventado, num jogo por jogar)
    for j in jogos:
        if j["sport"] != "nba" or j["estado"] == "aquecimento":
            continue
        f = min(1, 0.55 + desde / 600)
        if j["id"] in aquecer_ids:   # começou há pouco: do início
            f = min(1, -falta / 600)
        semente = sum(map(ord, j["id"]))
        hs, as_ = (j["hs"], j["as"]) if j["hs"] is not None else (98 + semente % 23, 96 + semente * 7 % 25)
        j["hs"], j["as"] = round(hs * f), round(as_ * f)
        j["estado"], j["tempo"] = "in", f"Q{min(4, 1 + int(f * 4))} {int(12 - (f * 48) % 12)}:{semente % 60:02d}"
    return jogos


def ao_vivo(seguir=(), simulado=False, desde=0, golo=None, sem_ruas=(), sem_estadio=(), aquecimento=()):
    """O que a página do Ao vivo mostra: os jogos a decorrer, os que começam daqui a AQUECIMENTO ou menos (e os que já
    deviam ter começado mas a ESPN ainda não deu como começados), e os seguidos, mesmo que já tenham acabado.
    Adiados e cancelados saem, mesmo seguidos."""
    agora = datetime.now().astimezone()
    if simulado:
        agora -= timedelta(days=1)
    dados = ler_dados()
    teams = dict(dados.get("teams") or {})
    equipas_fut = fut.Equipas(teams, baixar=False)
    equipas_nba = nba.Equipas(teams, baixar=False)
    dia = agora.strftime("%Y%m%d")
    jogos, falhas = [], []

    # Fontes do Ao vivo: (nome em data/fontes.json, função). A F1 é um item só, durante as sessões do fim de semana.
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
        return lista, erros

    FONTES = [
        ("ESPN ao vivo", futebol),
        ("Liga Portugal ao vivo", lambda: (jogos_taca_liga(dados, equipas_fut, agora), [])),
        ("ESPN NBA ao vivo", lambda: (jogos_nba(equipas_nba, agora), [])),
        ("F1 ao vivo", lambda: (f1_direto.entrada_ao_vivo(dados, agora), [])),
    ]
    if simulado:   # sem a Taça da Liga
        FONTES = [FONTES[0], FONTES[2]]
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
    if simulado:
        for j in jogos:   # teste: estádios como se ainda não estivessem preparados (só nesta resposta)
            e, siglas = j.get("estadio"), {j["home"], j["away"]}
            if e and siglas & set(sem_estadio):
                e.update(lat=None, lon=None, osm=False)
            elif e and siglas & set(sem_ruas):
                e["osm"] = False
        jogos = simular(jogos, desde, seguir, golo, aquecimento)
    else:
        for j in jogos:   # a começar (ou atrasado): "Aquecimento" até a ESPN o dar como começado
            h = _quando(j)
            if j["estado"] == "pre" and h and agora - JANELA_ANTES <= h <= agora + AQUECIMENTO:
                aquecer(j, h.astimezone())
    meus = {(dados.get("myTeam") or {}).get("code"), (dados.get("myTeam") or {}).get("selecao") or "PRT"}
    mostrar = [j for j in jogos if not j.get("cancelado") and (j["estado"] in ("in", "aquecimento") or j["id"] in seguir)]
    for j in mostrar:
        j["meu"] = bool({j.get("home"), j.get("away")} & (meus - {None}))
    # Sem jogos a decorrer: o próximo de hoje (dos scoreboards) ou, se não houver, o do live.json
    por_jogar = sorted((j for j in jogos if j["estado"] == "pre"), key=lambda j: j["iso"] or "")
    proximo = None if any(j["estado"] in ("in", "aquecimento") for j in jogos) else (por_jogar[0] if por_jogar else proximo_do_live(dados, agora))
    # a próxima sessão da F1, se vier antes do próximo jogo
    if not simulado and not any(j["estado"] in ("in", "aquecimento") for j in jogos):
        f1 = f1_direto.proximo(dados, agora)
        h = _quando(proximo) if proximo else None
        if f1 and (h is None or datetime.fromisoformat(f1["iso"]) < h):
            proximo = f1
    usados = {c for j in mostrar + ([proximo] if proximo else []) for c in (j.get("home"), j.get("away")) if c}
    return {
        "agora": agora.isoformat(timespec="seconds"),
        "jogos": sorted(mostrar, key=lambda j: (j["comp"]["nome"] or "", j["iso"] or "")),
        "proximo": proximo,
        "teams": {c: teams[c] for c in usados if c in teams},
        "myTeam": dados.get("myTeam"),
        "falhas": falhas,
        "competicoes": [c[1] for c in hoje],
    }


_tranca_caras = threading.Lock()


def cara(pid, nome, sigla):
    """A cara de quem marcou: "img/jogadores/<ficheiro>" ou None. Primeiro a cache das fotos (a mesma do
    atualizar_fotos.py), depois o facepack (só pelo id já guardado em data/facepack_ids.json) e por fim a ESPN pelo
    id do atleta. Uma procura falhada fica registada e só se repete no dia seguinte."""
    import shutil
    import atualizar_fotos as fotos   # noqa: E402  (só quando é preciso)
    if not nome:
        return None
    chave = f"fut|{nome}|{sigla}"
    with _tranca_caras:
        c = fotos.ler_cache().get(chave)
        if c and c.get("file") and (fotos.PASTA / c["file"]).exists():
            return f"img/jogadores/{c['file']}"
        if c and not c.get("file") and time.time() - c.get("t", 0) < fotos.DIAS_PARA_REPETIR * 86400:
            return None
        fotos.PASTA.mkdir(parents=True, exist_ok=True)
        f = None
        fid, pack = fotos.ler_ids_fm().get(chave), fotos.pasta_facepack()
        if fid and pack and (pack / f"face_{fid}.png").is_file():
            f = fotos.ficheiro("fm", nome)
            shutil.copyfile(pack / f"face_{fid}.png", fotos.PASTA / f)
        if not f and str(pid or "").isdigit():
            f = fotos.foto_espn(nome, pid)
        cache = fotos.ler_cache()
        cache[chave] = {"file": f, "t": time.time()}
        fotos.CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return f"img/jogadores/{f}" if f else None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if a != "--simular"]
    print(json.dumps(ao_vivo(args, simulado="--simular" in sys.argv), ensure_ascii=False, indent=1))
