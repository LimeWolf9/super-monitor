"""Taça da Liga (Allianz Cup), pela API pública do site da Liga Portugal. Opcional: vem desligada.

Uso:
    python tools/atualizar_taca_liga.py            # atualiza data/live.json (secção football.tl)
    python tools/atualizar_taca_liga.py --mostrar  # só mostra o que gravaria

A ESPN não tem a Taça da Liga. O site da Liga Portugal tem uma API JSON pública, sem chave:
    /api/v1/competition/season/rounds?competition=allianzcup&season=20262027   (as rondas: quartos, meias, final)
    /api/v1/competition/matches?competition=allianzcup&season=20262027&round=1 (os jogos de cada ronda)
Os termos de utilização da Liga Portugal só permitem uso pessoal e não comercial: por isso esta competição vem
desligada em /definicoes, e os dados e os emblemas que vêm daqui ficam só neste PC (live.json e web/img estão
fora do git). Quem a ligar deve ler e respeitar esses termos.

Grava football.tl no mesmo formato das outras taças (ver montar_taca em atualizar_futebol.py): resultados da ronda
atual (a mais recente com um jogo acabado), jogos da ronda seguinte, fase e janela. Se falhar, fica como estava; se
estiver desligada, sai do live.json.
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone

from comum import baixar_emblema, gravar, ler_dados, pedir, pedir_json, tem_emblema
from pathlib import Path
import competicoes

API = "https://www.ligaportugal.pt/api/v1/competition/{o_que}?competition=allianzcup&season={epoca}"
CHAVE = "tl"
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
TERMINADO = 5   # fixtureStateTypeId de um jogo acabado
COR_NEUTRA = "#4b5563"
PNG = bytes([0x89]) + b"PNG"
LOGO = "https://www.ligaportugal.pt/backoffice/assets/ic_allianzcup_cbcb5ca1e0.png"
LOGOS_LIGAS = Path(__file__).resolve().parent.parent / "web" / "img" / "ligas"
# Nome da equipa no site da Liga -> sigla do dashboard (as que não batem certo pelo nome nem pela sigla)
SIGLAS = {"Sporting CP": "SCP", "SL Benfica": "SLB", "FC Porto": "FCP", "SC Braga": "SCB", "Vitória SC": "VSC",
          "FC Famalicão": "FAM", "Gil Vicente FC": "GIL", "Académico": "ACV", "Marítimo M.": "MTO",
          "CD Santa Clara": "SCL", "FC Alverca": "ALV", "CD Tondela": "CDT", "Rio Ave FC": "RAV",
          "Moreirense FC": "MOR", "FC Arouca": "ARO", "Estoril Praia": "EST", "Casa Pia AC": "CPI",
          "CD Nacional": "NAC", "CF Estrela Amadora": "AMD", "AVS": "AVSX", "FC Vizela": "VIZ", "GD Chaves": "GDC"}
FASES = {"quartos de final": "Quartos de final", "meias finais": "Meias-finais", "final": "Final",
         "fase de grupos": "Fase de grupos"}


def epoca(agora):
    """Época em curso no formato da API: em outubro de 2026 é "20262027" (a época começa em julho)."""
    a = agora.year if agora.month >= 7 else agora.year - 1
    return f"{a}{a + 1}"


def normalizar(nome):
    nome = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]", " ", nome).split())


def nome_fase(descricao):
    return FASES.get(normalizar(descricao).replace("-", " "), descricao)


class Equipas:
    """Liga as equipas do site da Liga às siglas do dashboard (as da ESPN, para os emblemas e o ClubElo)."""

    def __init__(self, teams, baixar):
        self.teams, self.baixar = teams, baixar
        self.por_nome = {}
        for code, t in teams.items():
            for n in (t.get("name"), t.get("espnName")):
                if n:
                    self.por_nome.setdefault(normalizar(n), code)

    def sigla(self, t):
        nome = t.get("name") or ""
        code = SIGLAS.get(nome) or self.por_nome.get(normalizar(nome))
        if not code and (t.get("abbreviation") or "") in self.teams:
            code = t["abbreviation"]
        if not code:   # uma equipa que o dashboard ainda não conhece: fica com a sigla da Liga
            code = re.sub(r"[^A-Z]", "", (t.get("abbreviation") or nome[:3]).upper())[:4] or "TL"
            while code in self.teams and self.teams[code].get("_liga") != t.get("id"):
                code += "X"
            if code not in self.teams:
                cor = t.get("teamColour") or COR_NEUTRA
                self.teams[code] = {"name": nome, "c1": cor, "c2": t.get("teamSecondaryColour") or "#ffffff",
                                    "_liga": t.get("id")}
        if self.baixar and not tem_emblema(code) and t.get("logo"):
            baixar_emblema(code, t["logo"])   # só neste PC (web/img/equipas está fora do git)
        return code


def quando(m):
    return datetime.fromisoformat(m["matchDate"].replace("Z", "+00:00"))


def jogo(m, eq, agora):
    casa, fora = eq.sigla(m["homeTeam"]), eq.sigla(m["awayTeam"])
    local = quando(m).astimezone()
    base = {"home": casa, "away": fora, "id": f"lp{m.get('fixtureCode')}"}
    if m.get("postponedFixture") or m.get("canceledFixture") or m.get("notPlayedFixture"):
        return {**base, "status": "adiado", "when": f"{DIAS[local.weekday()]} {local:%H:%M}", "date": f"{local:%d/%m}"}
    if m.get("fixtureStateTypeId") == TERMINADO:
        r = {**base, "hs": m["homeTeamGoals"], "as": m["awayTeamGoals"], "ev": []}
        ph, pa = m.get("liveHomeTeamPenalties") or 0, m.get("liveAwayTeamPenalties") or 0
        if ph or pa:
            r["nota"] = f"g.p. {ph}-{pa}"
        return r
    if m.get("fixtureStateTypeId") and quando(m) <= agora:   # a decorrer
        return {**base, "hs": m.get("liveHomeTeamGoals", 0), "as": m.get("liveAwayTeamGoals", 0), "ev": [],
                "live": True, "clock": m.get("time") or ""}
    return {**base, "when": f"{DIAS[local.weekday()]} {local:%H:%M}", "date": f"{local:%d/%m}"}


def montar(dados, agora, baixar):
    ep = epoca(agora)
    rondas = sorted(pedir_json(API.format(o_que="season/rounds", epoca=ep)), key=lambda r: r["round_number"])
    eq = Equipas(dados["teams"], baixar)
    lista = []
    for r in rondas:
        jogos = sorted(pedir_json(API.format(o_que="matches", epoca=ep) + f"&round={r['round_number']}"), key=quando)
        lista.append((nome_fase(r.get("description") or ""), jogos))
    feitos = lambda js: [m for m in js if m.get("fixtureStateTypeId") == TERMINADO]
    atual = next((i for i in range(len(lista) - 1, -1, -1) if feitos(lista[i][1])), None)
    nova = {"name": "Taça da Liga", "tipo": "taca", "fonte": "Liga Portugal"}
    if atual is None:
        nova.update(fase=None, results=[], partial=None)
    else:
        rotulo, js = lista[atual]
        nova["fase"] = rotulo
        nova["results"] = [jogo(m, eq, agora) for m in js]
        n = len(feitos(js))
        nova["partial"] = {"done": n, "total": len(js)} if n < len(js) else None
    por_jogar = lambda js: [m for m in js if m.get("fixtureStateTypeId") != TERMINADO and quando(m) > agora]
    seguinte = next(((r, por_jogar(js)) for r, js in lista[(atual + 1 if atual is not None else 0):] if por_jogar(js)),
                    (None, []))
    nova["proxFase"], nova["next"] = seguinte[0], [jogo(m, eq, agora) for m in seguinte[1]]
    todos = [m for _, js in lista for m in js]
    acabados = [quando(m) for m in todos if m.get("fixtureStateTypeId") == TERMINADO]
    futuros = [quando(m) for m in todos if m.get("fixtureStateTypeId") != TERMINADO and quando(m) > agora]
    iso = lambda d: d.isoformat(timespec="minutes") if d else None
    nova["janela"] = {"ultimo": iso(max(acabados, default=None)), "proximo": iso(min(futuros, default=None))}
    return nova


def na_ordem(futebol, tl):
    """football com a Taça da Liga logo a seguir à Taça de Portugal (a ordem da rotação)."""
    novo = {}
    for k, v in futebol.items():
        if k != CHAVE:
            novo[k] = v
        if k == "tp":
            novo[CHAVE] = tl
    novo.setdefault(CHAVE, tl)
    return novo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    futebol = dados.setdefault("football", {})
    if not competicoes.ler().get(CHAVE):
        if CHAVE in futebol and not args.mostrar:
            del futebol[CHAVE]
            gravar(dados, "taca_liga")
        print("Taça da Liga: desligada em /definicoes.")
        return
    agora = datetime.now(timezone.utc)
    try:
        tl = montar(dados, agora, baixar=not args.mostrar)
    except Exception as e:   # site em baixo ou formato mudou: fica como estava
        sys.exit(f"Não foi possível atualizar a Taça da Liga ({e!r}). O live.json não foi alterado.")
    if args.mostrar:
        print(json.dumps(tl, ensure_ascii=False, indent=2))
        return
    if not any(LOGOS_LIGAS.glob(f"{CHAVE}.*")):
        try:   # o símbolo da competição, também só neste PC (web/img/ligas está fora do git)
            png = pedir(LOGO)
            if png[:4] == PNG:
                (LOGOS_LIGAS / f"{CHAVE}.png").write_bytes(png)
        except Exception:
            pass
    dados["football"] = na_ordem(futebol, tl)
    gravar(dados, "taca_liga")
    print(f"Taça da Liga: {tl['fase'] or 'sem resultados'} ({len(tl['results'])} jogos), "
          f"{tl['proxFase'] or 'sem próximos'} ({len(tl['next'])} jogos).")


if __name__ == "__main__":
    main()
