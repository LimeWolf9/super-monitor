"""F1 ao vivo em direto: o cliente do live timing oficial (livetiming.formula1.com) que alimenta o ecrã da F1.

- Só corre enquanto alguém pergunta: o Ao vivo (GET /api/aovivo, a cada 30 s) liga-o quando há uma sessão do fim
  de semana (live.json, f1.weekend) a decorrer ou a começar daqui a 30 min ou menos; o ecrã da F1
  (GET /api/f1/aovivo, a cada segundo) mantém-no ligado. Sem pedidos durante PARAR_S, desliga-se sozinho.
- A ligação é a do tools/f1_gravar.py (SignalR Core), o estado é o redutor do tools/f1_aovivo.py (o mesmo da
  simulação) e o desenho é o mesmo vista(). Cada mensagem também fica gravada em
  data/f1_gravacoes/<data>-direto.jsonl (fora do git), no formato do f1_gravar.py.
- Token da F1 TV (data/f1tv_token.txt, opcional e fora do git): com ele vêm as posições dos carros (Position.z);
  sem ele (ou se for recusado) liga sem token e o mapa mostra só a pista, com a nota "sem F1 TV: sem posições".
  O token nunca é escrito em lado nenhum (nem no registo das fontes).
- O traçado do mapa: o guardado do circuito (data/f1_gravacoes/pistas/), ou o de uma volta limpa desta sessão
  (com posições), ou o desenho do OpenStreetMap do live.json (sem carros).
- Para testar entre corridas: F1_DIRETO_REPLAY=<pasta do arquivo>[,<vel>[,<min desde a partida>]] no ambiente do
  serve.py faz o cliente "receber" essa sessão do arquivo em vez de ligar ao feed (o resto é igual; o relógio
  passa a ser o da sessão, e o Ao vivo mostra-a como se estivesse a decorrer).
Só usa a biblioteca standard do Python.
"""

import bisect
import json
import os
import threading
import time
import zlib
from array import array
from datetime import datetime, timedelta, timezone

import f1_aovivo as av
import f1_gravar as grav
from comum import ler_dados, registar_fonte

TOPICOS = list(av.TOPICOS) + ["Position.z"]
PARAR_S = 90                # sem pedidos há 90 s: desliga
ATRASO_S = 3.0              # as posições chegam em lotes: os carros andam 3 s atrás do que já se sabe
ANTES = timedelta(minutes=30)
DEPOIS = timedelta(minutes=30)
DURACAO = {"Treino livre": 60, "Qualificação sprint": 45, "Qualificação": 60, "Sprint": 60, "Corrida": 180}   # min
FONTE = "F1 ao vivo (live timing)"
REPLAY = os.environ.get("F1_DIRETO_REPLAY")   # só para testar (ver acima)
_relogio = None                               # no replay: a hora da sessão; senão, a de agora


def relogio():
    return _relogio() if _relogio else time.time()


def duracao(nome):
    return timedelta(minutes=next((m for k, m in DURACAO.items() if (nome or "").startswith(k)), 120))


def sessao_agora(dados, agora):
    """A sessão do fim de semana em que estamos (de 30 min antes do início a 30 min depois do fim previsto):
    {"gp", "nome", "inicio"} ou None."""
    fds = (dados.get("f1") or {}).get("weekend") or {}
    for s in fds.get("sessions") or []:
        try:
            inicio = datetime.fromisoformat(s["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if inicio - ANTES <= agora <= inicio + duracao(s.get("name")) + DEPOIS:
            return {"gp": fds.get("name"), "nome": s.get("name"), "inicio": inicio}
    return None


def proxima_sessao(dados, agora):
    fds = (dados.get("f1") or {}).get("weekend") or {}
    futuras = []
    for s in fds.get("sessions") or []:
        try:
            inicio = datetime.fromisoformat(s["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if inicio > agora:
            futuras.append({"gp": fds.get("name"), "nome": s.get("name"), "inicio": inicio})
    return min(futuras, key=lambda s: s["inicio"]) if futuras else None


class Posicoes:
    """As posições de cada carro (t = hora UTC em segundos), como as do Sessao: (t, x, y, fora de pista)."""

    def __init__(self):
        self.pos = {}

    def juntar(self, z):
        try:
            amostras = av.descomprimir(z).get("Position") or []
        except (ValueError, zlib.error, TypeError):
            return
        for a in amostras:
            try:
                t = av.utc(a["Timestamp"])
            except (KeyError, ValueError):
                continue
            for n, p in (a.get("Entries") or {}).items():
                if not p.get("X") and not p.get("Y"):
                    continue
                ts, xs, ys, fora = self.pos.setdefault(n, (array("d"), array("f"), array("f"), bytearray()))
                if ts and t <= ts[-1]:
                    continue
                ts.append(t)
                xs.append(p.get("X", 0))
                ys.append(p.get("Y", 0))
                fora.append(0 if p.get("Status") == "OnTrack" else 1)

    def ultima(self):
        return max((d[0][-1] for d in self.pos.values() if d[0]), default=None)

    def posicao(self, n, t):
        dados = self.pos.get(n)
        if not dados or not dados[0]:
            return None
        ts, xs, ys, _ = dados
        i = bisect.bisect_right(ts, t)
        if i == 0 or i >= len(ts):
            return (xs[0], ys[0]) if i == 0 else (xs[-1], ys[-1])
        f = (t - ts[i - 1]) / ((ts[i] - ts[i - 1]) or 1)
        return xs[i - 1] + (xs[i] - xs[i - 1]) * f, ys[i - 1] + (ys[i] - ys[i - 1]) * f


class Direto:
    def __init__(self):
        self.tranca = threading.Lock()
        self.fio = None
        self.ultimo_pedido = 0.0
        self._limpar()

    def _limpar(self):
        self.estado = av.Estado()
        self.posicoes = Posicoes()
        self.fim_volta = {}
        self.pista_t = []
        self.ligado = False
        self.erro = None
        self.mapa, self.transf, self.mapa_id = None, None, None
        self.circuito = None
        self.tentou_volta = 0.0

    # ------------------------------------------------ ciclo de vida
    def pedir(self):
        """Mantém o cliente ligado (arranca-o se estiver parado)."""
        with self.tranca:
            self.ultimo_pedido = time.time()
            if self.fio is None or not self.fio.is_alive():
                self._limpar()
                self.fio = threading.Thread(target=self._correr, name="f1-direto", daemon=True)
                self.fio.start()

    def _correr(self):
        if REPLAY:
            return self._replay()
        token = grav.ler_token()
        tentativas = 0
        while time.time() - self.ultimo_pedido < PARAR_S:
            ws = None
            try:
                try:
                    ws = grav.ligar(token, TOPICOS)
                except Exception:
                    if not token:
                        raise
                    token = None   # token recusado ou expirado: segue com os tópicos gratuitos
                    ws = grav.ligar(None, TOPICOS)
                self.ligado, self.erro = True, None
                registar_fonte(FONTE, itens=1, esperado=False,
                               aviso=None if token else "sem token da F1 TV: sem posições dos carros")
                tentativas = 0
                ultimo_ping = time.monotonic()
                destino = grav.PASTA / f"{datetime.now():%Y-%m-%d}-direto.jsonl"
                grav.PASTA.mkdir(parents=True, exist_ok=True)
                with open(destino, "a", encoding="utf-8") as gravacao:
                    while time.time() - self.ultimo_pedido < PARAR_S:
                        if time.monotonic() - ultimo_ping > grav.PING:
                            ws.enviar('{"type":6}' + grav.SEP)
                            ultimo_ping = time.monotonic()
                        texto = ws.receber(1.0)
                        if texto is None:
                            continue
                        t_rec = grav.agora()
                        for parte in texto.split(grav.SEP):
                            if not parte.strip():
                                continue
                            try:
                                msg = json.loads(parte)
                            except ValueError:
                                continue
                            if msg.get("type") == 6:
                                continue
                            if msg.get("type") == 7:
                                raise grav.FechadoErro(f"servidor fechou: {msg.get('error')}")
                            gravacao.write(json.dumps({"t": t_rec, "m": msg}, ensure_ascii=False, separators=(",", ":")) + "\n")
                            with self.tranca:
                                self.mensagem(msg)
                        gravacao.flush()
            except Exception as e:   # a ligação caiu: tenta outra vez (sem deitar o servidor abaixo)
                self.ligado, self.erro = False, f"{type(e).__name__}: {e}"
                registar_fonte(FONTE, erro=self.erro)
                tentativas += 1
                time.sleep(min(30, 2 ** min(tentativas, 5)))
            finally:
                if ws is not None:
                    ws.fechar()
        self.ligado = False

    def _replay(self):
        """Teste: uma sessão do arquivo a chegar pelo mesmo caminho (aplicar), ao ritmo da sessão (x vel)."""
        global _relogio
        partes = REPLAY.split(",")
        sessao = av.sessao(partes[0])
        vel = float(partes[1]) if len(partes) > 1 else 1.0
        t0 = sessao.inicio(float(partes[2]) if len(partes) > 2 else 0)
        base, parede = sessao.base_utc, time.time()
        _relogio = lambda: base + t0 + (time.time() - parede) * vel
        # as posições já estão todas (o ecrã só usa as de até agora), na hora UTC
        for n, (ts, xs, ys, fora) in sessao.pos.items():
            self.posicoes.pos[n] = (array("d", (x + base for x in ts)), xs, ys, fora)
        self.ligado = True
        for t, topico, dados in sessao.msgs:
            while base + t > relogio():
                if time.time() - self.ultimo_pedido > PARAR_S:
                    self.ligado, _relogio = False, None
                    return
                time.sleep(0.05)
            with self.tranca:
                self.aplicar(topico, dados, base + t)
                if t <= t0:
                    self.estado.eventos = []   # o que aconteceu antes de "ligar" já não é novidade
        self.ligado = False

    # ------------------------------------------------ mensagens
    def mensagem(self, msg):
        tipo = msg.get("type")
        if tipo == 3:   # o retrato inicial: todos os tópicos, sem acontecimentos (já tinham acontecido)
            res = msg.get("result") or {}
            agora = relogio()
            for topico in av.TOPICOS:
                if res.get(topico) is not None:
                    self.aplicar(topico, res[topico], agora)
            if res.get("Position.z"):
                self.posicoes.juntar(res["Position.z"])
            self.estado.eventos = []
        elif tipo == 1 and msg.get("target") == "feed":
            a = msg.get("arguments") or []
            if len(a) >= 2:
                # a hora da mensagem no feed (UTC), na mesma escala das posições; sem ela, a de agora
                try:
                    t = av.utc(a[2])
                except (IndexError, TypeError, ValueError):
                    t = relogio()
                self.aplicar(a[0], a[1], t)

    def aplicar(self, topico, dados, t):
        if topico == "Position.z":
            self.posicoes.juntar(dados)
            return
        self.estado.aplicar(topico, dados, t)
        if topico == "TimingData" and isinstance(dados, dict):
            for n, l in (dados.get("Lines") or {}).items():
                if isinstance(l, dict) and l.get("NumberOfLaps"):
                    self.fim_volta.setdefault(n, {}).setdefault(l["NumberOfLaps"], t)
        elif topico == "TrackStatus":
            self.pista_t.append((t, (self.estado.d.get("TrackStatus") or {}).get("Status")))
        # os acontecimentos guardam-se só 60 s (o ecrã só mostra os dos últimos 8 s)
        if len(self.estado.eventos) > 50:
            self.estado.eventos = [ev for ev in self.estado.eventos if ev["t"] > t - 60]

    def _verde(self, a, b):
        estado = "1"
        for t, st in self.pista_t:
            if t > b:
                break
            if t <= a:
                estado = st
            elif st != "1":
                return False
        return estado == "1"

    # ------------------------------------------------ mapa
    def _atualizar_mapa(self):
        circuito = (((self.estado.d.get("SessionInfo") or {}).get("Meeting") or {}).get("Circuit") or {}).get("ShortName")
        if circuito != self.circuito:
            self.circuito, self.mapa, self.transf, self.mapa_id = circuito, None, None, None
        if self.transf:
            return
        pontos = av.ler_pista(circuito)
        if len(pontos) < 50 and self.posicoes.pos and time.time() - self.tentou_volta > 60:
            self.tentou_volta = time.time()
            pontos = av.volta_limpa(self.fim_volta, self.posicoes.pos, self._verde)
            if len(pontos) >= 50:
                av.guardar_pista(circuito, pontos, "direto")
        if len(pontos) >= 50:
            self.mapa, self.transf = av.desenho(pontos)
            self.mapa_id = f"f1:{circuito}"
        elif self.mapa is None:
            track = ((ler_dados().get("f1") or {}).get("next") or {}).get("track")
            self.mapa = av.desenho_svg(track) if track else None
            self.mapa_id = f"osm:{circuito}" if self.mapa else None

    def converter(self, x, y):
        return av.converter(self.transf, x, y)

    def posicao(self, n, t):
        return self.posicoes.posicao(n, t)

    # ------------------------------------------------ o que o ecrã pede
    def vista(self, mapa=False):
        self.pedir()
        with self.tranca:
            self._atualizar_mapa()
            agora = relogio()
            if not self.estado.d.get("SessionInfo"):
                return {"semDados": True, "ligado": self.ligado, "erro": self.erro, "carros": [], "direcao": [],
                        "pista": {"estado": "verde", "amarelas": []}, "tempo": {}, "mapaId": self.mapa_id,
                        **({"mapa": self.mapa} if mapa else {})}
            # as posições: um pouco atrás da última amostra (chegam em lotes)
            ultima = self.posicoes.ultima()
            t_pos = min(agora, ultima) - ATRASO_S if ultima else None
            com_carros = bool(self.transf and t_pos)
            v = av.vista(self.estado, t_pos if com_carros else agora, utc_t=agora,
                         sessao=self if com_carros else None, passo=1.0)
            v["eventos"] = [ev for ev in self.estado.eventos if agora - av.JANELA_EVENTOS < ev["t"] <= agora]
            v["t"] = round(agora, 2)
            v["semPosicoes"] = not self.posicoes.pos
            v["mapaId"] = self.mapa_id
            if mapa:
                v["mapa"] = self.mapa
            return v

    def resumo(self):
        """Para a lista do Ao vivo: (estado da sessão, SessionInfo, o texto do minuto) do que está no feed."""
        with self.tranca:
            e = self.estado
            info = e.d.get("SessionInfo") or {}
            st = (e.d.get("SessionStatus") or {}).get("Status")
            lap = e.d.get("LapCount") or {}
            rel = e.d.get("ExtrapolatedClock") or {}
            falta = None
            if rel.get("Remaining"):
                falta = av.segundos(rel["Remaining"])
                if rel.get("Extrapolating") and rel.get("Utc"):
                    falta -= max(0.0, relogio() - av.utc(rel["Utc"]))
                falta = max(0, round(falta))
            return {"info": info, "status": st, "partida": e.x.get("partida"), "volta": lap.get("CurrentLap"),
                    "voltas": lap.get("TotalLaps"), "parte": e.nome_parte(), "falta": falta, "modo": e.modo(),
                    "pais": (info.get("Meeting") or {}).get("Country", {}).get("Code")}


DIRETO = Direto()


def _inicio_utc(info):
    """A hora de início da sessão no feed (StartDate é local; GmtOffset diz o fuso)."""
    try:
        h, m, _ = (int(float(x)) for x in (info.get("GmtOffset") or "0:0:0").lstrip("-").split(":"))
        sinal = -1 if (info.get("GmtOffset") or "").startswith("-") else 1
        local = datetime.fromisoformat(info["StartDate"]).replace(tzinfo=timezone.utc)
        return local - sinal * timedelta(hours=h, minutes=m)
    except (KeyError, ValueError, TypeError):
        return None


def entrada_ao_vivo(dados, agora):
    """A F1 na lista do Ao vivo: [] fora das sessões; senão um item como os jogos (sport "f1"), que liga o cliente."""
    s = sessao_agora(dados, agora)
    if REPLAY:   # teste: a sessão do arquivo, como se fosse agora
        DIRETO.pedir()
        info = DIRETO.resumo()["info"]
        s = {"gp": (info.get("Meeting") or {}).get("Name"), "nome": info.get("Name"),
             "inicio": _inicio_utc(info) or datetime.now(timezone.utc)}
    if not s:
        return []
    DIRETO.pedir()
    r = DIRETO.resumo()
    inicio_feed = _inicio_utc(r["info"])
    do_feed = inicio_feed is not None and abs((inicio_feed - s["inicio"]).total_seconds()) < 3 * 3600
    st = r["status"] if do_feed else None
    if st in ("Ends", "Finalised"):
        estado, tempo = "post", "Terminada"
    elif do_feed and (st == "Started" or r["partida"] is not None):
        estado = "in"
        if r["modo"] == "corrida":
            tempo = f"Volta {r['volta'] or '–'}/{r['voltas'] or '–'}"
        else:
            relogio = f"{r['falta'] // 60}:{r['falta'] % 60:02d}" if r["falta"] is not None else ""
            tempo = " · ".join(x for x in (r["parte"], relogio) if x) or "a decorrer"
    else:
        estado, tempo = "aquecimento", f"Aquecimento · {s['inicio'].astimezone().strftime('%H:%M')}"
    return [{
        "id": f"f1:{s['inicio'].strftime('%Y%m%d%H%M')}", "sport": "f1", "comp": {"chave": "f1", "nome": "Fórmula 1"},
        "home": None, "away": None, "hs": None, "as": None, "ev": [],
        "gp": s["gp"], "sessao": s["nome"], "estado": estado, "tempo": tempo,
        "iso": s["inicio"].astimezone().isoformat(timespec="minutes"),
        "bandeira": av.bandeira(r["pais"]) if do_feed else None,
    }]


def proximo(dados, agora):
    """A próxima sessão da F1 (para "Sem jogos ao vivo"), no formato do "proximo" do Ao vivo."""
    s = proxima_sessao(dados, agora)
    if not s:
        return None
    return {"sport": "f1", "comp": {"chave": "f1", "nome": "Fórmula 1"}, "gp": s["gp"], "sessao": s["nome"],
            "iso": s["inicio"].astimezone().isoformat(timespec="minutes")}
