"""Escolhe os "jogadores em destaque" a partir dos dados reais que já estão em data/live.json (secção "players").

Uso:
    python tools/atualizar_destaques.py            # atualiza data/live.json
    python tools/atualizar_destaques.py --mostrar  # só mostra o que gravaria

Não faz pedidos à rede: corre depois de atualizar_futebol.py, atualizar_nba.py e atualizar_f1.py.
- Futebol: quem marcou mais golos na última jornada (Liga Portugal, Premier League, La Liga, Champions, Liga Europa).
  Em caso de empate ganha um jogador da equipa em destaque (myTeam), depois a ordem das competições.
- NBA: o melhor marcador da noite passada (vem do box score, guardado pelo atualizar_nba.py).
- F1: o vencedor do último GP.
Só entram as partes que já vieram de fontes reais (ver "_atualizado"). Se nenhuma tiver dados, "players" fica vazio
e a cena sai da rotação. Só usa a biblioteca standard do Python.
"""

import argparse
import json
import sys
from collections import defaultdict

from comum import gravar, ler_dados

LIGAS = ["pt", "ucl", "en", "es", "uel"]   # ordem de preferência em caso de empate


def nome_equipa(dados, code):
    return dados["teams"].get(code, {}).get("name", code)


def numero_jornada(round_):
    return round_.removeprefix("Jornada ").strip()


def destaque_futebol(dados):
    futebol = dados.get("football") or {}
    meu = dados.get("myTeam", {}).get("code")
    golos = defaultdict(list)   # (liga, jogador, equipa) -> [(minuto, jogo, penálti?)]
    for liga in LIGAS:
        L = futebol.get(liga)
        for m in (L or {}).get("results", []):
            if m.get("hs") is None or m.get("live"):   # por jogar, adiado ou a decorrer
                continue
            for e in m.get("ev", []):
                if e.get("t") in ("og", "pen_miss", "red"):
                    continue
                equipa = m["home"] if e["s"] == "h" else m["away"]
                golos[(liga, e["p"], equipa)].append((e["m"], m, e.get("t") == "pen"))
    if not golos:
        return None

    def criterio(item):
        (liga, _, equipa), lista = item
        return (-len(lista), equipa != meu, LIGAS.index(liga))

    (liga, jogador, equipa), lista = min(golos.items(), key=criterio)
    L, jogo = futebol[liga], lista[0][1]
    casa = jogo["home"] == equipa
    adversario = nome_equipa(dados, jogo["away"] if casa else jogo["home"])
    marcados, sofridos = (jogo["hs"], jogo["as"]) if casa else (jogo["as"], jogo["hs"])
    n = len(lista)
    minutos = [f"{m}'" for m, _, _ in sorted(lista, key=lambda x: int(str(x[0]).split("+")[0]))]
    quando = minutos[0] if n == 1 else ", ".join(minutos[:-1]) + " e " + minutos[-1]
    penaltis = sum(1 for _, _, p in lista if p)

    if n >= 3:
        blurb = f"Hat-trick frente ao {adversario}: {n} golos e a bola do jogo para levar para casa."
    elif n == 2:
        blurb = f"Bis frente ao {adversario}. Dois golos num jogo e o nome mais repetido da jornada."
    elif marcados > sofridos and marcados - sofridos == 1:
        blurb = f"Um golo, e foi o que fez a diferença: {marcados}-{sofridos} frente ao {adversario}."
    else:
        blurb = f"Marcou frente ao {adversario}, numa jornada em que ninguém fez mais do que um golo."
    blurb += f" {'Golo' if n == 1 else 'Golos'} aos {quando}" + (
        "." if not penaltis else ", de penálti." if n == 1 else
        ", um deles de penálti." if penaltis == 1 else f", {penaltis} de penálti.")
    resultado = "Vitória" if marcados > sofridos else "Empate" if marcados == sofridos else "Derrota"
    return {
        "name": jogador, "team": equipa, "sport": "football",
        "tag": f"Futebol · {L['name']} · Jornada {numero_jornada(L['round'])}",
        "stats": [
            {"label": "Golos", "value": str(n)},
            {"label": resultado, "value": f"{marcados}-{sofridos}"},
            {"label": "Penáltis", "value": str(penaltis)},
            {"label": "Da equipa", "value": str(marcados)},
        ],
        "blurb": blurb,
    }


def destaque_nba(dados):
    p = (dados.get("nba") or {}).get("topPerformer")
    if not p:
        return None
    adversario = nome_equipa(dados, p["opp"])
    casa = p["team"] == p["home"]
    ganhou = (int(p["score"].split("–")[0]) > int(p["score"].split("–")[1])) == casa
    if p["pts"] >= 50:
        blurb = f"{p['pts']} pontos contra os {adversario}. Há noites em que o cesto parece maior."
    elif p["pts"] >= 40:
        blurb = f"Passou os 40 frente aos {adversario}: {p['pts']} pontos, {p['reb']} ressaltos e {p['ast']} assistências."
    else:
        blurb = f"O melhor marcador da noite: {p['pts']} pontos frente aos {adversario}" + \
                (", e a vitória no fim." if ganhou else ", mas a vitória ficou do outro lado.")
    return {
        "name": p["name"], "team": p["team"], "sport": "nba",
        "tag": f"NBA · {nome_equipa(dados, p['team'])}",
        "stats": [
            {"label": "Pontos", "value": str(p["pts"])},
            {"label": "Ressaltos", "value": str(p["reb"])},
            {"label": "Assistências", "value": str(p["ast"])},
            {"label": "Minutos", "value": str(p["min"])},
        ],
        "blurb": blurb,
    }


def destaque_f1(dados):
    f1 = dados.get("f1") or {}
    last = f1.get("last") or {}
    if not last.get("podium"):
        return None
    vencedor = last["podium"][0]
    pilotos = f1.get("drivers", [])
    pos = next((i + 1 for i, d in enumerate(pilotos) if d["name"] == vencedor["name"]), None)
    pontos = next((d["pts"] for d in pilotos if d["name"] == vencedor["name"]), None)
    lider = pilotos[0] if pilotos else None
    if pos == 1 and len(pilotos) > 1:
        blurb = f"Ganhou o {last['name']} e continua a liderar, com {pontos - pilotos[1]['pts']} pontos de avanço."
    elif pos and lider:
        blurb = f"Ganhou o {last['name']}. No campeonato está em {pos}.º, a {lider['pts'] - pontos} pontos do líder."
    else:
        blurb = f"Ganhou o {last['name']}."
    return {
        "name": vencedor["name"], "team": vencedor["team"], "sport": "f1",
        "tag": f"Fórmula 1 · Vencedor do {last['name']}",
        "stats": [
            {"label": "Lugar no GP", "value": "1.º"},
            {"label": "Campeonato", "value": f"{pos}.º" if pos else "—"},
            {"label": "Pontos", "value": str(pontos) if pontos is not None else "—"},
            {"label": "Para o líder", "value": str(lider["pts"] - pontos) if pos and pos > 1 else "—"},
        ],
        "blurb": blurb + (f" Tempo de corrida: {vencedor['time']}." if vencedor.get("time") else ""),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    reais = dados.get("_atualizado", {})
    escolhas = [("futebol", destaque_futebol), ("nba", destaque_nba), ("f1", destaque_f1)]
    try:
        # só usa partes que já vieram de fontes reais, para nunca misturar com o mock
        jogadores = [j for parte, f in escolhas if parte in reais and (j := f(dados))]
    except Exception as e:
        sys.exit(f"Não foi possível escolher os destaques ({e!r}). O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(jogadores, ensure_ascii=False, indent=2))
        return
    dados["players"] = jogadores
    gravar(dados, "destaques")
    print(f"Destaques: {', '.join(f'{j['name']} ({j['sport']})' for j in jogadores) or 'nenhum'}.")


if __name__ == "__main__":
    main()
