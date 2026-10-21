"""Peças partilhadas pelos atualizadores (futebol, NBA, destaques, curiosidades).

- pedir(): pedido HTTP com User-Agent e descompressão gzip (a ESPN comprime mesmo sem se pedir).
- ler_dados() / gravar(): lê o live.json (ou o mock, na primeira vez) e grava-o de forma atómica.
- baixar_emblema(): descarrega o emblema de uma equipa nova para web/img/equipas/.
- registar_fonte() / fonte(): guardam em data/fontes.json como correu cada fonte (para as Definições e o hub).
Só usa a biblioteca standard do Python.
"""

import gzip
import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MOCK = RAIZ / "data" / "mock.json"
LIVE = RAIZ / "data" / "live.json"
EMBLEMAS = RAIZ / "web" / "img" / "equipas"
FONTES = RAIZ / "data" / "fontes.json"
USER_AGENT = "dashboard-desportivo/1.0 (uso pessoal)"
PAUSA = 0.5   # segundos entre pedidos, para não abusar das APIs

# Quando todas estas partes tiverem vindo de fontes reais, sai o aviso de "DADOS FICTÍCIOS".
PARTES = ("f1", "futebol", "nba", "destaques", "curiosidades")


def pedir(url, pausa=PAUSA, ua=USER_AGENT):
    pedido = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
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


# ------------------------------------------------------------ resultado de cada fonte (data/fontes.json)
# Uma entrada por fonte ("ESPN Liga Portugal", "Jolpica F1", "RSS A Bola"...):
#   estado            "ok" | "aviso" (respondeu, mas sem itens onde se esperavam) | "falhou"
#   ok                False só se falhou
#   ultima_ok         hora (ISO) da última vez que trouxe dados
#   ultima_tentativa  hora (ISO) da última vez que se tentou
#   itens             quantos jogos/notícias/... trouxe na última tentativa (None se não se conta)
#   erro              texto curto do erro ou do aviso, ou None
#   passo             o atualizador que a usa (ex.: "atualizar_futebol.py")
_tranca_fontes = threading.Lock()   # o futebol pede várias ligas em paralelo


def _curto(erro, n=120):
    texto = " ".join(str(erro).split()) or type(erro).__name__
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def registar_fonte(nome, itens=None, erro=None, esperado=True, aviso=None):
    """Regista como correu uma fonte. erro -> falhou; aviso (texto), ou 0 itens com esperado=True -> aviso; senão ok.

    aviso serve, por exemplo, para uma fonte que falhou mas tinha outra de reserva que trouxe os dados.
    """
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if erro is not None:
        estado, texto = "falhou", _curto(erro)
    elif aviso is not None:
        estado, texto = "aviso", _curto(aviso)
    elif itens == 0 and esperado:
        estado, texto = "aviso", "respondeu sem dados"
    else:
        estado, texto = "ok", None
    with _tranca_fontes:
        try:
            fontes = json.loads(FONTES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fontes = {}
        antes = fontes.get(nome, {})
        fontes[nome] = {
            "estado": estado, "ok": estado != "falhou",
            "ultima_ok": agora if estado == "ok" else antes.get("ultima_ok"),
            "ultima_tentativa": agora, "itens": itens, "erro": texto,
            "passo": Path(sys.argv[0]).name or antes.get("passo"),
        }
        tmp = FONTES.with_name(f"fontes.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(fontes, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(FONTES)   # de uma vez: quem lê nunca apanha um ficheiro a meio


def fonte(nome, funcao, contar=len, esperado=True):
    """Corre funcao(), regista a fonte (itens = contar(resultado)) e devolve o resultado; se falhar, regista e relança."""
    try:
        r = funcao()
    except Exception as e:
        registar_fonte(nome, erro=e)
        raise
    try:
        n = contar(r) if contar else None
    except Exception:
        n = None
    registar_fonte(nome, itens=n, esperado=esperado)
    return r
