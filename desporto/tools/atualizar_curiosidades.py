"""Gera as curiosidades da cena "fun" e grava-as em data/live.json (secção "fun").

Uso:
    python tools/atualizar_curiosidades.py            # atualiza data/live.json
    python tools/atualizar_curiosidades.py --mostrar  # só mostra o que gravaria

- "Neste dia na história": API REST da Wikipédia em português (feed "onthisday"), sem chave. Primeiro os
  acontecimentos desportivos do dia; se não chegarem, os desportistas que nasceram neste dia (os portugueses
  primeiro, depois os mais conhecidos); em último caso, os acontecimentos desportivos da Wikipédia em inglês.
- "Recordes curiosos": não há API. Vêm de data/recordes.json (só factos confirmados) e rodam um pouco por dia.
- "Comparações absurdas": calculadas a partir dos dados reais do live.json (golos, pontos, quilómetros).
Corre depois dos outros atualizadores. Só usa a biblioteca standard do Python.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from itertools import combinations

from comum import RAIZ, gravar, ler_dados, pedir_json, registar_fonte

RECORDES = RAIZ / "data" / "recordes.json"
WIKI = "https://{lingua}.wikipedia.org/api/rest_v1/feed/onthisday/{tipo}/{mes:02d}/{dia:02d}"
MAX_ITENS = 6
MAX_TEXTO = 220

# \b no início: "NBA" não pode apanhar "Jeenbekov"
DESPORTO_PT = re.compile(
    r"\b(?:futebol|Copa do Mundo|Campeonato (do )?Mundo de|Campeonato Mundial de|Jogos Olímpicos|olímpic|Fórmula 1|"
    r"Grande Prémio|Grande Prêmio|NBA|basquet|ténis|tênis|Wimbledon|ciclismo|Volta a|Tour de France|maratona|"
    r"recorde mundial|atletismo|golo|boxe|pugil|seleção (nacional|portuguesa)|estádio|medalha|UEFA|FIFA|"
    r"Taça dos Campeões|Liga dos Campeões|automobilismo|Benfica|Sporting Clube|FC Porto|Futebol Clube do Porto)",
    re.I)
DESPORTO_EN = re.compile(
    r"\b(?:football|soccer|FIFA|UEFA|World Cup|Olympic|Formula One|Grand Prix|NBA|basketball|tennis|Wimbledon|"
    r"Tour de France|marathon|world record|boxing|heavyweight champion|World Series|Super Bowl|Premier League|"
    r"Champions League)", re.I)
DESPORTISTA = re.compile(
    r"\b(?:futebolista|basquetebolista|jogador de basquete|piloto|tenista|atleta|ciclista|nadador|nadadora|pugilista|"
    r"treinador de futebol|maratonista|velocista|automobilista)", re.I)


def cortar(texto):
    texto = " ".join(texto.split())
    return texto if len(texto) <= MAX_TEXTO else texto[:MAX_TEXTO - 1].rsplit(" ", 1)[0] + "…"


def neste_dia(hoje):
    feed = lambda lingua, tipo: pedir_json(WIKI.format(lingua=lingua, tipo=tipo, mes=hoje.month, dia=hoje.day))
    itens = [{"year": e["year"], "text": cortar(e["text"])}
             for e in feed("pt", "events").get("events", []) if DESPORTO_PT.search(e["text"])]

    if len(itens) < MAX_ITENS:
        # Desportistas que nasceram neste dia: portugueses primeiro, depois os que têm fotografia
        # e os artigos mais antigos (pageid baixo), que costumam ser os mais conhecidos.
        nascidos = [e for e in feed("pt", "births").get("births", []) if DESPORTISTA.search(e["text"])]

        def fama(e):
            p = (e.get("pages") or [{}])[0]
            return ("portugu" not in e["text"], "thumbnail" not in p, p.get("pageid", 10 ** 9))

        for e in sorted(nascidos, key=fama)[:MAX_ITENS - len(itens)]:
            texto = e["text"].strip().rstrip(".")
            itens.append({"year": e["year"], "text": cortar(f"Nasce {texto}.")})

    if len(itens) < 2:
        itens += [{"year": e["year"], "text": cortar(e["text"])}
                  for e in feed("en", "events").get("events", []) if DESPORTO_EN.search(e["text"])][:MAX_ITENS]
    return sorted(itens[:MAX_ITENS], key=lambda i: -i["year"])


def recordes(hoje):
    lista = json.loads(RECORDES.read_text(encoding="utf-8"))["records"]
    k = hoje.timetuple().tm_yday % len(lista)   # todos os dias começa num recorde diferente
    return lista[k:] + lista[:k]


# ---------- Comparações a partir dos dados reais ----------

def nome(dados, code):
    return dados["teams"].get(code, {}).get("name", code)


def lista_nomes(nomes):
    nomes = [f"o {n}" for n in nomes]
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def marcador_vs_equipas(dados, L):
    """O melhor marcador comparado com os golos de equipas inteiras da mesma liga."""
    if not L.get("scorers") or not all("gf" in r for r in L.get("table", [])):
        return None
    s = L["scorers"][0]
    g, apelido = s["goals"], s["name"].split()[-1]
    outras = [r for r in reversed(L["table"]) if r["team"] != s["team"]]   # do último para o primeiro
    for a, b in combinations(outras[:8], 2):
        if a["gf"] + b["gf"] == g and a["gf"] and b["gf"]:
            return f"O {apelido} já marcou tantos golos como {lista_nomes([nome(dados, a['team']), nome(dados, b['team'])])} juntos."
    iguais = [r for r in outras if r["gf"] == g]
    if iguais:
        return f"O {apelido} já marcou tantos golos como o {nome(dados, iguais[0]['team'])} inteiro. Sozinho."
    menos = [r for r in outras if r["gf"] < g]
    if menos:
        return f"O {apelido} já marcou mais golos do que o {nome(dados, menos[0]['team'])} inteiro. Sozinho."
    return None


def lider_vs_ultimos(dados, L):
    """O líder tem mais pontos do que vários dos últimos juntos."""
    tabela = L.get("table") or []
    if len(tabela) < 4 or not tabela[0]["pts"]:
        return None
    lider, soma, juntos = tabela[0], 0, []
    for r in reversed(tabela[1:]):
        if soma + r["pts"] >= lider["pts"] or len(juntos) == 4:
            break
        soma += r["pts"]
        juntos.append(nome(dados, r["team"]))
    if len(juntos) < 2:
        return None
    return f"O {nome(dados, lider['team'])} tem mais pontos ({lider['pts']}) do que {lista_nomes(juntos)} juntos ({soma})."


def golos_da_jornada(L):
    jogos = [m for m in (L.get("results") or []) if m.get("hs") is not None and not m.get("live")]
    return sum(m["hs"] + m["as"] for m in jogos), len(jogos)


def nba_vs_futebol(dados):
    noite = (dados.get("nba") or {}).get("lastNight") or []
    L = (dados.get("football") or {}).get("pt") or {}
    golos, n = golos_da_jornada(L)
    if not noite or not n:
        return None
    pontos = sum(j["hs"] + j["as"] for j in noite)
    return (f"Na noite passada, {len(noite)} jogos da NBA deram {pontos} pontos. A última jornada da "
            f"Liga Portugal deu {golos} golos em {n} jogos. Cada um com os seus hábitos.")


def f1_distancia(dados):
    prox = (dados.get("f1") or {}).get("next") or {}
    try:
        km = int(prox["laps"]) * float(str(prox["length"]).split()[0].replace(",", "."))
    except (KeyError, ValueError, TypeError):
        return None
    return (f"No {prox['name']} cada piloto vai fazer {km:.0f} km. É mais ou menos Lisboa–Porto pela autoestrada, "
            f"mas às voltas no mesmo sítio, {prox['laps']} vezes.")


def champions_vs_liga(dados):
    futebol = dados.get("football") or {}
    ucl, pt = futebol.get("ucl") or {}, futebol.get("pt") or {}
    (gu, nu), (gp, np_) = golos_da_jornada(ucl), golos_da_jornada(pt)
    if not nu or not np_:
        return None
    return (f"Na última jornada da Champions marcaram-se {gu / nu:.1f} golos por jogo; na Liga Portugal, "
            f"{gp / np_:.1f}. A Europa tem mais pressa.".replace(".", ",", 2) if gu / nu > gp / np_ else
            f"Na última jornada da Liga Portugal marcaram-se {gp / np_:.1f} golos por jogo; na Champions, "
            f"{gu / nu:.1f}. Afinal, quem precisa da Europa?".replace(".", ",", 2))


def comparacoes(dados):
    reais = dados.get("_atualizado", {})
    futebol = dados.get("football") or {}
    lista = []
    if "futebol" in reais:
        for chave in ("pt", "en", "es"):
            L = futebol.get(chave) or {}
            lista += [marcador_vs_equipas(dados, L), lider_vs_ultimos(dados, L)]
        lista.append(champions_vs_liga(dados))
        if "nba" in reais:
            lista.append(nba_vs_futebol(dados))
    if "f1" in reais:
        lista.append(f1_distancia(dados))
    return [{"text": t} for t in lista if t]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    hoje = datetime.now()
    try:
        fun = {"onThisDay": neste_dia(hoje), "records": recordes(hoje), "comparisons": comparacoes(dados)}
        registar_fonte("Wikipédia (neste dia)", itens=len(fun["onThisDay"]))
    except Exception as e:   # sem rede, Wikipédia em baixo...: fica tudo como estava
        registar_fonte("Wikipédia (neste dia)", erro=e)
        sys.exit(f"Não foi possível atualizar as curiosidades ({e!r}). O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(fun, ensure_ascii=False, indent=2))
        return
    dados["fun"] = fun
    gravar(dados, "curiosidades")
    print(f"Curiosidades: {len(fun['onThisDay'])} 'neste dia', {len(fun['records'])} recordes, "
          f"{len(fun['comparisons'])} comparações.")


if __name__ == "__main__":
    main()
