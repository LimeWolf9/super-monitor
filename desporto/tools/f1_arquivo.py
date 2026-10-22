"""Descarrega sessões passadas do arquivo do live timing da F1 (livetiming.formula1.com/static).

O arquivo precisa do token da F1 TV (data/f1tv_token.txt, o mesmo do f1_gravar.py).
Para cada sessão guarda o Index.json e, de cada tópico, o <Tópico>.json (retrato final) e o
<Tópico>.jsonStream (todas as mudanças, uma por linha, com a hora relativa ao início da gravação).
Os tópicos .z vêm em base64 + deflate cru: zlib.decompress(base64.b64decode(x), -15).

Pasta: data/f1_gravacoes/arquivo/<ano>-<GP>-<sessão>/ (fora do git). O que já existe não se volta
a descarregar. Pedidos um a um, com pausa, para não abusar.

Uso:
  py tools/f1_arquivo.py --listar                     (GP e sessões do ano)
  py tools/f1_arquivo.py --gp Singapore --sessao Race Qualifying
  py tools/f1_arquivo.py                              (último GP, corrida e qualificação)
Só usa a biblioteca standard do Python.
"""

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f1_gravar import PASTA, TOKEN, USER_AGENT, ler_token  # noqa: E402

BASE = "https://livetiming.formula1.com/static/"
DESTINO = PASTA / "arquivo"
PAUSA = 0.5


def pedir(caminho, token):
    pedido = urllib.request.Request(BASE + caminho, headers={
        "User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(pedido, timeout=120) as resp:
        dados = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            dados = gzip.decompress(dados)
    time.sleep(PAUSA)
    return dados


def ler_json(dados):
    return json.loads(dados.decode("utf-8-sig"))


def nome_pasta(texto):
    return re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")


def duracao(ficheiro):
    """Primeira e última hora (relativas) de um .jsonStream, ex. ('00:00:01.2', '02:31:07.9')."""
    primeira = ultima = None
    with open(ficheiro, encoding="utf-8-sig", errors="replace") as f:
        for linha in f:
            if len(linha) > 12 and linha[2] == ":":
                ultima = linha[:12]
                primeira = primeira or ultima
    return primeira, ultima


def tamanho(n):
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB"


def descarregar(ano, gp, sessao, token):
    pasta = DESTINO / f"{ano}-{nome_pasta(gp['Name'])}-{nome_pasta(sessao['Name'])}"
    pasta.mkdir(parents=True, exist_ok=True)
    print(f"\n{gp['Name']} - {sessao['Name']} -> {pasta}")
    indice = pedir(sessao["Path"] + "Index.json", token)
    (pasta / "Index.json").write_bytes(indice)
    feeds = ler_json(indice).get("Feeds") or {}
    resumo = []
    for topico, f in sorted(feeds.items()):
        total = 0
        for chave in ("KeyFramePath", "StreamPath"):
            nome = f.get(chave)
            if not nome:
                continue
            alvo = pasta / nome
            if not alvo.exists():
                try:
                    dados = pedir(sessao["Path"] + nome, token)
                except urllib.error.HTTPError as e:
                    print(f"  {nome}: HTTP {e.code}")
                    continue
                alvo.with_suffix(alvo.suffix + ".tmp").write_bytes(dados)
                alvo.with_suffix(alvo.suffix + ".tmp").replace(alvo)
            total += alvo.stat().st_size
        resumo.append((topico, total))
        print(f"  {topico}: {tamanho(total)}")
    for topico in ("Position.z", "CarData.z", "Heartbeat"):
        stream = pasta / (feeds.get(topico) or {}).get("StreamPath", "-")
        if stream.is_file():
            ini, fim = duracao(stream)
            print(f"  {topico}.jsonStream cobre {ini} -> {fim}")
    print(f"  total: {tamanho(sum(t for _, t in resumo))}")


def main():
    p = argparse.ArgumentParser(description="Descarrega sessões do arquivo do live timing da F1.")
    p.add_argument("--ano", type=int, default=datetime.now().year)
    p.add_argument("--gp", help="parte do nome do GP (por omissão, o último do ano)")
    p.add_argument("--sessao", nargs="+", default=["Race", "Qualifying"],
                   help="nomes das sessões (Practice 1, Qualifying, Sprint, Race, ...)")
    p.add_argument("--listar", action="store_true", help="só mostra os GP e sessões do ano")
    args = p.parse_args()

    token = ler_token()
    if not token:
        sys.exit(f"Falta o token da F1 TV em {TOKEN}")
    try:
        gps = ler_json(pedir(f"{args.ano}/Index.json", token)).get("Meetings") or []
    except urllib.error.HTTPError as e:
        sys.exit(f"Index.json do arquivo: HTTP {e.code} (token inválido ou expirado?)")
    if args.listar:
        for gp in gps:
            print(gp["Name"] + ": " + ", ".join(s["Name"] for s in gp.get("Sessions") or [] if s.get("Path")))
        return
    if args.gp:
        gps = [g for g in gps if args.gp.lower() in g["Name"].lower()]
    if not gps:
        sys.exit("GP não encontrado (vê --listar)")
    gp = gps[-1]
    for nome in args.sessao:
        sessoes = [s for s in gp.get("Sessions") or [] if s["Name"].lower() == nome.lower() and s.get("Path")]
        if not sessoes:
            print(f"\n{gp['Name']}: sessão '{nome}' não está no arquivo")
            continue
        descarregar(args.ano, gp, sessoes[0], token)


if __name__ == "__main__":
    main()
