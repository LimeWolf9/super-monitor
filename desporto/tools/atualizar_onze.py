"""Calcula o "melhor 11 da jornada" de cada competição e grava-o em data/live.json (football.<liga>.onze).

Uso:
    python tools/atualizar_onze.py            # atualiza data/live.json
    python tools/atualizar_onze.py --mostrar  # só mostra o que gravaria

Não há uma fonte aberta e sem chave com o 11 oficial da jornada, por isso é calculado pelo dashboard (e a cena
diz isso): para cada jogo da última jornada, a ESPN dá o onze de cada equipa, a posição de cada jogador e as
estatísticas do jogo (golos, assistências, golos sofridos, defesas, cartões). Cada jogador recebe uma pontuação
(PONTOS, mais abaixo) e escolhem-se os melhores numa formação fixa 4-3-3: 1 guarda-redes, 4 defesas,
3 médios e 3 avançados.

Corre depois do atualizar_futebol.py (precisa dos ids dos jogos em "results"). Os jogos terminados não mudam,
por isso as estatísticas de cada jogo ficam em cache (data/cache_onze.json) e só se pedem uma vez.
Uma competição sem dados fica sem "onze" e o ecrã sai da rotação. Só usa a biblioteca standard do Python.
"""

import argparse
import json

from comum import RAIZ, gravar, ler_dados, pedir_json, registar_fonte

LIGAS = ["pt", "en", "es", "de", "fr", "it", "ucl"]   # as que mostram resultados (a Liga Europa e a Conferência não)
from atualizar_futebol import EQUIPAS, LIGAS as LIGAS_ESPN   # noqa: E402
RESUMO = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/summary?event={id}"
CACHE = RAIZ / "data" / "cache_onze.json"
FORMACAO = {"GR": 1, "DEF": 4, "MED": 3, "AV": 3}   # 4-3-3

# Posição da ESPN -> linha do 11
LINHAS = {"G": "GR", "GK": "GR",
          "CD": "DEF", "CD-L": "DEF", "CD-R": "DEF", "LB": "DEF", "RB": "DEF", "D": "DEF", "SW": "DEF",
          "LWB": "DEF", "RWB": "DEF",
          "DM": "MED", "CM": "MED", "CM-L": "MED", "CM-R": "MED", "LM": "MED", "RM": "MED", "M": "MED", "AM": "MED",
          "F": "AV", "CF": "AV", "CF-L": "AV", "CF-R": "AV", "ST": "AV", "SS": "AV", "LW": "AV", "RW": "AV",
          "AM-L": "AV", "AM-R": "AV", "LF": "AV", "RF": "AV"}

# Pontuação de cada jogador num jogo
PONTOS = {
    "golo": 5, "assistencia": 3, "titular": 1, "vitoria": 2, "empate": 0.5,
    "zeros": {"GR": 4, "DEF": 3, "MED": 1, "AV": 0},          # baliza a zeros (só titulares)
    "sofrido": {"GR": -1, "DEF": -0.5, "MED": 0, "AV": 0},     # por golo sofrido
    "defesa": 0.7,                                            # por defesa do guarda-redes
    "amarelo": -0.5, "vermelho": -4, "autogolo": -2,
}


def ler_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def jogadores_do_jogo(liga, jogo_id):
    """Lista de jogadores que jogaram: nome, equipa ESPN, linha, titular e estatísticas."""
    d = pedir_json(RESUMO.format(liga=liga, id=jogo_id))
    lista = []
    for lado in d.get("rosters", []):
        equipa_id = str(lado.get("team", {}).get("id"))
        for p in lado.get("roster", []):
            pos = (p.get("position") or {}).get("abbreviation", "")
            st = {s["name"]: s.get("value") or 0 for s in p.get("stats", [])}
            if not st.get("appearances") or pos == "SUB" and not p.get("subbedIn"):
                continue
            linha = LINHAS.get(pos)
            if not linha:   # suplente que entrou: a ESPN não dá a posição; fica de fora do cálculo
                continue
            lista.append({"name": p["athlete"].get("displayName"), "short": p["athlete"].get("shortName"),
                          "teamId": equipa_id, "line": linha, "starter": bool(p.get("starter")),
                          "g": st.get("totalGoals", 0), "a": st.get("goalAssists", 0), "gc": st.get("goalsConceded", 0),
                          "sv": st.get("saves", 0), "yc": st.get("yellowCards", 0), "rc": st.get("redCards", 0),
                          "og": st.get("ownGoals", 0)})
    return lista


def pontuar(j, resultado):
    p = PONTOS
    v = j["g"] * p["golo"] + j["a"] * p["assistencia"] + (p["titular"] if j["starter"] else 0)
    v += p["vitoria"] if resultado == "V" else p["empate"] if resultado == "E" else 0
    if j["starter"] and j["gc"] == 0:
        v += p["zeros"][j["line"]]
    v += j["gc"] * p["sofrido"][j["line"]]
    if j["line"] == "GR":
        v += j["sv"] * p["defesa"]
    v += j["yc"] * p["amarelo"] + j["rc"] * p["vermelho"] + j["og"] * p["autogolo"]
    return round(v, 1)


def porque(j):
    """Texto curto com o motivo: "2 golos · 1 assist." / "baliza a zeros · 5 defesas"."""
    partes = []
    if j["g"]:
        partes.append(f"{int(j['g'])} golo{'s' if j['g'] > 1 else ''}")
    if j["a"]:
        partes.append(f"{int(j['a'])} assist.")
    if j["starter"] and j["gc"] == 0 and j["line"] in ("GR", "DEF"):
        partes.append("baliza a zeros")
    if j["line"] == "GR" and j["sv"]:
        partes.append(f"{int(j['sv'])} defesa{'s' if j['sv'] > 1 else ''}")
    return " · ".join(partes) or "vitória"


def onze_da_liga(chave, L, codigos, cache):
    """O 11 da última jornada da liga, ou None se não houver dados."""
    candidatos = []
    for m in L.get("results", []):
        if not m.get("id") or m.get("hs") is None or m.get("live"):   # só jogos acabados
            continue
        if m["id"] not in cache:
            cache[m["id"]] = jogadores_do_jogo(LIGAS_ESPN[chave], m["id"])
        for j in cache[m["id"]]:
            sigla = codigos.get(j["teamId"])
            if not sigla:
                continue
            casa = sigla == m["home"]
            marcados, sofridos = (m["hs"], m["as"]) if casa else (m["as"], m["hs"])
            res = "V" if marcados > sofridos else "E" if marcados == sofridos else "D"
            candidatos.append({**j, "team": sigla, "pts": pontuar(j, res), "why": porque(j) if res == "V" or j["g"] or j["a"] or (j["starter"] and j["gc"] == 0) else ""})
    if not candidatos:
        return None
    onze = []
    for linha, n in FORMACAO.items():
        da_linha = sorted((c for c in candidatos if c["line"] == linha), key=lambda c: (-c["pts"], -c["g"], -c["a"]))
        if len(da_linha) < n:
            return None
        onze += [{"name": c["name"], "short": c["short"], "team": c["team"], "line": linha, "pts": c["pts"],
                  "why": c["why"]} for c in da_linha[:n]]
    return {"formation": "4-3-3", "round": L.get("round"), "players": onze}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    cache = ler_cache()
    # id ESPN da equipa -> sigla: o mapa EQUIPAS do atualizador do futebol
    feitos, falhas = [], []
    for chave in LIGAS:
        L = (dados.get("football") or {}).get(chave)
        if not L:
            continue
        try:
            L["onze"] = onze_da_liga(chave, L, EQUIPAS, cache)
        except Exception as e:   # ESPN sem resposta: essa liga fica sem 11 (o ecrã sai da rotação)
            print(f"Aviso: 11 da jornada, {chave}: {e!r}")
            falhas.append(f"{chave} ({e})")
            L["onze"] = None
        if L["onze"]:
            feitos.append(chave)
    # Uma linha nas Definições para todas as ligas; falha se alguma falhou (a mensagem diz quais)
    registar_fonte("ESPN 11 da jornada", itens=len(feitos), erro="; ".join(falhas) or None, esperado=False)
    # a cache só guarda jogos que ainda estão nas listas (não cresce para sempre)
    ids = {m.get("id") for L in (dados.get("football") or {}).values() if L for m in L.get("results", [])}
    cache = {k: v for k, v in cache.items() if k in ids}
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    if args.mostrar:
        print(json.dumps({k: dados["football"][k].get("onze") for k in LIGAS if k in dados["football"]},
                         ensure_ascii=False, indent=2))
        return
    gravar(dados, "onze")
    print(f"11 da jornada: {', '.join(feitos) or 'nenhum'}.")


if __name__ == "__main__":
    main()
