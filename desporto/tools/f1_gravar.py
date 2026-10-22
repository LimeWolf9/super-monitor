"""Grava o live timing oficial da F1 (livetiming.formula1.com) para um ficheiro .jsonl.

Usa o hub SignalR Core (o mesmo da app oficial). Com o token da F1 TV (data/f1tv_token.txt)
vêm também os tópicos pagos (CarData.z, Position.z, ...); sem token vem o que for público.

- data/f1tv_token.txt: o valor do cookie "login-session" do formula1.com (JSON codificado
  em URL com data.subscriptionToken) ou só o token. Está no .gitignore e nunca é escrito.
- Cada mensagem recebida fica numa linha: {"t": hora local de receção, "m": mensagem SignalR}.
  A mensagem type 3 traz o retrato inicial; type 1 target "feed" traz [tópico, dados, hora].
  Os tópicos .z ficam como vêm (base64 + deflate cru: zlib.decompress(b64, -15)).
- Ficheiro: data/f1_gravacoes/<AAAA-MM-DD>-<rótulo>.jsonl (e um .log ao lado).

Uso:
  py tools/f1_gravar.py --segundos 60 --rotulo teste
  py tools/f1_gravar.py --ate-fim --rotulo FP1
  py tools/f1_gravar.py --diagnostico        (só testa negotiate e o Index.json, com e sem token)
Só usa a biblioteca standard do Python.
"""

import argparse
import base64
import http.cookiejar
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOKEN = RAIZ / "data" / "f1tv_token.txt"
PASTA = RAIZ / "data" / "f1_gravacoes"
ANFITRIAO = "livetiming.formula1.com"
USER_AGENT = "BestHTTP"   # o que a app oficial manda; o servidor aceita outros, mas este é o seguro
SEP = "\x1e"
TOPICOS = [
    "Heartbeat", "ExtrapolatedClock", "TopThree", "TimingStats", "TimingAppData",
    "WeatherData", "TrackStatus", "SessionStatus", "DriverList", "RaceControlMessages",
    "SessionInfo", "SessionData", "LapCount", "TimingData", "TeamRadio",
    "PitLaneTimeCollection", "PitStopSeries", "ChampionshipPrediction", "CarData.z", "Position.z",
]
FIM = ("Ends", "Finalised")
DEPOIS_DO_FIM = 10 * 60      # segundos que ainda se grava depois de a sessão acabar
MAXIMO = 3 * 3600            # --ate-fim nunca passa disto
PING = 10                    # segundos entre pings SignalR do cliente

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


# ---------- token ----------

def ler_token():
    """Devolve o subscriptionToken (ou None). Nunca o escreve em lado nenhum."""
    try:
        bruto = TOKEN.read_text(encoding="utf-8-sig").strip().strip('"')
    except OSError:
        return None
    if not bruto:
        return None
    if bruto.startswith("%7B") or bruto.startswith("{"):
        try:
            dados = json.loads(urllib.parse.unquote(bruto))
            return (dados.get("data") or {}).get("subscriptionToken") or None
        except (ValueError, AttributeError):
            return None
    return bruto


# ---------- HTTP ----------

def negociar(token):
    """POST /signalrcore/negotiate. Devolve (connectionToken, texto do cabeçalho Cookie)."""
    jarro = http.cookiejar.CookieJar()
    abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jarro))
    cab = {"User-Agent": USER_AGENT, "Content-Type": "text/plain;charset=UTF-8"}
    if token:
        cab["Authorization"] = "Bearer " + token
    pedido = urllib.request.Request(
        f"https://{ANFITRIAO}/signalrcore/negotiate?negotiateVersion=1", data=b"", headers=cab, method="POST")
    with abridor.open(pedido, timeout=30) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    cookies = "; ".join(f"{c.name}={c.value}" for c in jarro)
    return dados["connectionToken"], cookies


def pedir_estado(url, token):
    """GET simples; devolve (código HTTP, tamanho)."""
    cab = {"User-Agent": USER_AGENT}
    if token:
        cab["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=30) as resp:
            return resp.status, len(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, 0


# ---------- WebSocket mínimo (RFC 6455) ----------

class FechadoErro(Exception):
    pass


class WebSocket:
    def __init__(self, caminho, cabecalhos):
        ctx = ssl.create_default_context()
        bruto = socket.create_connection((ANFITRIAO, 443), timeout=30)
        self.s = ctx.wrap_socket(bruto, server_hostname=ANFITRIAO)
        chave = base64.b64encode(os.urandom(16)).decode()
        linhas = [f"GET {caminho} HTTP/1.1", f"Host: {ANFITRIAO}", "Upgrade: websocket",
                  "Connection: Upgrade", f"Sec-WebSocket-Key: {chave}", "Sec-WebSocket-Version: 13"]
        linhas += [f"{k}: {v}" for k, v in cabecalhos.items() if v]
        self.s.sendall(("\r\n".join(linhas) + "\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            bloco = self.s.recv(4096)
            if not bloco:
                raise FechadoErro("ligação fechada no handshake")
            resp += bloco
        cabeca, self.buf = resp.split(b"\r\n\r\n", 1)
        estado = cabeca.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in estado + " ":
            raise FechadoErro(f"handshake recusado: {estado}")
        self.partes = []
        self.op_partes = None

    def enviar(self, dados, op=0x1):
        if isinstance(dados, str):
            dados = dados.encode("utf-8")
        n = len(dados)
        cab = bytearray([0x80 | op])
        if n < 126:
            cab.append(0x80 | n)
        elif n < 65536:
            cab.append(0x80 | 126)
            cab += struct.pack("!H", n)
        else:
            cab.append(0x80 | 127)
            cab += struct.pack("!Q", n)
        mascara = os.urandom(4)
        corpo = bytes(b ^ mascara[i % 4] for i, b in enumerate(dados))
        self.s.sendall(bytes(cab) + mascara + corpo)

    def _ler(self, n):
        while len(self.buf) < n:
            bloco = self.s.recv(65536)
            if not bloco:
                raise FechadoErro("ligação fechada pelo servidor")
            self.buf += bloco
        dados, self.buf = self.buf[:n], self.buf[n:]
        return dados

    def receber(self, espera=1.0):
        """Devolve uma mensagem de texto completa, ou None se nada chegou em `espera` segundos."""
        self.s.settimeout(espera)
        try:
            while True:
                b0, b1 = self._ler(2)
                fin, op = b0 & 0x80, b0 & 0x0F
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", self._ler(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", self._ler(8))[0]
                mascara = self._ler(4) if b1 & 0x80 else None
                self.s.settimeout(30)          # a meio de uma trama, espera-se pelo resto
                dados = self._ler(n)
                if mascara:
                    dados = bytes(b ^ mascara[i % 4] for i, b in enumerate(dados))
                if op == 0x9:
                    self.enviar(dados, op=0xA)
                elif op == 0xA:
                    pass
                elif op == 0x8:
                    codigo = struct.unpack("!H", dados[:2])[0] if len(dados) >= 2 else None
                    raise FechadoErro(f"servidor fechou (código {codigo})")
                elif op in (0x1, 0x2):
                    if fin:
                        return dados.decode("utf-8", errors="replace")
                    self.partes, self.op_partes = [dados], op
                elif op == 0x0:
                    self.partes.append(dados)
                    if fin:
                        tudo, self.partes = b"".join(self.partes), []
                        return tudo.decode("utf-8", errors="replace")
                self.s.settimeout(espera)
        except (socket.timeout, TimeoutError):
            return None
        except ssl.SSLWantReadError:
            return None

    def fechar(self):
        try:
            self.enviar(struct.pack("!H", 1000), op=0x8)
        except OSError:
            pass
        try:
            self.s.close()
        except OSError:
            pass


# ---------- gravação ----------

def ligar(token, topicos=None):
    conn, cookies = negociar(token)
    caminho = "/signalrcore?id=" + urllib.parse.quote(conn, safe="")
    cab = {"User-Agent": USER_AGENT, "Cookie": cookies}
    if token:
        cab["Authorization"] = "Bearer " + token
    ws = WebSocket(caminho, cab)
    ws.enviar('{"protocol":"json","version":1}' + SEP)
    ws.enviar(json.dumps({"type": 1, "target": "Subscribe", "arguments": [topicos or TOPICOS], "invocationId": "0"}) + SEP)
    return ws


def agora():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def gravar(args):
    token = ler_token()
    PASTA.mkdir(parents=True, exist_ok=True)
    base = PASTA / f"{datetime.now():%Y-%m-%d}-{args.rotulo}"
    destino, registo = base.with_suffix(".jsonl"), base.with_suffix(".log")

    def log(texto):
        linha = f"{agora()} {texto}"
        print(linha, flush=True)
        with open(registo, "a", encoding="utf-8") as f:
            f.write(linha + "\n")

    inicio = time.monotonic()
    limite = inicio + (args.segundos if args.segundos else MAXIMO)
    fim_em = None                   # hora (monotonic) a que paramos depois do fim da sessão
    viu_inicio = False
    contagem, retrato = {}, {}
    tentativas = 0
    log(f"a gravar para {destino.name} ({'com' if token else 'sem'} token)")
    with open(destino, "a", encoding="utf-8") as saida:
        while time.monotonic() < limite and (fim_em is None or time.monotonic() < fim_em):
            try:
                ws = ligar(token)
                log("ligado")
                tentativas = 0
                ultimo_ping = time.monotonic()
                while time.monotonic() < limite and (fim_em is None or time.monotonic() < fim_em):
                    if time.monotonic() - ultimo_ping > PING:
                        ws.enviar('{"type":6}' + SEP)
                        ultimo_ping = time.monotonic()
                    texto = ws.receber(1.0)
                    if texto is None:
                        continue
                    t = agora()
                    for parte in texto.split(SEP):
                        if not parte.strip():
                            continue
                        try:
                            msg = json.loads(parte)
                        except ValueError:
                            msg = {"bruto": parte}
                        tipo = msg.get("type")
                        if tipo == 6:
                            continue
                        saida.write(json.dumps({"t": t, "m": msg}, ensure_ascii=False, separators=(",", ":")) + "\n")
                        estados = []
                        if tipo == 3:
                            res = msg.get("result") or {}
                            if msg.get("error"):
                                log(f"erro na subscrição: {msg['error']}")
                            for top, val in res.items():
                                retrato[top] = len(json.dumps(val)) if val not in (None, {}, []) else 0
                            estados.append(((res.get("SessionStatus") or {}).get("Status"), False))
                            log("retrato inicial: " + ", ".join(f"{k}={v}" for k, v in sorted(retrato.items())))
                        elif tipo == 1 and msg.get("target") == "feed":
                            a = msg.get("arguments") or []
                            if a:
                                contagem[a[0]] = contagem.get(a[0], 0) + 1
                                if a[0] == "SessionStatus" and isinstance(a[1], dict):
                                    estados.append((a[1].get("Status"), True))
                        elif tipo == 7:
                            log(f"servidor fechou: {msg.get('error')}")
                            raise FechadoErro("close")
                        for estado, ao_vivo in estados:
                            if estado == "Started":
                                viu_inicio = True
                            if (args.ate_fim and estado in FIM and fim_em is None
                                    and (ao_vivo or viu_inicio)):
                                fim_em = time.monotonic() + DEPOIS_DO_FIM
                                log(f"sessão: {estado}; paro daqui a {DEPOIS_DO_FIM // 60} min")
                    saida.flush()
                ws.fechar()
            except (OSError, FechadoErro, urllib.error.URLError, KeyError, ValueError) as e:
                tentativas += 1
                espera = min(60, 2 ** min(tentativas, 6))
                log(f"ligação caiu ({type(e).__name__}: {e}); nova tentativa em {espera} s")
                time.sleep(espera)
    log("fim. mensagens por tópico no feed: "
        + (", ".join(f"{k}={v}" for k, v in sorted(contagem.items())) or "nenhuma"))


def diagnostico():
    token = ler_token()
    print(f"token: {'encontrado' if token else 'NÃO encontrado'} em {TOKEN}")
    for com in ([None, token] if token else [None]):
        nome = "com token" if com else "sem token"
        try:
            conn, cookies = negociar(com)
            print(f"negotiate {nome}: ok (connectionToken com {len(conn)} caracteres; cookies: "
                  f"{', '.join(c.split('=')[0] for c in cookies.split('; ') if c) or 'nenhum'})")
        except Exception as e:
            print(f"negotiate {nome}: falhou ({type(e).__name__}: {e})")
        ano = datetime.now().year
        estado, tam = pedir_estado(f"https://{ANFITRIAO}/static/{ano}/Index.json", com)
        print(f"static/{ano}/Index.json {nome}: HTTP {estado} ({tam} bytes)")


def main():
    p = argparse.ArgumentParser(description="Grava o live timing da F1.")
    p.add_argument("--rotulo", default="sessao", help="nome no ficheiro (FP1, FP2, Q, R, ...)")
    p.add_argument("--segundos", type=int, help="grava só N segundos (para testar)")
    p.add_argument("--ate-fim", action="store_true",
                   help="para 10 min depois de a sessão acabar (no máximo 3 h)")
    p.add_argument("--diagnostico", action="store_true", help="só testa os pedidos HTTP, com e sem token")
    args = p.parse_args()
    if args.diagnostico:
        diagnostico()
    else:
        gravar(args)


if __name__ == "__main__":
    main()
