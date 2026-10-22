"""F1 ao vivo: transforma as mensagens do live timing da F1 num estado e numa "vista" para o ecrã.

- Estado: o redutor. Recebe (tópico, dados, t) pela ordem em que chegam e funde-os (as mensagens são
  incrementais: dicionários fundem-se; as listas chegam como dicionários com o índice como chave).
  Também regista o que interessa ao ecrã (posição no início de cada volta, setores com amarela) e os
  acontecimentos (novo líder, Safety Car / VSC / vermelha, penalização, desistência, volta mais rápida, xadrez).
  É o mesmo para o arquivo (simulação) e para o feed ao vivo do tools/f1_gravar.py.
- Simulação: lê uma sessão de data/f1_gravacoes/arquivo/<pasta>/ (tools/f1_arquivo.py) e dá a vista em
  qualquer instante t (segundos desde o início da gravação). Reduz tudo uma vez e guarda retratos a cada 30 s,
  por isso cada pedido só aplica as mensagens desde o retrato anterior.
- Posições (Position.z): base64 + deflate cru; cada amostra traz a hora UTC. O desenho da pista sai de uma
  volta limpa do líder, rodado para ocupar o máximo do retângulo do mapa.

GET /api/f1/aovivo?simular=<pasta>&inicio=<min desde a partida>|volta=<n>&decorrido=<s>&vel=<x>[&mapa=1]
(ver serve.py). Só usa a biblioteca standard do Python.
"""

import base64
import bisect
import json
import math
import re
import threading
import urllib.request
import zlib
from array import array
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "f1_gravacoes" / "arquivo"
PISTAS = RAIZ / "data" / "f1_gravacoes" / "pistas"   # o traçado de cada circuito, tirado uma vez de uma volta limpa
BANDEIRAS = RAIZ / "web" / "img" / "bandeiras"         # bandeiras dos países (domínio público, flagcdn.com), uma vez
# o código do país no live timing da F1 -> ISO 3166 (o nome do ficheiro no flagcdn)
PAISES_ISO = {"AUS": "au", "CHN": "cn", "JPN": "jp", "BRN": "bh", "KSA": "sa", "USA": "us", "ITA": "it", "MON": "mc",
              "ESP": "es", "CAN": "ca", "AUT": "at", "GBR": "gb", "BEL": "be", "HUN": "hu", "NED": "nl", "AZE": "az",
              "SGP": "sg", "MEX": "mx", "BRA": "br", "QAT": "qa", "UAE": "ae", "POR": "pt", "FRA": "fr", "GER": "de",
              "RSA": "za", "TUR": "tr", "ARG": "ar", "RUS": "ru", "VIE": "vn", "MAL": "my", "KOR": "kr", "IND": "in"}
TOPICOS = ("SessionInfo", "SessionStatus", "TrackStatus", "LapCount", "ExtrapolatedClock", "Heartbeat",
           "DriverList", "TimingData", "TimingAppData", "RaceControlMessages", "WeatherData",
           "PitStopSeries", "ChampionshipPrediction")
RETRATO_S = 30          # um retrato do estado a cada 30 s da sessão
JANELA_EVENTOS = 8      # a vista leva os acontecimentos dos últimos 8 s (o ecrã mostra cada um 7 s)
MAPA_W, MAPA_H, MARGEM = 1000, 640, 34
ESTADOS_PISTA = {"1": "verde", "2": "amarela", "4": "sc", "5": "vermelha", "6": "vsc", "7": "vsc_fim"}
FIM_PARTE_S = 240       # qualificação: depois do xadrez, espera no máximo 4 min que os carros em pista acabem a volta
ANULADA = re.compile(r"CAR (\d+) \((\w+)\) (?:LAP|TIME ([\d:.]+)) DELETED - (.+?)(?: AT TURN (\d+)|$)")
MOTIVOS = {"TRACK LIMITS": "limites de pista", "DOUBLE YELLOW": "dupla amarela", "RED FLAG": "bandeira vermelha"}


# ---------------------------------------------------------------- utilitários

def segundos(hms):
    """'01:23:45.678' -> 5025.678"""
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def utc(texto):
    """'2026-10-11T11:57:48.5908289Z' -> segundos desde 1970 (os 7 decimais do .NET cortam-se a 6)"""
    texto = texto.rstrip("Z")
    if "." in texto:
        base, frac = texto.split(".")
        texto = f"{base}.{frac[:6]}"
    return datetime.fromisoformat(texto + "+00:00").timestamp()


def tempo_volta(v):
    """'1:37.280' -> 97.28 (None se vazio)"""
    if not v:
        return None
    try:
        m, s = v.split(":") if ":" in v else ("0", v)
        return int(m) * 60 + float(s)
    except ValueError:
        return None


def descomprimir(z):
    return json.loads(zlib.decompress(base64.b64decode(z), -15))


def fundir(alvo, upd):
    """Funde uma mensagem incremental no estado (e devolve o novo valor)."""
    if isinstance(upd, dict):
        if isinstance(alvo, list):
            for k, v in upd.items():
                if k == "_kf":
                    continue
                i = int(k)
                while len(alvo) <= i:
                    alvo.append(None)
                alvo[i] = fundir(alvo[i], v)
            return alvo
        if not isinstance(alvo, dict):
            alvo = {}
        for k, v in upd.items():
            if k == "_kf":
                continue
            if k == "_deleted":
                for d in v or []:
                    alvo.pop(str(d), None)
                continue
            alvo[k] = fundir(alvo.get(k), v)
        return alvo
    return upd


# ---------------------------------------------------------------- redutor

class Estado:
    def __init__(self):
        self.d = {}
        # derivados: posição de cada carro no início da volta, setores com amarela, melhor volta, líder
        self.x = {"pos_volta": {}, "voltas": {}, "amarelas": [], "melhor": None, "lider": None,
                  "partida": None, "rcm_vistos": 0,
                  # qualificação / treinos: o tipo de volta de cada carro, os melhores setores, o P1 da parte,
                  # quando começou cada parte, os eliminados {num: parte} e o fim de parte à espera dos carros em pista
                  "tipo_volta": {}, "setores_melhores": [None, None, None], "p1": None, "partes": {},
                  "fora": {}, "fim_parte": None,
                  # qualificação: os setores da melhor volta de cada carro e os da última volta completa
                  "setores_mv": {}, "setores_ult": {},
                  # corrida: paragens já vistas por carro, a paragem mais rápida, quando cada carro passou na box
                  "paragens": {}, "paragem_rapida": None, "box_t": {}}
        self.eventos = []

    def copia(self):
        return json.dumps([self.d, self.x])

    @classmethod
    def de_copia(cls, texto):
        e = cls()
        e.d, e.x = json.loads(texto)
        return e

    def linhas(self):
        return (self.d.get("TimingData") or {}).get("Lines") or {}

    def piloto(self, n):
        p = (self.d.get("DriverList") or {}).get(n) or {}
        return p.get("Tla") or n

    def modo(self):
        """'corrida' (também a sprint), 'quali' (também a qualificação sprint) ou 'treino'"""
        info = self.d.get("SessionInfo") or {}
        tipo, nome = info.get("Type") or "", info.get("Name") or ""
        if "Qualifying" in tipo or "Qualifying" in nome or "Shootout" in nome:
            return "quali"
        if tipo == "Practice" or "Practice" in nome:
            return "treino"
        return "corrida"

    def parte(self):
        try:
            return int((self.d.get("TimingData") or {}).get("SessionPart") or 0)
        except (TypeError, ValueError):
            return 0

    def nome_parte(self, k=None):
        """'Q2' (ou 'SQ2' na qualificação sprint); '' fora da qualificação"""
        k = self.parte() if k is None else k
        if self.modo() != "quali" or not k:
            return ""
        nome = (self.d.get("SessionInfo") or {}).get("Name") or ""
        return f"{'SQ' if 'Sprint' in nome or 'Shootout' in nome else 'Q'}{k}"

    def vagas(self, k):
        """Quantos passam da parte k para a seguinte (NoEntries[k]); None na última parte"""
        ne = (self.d.get("TimingData") or {}).get("NoEntries") or []
        if isinstance(ne, dict):
            ne = [ne[i] for i in sorted(ne, key=int)]
        return ne[k] if k < len(ne) and ne[k] else None

    def evento(self, t, tipo, titulo, texto="", num=None):
        self.eventos.append({"t": round(t, 3), "tipo": tipo, "titulo": titulo, "texto": texto, "num": num,
                             "id": f"{tipo}-{round(t, 1)}-{num or ''}"})

    def aplicar(self, topico, dados, t):
        if topico not in TOPICOS:
            return
        antes = None
        if topico == "SessionStatus":
            antes = (self.d.get("SessionStatus") or {}).get("Status")
        elif topico == "TrackStatus":
            antes = (self.d.get("TrackStatus") or {}).get("Status")
        elif topico == "TimingData":
            antes = {n: (l.get("Position"), l.get("Retired") or l.get("Stopped"), l.get("NumberOfLaps"))
                     for n, l in self.linhas().items()}
        self.d[topico] = fundir(self.d.get(topico), dados)
        if topico == "SessionStatus":
            st = (self.d["SessionStatus"] or {}).get("Status")
            if self.modo() != "corrida":
                self._sessao_quali(t, st, antes)
            elif st == "Started" and self.x["partida"] is None:
                self.x["partida"] = t
                self.evento(t, "partida", "LUZES APAGADAS", "Começou a corrida")
        elif topico == "TrackStatus":
            self._pista(t, antes)
        elif topico == "TimingData":
            if self.modo() == "corrida":
                self._tempos(t, antes)
            else:
                self._tempos_quali(t, antes)
        elif topico == "RaceControlMessages":
            self._direcao(t)
        elif topico == "PitStopSeries":
            self._paragens(t)
        if self.x.get("fim_parte"):
            self._fim_parte(t)

    def _pista(self, t, antes):
        st = (self.d.get("TrackStatus") or {}).get("Status")
        if st == antes:
            return
        if st == "4":
            self.evento(t, "sc", "SAFETY CAR", "Safety Car em pista")
        elif st == "6":
            self.evento(t, "vsc", "VIRTUAL SAFETY CAR", "VSC acionado")
        elif st == "5":
            self.evento(t, "vermelha", "BANDEIRA VERMELHA",
                        "Corrida interrompida" if self.modo() == "corrida" else "Sessão interrompida")
        elif st == "7":
            self.evento(t, "vsc_fim", "VSC A TERMINAR", "Recomeço em breve")
        elif st == "1" and antes in ("4", "5", "6", "7"):
            retomada = "Corrida retomada" if self.modo() == "corrida" else "Sessão retomada"
            nome = {"4": "Safety Car recolheu", "5": retomada}.get(antes, "Fim do VSC")
            self.evento(t, "verde", "BANDEIRA VERDE", nome)
        if st == "1":
            self.x["amarelas"] = []

    def _tempos(self, t, antes):
        linhas = self.linhas()
        a_correr = self.x["partida"] is not None
        for n, l in linhas.items():
            pos, ret, voltas = antes.get(n, (None, None, None))
            if l.get("NumberOfLaps") != voltas or n not in self.x["pos_volta"]:
                self.x["pos_volta"][n] = l.get("Position")
            if a_correr and (l.get("Retired") or l.get("Stopped")) and not ret:
                self.evento(t, "abd", "DESISTÊNCIA", self.piloto(n), n)
            if l.get("InPit") or l.get("PitOut"):
                self.x["box_t"][n] = t
        if a_correr:
            self._ultrapassagens(t, antes)
        # novo líder (depois dos primeiros 20 s, quando a ordem da grelha já assentou)
        lider = next((n for n, l in linhas.items() if l.get("Position") == "1"), None)
        if lider and lider != self.x["lider"]:
            if a_correr and self.x["lider"] and t - self.x["partida"] > 20:
                self.evento(t, "lider", "NOVO LÍDER", self.piloto(lider), lider)
            self.x["lider"] = lider
        # volta mais rápida da corrida (a partir da 3.ª volta, para não haver um destaque por carro no início)
        if a_correr:
            melhor = None
            for n, l in linhas.items():
                v = tempo_volta(((l.get("BestLapTime") or {}).get("Value")))
                if v and (melhor is None or v < melhor[0]):
                    melhor = (v, n, (l.get("BestLapTime") or {}).get("Value"))
            if melhor and (self.x["melhor"] is None or melhor[0] < self.x["melhor"][0] - 1e-6):
                volta = ((self.d.get("LapCount") or {}).get("CurrentLap") or 0)
                if self.x["melhor"] is not None and volta >= 3:
                    self.evento(t, "rapida", "VOLTA MAIS RÁPIDA", f"{self.piloto(melhor[1])} · {melhor[2]}", melhor[1])
                self.x["melhor"] = list(melhor)

    # ------------------------------------------------ qualificação e treinos
    def _sessao_quali(self, t, st, antes):
        if st == antes:
            return
        if st == "Started":
            if self.x["partida"] is None:
                self.x["partida"] = t
            k = self.parte()
            self.x["partes"].setdefault(str(k), t)
            self.x["p1"] = None
            self.x["tipo_volta"] = {}
            if self.modo() == "quali":
                self.evento(t, "partida", f"COMEÇOU A {self.nome_parte(k)}", "Pit lane aberta")
            else:
                self.evento(t, "partida", "COMEÇOU O TREINO", "Pit lane aberta")
        elif st == "Finished" and self.modo() == "quali":
            # os que estão numa volta lançada ainda a acabam: os eliminados e a pole só se sabem depois
            pend = {n: l.get("NumberOfLaps") for n, l in self.linhas().items()
                    if not l.get("InPit") and not l.get("KnockedOut") and n not in self.x["fora"]
                    and self.x["tipo_volta"].get(n) == "lancada"}
            self.x["fim_parte"] = {"parte": self.parte(), "t": t, "pend": pend}

    def _fim_parte(self, t):
        f = self.x["fim_parte"]
        linhas = self.linhas()
        f["pend"] = {n: v for n, v in f["pend"].items()
                     if n in linhas and not linhas[n].get("InPit") and linhas[n].get("NumberOfLaps") == v
                     and self.x["tipo_volta"].get(n) == "lancada"}
        k = f["parte"]
        nome = self.nome_parte(k)
        vagas = self.vagas(k)

        def posicao(n):
            try:
                return int(linhas[n].get("Position") or 99)
            except ValueError:
                return 99
        # quem está abaixo da linha e já não vai numa volta lançada já não sobe: fica logo fora (o aviso espera pelos outros)
        for n in linhas:
            if vagas and posicao(n) > vagas and n not in f["pend"] and n not in self.x["fora"]:
                self.x["fora"][n] = k
        if f["pend"] and t - f["t"] < FIM_PARTE_S:
            return
        self.x["fim_parte"] = None
        if vagas:
            fora = sorted((n for n in linhas if posicao(n) > vagas and self.x["fora"].get(n, k) == k), key=posicao)
            for n in fora:
                self.x["fora"][n] = k
            if fora:
                self.evento(t, "eliminados", f"FORA NA {nome}", " · ".join(self.piloto(n) for n in fora))
        else:
            pole = next((n for n in linhas if posicao(n) == 1), None)
            if pole:
                tempo = self.melhor_volta(linhas[pole], k)
                self.evento(t, "pole", "POLE POSITION", f"{self.piloto(pole)} · {tempo}".strip(" ·"), pole)

    def melhor_volta(self, l, k=None):
        """O melhor tempo do carro na parte k (a atual por omissão); nos treinos, o melhor da sessão"""
        k = self.parte() if k is None else k
        tempos = l.get("BestLapTimes")
        if k and tempos:
            if isinstance(tempos, dict):
                tempos = [tempos.get(str(i)) for i in range(3)]
            return ((tempos[k - 1] if k - 1 < len(tempos) else None) or {}).get("Value") or ""
        return (l.get("BestLapTime") or {}).get("Value") or ""

    def setores_volta(self, l):
        """Os setores já feitos nesta volta: [(tempo, 'roxo'|'verde'|'amarelo') ou None] x3
        (um setor é desta volta quando todos os mini-setores dele já têm estado: no fim da volta voltam a 0)"""
        sectores = l.get("Sectors") or []
        if isinstance(sectores, dict):
            sectores = [sectores.get(str(i)) for i in range(3)]
        saida = []
        for s in sectores[:3]:
            s = s or {}
            segs = s.get("Segments") or []
            if isinstance(segs, dict):
                segs = list(segs.values())
            feito = bool(s.get("Value")) and bool(segs) and all((g or {}).get("Status") for g in segs)
            if not feito:
                saida.append(None)
                continue
            cor = "roxo" if s.get("OverallFastest") else "verde" if s.get("PersonalFastest") else "amarelo"
            saida.append((s["Value"], cor))
        saida += [None] * (3 - len(saida))
        # só contam pela ordem (S1, depois S2); os três feitos é a volta que acabou (os mini-setores ainda não
        # voltaram a 0) e um S2/S3 sem o S1 é o que sobrou da volta anterior
        if all(saida) or not saida[0]:
            return [None] * 3
        return saida if saida[1] else [saida[0], None, None]

    def _tempos_quali(self, t, antes):
        linhas = self.linhas()
        melhores = self.x["setores_melhores"]
        tipos = self.x["tipo_volta"]
        bandeira = (self.d.get("SessionStatus") or {}).get("Status") != "Started"   # depois do xadrez já não há voltas lançadas
        for n, l in linhas.items():
            pos, ret, voltas = antes.get(n, (None, None, None))
            sectores = l.get("Sectors") or []
            if isinstance(sectores, dict):
                sectores = [sectores.get(str(i)) for i in range(3)]
            for i, s in enumerate(sectores[:3]):
                v = tempo_volta((s or {}).get("Value"))
                if v and (melhores[i] is None or v < melhores[i]):
                    melhores[i] = v
            # uma volta completa (os três setores com tempo): guarda-a; se é a melhor da parte, ficam os setores dela
            tres = tuple(tempo_volta((s or {}).get("Value")) for s in sectores[:3])
            if len(tres) == 3 and all(tres) and list(tres) != self.x["setores_ult"].get(n):
                self.x["setores_ult"][n] = list(tres)
                mv = tempo_volta(self.melhor_volta(l))
                if mv and abs(sum(tres) - mv) < 0.06:
                    self.x["setores_mv"][n] = list(tres)
            setores = self.setores_volta(l)
            # o tipo de volta: box -> saída -> lançada -> (lenta ou outra lançada); os setores feitos corrigem
            tipo = tipos.get(n)
            if l.get("InPit"):
                tipo = "box"
            elif tipo in (None, "box") or l.get("PitOut"):
                tipo = "saida"
            elif voltas is not None and l.get("NumberOfLaps") != voltas:
                tipo = "lancada" if tipo in ("saida", "lenta") and not bandeira else "lenta"
            if tipo in ("lancada", "lenta") and not (bandeira and tipo == "lenta"):
                for i, s in enumerate(setores):
                    v = tempo_volta(s[0]) if s else None
                    if v and melhores[i]:
                        if v <= melhores[i] * 1.03:
                            tipo = "lancada"
                        elif v > melhores[i] * 1.10:
                            tipo = "lenta"
            tipos[n] = tipo
        # novo P1 da parte (a pole provisória na Q3); o primeiro tempo só conta se já houver outro para bater
        melhor, quantos = None, 0
        for n, l in linhas.items():
            if n in self.x["fora"] or l.get("KnockedOut"):
                continue
            v = tempo_volta(self.melhor_volta(l))
            if v:
                quantos += 1
                if melhor is None or v < melhor[0]:
                    melhor = (v, n, self.melhor_volta(l))
        if not melhor:
            return
        k = self.parte()
        if self.x["p1"] is None or melhor[0] < self.x["p1"][0] - 1e-6:
            if quantos >= 2 or k >= 2:
                if self.modo() != "quali":
                    titulo = "MAIS RÁPIDO"
                elif self.vagas(k) is None:
                    titulo = "POLE PROVISÓRIA"
                else:
                    titulo = f"MAIS RÁPIDO NA {self.nome_parte(k)}"
                self.evento(t, "p1", titulo, f"{self.piloto(melhor[1])} · {melhor[2]}", melhor[1])
        self.x["p1"] = list(melhor)

    def _ultrapassagens(self, t, antes):
        """Ultrapassagem no top 5 (do 2.º ao 5.º; a do 1.º é o "novo líder"): dois carros que trocam de lugar com a
        pista verde, depois da 1.ª volta e sem nenhum deles ter passado pela box no último minuto (as trocas das
        paragens não contam). As que se desfazem em 15 s saem no limpar_eventos."""
        if (self.d.get("TrackStatus") or {}).get("Status") not in ("1", "2", None):
            return
        if ((self.d.get("LapCount") or {}).get("CurrentLap") or 0) < 2:
            self.x["ult_pend"] = []
            return
        linhas = self.linhas()
        por_pos = {l.get("Position"): n for n, l in linhas.items()}
        for n, l in linhas.items():
            try:
                p, p0 = int(l.get("Position") or 0), int((antes.get(n) or (None,))[0] or 0)
            except ValueError:
                continue
            if not (2 <= p <= 5) or p0 != p + 1:
                continue
            m = next((x for x, a in antes.items() if a[0] == str(p) and x != n), None)
            if not m or por_pos.get(str(p + 1)) != m:
                continue
            if any(t - self.x["box_t"].get(x, -1e9) < 60 or (linhas.get(x) or {}).get("Retired") for x in (n, m)):
                continue
            self.x.setdefault("ult_pend", []).append([t, n, m, p])
        # só conta se a nova ordem aguentar 8 s (nas linhas de tempo a ordem às vezes baralha por uns segundos)
        pend = []
        for t0, n, m, p in self.x.get("ult_pend") or []:
            if t - t0 < 8:
                pend.append([t0, n, m, p])
            elif (linhas.get(n) or {}).get("Position") == str(p) and (linhas.get(m) or {}).get("Position") == str(p + 1):
                self.evento(t, "ultrapassagem", "ULTRAPASSAGEM", f"{self.piloto(n)} passa {self.piloto(m)} · P{p}", n)
                self.eventos[-1]["contra"] = m
        self.x["ult_pend"] = pend

    def _paragens(self, t):
        """Cada paragem nova: o tempo parado (7 s no ecrã) e a mais rápida da corrida."""
        tempos = (self.d.get("PitStopSeries") or {}).get("PitTimes") or {}
        for n, lista in tempos.items():
            if isinstance(lista, dict):
                lista = [lista[k] for k in sorted(lista, key=int)]
            vistas = self.x["paragens"].get(n, 0)
            for ps in [x for x in lista if x][vistas:]:
                ps = ps.get("PitStop") or {}
                try:
                    parado = float(ps.get("PitStopTime") or "")
                except ValueError:
                    continue
                if not 0 < parado < 60:
                    continue
                texto = f"{self.piloto(n)} · {str(round(parado, 1)).replace('.', ',')} s"
                rapida = self.x["paragem_rapida"]
                if rapida is None or parado < rapida[0]:
                    self.x["paragem_rapida"] = [parado, n, texto]
                titulo = "PARAGEM MAIS RÁPIDA" if rapida is not None and parado < rapida[0] else "PARAGEM NA BOX"
                self.evento(t, "paragem", titulo, texto, n)
            self.x["paragens"][n] = len([x for x in lista if x])

    def _direcao(self, t):
        msgs = (self.d.get("RaceControlMessages") or {}).get("Messages") or []
        if isinstance(msgs, dict):
            msgs = [msgs[k] for k in sorted(msgs, key=int)]
            self.d["RaceControlMessages"]["Messages"] = msgs
        for m in msgs[self.x["rcm_vistos"]:]:
            if not m:
                continue
            texto = (m.get("Message") or "").upper()
            flag, scope = m.get("Flag"), m.get("Scope")
            if flag in ("YELLOW", "DOUBLE YELLOW") and scope == "Sector" and m.get("Sector"):
                if m["Sector"] not in self.x["amarelas"]:
                    self.x["amarelas"].append(m["Sector"])
            elif flag == "CLEAR" and scope == "Sector":
                self.x["amarelas"] = [s for s in self.x["amarelas"] if s != m.get("Sector")]
            elif flag in ("GREEN", "CLEAR") and scope == "Track":
                self.x["amarelas"] = []
            anulada = ANULADA.search(texto) if self.modo() != "corrida" else None
            if flag == "CHEQUERED" or "CHEQUERED FLAG" in texto:
                fim = {"corrida": "Fim da corrida", "treino": "Fim do treino"}.get(self.modo(), f"Fim da {self.nome_parte()}")
                self.evento(t, "xadrez", "BANDEIRA DE XADREZ", fim)
            elif anulada:
                num, tla, tempo, motivo, curva = anulada.groups()
                motivo = MOTIVOS.get(motivo.strip(), motivo.strip().lower())
                texto_ev = " · ".join(x for x in (tla, tempo, motivo + (f" (curva {curva})" if curva else "")) if x)
                self.evento(t, "anulada", "VOLTA ANULADA", texto_ev, num)
            elif "PENALTY" in texto and "NO FURTHER" not in texto and "SERVED" not in texto:
                self.evento(t, "penalizacao", "PENALIZAÇÃO", m.get("Message") or "", m.get("RacingNumber"))
        self.x["rcm_vistos"] = len(msgs)


# ---------------------------------------------------------------- simulação a partir do arquivo

def ler_stream(ficheiro):
    """[(t, dados)] de um .jsonStream"""
    saida = []
    with open(ficheiro, encoding="utf-8-sig") as f:
        for linha in f:
            if len(linha) > 12 and linha[2] == ":":
                try:
                    saida.append((segundos(linha[:12]), json.loads(linha[12:])))
                except ValueError:
                    pass
    return saida


def limpar_eventos(eventos):
    """Tira o ruído: a liderança que só muda durante as paragens (volta ao mesmo em menos de 15 s) e as
    "desistências" depois da bandeira de xadrez (os carros que param depois da meta)."""
    xadrez = next((ev["t"] for ev in eventos if ev["tipo"] == "xadrez"), None)
    lideres = [ev for ev in eventos if ev["tipo"] == "lider"]
    fora = set()
    for a, b in zip(lideres, lideres[1:]):
        if b["t"] - a["t"] < 15:
            fora.update((a["id"], b["id"]))
    # ultrapassagens que se desfazem em menos de 15 s (A passa B e B volta a passar A)
    ult = [ev for ev in eventos if ev["tipo"] == "ultrapassagem"]
    for i, a in enumerate(ult):
        for b in ult[i + 1:]:
            if b["t"] - a["t"] > 15:
                break
            if b["num"] == a.get("contra") and b.get("contra") == a["num"]:
                fora.update((a["id"], b["id"]))
    return [ev for ev in eventos if ev["id"] not in fora
            and not (ev["tipo"] == "abd" and xadrez is not None and ev["t"] > xadrez)]


# ---------------------------------------------------------------- traçado da pista

def _ficheiro_pista(circuito):
    return PISTAS / f"{''.join(ch for ch in (circuito or '') if ch.isalnum() or ch in '-_ ')}.json"


def ler_pista(circuito):
    """Os pontos (coordenadas da F1) do traçado guardado deste circuito; [] se ainda não há."""
    if not circuito or not _ficheiro_pista(circuito).is_file():
        return []
    try:
        return [tuple(p) for p in json.loads(_ficheiro_pista(circuito).read_text(encoding="utf-8"))["pontos"]]
    except (OSError, ValueError, KeyError):
        return []


def guardar_pista(circuito, pontos, origem):
    if not circuito:
        return
    PISTAS.mkdir(parents=True, exist_ok=True)
    _ficheiro_pista(circuito).write_text(json.dumps({"circuito": circuito, "sessao": origem,
                                                     "pontos": [[round(x), round(y)] for x, y in pontos]}), encoding="utf-8")


def volta_limpa(fim_volta, pos, verde):
    """Os pontos de uma volta rápida e limpa: das voltas mais curtas (até 3% da mais rápida), a primeira com o
    carro sempre em pista, a pista verde (verde(a, b)), sem saltos entre amostras e que fecha onde começou.
    fim_volta: carro -> {voltas feitas: t}; pos: carro -> (t, x, y, fora de pista), na mesma escala de t."""
    voltas = []
    for n, fins in fim_volta.items():
        for v, b in fins.items():
            a = fins.get(v - 1)
            if a is not None and b - a > 40:
                voltas.append((b - a, n, a, b))
    if not voltas:
        return []
    rapida = min(v[0] for v in voltas)
    for dur, n, a, b in sorted(v for v in voltas if v[0] <= rapida * 1.03):
        if n not in pos or not verde(a, b):
            continue
        ts, xs, ys, fora = pos[n]
        i, j = bisect.bisect_left(ts, a), bisect.bisect_right(ts, b)
        if j - i < 100 or any(fora[i:j]):
            continue
        pontos = [(xs[k], ys[k]) for k in range(i, j)]
        passos = sorted(math.dist(p, q) for p, q in zip(pontos, pontos[1:]))
        mediana = passos[len(passos) // 2] or 1
        if passos[-1] > mediana * 6 or math.dist(pontos[0], pontos[-1]) > mediana * 4:
            continue
        return pontos
    return []


def desenho(pontos):
    """O desenho da pista no retângulo do mapa (rodado para ficar o maior possível) e a transformação
    (coordenadas da F1 -> mapa) para pôr lá os carros: (mapa, transf)."""
    melhor = None
    for graus in range(0, 180, 3):
        r = math.radians(graus)
        c, s = math.cos(r), math.sin(r)
        rx = [x * c - y * s for x, y in pontos]
        ry = [x * s + y * c for x, y in pontos]
        w, h = max(rx) - min(rx), max(ry) - min(ry)
        esc = min((MAPA_W - 2 * MARGEM) / (w or 1), (MAPA_H - 2 * MARGEM) / (h or 1))
        if melhor is None or esc > melhor[0]:
            melhor = (esc, c, s, min(rx), max(rx), min(ry), max(ry))
    esc, c, s, x0, x1, y0, y1 = melhor
    dx = (MAPA_W - (x1 - x0) * esc) / 2 - x0 * esc
    dy = (MAPA_H - (y1 - y0) * esc) / 2 + y1 * esc   # y para baixo no ecrã
    transf = (c, s, esc, dx, dy)
    caminho = [converter(transf, x, y) for x, y in pontos]
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in caminho) + " Z"
    return {"w": MAPA_W, "h": MAPA_H, "d": d, "partida": caminho[0] if caminho else None}, transf


def converter(transf, x, y):
    c, s, esc, dx, dy = transf
    return round((x * c - y * s) * esc + dx, 1), round(-(x * s + y * c) * esc + dy, 1)


def desenho_svg(track):
    """Sem traçado da F1 (circuito novo, sem token): o desenho do OpenStreetMap do live.json (f1.next.track,
    viewBox próprio) passado para o retângulo do mapa. Sem transformação: aí não há carros."""
    try:
        _, _, w, h = (float(v) for v in track["viewBox"].split())
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", track["d"])]
    except (KeyError, ValueError, AttributeError):
        return None
    esc = min((MAPA_W - 2 * MARGEM) / w, (MAPA_H - 2 * MARGEM) / h)
    ox, oy = (MAPA_W - w * esc) / 2, (MAPA_H - h * esc) / 2
    pares = [(ox + x * esc, oy + y * esc) for x, y in zip(nums[::2], nums[1::2])]
    if len(pares) < 10:
        return None
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pares) + " Z"
    return {"w": MAPA_W, "h": MAPA_H, "d": d, "partida": [round(pares[0][0], 1), round(pares[0][1], 1)]}


class Sessao:
    """Uma sessão do arquivo, reduzida uma vez, com retratos a cada 30 s e as posições dos carros."""

    def __init__(self, pasta):
        self.pasta = pasta
        msgs = []
        for topico in TOPICOS:
            f = pasta / f"{topico}.jsonStream"
            if f.is_file():
                msgs += [(t, i, topico, d) for i, (t, d) in enumerate(ler_stream(f))]
        msgs.sort(key=lambda m: (m[0], TOPICOS.index(m[2]), m[1]))
        self.msgs = [(t, top, d) for t, _, top, d in msgs]
        self.tempos = [m[0] for m in self.msgs]
        # passagem completa: acontecimentos, retratos, voltas e a hora UTC de cada t
        e = Estado()
        self.retratos, self.t_retratos = [], []
        self.voltas = {}          # volta -> t em que o líder a começou
        self.utc0 = []            # (utc - t) de cada Heartbeat
        self.pista_t = []         # (t, estado da pista)
        self.fim_volta = {}       # carro -> {n.º de voltas feitas: t em que passou a meta}
        proximo = 0.0
        for t, top, d in self.msgs:
            while t >= proximo:
                self.retratos.append(e.copia())
                self.t_retratos.append(proximo)
                proximo += RETRATO_S
            e.aplicar(top, d, t)
            if top == "LapCount" and isinstance(d, dict) and d.get("CurrentLap") and e.x["partida"] is not None:
                self.voltas.setdefault(d["CurrentLap"], t)
            if top == "Heartbeat" and d.get("Utc"):
                self.utc0.append(utc(d["Utc"]) - t)
            if top == "TimingData" and isinstance(d, dict):
                for n, l in (d.get("Lines") or {}).items():
                    if isinstance(l, dict) and l.get("NumberOfLaps"):
                        self.fim_volta.setdefault(n, {}).setdefault(l["NumberOfLaps"], t)
            if top == "TrackStatus":
                self.pista_t.append((t, (e.d.get("TrackStatus") or {}).get("Status")))
        self.eventos = limpar_eventos(e.eventos)
        self.partida = e.x["partida"] or 0.0
        self.fim = self.tempos[-1] if self.tempos else 0.0
        self.base_utc = sorted(self.utc0)[len(self.utc0) // 2] if self.utc0 else 0.0
        self.final = e
        self._posicoes()
        self._mapa()

    # ------------------------------------------------ posições
    def _posicoes(self):
        self.pos = {}   # n -> (array t, array x, array y, bytearray fora de pista)
        f = self.pasta / "Position.z.jsonStream"
        if not f.is_file():
            return
        for _, z in ler_stream(f):
            try:
                amostras = descomprimir(z).get("Position") or []
            except (ValueError, zlib.error):
                continue
            for a in amostras:
                t = utc(a["Timestamp"]) - self.base_utc
                for n, p in (a.get("Entries") or {}).items():
                    ts, xs, ys, fora = self.pos.setdefault(n, (array("d"), array("f"), array("f"), bytearray()))
                    if ts and t <= ts[-1]:
                        continue
                    if not p.get("X") and not p.get("Y"):   # (0, 0): carro sem posição (na garagem, sem sinal)
                        continue
                    ts.append(t)
                    xs.append(p.get("X", 0))
                    ys.append(p.get("Y", 0))
                    fora.append(0 if p.get("Status") == "OnTrack" else 1)

    def posicao(self, n, t):
        dados = self.pos.get(n)
        if not dados or not dados[0]:
            return None
        ts, xs, ys, _ = dados
        i = bisect.bisect_right(ts, t)
        if i == 0:
            return xs[0], ys[0]
        if i >= len(ts):
            return xs[-1], ys[-1]
        f = (t - ts[i - 1]) / ((ts[i] - ts[i - 1]) or 1)
        return xs[i - 1] + (xs[i] - xs[i - 1]) * f, ys[i - 1] + (ys[i] - ys[i - 1]) * f

    # ------------------------------------------------ desenho da pista
    def _verde(self, a, b):
        """A pista esteve verde entre a e b?"""
        estado = "1"
        for t, st in self.pista_t:
            if t > b:
                break
            if t <= a:
                estado = st
            elif st != "1":
                return False
        return estado == "1"

    def _mapa(self):
        self.mapa, self.transf = None, None
        if not self.pos:
            return
        # o traçado guarda-se por circuito (as coordenadas da F1 são as mesmas em todas as sessões do circuito)
        circuito = (((self.final.d.get("SessionInfo") or {}).get("Meeting") or {}).get("Circuit") or {}).get("ShortName")
        pontos = ler_pista(circuito)
        if len(pontos) < 50:
            pontos = volta_limpa(self.fim_volta, self.pos, self._verde)
            if len(pontos) >= 50:
                guardar_pista(circuito, pontos, self.pasta.name)
        if len(pontos) < 50:   # sem volta limpa: as amostras em pista do carro com mais amostras
            n = max(self.pos, key=lambda k: len(self.pos[k][0]))
            ts, xs, ys, fora = self.pos[n]
            pontos = [(xs[k], ys[k]) for k in range(0, len(ts), 3) if not fora[k]][:3000]
        self.mapa, self.transf = desenho(pontos)

    def converter(self, x, y):
        return converter(self.transf, x, y)

    # ------------------------------------------------ estado em t
    def estado(self, t):
        i = max(0, bisect.bisect_right(self.t_retratos, t) - 1)
        e = Estado.de_copia(self.retratos[i]) if self.retratos else Estado()
        a = bisect.bisect_left(self.tempos, self.t_retratos[i] if self.retratos else 0)
        b = bisect.bisect_right(self.tempos, t)
        for tm, top, d in self.msgs[a:b]:
            e.aplicar(top, d, tm)
        e.eventos = []
        return e

    def inicio(self, minutos=None, volta=None, parte=None):
        if parte:   # qualificação: 'Q2' / 'SQ2' / '2' -> 5 s antes de abrir a pit lane dessa parte
            k = "".join(ch for ch in str(parte) if ch.isdigit())
            if k in self.final.x["partes"]:
                return self.final.x["partes"][k] - 5 + (minutos or 0) * 60
        if volta is not None and self.voltas:
            v = min(self.voltas, key=lambda k: abs(k - volta))
            return self.voltas[v] - 2
        return self.partida + (minutos or 0) * 60


def vista_quali(e, carros):
    """Qualificação e treinos: a torre ordenada pelo melhor tempo da parte, com o tipo de volta de cada carro,
    os setores desta volta e os eliminados em baixo (com o tempo da parte em que caíram)."""
    k = e.parte()
    linhas = e.linhas()
    fora = dict(e.x.get("fora") or {})
    vagas = e.vagas(k) if e.modo() == "quali" else None
    for c in carros:
        l = linhas.get(c["num"]) or {}
        stats = l.get("Stats") or []
        if isinstance(stats, dict):
            stats = [stats.get(str(i)) for i in range(3)]
        # eliminado numa parte anterior (o KnockedOut só chega quando começa a parte seguinte)
        kf = fora.get(c["num"])
        if kf is None and l.get("KnockedOut") and k > 1:
            kf = next((j for j in range(1, k) if e.vagas(j) and c["pos"] > e.vagas(j)), k - 1)
        if kf is not None:
            c["fora"] = e.nome_parte(kf)
            c["melhorVolta"] = e.melhor_volta(l, kf)
            c["gap"] = ""
            c["estado"] = "fora"
            c["setores"] = []
            continue
        c["melhorVolta"] = e.melhor_volta(l, k)
        st = (stats[k - 1] if k and k - 1 < len(stats) else None) or {}
        c["gap"] = "" if c["pos"] == 1 or not c["melhorVolta"] else (st.get("TimeDiffToFastest") or "") if k else (l.get("TimeDiffToFastest") or "")
        tipo = (e.x.get("tipo_volta") or {}).get(c["num"])
        c["estado"] = "box" if l.get("InPit") else (tipo or "")
        feitos = e.setores_volta(l) if c["estado"] == "lancada" else []
        c["setores"] = [s[1] if s else "" for s in feitos]
        # delta ao vivo: os setores feitos desta volta contra os mesmos setores da melhor volta dele
        mv = (e.x.get("setores_mv") or {}).get(c["num"])
        tempos = [tempo_volta(s[0]) if s else None for s in feitos]
        if mv and tempos and tempos[0]:
            c["deltaVolta"] = round(sum(v - mv[i] for i, v in enumerate(tempos) if v), 3)
    ativos = sorted((c for c in carros if c.get("estado") != "fora"),
                    key=lambda c: (not c["melhorVolta"], c["pos"]))
    # distância para a linha: quem está até 3 lugares acima ou abaixo vê a margem que tem ou o que lhe falta
    a_decorrer = (e.d.get("SessionStatus") or {}).get("Status") == "Started" or e.x.get("fim_parte")
    if vagas and a_decorrer and len(ativos) > vagas:
        dentro, primeiro_fora = tempo_volta(ativos[vagas - 1]["melhorVolta"]), tempo_volta(ativos[vagas]["melhorVolta"])
        for i, c in enumerate(ativos):
            v = tempo_volta(c["melhorVolta"])
            if i < vagas and i >= vagas - 3 and v and primeiro_fora:
                c["corte"] = {"v": f"{primeiro_fora - v:.3f}", "txt": "de margem", "lado": "dentro"}
            elif vagas <= i < vagas + 3 and v and dentro:
                c["corte"] = {"v": f"+{v - dentro:.3f}", "txt": "para passar", "lado": "fora"}
    fora_l = sorted((c for c in carros if c.get("estado") == "fora"), key=lambda c: c["pos"])
    return ativos + fora_l, {"parte": e.nome_parte(k), "vagas": vagas, "modo": e.modo()}


def campeonato(e):
    """"O campeonato se acabasse agora" (ChampionshipPrediction): os 6 primeiros pilotos e as 5 primeiras equipas,
    com os pontos previstos, quantos ganham nesta corrida e os lugares que sobem ou descem."""
    cp = e.d.get("ChampionshipPrediction") or {}
    pilotos = e.d.get("DriverList") or {}
    if not cp.get("Drivers"):
        return None

    def linha(x, nome, cor):
        pts, atual = x.get("PredictedPoints") or 0, x.get("CurrentPoints") or 0
        return {"pos": x.get("PredictedPosition"), "nome": nome, "cor": cor, "pontos": round(pts),
                "ganha": round(pts - atual), "sobe": (x.get("CurrentPosition") or 0) - (x.get("PredictedPosition") or 0)}
    ps = sorted((x for x in cp["Drivers"].values() if x and x.get("PredictedPosition")), key=lambda x: x["PredictedPosition"])[:6]
    eq = sorted((x for x in (cp.get("Teams") or {}).values() if x and x.get("PredictedPosition")), key=lambda x: x["PredictedPosition"])[:6]
    cor_eq = {p.get("TeamName"): "#" + (p.get("TeamColour") or "888888") for p in pilotos.values() if isinstance(p, dict)}
    return {
        "pilotos": [linha(x, (pilotos.get(x.get("RacingNumber")) or {}).get("Tla") or x.get("RacingNumber"),
                          "#" + ((pilotos.get(x.get("RacingNumber")) or {}).get("TeamColour") or "888888")) for x in ps],
        "equipas": [linha(x, x.get("TeamName") or "", cor_eq.get(x.get("TeamName"), "#888888")) for x in eq],
    }


def vista(e, t, utc_t=None, sessao=None, passo=1.0):
    """O que o ecrã precisa, a partir de um Estado."""
    d = e.d
    info = d.get("SessionInfo") or {}
    reuniao = info.get("Meeting") or {}
    pilotos = d.get("DriverList") or {}
    app = (d.get("TimingAppData") or {}).get("Lines") or {}
    voltas = d.get("LapCount") or {}
    melhor = e.x.get("melhor")
    carros = []
    for n, l in e.linhas().items():
        p = pilotos.get(n) or {}
        stints = (app.get(n) or {}).get("Stints") or []
        if isinstance(stints, dict):
            stints = [stints[k] for k in sorted(stints, key=int)]
        st = next((s for s in reversed(stints) if s), None) or {}
        ultima = l.get("LastLapTime") or {}
        try:
            pos = int(l.get("Position") or 99)
        except ValueError:
            pos = 99
        try:
            delta = int(e.x["pos_volta"].get(n) or pos) - pos
        except ValueError:
            delta = 0
        if not l.get("NumberOfLaps"):   # 1.ª volta: compara com a grelha
            try:
                delta = int((app.get(n) or {}).get("GridPos") or pos) - pos
            except ValueError:
                delta = 0
        intervalo = (l.get("IntervalToPositionAhead") or {}).get("Value") or ""
        estado = "abd" if (l.get("Retired") or l.get("Stopped")) else "box" if (l.get("InPit") or l.get("PitOut")) else ""
        carro = {
            "num": n, "tla": p.get("Tla") or n, "nome": p.get("LastName") or p.get("BroadcastName") or n,
            "equipa": p.get("TeamName") or "", "cor": "#" + (p.get("TeamColour") or "888888"),
            "pos": pos, "gap": l.get("GapToLeader") or "", "int": intervalo,
            "pneu": st.get("Compound"), "idade": st.get("TotalLaps"), "novo": st.get("New") == "true",
            "paragens": l.get("NumberOfPitStops") or 0, "voltas": l.get("NumberOfLaps") or 0,
            "ultima": ultima.get("Value") or "", "roxo": bool(melhor and ultima.get("Value") == melhor[2] and melhor[1] == n),
            "verde": bool(ultima.get("PersonalFastest")), "delta": delta, "estado": estado,
        }
        if sessao is not None:
            a, b = sessao.posicao(n, t), sessao.posicao(n, t + passo)
            if a and b:
                carro["xy"] = [*sessao.converter(*a), *sessao.converter(*b)]
        carros.append(carro)
    carros.sort(key=lambda c: (c["estado"] == "abd", c["pos"]))
    # lutas: a menos de 1 s do da frente, os dois em pista (o da frente fica marcado também)
    lutas = []
    if e.modo() == "corrida":
        for a, b in zip(carros, carros[1:]):
            try:
                gap = float(str(b["int"]).lstrip("+"))
            except ValueError:
                continue
            if 0 < gap < 1.0 and not a["estado"] and not b["estado"] and b["pos"] == a["pos"] + 1:
                a["luta"] = a.get("luta") or "frente"
                b["luta"] = "tras"
                lutas.append([b["num"], a["num"]])
    quali = None
    if e.modo() != "corrida":
        carros, quali = vista_quali(e, carros)
    # relógio: o tempo que falta (a F1 extrapola a partir da última mensagem)
    relogio = None
    rel = d.get("ExtrapolatedClock") or {}
    if rel.get("Remaining") and utc_t is not None:
        falta = segundos(rel["Remaining"])
        if rel.get("Extrapolating") and rel.get("Utc"):
            falta -= max(0.0, utc_t - utc(rel["Utc"]))
        relogio = max(0, round(falta))
    msgs = [m for m in ((d.get("RaceControlMessages") or {}).get("Messages") or []) if m]
    tempo = d.get("WeatherData") or {}
    pista = d.get("TrackStatus") or {}
    return {
        "gp": reuniao.get("Name"), "pais": (reuniao.get("Country") or {}).get("Code"),
        "bandeira": bandeira((reuniao.get("Country") or {}).get("Code")),
        "paisNome": (reuniao.get("Country") or {}).get("Name"), "circuito": (reuniao.get("Circuit") or {}).get("ShortName"),
        "sessao": info.get("Name"), "tipo": info.get("Type"),
        "volta": voltas.get("CurrentLap"), "voltas": voltas.get("TotalLaps"), "relogio": relogio,
        "estadoSessao": (d.get("SessionStatus") or {}).get("Status"),
        "pista": {"estado": ESTADOS_PISTA.get(pista.get("Status"), "verde"), "amarelas": sorted(e.x.get("amarelas") or [])},
        "melhor": {"num": melhor[1], "tempo": melhor[2]} if melhor else None,
        "carros": carros, "modo": e.modo(), "quali": quali, "lutas": lutas,
        "paragemRapida": {"num": e.x["paragem_rapida"][1], "texto": e.x["paragem_rapida"][2]} if e.x.get("paragem_rapida") else None,
        "campeonato": campeonato(e),
        "direcao": [{"volta": m.get("Lap"), "texto": m.get("Message"), "cat": m.get("Category"), "flag": m.get("Flag")}
                    for m in msgs[-3:]][::-1],
        "tempo": {"ar": tempo.get("AirTemp"), "pista": tempo.get("TrackTemp"), "chuva": tempo.get("Rainfall") not in (None, "0", 0)},
    }


def bandeira(codigo):
    """O endereço da bandeira do país do GP (web/img/bandeiras/<iso>.svg), descarregada do flagcdn.com da
    primeira vez; None se o país não está na tabela ou se não deu para descarregar (o ecrã mostra o código)."""
    iso = PAISES_ISO.get((codigo or "").upper())
    if not iso:
        return None
    f = BANDEIRAS / f"{iso}.svg"
    if not f.is_file():
        try:
            pedido = urllib.request.Request(f"https://flagcdn.com/{iso}.svg", headers={"User-Agent": "super-monitor"})
            with urllib.request.urlopen(pedido, timeout=8) as r:
                svg = r.read()
            if b"<svg" not in svg[:400]:
                return None
            BANDEIRAS.mkdir(parents=True, exist_ok=True)
            f.write_bytes(svg)
        except OSError:
            return None
    return f"img/bandeiras/{iso}.svg"


# ---------------------------------------------------------------- API (serve.py)

_sessoes, _tranca = {}, threading.Lock()


def pastas():
    return sorted(p.name for p in ARQUIVO.iterdir() if p.is_dir()) if ARQUIVO.is_dir() else []


def sessao(nome=None):
    """A sessão do arquivo com este nome (por omissão, a corrida mais recente), carregada uma vez."""
    todas = pastas()
    if not nome or nome in ("1", "f1"):
        corridas = [p for p in todas if p.endswith("-Race")]
        nome = (corridas or todas or [None])[-1]
    if not nome or nome not in todas:
        raise FileNotFoundError("Sem sessões no arquivo (corre o tools/f1_arquivo.py)")
    with _tranca:
        if nome not in _sessoes:
            _sessoes[nome] = Sessao(ARQUIVO / nome)
        return _sessoes[nome]


def simular(nome=None, inicio=None, volta=None, decorrido=0.0, vel=1.0, mapa=False, parte=None):
    s = sessao(nome)
    t0 = s.inicio(inicio, volta, parte)
    t = min(s.fim, t0 + decorrido * vel)
    v = vista(s.estado(t), t, utc_t=s.base_utc + t, sessao=s, passo=vel)
    v["t"] = round(t, 2)
    v["simulado"] = s.pasta.name
    v["eventos"] = [ev for ev in s.eventos if t - JANELA_EVENTOS * max(1.0, vel) < ev["t"] <= t]
    if mapa:
        v["mapa"] = s.mapa
    return v


if __name__ == "__main__":
    import sys
    import time
    t_ini = time.time()
    s = sessao(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{s.pasta.name}: {len(s.msgs)} mensagens, {len(s.pos)} carros com posições, "
          f"partida em {s.partida:.0f} s, fim {s.fim:.0f} s, carregada em {time.time() - t_ini:.1f} s")
    for ev in s.eventos:
        print(f"  {(ev['t'] - s.partida) / 60:6.1f} min  {ev['tipo']:12} {ev['titulo']} · {ev['texto'][:70]}")
