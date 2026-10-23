"""Agenda da atualização automática: diz o que atualizar e quando (o MonitorHub é que corre).

Uso:
    python tools/agenda.py --proximas                 # JSON com o que está na hora e o que vem aí (o hub chama isto)
    python tools/agenda.py --proximas --agora 2026-10-24T22:00   # o mesmo, como se fosse a essa hora (para testar)
    python tools/agenda.py --estado                   # o que a página /definicoes mostra (ligada, próximas, registo)
    python tools/agenda.py --ligar | --desligar       # o interruptor (o mesmo da página /definicoes)

O hub (hub/hub.py, entrada "agenda" no apps.json) chama o --proximas a cada minuto e depois de cada execução. Quando
a agenda está ligada, corre as tarefas com "quando" já passado, uma de cada vez, com o comando "atualizar" do
apps.json mais os "args" da tarefa (ex.: tools/atualizar_tudo.py --passos noticias,destaques), e escreve cada
execução em data/agenda_registo.json. Este ficheiro decide tudo a partir do live.json, do registo e da hora; o hub
não sabe nada de desporto.

Regras (hora deste PC):
- Entre a 01:00 e as 07:00 não corre nada. Às 07:00 atualiza tudo (como o botão "Atualizar").
- Notícias de 30 em 30 min, das 08:00 às 00:30.
- NBA às 18:00 (a noite fica para as 07:00).
- Futebol, por competição: 2h05 depois do início de cada jogo (os da mesma competição que acabam perto uns dos
  outros vão juntos). Se o jogo ainda não acabou nos dados novos, tenta outra vez 20 min depois, no máximo 3 vezes
  (prolongamento, penáltis, atrasos). A Taça da Liga tem o seu passo (taca_liga).
- F1: 1 h e 3 h depois do fim de cada sessão (do live.json só vem o início: TL 1 h, qualificações 1 h, sprint 1 h,
  corrida 2 h). As sessões ficam lembradas em data/agenda_memoria.json, porque o live.json passa para o GP seguinte
  mal a corrida começa.
- Depois de cada parte correm os destaques (as mesmas partes da /definicoes: atualizar_tudo.PARTES).
- Se já estava a correr uma atualização (o hub regista "ocupado"), tenta 5 min depois.
- Se uma parte falha 3 vezes seguidas, espera 30 min, depois 1 h, depois 2 h (a tarefa diz porquê em "nota").
- Só conta o que passou depois de ligada (não há uma fila de atrasadas ao ligar); de cada tarefa que se repete só
  fica a mais recente que falta; o que ficou antes das 07:00 já foi coberto pela atualização das 07:00.

O interruptor está em data/agenda_config.json: {"ligada": false} (desligada se o ficheiro não existir). Para testar
pode ter "testes": [{"em": "2026-10-23T09:15", "passos": "noticias"}] (uma tarefa de uma vez, a essa hora).
Registo (data/agenda_registo.json, o hub escreve, últimas 200): [{"em", "id", "chave", "nome", "resultado"
("ok" | "falhou" | "ocupado"), "erro", "segundos"}].
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atualizar_tudo   # noqa: E402  (as partes e o gravar_json atómico)
import competicoes      # noqa: E402  (as competições ligadas)

RAIZ = Path(__file__).resolve().parent.parent
LIVE = RAIZ / "data" / "live.json"
CONFIG = RAIZ / "data" / "agenda_config.json"
REGISTO = RAIZ / "data" / "agenda_registo.json"
MEMORIA = RAIZ / "data" / "agenda_memoria.json"

NOITE = (1, 7)                       # das 01:00 às 07:00 não corre nada
HORA_COMPLETA = 7
NOTICIAS = (8, 30, 33)               # das 08:00, de 30 em 30 min, mais 33 vezes (a última às 00:30)
HORA_NBA = 18
FIM_JOGO = timedelta(hours=2, minutes=5)
JUNTOS = timedelta(minutes=30)       # jogos da mesma competição que acabam até 30 min uns dos outros: uma só vez
DE_NOVO = timedelta(minutes=20)      # jogo ainda por acabar: tenta outra vez 20 min depois...
VEZES_JOGO = 4                       # ...no máximo 3 vezes depois da primeira
OCUPADO = timedelta(minutes=5)
PAUSAS = (30, 60, 120)               # minutos de espera depois de 3, 4, 5+ falhas seguidas
F1_DURACAO = {"Corrida": 2}          # horas; as outras sessões 1 h
F1_DEPOIS = (1, 3)                   # horas depois do fim da sessão
HORIZONTE = timedelta(days=2)        # até onde se mostram as próximas
PASSOS = {i: p for i, _, p in atualizar_tudo.PARTES}   # "futebol" -> ["futebol", "onze", "destaques"]


def ler_json(caminho, omissao):
    return atualizar_tudo.ler_json(caminho, omissao)


def ler_config():
    c = ler_json(CONFIG, {})
    return c if isinstance(c, dict) else {}


def gravar_config(ligada):
    """Liga ou desliga. Ao ligar guarda a hora: o que devia ter corrido antes disso não corre."""
    c = ler_config()
    if ligada and not c.get("ligada"):
        c["ligada_em"] = datetime.now().astimezone().isoformat(timespec="seconds")
    c["ligada"] = bool(ligada)
    atualizar_tudo.gravar_json(CONFIG, c)
    return c


def ler_registo():
    r = ler_json(REGISTO, [])
    return r if isinstance(r, list) else []


def hora(iso):
    """datetime com fuso (os do live.json têm fuso; um sem fuso é a hora deste PC)."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d if d.tzinfo else d.astimezone()


def noite(d):
    return NOITE[0] <= d.astimezone().hour < NOITE[1]


def a_hora(dia, h, m=0):
    """Dia (date) a essa hora local, com o fuso certo (muda com a hora de verão)."""
    return datetime(dia.year, dia.month, dia.day, h, m).astimezone()


def tarefa(chave, nome, quando, passos, competicao=None, ident=None):
    args = ["--passos", ",".join(passos)] if passos else []
    if competicao:
        args += ["--competicoes", competicao]
    # _desde: a hora marcada (o "quando" pode passar para mais tarde: outra tentativa, ocupado, pausa)
    return {"id": ident or f"{chave}@{quando.astimezone():%Y-%m-%dT%H:%M}", "chave": chave, "nome": nome,
            "quando": quando, "_desde": quando, "args": args}


# ------------------------------------------------------------------ o que se repete a horas certas
def repetidas(agora):
    """Atualização completa, notícias e NBA, de ontem a depois de amanhã."""
    lista = []
    for n in range(-1, 3):
        dia = (agora + timedelta(days=n)).date()
        lista.append(tarefa("completa", "Tudo", a_hora(dia, HORA_COMPLETA), None))
        lista.append(tarefa("nba", "NBA", a_hora(dia, HORA_NBA), PASSOS["nba"]))
        h, passo, vezes = NOTICIAS
        inicio = a_hora(dia, h)
        for k in range(vezes + 1):
            # soma em hora "de parede" (a hora de verão não baralha as meias horas)
            q = (inicio.replace(tzinfo=None) + timedelta(minutes=passo * k)).astimezone()
            lista.append(tarefa("noticias", "Notícias", q, PASSOS["noticias"]))
    return lista


def sessoes_f1(dados, agora):
    """As sessões do GP (do live.json e as lembradas), sem as que acabaram há mais de 2 dias."""
    mem = ler_json(MEMORIA, {})
    vistas = {s["date"]: s["name"] for s in mem.get("f1", []) if isinstance(s, dict) and s.get("date")}
    antes = dict(vistas)
    for s in ((dados.get("f1") or {}).get("weekend") or {}).get("sessions") or []:
        if s.get("date") and s.get("name"):
            vistas[s["date"]] = s["name"]
    vistas = {d: n for d, n in vistas.items() if hora(d) > agora - timedelta(days=2)}
    if vistas != antes:
        try:
            atualizar_tudo.gravar_json(MEMORIA, {**mem, "f1": [{"date": d, "name": n} for d, n in sorted(vistas.items())]})
        except OSError:
            pass   # sem memória: só se perde uma atualização da F1
    return sorted((hora(d), n) for d, n in vistas.items())


def f1(dados, agora):
    lista = []
    for inicio, nome in sessoes_f1(dados, agora):
        fim = inicio + timedelta(hours=F1_DURACAO.get(nome, 1))
        for h in F1_DEPOIS:
            lista.append(tarefa("f1", f"Fórmula 1 · {nome} +{h} h", fim + timedelta(hours=h), PASSOS["f1"]))
    return lista


# ------------------------------------------------------------------ futebol: depois de cada jogo
def acabado(j):
    return "hs" in j and not j.get("live") and j.get("status") != "adiado"


def competicoes_a_seguir():
    """[(chave no live.json, nome, passos, --competicoes)]: as ligadas, e a Taça da Liga com o seu passo."""
    lista = [(k, nome, PASSOS["futebol"], k) for k, nome, *_ in competicoes.a_buscar()]
    if competicoes.ler().get("tl"):
        lista.append(("tl", "Taça da Liga", PASSOS["taca_liga"], None))
    return lista


def grupos_de_jogos(jogos):
    """Junta os jogos que acabam perto uns dos outros: [(hora a que se atualiza, [jogos])]."""
    grupos = []
    for fim, j in sorted(jogos, key=lambda x: x[0]):
        if grupos and fim - grupos[-1][1][0][0] <= JUNTOS:
            grupos[-1][1].append((fim, j))
            grupos[-1][0] = fim
        else:
            grupos.append([fim, [(fim, j)]])
    return [(fim, [j for _, j in js]) for fim, js in grupos]


def futebol(dados, agora, registo):
    lista = []
    bola = dados.get("football") or {}
    for k, nome, passos, comp in competicoes_a_seguir():
        L = bola.get(k) or {}
        jogos = [(hora(j["iso"]) + FIM_JOGO, j) for j in (L.get("results") or []) + (L.get("next") or [])
                 if isinstance(j, dict) and j.get("iso") and j.get("status") != "adiado"]
        chave = f"futebol:{k}"
        nome_t = f"Futebol · {L.get('name') or nome}" if k != "tl" else "Futebol · Taça da Liga"
        for quando, js in grupos_de_jogos(jogos):
            if quando > agora:
                lista.append(tarefa(chave, nome_t, quando, passos, comp))
                continue
            if all(acabado(j) for j in js):
                continue   # os dados já têm o resultado (desta agenda, do botão ou das 07:00)
            depois = [r for r in registo if r.get("chave") == chave and hora(r["em"]) >= quando]
            feitas = [r for r in depois if r.get("resultado") != "ocupado"]
            if len(feitas) >= VEZES_JOGO:
                continue   # já tentou 4 vezes: fica para a próxima atualização (no máximo às 07:00)
            q = max([quando] + [hora(r["em"]) + DE_NOVO for r in feitas[-1:]])
            t = tarefa(chave, nome_t, q, passos, comp, ident=f"{chave}@{quando.astimezone():%Y-%m-%dT%H:%M}#{len(feitas) + 1}")
            t["_desde"] = quando
            if feitas:
                t["nota"] = f"ainda a decorrer: {len(feitas) + 1}.ª vez"
            lista.append(t)
    return lista


# ------------------------------------------------------------------ juntar tudo
def falhas_seguidas(registo, chave):
    """(quantas falhas seguidas, hora da última) desta parte, sem contar os "ocupado"."""
    n, ultima = 0, None
    for r in reversed(registo):
        if r.get("chave") != chave or r.get("resultado") == "ocupado":
            continue
        if r.get("resultado") != "falhou":
            break
        n += 1
        ultima = ultima or hora(r["em"])
    return n, ultima


def proximas(agora=None):
    """{"ligada", "agora", "tarefas": [...]}: as que estão na hora (quando <= agora) e as que vêm aí, por ordem."""
    agora = (agora or datetime.now()).astimezone()
    config, registo = ler_config(), ler_registo()
    dados = ler_json(LIVE, {})
    ligada_em = hora(config["ligada_em"]) if config.get("ligada_em") else None
    # Últimas 07:00 que já passaram (o que ficou antes foi coberto por essa atualização)
    hoje = a_hora(agora.date(), HORA_COMPLETA)
    ultimas7 = hoje if hoje <= agora else a_hora((agora - timedelta(days=1)).date(), HORA_COMPLETA)
    completas_ok = [hora(r["em"]) for r in registo if r.get("chave") == "completa" and r.get("resultado") == "ok"]
    por_id = {}
    for r in registo:
        por_id.setdefault(r.get("id"), []).append(r)

    candidatas = repetidas(agora) + f1(dados, agora) + futebol(dados, agora, registo)
    for t in config.get("testes") or []:
        try:
            em = hora(t["em"])
            candidatas.append(tarefa("teste", f"Teste · {t['passos']}", em, t["passos"].split(","),
                                     ident=f"teste@{em.astimezone():%Y-%m-%dT%H:%M}"))
        except (KeyError, ValueError, TypeError, AttributeError):
            pass

    # Das que se repetem (notícias, NBA, F1, completa) só conta a última hora marcada que já passou, feita ou não
    ultima_marcada = {}
    for t in candidatas:
        if t["_desde"] <= agora and not t["chave"].startswith("futebol:"):
            ultima_marcada[t["chave"]] = max(ultima_marcada.get(t["chave"], t["_desde"]), t["_desde"])
    vencidas, futuras = {}, []
    for t in candidatas:
        q = t["quando"]
        if q > agora:
            if q <= agora + HORIZONTE:
                futuras.append(t)
            continue
        if t["chave"] in ultima_marcada and t["_desde"] < ultima_marcada[t["chave"]]:
            continue
        # Já devia ter corrido: só se foi marcada depois de ligada e depois das últimas 07:00 (que cobrem o que veio antes)
        desde = t["_desde"]
        if (ligada_em and desde < ligada_em) or (t["chave"] != "completa" and desde < ultimas7):
            continue
        if t["chave"] != "completa" and not t["chave"].startswith("futebol:") and any(c >= desde for c in completas_ok):
            continue   # uma atualização completa depois desta hora já a cobriu (o futebol vê-se pelos dados)
        feitas = por_id.get(t["id"], [])
        if feitas and feitas[-1].get("resultado") != "ocupado":
            continue   # já correu (bem ou mal: a falha conta para a pausa, não se repete já)
        if feitas:
            t["quando"] = hora(feitas[-1]["em"]) + OCUPADO
            t["nota"] = "estava a correr outra atualização"
        # Uma por parte (ex.: dois grupos de jogos da mesma competição por acabar: uma atualização serve aos dois)
        ant = vencidas.get(t["chave"])
        if not ant or t["quando"] >= ant["quando"]:
            vencidas[t["chave"]] = t

    tarefas = []
    for t in list(vencidas.values()) + futuras:
        n, ultima = falhas_seguidas(registo, t["chave"])
        if n >= 3:
            espera = PAUSAS[min(n - 3, len(PAUSAS) - 1)]
            if ultima + timedelta(minutes=espera) > t["quando"]:
                t["quando"] = ultima + timedelta(minutes=espera)
                t["nota"] = f"em pausa {espera} min depois de {n} falhas seguidas"
        if noite(t["quando"]) or (noite(agora) and t["quando"] <= agora):
            continue   # de noite não corre: fica para as 07:00
        tarefas.append(t)
    if not config.get("ligada"):
        tarefas = [t for t in tarefas if t["quando"] > agora]   # desligada: nada está "na hora"
    tarefas.sort(key=lambda t: (t["quando"], t["chave"] != "completa"))
    for t in tarefas:
        del t["_desde"]
        t["quando"] = t["quando"].astimezone().isoformat(timespec="seconds")
        t["na_hora"] = t["quando"] <= agora.isoformat(timespec="seconds")
    return {"ligada": bool(config.get("ligada")), "ligada_em": config.get("ligada_em"),
            "agora": agora.isoformat(timespec="seconds"), "tarefas": tarefas}


def estado(agora=None):
    """Para a página /definicoes: o interruptor, as próximas 5 e as últimas 10 do registo (mais recente primeiro)."""
    p, vistas, proximas_5 = proximas(agora), set(), []
    for t in p["tarefas"]:   # a próxima de cada parte (senão as notícias de 30 em 30 min enchiam a lista)
        if t["chave"] not in vistas and len(proximas_5) < 5:
            vistas.add(t["chave"])
            proximas_5.append(t)
    return {"ligada": p["ligada"], "agora": p["agora"], "proximas": proximas_5,
            "registo": list(reversed(ler_registo()[-10:]))}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proximas", action="store_true", help="o que está na hora e o que vem aí (JSON, para o hub)")
    ap.add_argument("--estado", action="store_true", help="o que a página /definicoes mostra (JSON)")
    ap.add_argument("--agora", help="fazer de conta que é esta hora (ISO, ex.: 2026-10-24T22:00)")
    ap.add_argument("--ligar", action="store_true", help="liga a atualização automática")
    ap.add_argument("--desligar", action="store_true", help="desliga a atualização automática")
    args = ap.parse_args()
    if args.ligar or args.desligar:
        print(json.dumps(gravar_config(args.ligar), ensure_ascii=False))
        return
    agora = hora(args.agora) if args.agora else None
    print(json.dumps(estado(agora) if args.estado else proximas(agora), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
