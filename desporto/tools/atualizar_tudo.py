"""Atualiza todos os dados do dashboard de uma vez, sem precisar do servidor nem do dashboard aberto.

Uso:
    python tools/atualizar_tudo.py            # corre os 11 atualizadores, um a um, e mostra o progresso
    python tools/atualizar_tudo.py --json     # uma linha JSON por passo (para o MonitorHub mostrar um loading)
    python tools/atualizar_tudo.py --estado   # só mostra o estado da última atualização (ou da que está a correr)
    python tools/atualizar_tudo.py --passos noticias,fotos           # só estes passos (pela ordem de sempre)
    python tools/atualizar_tudo.py --passos futebol,onze --competicoes pt   # só a Liga Portugal (e o 11 dela)

Por partes: --passos com os nomes curtos f1, futebol, taca_liga, onze, elo, nba, noticias, fotos, destaques,
curiosidades, estadios (separados por vírgulas) corre só esses; o atualizacao.json só mostra esses passos e o
duracoes.json só muda nesses. --competicoes (chaves de competicoes.py, ex.: pt,en) passa para o futebol e para o
11 da jornada: só essas competições mudam, as outras ficam como estavam no live.json. Sem opções corre tudo (é o
que o botão "Atualizar" e o MonitorHub fazem).

É o mesmo código que o serve.py usa quando se carrega em "Atualizar" no dashboard:
- os passos correm em série (F1, futebol, Taça da Liga, 11 da jornada, ClubElo, NBA, notícias, fotos, destaques, curiosidades, estádios); um que
  falhe não para os outros, e essa parte fica com os dados anteriores;
- o progresso fica em data/atualizacao.json (gravado de forma atómica), que o dashboard e o MonitorHub leem:
    estado        "a_correr" | "ok" | "falhou" ("nunca" se ainda não houve nenhuma)
    passo         nome do passo a correr ("Futebol"), ou null
    feitos, total quantos passos acabaram, de quantos
    decorrido_s   segundos desde o início (até ao fim, se já acabou)
    estimativa_s  total estimado, em segundos (do que cada passo demorou da última vez)
    terminado_em  hora do fim (ISO), ou null
    erro          texto curto com as fontes que falharam ("Falharam: RSS Marca, ESPN NBA"), ou null;
                  um passo que falhe sem dizer que fonte foi aparece pelo nome ("Falharam: Fotos")
    passos        o detalhe de cada passo (nome, estado, segundos, última linha do atualizador)
- data/atualizacao.lock impede duas atualizações ao mesmo tempo (ex.: uma pelo hub e outra pelo dashboard);
- a estimativa vem do que cada passo demorou da última vez (data/duracoes.json).
Código de saída: 0 tudo bem; 1 algum passo falhou (com uma linha curta no stderr); 2 já havia uma atualização a
correr (a que está a correr, seja do comando ou do dashboard, escreve no mesmo ficheiro, por isso dá para a seguir).
Só usa a biblioteca standard do Python.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "tools"
ESTADO = RAIZ / "data" / "atualizacao.json"
TRANCA = RAIZ / "data" / "atualizacao.lock"
DURACOES = RAIZ / "data" / "duracoes.json"
FONTES = RAIZ / "data" / "fontes.json"   # como correu cada fonte (gravado pelos atualizadores: comum.registar_fonte)
TRANCA_VELHA = 20 * 60   # uma tranca com mais de 20 min é de uma atualização que morreu a meio

# Por esta ordem: os destaques e as curiosidades usam os dados que os outros acabaram de gravar.
PASSOS = [("atualizar_f1.py", "Fórmula 1"), ("atualizar_futebol.py", "Futebol"), ("atualizar_taca_liga.py", "Taça da Liga"), ("atualizar_onze.py", "11 da jornada"), ("atualizar_elo.py", "ClubElo"),
          ("atualizar_nba.py", "NBA"), ("atualizar_noticias.py", "Notícias"), ("atualizar_fotos.py", "Fotos"),
          ("atualizar_destaques.py", "Destaques"), ("atualizar_curiosidades.py", "Curiosidades"),
          ("atualizar_estadios.py", "Estádios")]   # o mapa do Ao vivo (não mexe no live.json; é o mais demorado)
CURTOS = {f[len("atualizar_"):-len(".py")]: f for f, _ in PASSOS}   # "noticias" -> "atualizar_noticias.py" (--passos)
POR_COMPETICAO = ("atualizar_futebol.py", "atualizar_onze.py")      # os que aceitam --competicoes


def ler_json(caminho, omissao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return omissao


def gravar_json(caminho, dados):
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    for tentativa in range(20):
        try:
            tmp.replace(caminho)
            return
        except PermissionError:   # Windows: alguém está a ler o ficheiro (o /api/atualizar/estado, a cada 1,5 s)
            if tentativa == 19:
                raise
            time.sleep(0.05)


def a_correr():
    """Há uma atualização a correr (de quem quer que seja)?"""
    if not TRANCA.exists():
        return False
    if time.time() - TRANCA.stat().st_mtime > TRANCA_VELHA:
        TRANCA.unlink(missing_ok=True)   # ficou de uma atualização interrompida
        return False
    return True


def formatar(e, corre):
    """Estado público a partir do estado interno (inicio/fim em segundos, passos)."""
    passos = e.get("passos", [])
    agora = time.time()
    falhados = [p["nome"] for p in passos if p["estado"] == "falhou"]
    falhas = e.get("falhas") or falhados   # as fontes, quando a atualização acabou (ver fontes_falhadas)
    atual = next((p for p in passos if p["estado"] == "a_correr"), None)
    return {
        "estado": ("a_correr" if corre else "nunca" if not e.get("inicio")
                   else "falhou" if falhas or not e.get("fim") else "ok"),
        "passo": atual["nome"] if atual and corre else None,
        "feitos": sum(1 for p in passos if p["estado"] in ("ok", "falhou")),
        "total": len(passos) or len(PASSOS),
        "decorrido_s": round((e.get("fim") or (agora if corre else e.get("inicio") or agora)) - e["inicio"], 1)
                       if e.get("inicio") else 0,
        "estimativa_s": (round(sum(p.get("estimativa", 0) for p in passos), 1) if passos
                         else round(sum(ler_json(DURACOES, {}).values()), 1) or None),
        "inicio_em": datetime.fromtimestamp(e["inicio"]).isoformat(timespec="seconds") if e.get("inicio") else None,
        "terminado_em": datetime.fromtimestamp(e["fim"]).isoformat(timespec="seconds") if e.get("fim") else None,
        "erro": (f"Falharam: {', '.join(falhas)}" if falhas
                 else "Interrompida a meio" if e.get("inicio") and not e.get("fim") and not corre else None),
        "passos": passos,
    }


def fontes_falhadas(e):
    """Nomes das fontes que falharam nesta atualização; um passo que falhou sem nenhuma fonte falhada vai pelo nome."""
    inicio = datetime.fromtimestamp(e["inicio"], timezone.utc).isoformat(timespec="seconds")   # como em comum.py
    fontes = ler_json(FONTES, {})
    nesta = {n: f for n, f in fontes.items() if (f.get("ultima_tentativa") or "") >= inicio}
    nomes = []
    for p in e["passos"]:
        da_fonte = [n for n, f in nesta.items() if f.get("passo") == p["id"] and f.get("estado") == "falhou"]
        nomes += da_fonte or ([p["nome"]] if p["estado"] == "falhou" else [])
    return nomes


def gravar_estado(e):
    """Grava no ficheiro o estado público (o que o hub lê) mais os campos internos (inicio, fim, a_correr)."""
    gravar_json(ESTADO, {**formatar(e, e["a_correr"]), "inicio": e["inicio"], "fim": e["fim"], "a_correr": e["a_correr"],
                         "falhas": e.get("falhas")})


def estado():
    """Estado para mostrar (o mesmo formato no ficheiro, no comando --estado e no /api/atualizar/estado)."""
    e = ler_json(ESTADO, {"inicio": None, "fim": None, "passos": []})
    return formatar(e, bool(e.get("a_correr")) and a_correr())


def escolher_passos(nomes):
    """Os passos com estes nomes curtos ("futebol,nba"), pela ordem de PASSOS. ValueError se algum não existir."""
    pedidos = [n.strip() for n in nomes.split(",") if n.strip()]
    errados = [n for n in pedidos if n not in CURTOS]
    if errados or not pedidos:
        raise ValueError(f"Passos desconhecidos: {', '.join(errados) or '(nenhum)'}. Os que há: {', '.join(CURTOS)}.")
    return [f for f, _ in PASSOS if f in {CURTOS[n] for n in pedidos}]


def atualizar(ao_mudar=lambda e: None, passos=None, competicoes=None):
    """Corre os passos (por omissão, todos). Devolve o estado final, ou None se já havia uma atualização a correr.

    passos: ficheiros dos passos a correr (ver escolher_passos); competicoes: "pt,en" para o futebol e o 11.
    """
    if a_correr():
        return None
    try:
        with open(TRANCA, "x", encoding="utf-8") as f:   # "x": falha se outra atualização a criou entretanto
            f.write(str(os.getpid()))
    except FileExistsError:
        return None
    try:
        duracoes = ler_json(DURACOES, {})
        e = {"a_correr": True, "inicio": time.time(), "fim": None, "passos": [
            {"id": f, "nome": nome, "estado": "espera", "seg": None, "msg": "", "estimativa": duracoes.get(f, 30)}
            for f, nome in PASSOS if passos is None or f in passos]}
        for passo in e["passos"]:
            passo["estado"] = "a_correr"
            gravar_estado(e)
            ao_mudar(estado())
            t0 = time.time()
            try:
                # PYTHONIOENCODING: no Windows, sem isto um "ç" no print faz o atualizador falhar
                extra = ["--competicoes", competicoes] if competicoes and passo["id"] in POR_COMPETICAO else []
                proc = subprocess.Popen([sys.executable, str(PASTA / passo["id"]), *extra], cwd=RAIZ, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                while True:
                    try:
                        saida, _ = proc.communicate(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        # a cada segundo: o ficheiro (decorrido_s) e a tranca (sinal de que está viva)
                        gravar_estado(e)
                        TRANCA.touch()
                        if time.time() - t0 > 600:
                            proc.kill()
                            raise TimeoutError("demorou mais de 10 minutos")
                linhas = (saida or "").strip().splitlines()
                ok, msg = proc.returncode == 0, (linhas[-1] if linhas else "")
            except Exception as ex:   # timeout, Python em falta...: segue para o próximo
                ok, msg = False, str(ex)
            passo.update(estado="ok" if ok else "falhou", seg=round(time.time() - t0, 1), msg=msg[:200])
            if ok and not extra:   # só com algumas competições é mais rápido: não serve de estimativa
                duracoes[passo["id"]] = passo["seg"]
        e.update(a_correr=False, fim=time.time())
        e["falhas"] = fontes_falhadas(e)
        gravar_estado(e)
        gravar_json(DURACOES, duracoes)
        final = estado()
        ao_mudar(final)   # a última linha (no --json) já diz "ok" ou "falhou"
        return final
    finally:
        TRANCA.unlink(missing_ok=True)


def main():
    sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="uma linha JSON por mudança de estado")
    ap.add_argument("--estado", action="store_true", help="só mostra o estado atual e sai")
    ap.add_argument("--passos", help=f"só estes passos, separados por vírgulas ({','.join(CURTOS)})")
    ap.add_argument("--competicoes", help="só estas competições no futebol e no 11 da jornada (ex.: pt,en)")
    args = ap.parse_args()
    try:
        passos = escolher_passos(args.passos) if args.passos else None
    except ValueError as e:
        ap.error(str(e))

    if args.estado:
        print(json.dumps(estado(), ensure_ascii=False))
        return

    def mostrar(e):
        if args.json:
            print(json.dumps(e, ensure_ascii=False), flush=True)
        elif e["passo"]:
            print(f"[{e['feitos'] + 1}/{e['total']}] {e['passo']}...", flush=True)

    final = atualizar(mostrar, passos, args.competicoes)
    if final is None:
        if args.json:
            print(json.dumps({"erro": "ja_a_correr", **estado()}, ensure_ascii=False))
        else:
            print("Já está a correr uma atualização.")
        sys.exit(2)
    if not args.json:
        print(f"Atualizado em {final['decorrido_s']:.0f} s.")
    if final["erro"]:
        print(final["erro"], file=sys.stderr)   # o hub mostra esta linha
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
