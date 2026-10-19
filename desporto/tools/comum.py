"""Peças partilhadas pelos atualizadores (futebol, NBA, destaques, curiosidades).

- pedir(): pedido HTTP com User-Agent e descompressão gzip (a ESPN comprime mesmo sem se pedir).
- ler_dados() / gravar(): lê o live.json (ou o mock, na primeira vez) e grava-o de forma atómica.
- baixar_emblema(): descarrega o emblema de uma equipa nova para web/img/equipas/.
Só usa a biblioteca standard do Python.
"""

import gzip
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MOCK = RAIZ / "data" / "mock.json"
LIVE = RAIZ / "data" / "live.json"
EMBLEMAS = RAIZ / "web" / "img" / "equipas"
USER_AGENT = "dashboard-desportivo/1.0 (uso pessoal)"
PAUSA = 0.5   # segundos entre pedidos, para não abusar das APIs

# Quando todas estas partes tiverem vindo de fontes reais, sai o aviso de "DADOS FICTÍCIOS".
PARTES = ("f1", "futebol", "nba", "destaques", "curiosidades")


def pedir(url, pausa=PAUSA):
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(pedido, timeout=30) as resp:
        dados = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            dados = gzip.decompress(dados)
    time.sleep(pausa)
    return dados


def pedir_json(url):
    d = json.loads(pedir(url))
    # A ESPN às vezes responde 200 com {"code": 400, "message": ...} quando um pedido falha
    if isinstance(d, dict) and "code" in d and "message" in d and len(d) <= 3:
        raise RuntimeError(f"{url}: {d['message']}")
    return d


def ler_dados():
    base = LIVE if LIVE.exists() else MOCK
    return json.loads(base.read_text(encoding="utf-8"))


def gravar(dados, parte):
    """Regista a hora da atualização e grava de uma vez (live.tmp -> live.json)."""
    atualizado = dados.setdefault("_atualizado", {})
    atualizado[parte] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if all(p in atualizado for p in PARTES):
        dados.pop("_aviso", None)
    tmp = LIVE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LIVE)   # troca de uma vez, para o dashboard nunca ler um ficheiro a meio


def tem_emblema(code):
    return any((EMBLEMAS / f"{code}.{ext}").exists() for ext in ("png", "svg"))


def baixar_emblema(code, url):
    """Grava web/img/equipas/<code>.png. Devolve True se correu bem."""
    try:
        png = pedir(url)
        if not png.startswith(b"\x89PNG"):
            raise ValueError("não é um PNG")
        (EMBLEMAS / f"{code}.png").write_bytes(png)
        return True
    except Exception as e:
        print(f"Aviso: sem emblema para {code} ({e}). Aparece o círculo com a sigla.")
        return False
