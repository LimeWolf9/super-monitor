"""MonitorHub: transforma o monitor da parede numa "TV" com apps, comandada pelo telemóvel.

Uso:  python hub.py                 (porto 8080, aceita ligações da rede de casa)
      python hub.py --port 9000
      python hub.py --host 127.0.0.1 (só este PC; o telemóvel deixa de chegar cá)

Páginas:
  /          ecrã da parede (o Início, o código, o loading e a app escolhida; as apps escolhem-se no comando)
  /comando   comando para o telemóvel

Cada app está em apps.json. Uma app com "arrancar" só corre enquanto está escolhida:
o hub arranca-a ao abrir e para-a ao sair (só se foi ele a arrancá-la).
Uma entrada com "agenda" atualiza-se sozinha: o hub pergunta-lhe a cada minuto o que está na hora (ver PROTOCOLO.md).

Só usa a biblioteca standard do Python, por isso não há nada para instalar.
"""

import argparse
import hmac
import json
import math
import os
import posixpath
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

RAIZ = Path(__file__).parent.resolve()
PASTA_WEB = RAIZ / "web"
# apps.json (no git) tem as apps; apps.local.json (fora do git) só o que muda neste PC, ex.: o PIN (ver ler_apps)
FICHEIRO_APPS = RAIZ / "apps.json"
FICHEIRO_APPS_LOCAL = RAIZ / "apps.local.json"
FICHEIRO_CONFIG = RAIZ / "config.json"
FICHEIRO_CONFIG_LOCAL = RAIZ / "config.local.json"   # fora do git: o que muda neste PC (ex.: a localidade do tempo)
NO_WINDOWS = os.name == "nt"

# Ações que o comando envia. As de navegação vão para a app ativa (no Início, ◀ ▶ mudam as notícias).
# "sair" fecha a app e volta ao Início (o ecrã manda-a quando a app não trata o "voltar").
# "atualizar" só faz sentido numa app que o anuncie (o comando só mostra o botão nesse caso).
ACOES = {"cima", "baixo", "esquerda", "direita", "ok", "voltar", "pausa", "menu", "energia", "sair", "atualizar"}


def e_acao(acao):
    """Ações conhecidas, mais os atalhos "ir_<sítio>" que uma app anuncia (ex.: ir_f1 salta para a F1)."""
    return acao in ACOES or bool(re.fullmatch(r"ir_[a-z0-9_]{1,30}", acao))
CAMPOS_MENU = ("id", "nome", "icone", "descricao", "em_breve", "etiqueta")
# Ações que o Início (web/apps/inicio.html) recebe quando está no ecrã; as outras são ignoradas
ACOES_INICIO = {"esquerda", "direita"}
EXT_PASTAS = ("js", "css", "png", "svg", "webp", "jpg", "woff2")
# A cada 5 códigos errados seguidos, o bloqueio cresce: 1 min, 5, 15 e depois sempre 60.
# Só volta a 1 min depois de um código certo.
BLOQUEIOS_PIN = (60, 5 * 60, 15 * 60, 60 * 60)
AGENDA_CADA = 60          # segundos entre perguntas à agenda de uma app (e logo a seguir a cada tarefa)
AGENDA_REGISTO_MAX = 200  # linhas que ficam no registo da agenda


def ler_json(caminho, omissao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return omissao


def ler_apps():
    """As apps do apps.json com o apps.local.json aplicado por cima.

    apps.local.json = {"<id da app ou do grupo>": {campos a mudar}}, ex.: {"despesas": {"pin": "..."}}.
    Fusão superficial: cada campo substitui o do apps.json; os ids dos filhos de um grupo também valem.
    Formato antigo (uma lista com as apps todas): usa-se tal e qual, como antes.
    """
    apps = ler_json(FICHEIRO_APPS, [])
    local = ler_json(FICHEIRO_APPS_LOCAL, None)
    if isinstance(local, list):
        return local
    if not isinstance(local, dict):
        return apps
    local = {k: v for k, v in local.items() if not k.startswith("_")}   # "_nota": comentários
    usados = set()

    def aplicar(item):
        mudar = local.get(item.get("id"))
        if isinstance(mudar, dict):
            usados.add(item["id"])
            item = {**item, **mudar}
        if isinstance(item.get("apps"), list):
            item = {**item, "apps": [aplicar(f) for f in item["apps"]]}
        return item

    apps = [aplicar(a) for a in apps]
    for desconhecido in sorted(set(local) - usados):
        print(f"Aviso: apps.local.json fala de \"{desconhecido}\", que não existe no apps.json (ignorado).")
    return apps


def responde(url, timeout=2):
    """True se o URL responde (qualquer código HTTP < 500 conta como "está vivo")."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def preparar_cmd(cfg):
    """(cmd, pasta) de um bloco {"pasta", "cmd"} do apps.json.

    "python" quer dizer o mesmo Python que corre o hub; um caminho relativo
    (ex.: .venv/Scripts/python.exe) é relativo à pasta da app.
    """
    pasta = RAIZ / Path(os.path.expandvars(os.path.expanduser(cfg.get("pasta", str(RAIZ)))))   # relativo à pasta do hub
    cmd = list(cfg["cmd"])
    if cmd[0] in ("python", "python3", "py"):
        cmd[0] = sys.executable
    elif (pasta / cmd[0]).exists():
        cmd[0] = str(pasta / cmd[0])
    return cmd, pasta


class Hub:
    """O estado do ecrã e as apps. Tudo o que muda passa por aqui, debaixo de um lock."""

    def __init__(self):
        self.lock = threading.RLock()
        # config.local.json por cima do config.json, campo a campo (ex.: {"inicio": {"tempo": {...}}})
        self.config = {**ler_json(FICHEIRO_CONFIG, {}), **ler_json(FICHEIRO_CONFIG_LOCAL, {})}
        # O menu tem dois níveis: uma entrada com "apps" é um grupo (ex.: Desporto -> Futebol, F1...).
        # Os filhos herdam do grupo o que não definirem (ex.: o "arrancar" do servidor do desporto).
        self.raiz = []
        self.folhas = {}            # id -> app que se abre (com "_grupo" se estiver dentro de um)
        for item in ler_apps():
            if item.get("escondida"):
                continue
            if item.get("apps"):
                comum = {k: v for k, v in item.items() if k not in CAMPOS_MENU + ("apps", "escondida", "atualizar", "agenda")}
                filhos = [{**comum, **f, "_grupo": item["id"]} for f in item["apps"] if not f.get("escondida")]
                self.raiz.append({**item, "apps": filhos})
                self.folhas.update({f["id"]: f for f in filhos})
            else:
                self.raiz.append(item)
                self.folhas[item["id"]] = item
        # Ficheiros soltos que uma app pode ler (ex.: o resumo das despesas). Um a um, de propósito:
        # servir a pasta inteira punha a base de dados das despesas acessível na rede de casa.
        self.ficheiros = {url: (RAIZ / Path(caminho), a["id"]) for a in self.folhas.values()
                          for url, caminho in (a.get("ficheiros") or {}).items()}
        # Pastas de páginas (ex.: o web/ do desporto, para o Início usar as mesmas peças e o mesmo estilo):
        # servem só código e imagens (EXT_PASTAS), nunca dados nem nada fora da pasta.
        self.pastas = {url: (RAIZ / Path(caminho), a["id"]) for a in self.folhas.values()
                       for url, caminho in (a.get("pastas") or {}).items()}
        self.grupo = None           # id do grupo cujo submenu está no ecrã (None = menu inicial)
        self.modo = "inicio"        # inicio | pin | a_carregar | app | erro | desligado (a parede já não tem menu)
        self.pin = ""               # dígitos já marcados no ecrã do código
        self.tentativas = 0         # códigos errados seguidos
        self.bloqueado_ate = 0.0    # depois de 5 errados, espera (ver BLOQUEIOS_PIN)
        self.bloqueios = 0          # bloqueios desde o último código certo
        self.foco = 0               # índice da app com foco no menu
        self.ativa = None           # id da app aberta (ou a carregar)
        self.mensagem = ""          # texto do loading / do erro
        self.processo = None        # processo arrancado por nós (para o parar ao sair)
        self.processo_def = None    # servidor arrancado só para abrir a página de definições (ver definicoes())
        self.def_limite = None      # Timer que o desliga se ninguém voltar ao comando
        self.geracao = 0            # muda a cada abrir/fechar: um arranque antigo não estraga um novo
        self.ouvintes = []          # filas dos clientes ligados a /api/eventos
        self.links_comando = []     # escritos no rodapé do ecrã, para abrires no telemóvel
        self.acoes_app = []         # ações que a app aberta disse usar (o comando mostra botões extra, ex.: Atualizar)
        # Entradas com "atualizar": o hub corre a atualização dos dados sem abrir a app (ex.: Desporto)
        self.atualizaveis = {a["id"]: a for a in list(self.raiz) + list(self.folhas.values()) if a.get("atualizar")}
        self.atualizacoes = {}
        for i, a in self.atualizaveis.items():
            p = self._ler_progresso(a) or {}
            if p.get("estado") == "a_correr":         # de uma vez anterior que não chegou ao fim: não bloqueia
                p = {}
            self.atualizacoes[i] = p
        # Entradas com "agenda" (e "atualizar"): o hub corre a atualização sozinho, às horas que a app diz
        self.agendas = {i: a for i, a in self.atualizaveis.items() if a.get("agenda")}

    # ------------------------------------------------------------ eventos para os ecrãs
    def estado(self):
        with self.lock:
            self._sincronizar_atualizacoes()
            app = self.app(self.ativa)
            return {
                "tipo": "estado",
                "modo": self.modo,
                "foco": self.foco,
                "ativa": self.ativa,
                "url": app.get("url") if app and self.modo == "app" else None,
                "mensagem": self.mensagem,
                "acoes_app": self.acoes_app if self.modo == "app" else [],
                "pin_marcados": len(self.pin),
                "pin_tamanho": len(str(app.get("pin", ""))) if app else 0,
                "bloqueado": max(0, round(self.bloqueado_ate - time.time())),
                "links_comando": self.links_comando,
                "grupo": {k: self.grupo_atual().get(k) for k in ("id", "nome", "icone")} if self.grupo else None,
                "apps": [{**{k: a.get(k) for k in CAMPOS_MENU}, "submenu": bool(a.get("apps"))} for a in self.itens()],
                # Para os atalhos do comando: tudo o que se pode abrir, já sem grupos
                "atalhos": [{**{k: a.get(k) for k in CAMPOS_MENU}, "nome": a.get("atalho") or a["nome"], "grupo": a.get("_grupo")}
                            for a in self.folhas.values()],
                # Os grupos (ex.: Desporto), para o comando mostrar as apps de cada um juntas
                "grupos": [{k: g.get(k) for k in ("id", "nome", "icone")} for g in self.raiz if g.get("apps")],
                # Dados que se podem atualizar sem abrir a app, e como está cada atualização
                # "definicoes": página de definições da app (ex.: "http://{host}:8000/definicoes"), se tiver
                "atualizacoes": [{"id": i, "nome": a["nome"], "icone": a.get("icone"), "definicoes": a.get("definicoes"),
                                  **self.atualizacoes.get(i, {})}
                                 for i, a in self.atualizaveis.items()],
            }

    def emitir(self, evento):
        with self.lock:
            for fila in list(self.ouvintes):
                fila.put(evento)

    def emitir_estado(self):
        self.emitir(self.estado())

    def app(self, ident):
        return self.folhas.get(ident)

    def grupo_atual(self):
        return next((g for g in self.raiz if g["id"] == self.grupo), {})

    def itens(self):
        """O que o menu mostra agora: o submenu do grupo aberto, ou o menu inicial."""
        return self.grupo_atual().get("apps", []) if self.grupo else self.raiz

    def focar(self, ident=None):
        """Põe o foco num item (ou no primeiro que se pode abrir)."""
        itens = self.itens()
        ids = [a["id"] for a in itens]
        if ident in ids:
            self.foco = ids.index(ident)
        else:
            self.foco = next((i for i, a in enumerate(itens) if not a.get("em_breve")), 0)

    def de_pasta(self, caminho):
        """(ficheiro, app) de um pedido a uma das "pastas" (só código e imagens, sem sair da pasta), ou None."""
        for url, (pasta, app_id) in self.pastas.items():
            nome = unquote(caminho[len(url):]) if caminho.startswith(url) else ""
            if not re.fullmatch(r"(?:[A-Za-z0-9_-]+/){0,4}[A-Za-z0-9_.-]{1,80}\.(?:" + "|".join(EXT_PASTAS) + ")", nome) or ".." in nome:
                continue
            alvo = (pasta / nome).resolve()
            if pasta.resolve() in alvo.parents:
                return alvo, app_id
        return None

    # ------------------------------------------------------------ comandos
    def comando(self, acao, app_id=None, valor=None):
        with self.lock:
            if acao == "digito":
                return self.digito(str(valor or ""))
            if acao == "app_acoes":                   # o ecrã conta o que a app anunciou no "pronto"
                if self.modo == "app" and isinstance(valor, list):
                    self.acoes_app = [str(a) for a in valor if e_acao(str(a))]
                    self.emitir_estado()
                return True
            if acao == "atualizar" and app_id:        # botão "Atualizar" de uma entrada, sem abrir a app
                return self.atualizar(app_id)
            if acao == "abrir" and app_id:
                if self.modo == "desligado":
                    self.correr_gancho("ao_ligar_ecra")
                return self.abrir(app_id)
            if not e_acao(acao):
                return False

            if acao == "energia":
                if self.modo == "desligado":
                    self.ligar()
                else:
                    self.desligar()
                return True
            if self.modo == "desligado":
                return True                       # ecrã apagado: só o botão de energia acorda

            if self.modo == "inicio" and acao != "atualizar":
                # Início: as apps abrem-se no comando ("abrir"); aqui só ◀ ▶ fazem alguma coisa (mudam as notícias)
                if acao in ACOES_INICIO:
                    self.emitir({"tipo": "comando", "acao": acao})
                return True
            if acao == "menu":
                self.fechar()
                return True
            if acao == "sair":
                self.fechar()
                return True

            if acao == "atualizar":
                # Sem app indicada: a app aberta trata disso se o anunciou; senão o hub corre a atualização
                # da app (ou do grupo dela) ou, no menu, da entrada com foco / do submenu aberto.
                if self.modo == "app" and "atualizar" in self.acoes_app:
                    self.emitir({"tipo": "comando", "acao": acao})
                    return True
                app = self.app(self.ativa) if self.modo == "app" else (self.itens()[self.foco] if self.itens() else {})
                for alvo in (app.get("id"), app.get("_grupo"), self.grupo):
                    if alvo in self.atualizaveis:
                        return self.atualizar(alvo)
                return True

            if self.modo == "pin":
                if acao == "voltar":
                    if self.pin:
                        self.pin = self.pin[:-1]          # apaga o último dígito
                        self.emitir_estado()
                    else:
                        self.fechar()
                return True

            if self.modo in ("a_carregar", "erro"):
                if acao in ("voltar", "ok"):
                    self.fechar()
                return True

            # modo app: o ecrã da parede passa a ordem à app (e decide o que fazer com "voltar")
            self.emitir({"tipo": "comando", "acao": acao})
            return True

    # ------------------------------------------------------------ atualizar dados sem abrir a app
    def atualizar(self, ident):
        entrada = self.atualizaveis.get(ident)
        if not entrada:
            return False
        if self.atualizacoes.get(ident, {}).get("estado") == "a_correr":
            self.emitir({"tipo": "aviso", "texto": f"{entrada['nome']}: já está a atualizar"})
            return True
        self.atualizacoes[ident] = {"estado": "a_correr", "passo": "A começar…", "inicio": time.time()}
        self.emitir_estado()
        threading.Thread(target=self._correr_atualizacao, args=(ident, entrada), daemon=True).start()
        return True

    def _sincronizar_atualizacoes(self):
        """Apanha as atualizações feitas sem o hub (ex.: dentro do dashboard, ou na linha de comandos).

        Sem isto o menu continuava a dizer "Atualizado há X" da última vez que fosse o hub a atualizar.
        """
        for i, a in self.atualizaveis.items():
            atual = self.atualizacoes.get(i, {})
            if atual.get("estado") == "a_correr":
                continue                                  # é o hub que a está a acompanhar
            p = self._ler_progresso(a) or {}
            if p.get("estado") in ("ok", "falhou") and p.get("terminado_em") != atual.get("terminado_em"):
                self.atualizacoes[i] = p

    @staticmethod
    def _ler_progresso(entrada):
        """Lê o ficheiro de progresso que o comando de atualização escreve (formato no PROTOCOLO.md)."""
        cfg = entrada["atualizar"]
        if not cfg.get("progresso"):
            return None
        _, pasta = preparar_cmd({**cfg, "cmd": ["-"]})
        try:
            dados = json.loads((pasta / cfg["progresso"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None                               # ainda não existe, ou está a meio de ser escrito
        if not isinstance(dados, dict):
            return None
        return {k: dados[k] for k in ("estado", "passo", "feitos", "total", "decorrido_s", "estimativa_s",
                                      "terminado_em", "erro") if k in dados}

    def _correr_atualizacao(self, ident, entrada, extra=(), agenda=None):
        """Corre o comando "atualizar" (mais os argumentos extra de uma tarefa da agenda). Devolve (resultado, erro),
        com resultado "ok", "falhou" ou "ocupado" (já havia uma a correr: acompanha-a até ao fim)."""
        cmd, pasta = preparar_cmd(entrada["atualizar"])
        try:
            proc = subprocess.Popen(cmd + list(extra), cwd=str(pasta), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                    creationflags=subprocess.CREATE_NO_WINDOW if NO_WINDOWS else 0)
        except Exception as e:
            self._fim_atualizacao(ident, entrada, "falhou", str(e), agenda)
            return "falhou", str(e)
        inicio = time.time()
        while proc.poll() is None:
            self._acompanhar(ident, entrada, inicio, agenda)
            time.sleep(1)
        erro = (proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
        codigo = proc.returncode
        if codigo == 2:
            # Já havia uma a correr (ex.: começada dentro do dashboard): acompanha-a pelo ficheiro
            limite = time.time() + 1800
            while time.time() < limite:
                p = self._acompanhar(ident, entrada, inicio, agenda)
                if not p or p.get("estado") != "a_correr":
                    break
                time.sleep(1)
            final = self._ler_progresso(entrada) or {}
            self._fim_atualizacao(ident, entrada, "ok" if final.get("estado") == "ok" else "falhou",
                                  final.get("erro"), agenda)
            return "ocupado", None
        resultado, texto = ("ok" if codigo == 0 else "falhou"), (erro[-1] if erro and codigo else None)
        self._fim_atualizacao(ident, entrada, resultado, texto, agenda)
        return resultado, texto

    def _acompanhar(self, ident, entrada, inicio, agenda=None):
        p = self._ler_progresso(entrada)
        with self.lock:
            novo = {**(p or {}), "estado": "a_correr", "inicio": inicio}
            if agenda:
                novo["agenda"] = agenda               # o nome da tarefa automática (ex.: "Notícias")
            novo.setdefault("decorrido_s", round(time.time() - inicio))
            if novo != self.atualizacoes.get(ident):
                self.atualizacoes[ident] = novo
                self.emitir_estado()
        return p

    def _fim_atualizacao(self, ident, entrada, resultado, erro=None, agenda=None):
        with self.lock:
            final = {**(self._ler_progresso(entrada) or {}), "estado": resultado}
            final.setdefault("terminado_em", datetime.now().isoformat(timespec="seconds"))
            if erro:
                final["erro"] = erro
            self.atualizacoes[ident] = final
            # As da agenda não mostram aviso no ecrã (as notícias de 30 em 30 min encheriam a parede de avisos)
            if not agenda:
                texto = f"{entrada['nome']} atualizado" if resultado == "ok" else f"{entrada['nome']}: a atualização falhou"
                self.emitir({"tipo": "aviso", "texto": texto})
            self.emitir_estado()

    # ------------------------------------------------------------ agenda: atualizar sozinho às horas que a app diz
    def arrancar_agendas(self):
        for ident, entrada in self.agendas.items():
            threading.Thread(target=self._agenda, args=(ident, entrada), daemon=True, name=f"agenda-{ident}").start()

    def _agenda(self, ident, entrada):
        """A cada minuto (e logo depois de cada tarefa) pergunta à app o que está na hora e corre a primeira.

        O comando da "agenda" imprime {"ligada": bool, "tarefas": [{"id", "chave", "nome", "args", "na_hora"}, ...]}
        (formato no PROTOCOLO.md). As regras (horas, novas tentativas, pausas depois de falhas) são da app;
        o hub só corre as tarefas e escreve o registo, que a app lê para decidir o que vem a seguir.
        """
        corridas = {}                                 # id -> quando correu (proteção: nunca a mesma 2x em 4 min)
        while True:
            correu = False
            try:
                agenda = self._ler_agenda(entrada["agenda"])
                if agenda and agenda.get("ligada"):
                    agora = time.time()
                    na_hora = [t for t in agenda.get("tarefas") or []
                               if isinstance(t, dict) and t.get("na_hora") and agora - corridas.get(t.get("id"), 0) > 240]
                    with self.lock:
                        livre = self.atualizacoes.get(ident, {}).get("estado") != "a_correr"
                    if na_hora and livre:             # a correr uma pedida no comando: tenta no próximo minuto
                        corridas[na_hora[0].get("id")] = agora
                        self._tarefa_agenda(ident, entrada, na_hora[0])
                        correu = True
            except Exception as e:                    # a agenda nunca pode parar o hub
                print(f"Agenda de {ident}: {e}", flush=True)
            time.sleep(1 if correu else AGENDA_CADA)

    @staticmethod
    def _ler_agenda(cfg):
        cmd, pasta = preparar_cmd(cfg)
        try:
            r = subprocess.run(cmd, cwd=str(pasta), capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               creationflags=subprocess.CREATE_NO_WINDOW if NO_WINDOWS else 0)
            if r.returncode == 0:
                return json.loads(r.stdout)
            linhas = (r.stderr or "").strip().splitlines()
            print(f"Agenda: {linhas[-1] if linhas else f'saiu com {r.returncode}'}", flush=True)
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            print(f"Agenda: {e}", flush=True)
        return None

    def _tarefa_agenda(self, ident, entrada, t):
        nome = str(t.get("nome") or t.get("id"))
        args = [str(a) for a in t.get("args") or []]
        with self.lock:
            self.atualizacoes[ident] = {"estado": "a_correr", "passo": "A começar…", "inicio": time.time(), "agenda": nome}
            self.emitir_estado()
        inicio = time.time()
        print(f"Agenda: {nome} ({' '.join(args) or 'tudo'})", flush=True)
        resultado, erro = self._correr_atualizacao(ident, entrada, args, agenda=nome)
        self._registar_agenda(entrada["agenda"], {
            "em": datetime.now().astimezone().isoformat(timespec="seconds"), "id": t.get("id"), "chave": t.get("chave"),
            "nome": nome, "resultado": resultado, "erro": erro, "segundos": round(time.time() - inicio)})

    @staticmethod
    def _registar_agenda(cfg, linha):
        """Acrescenta uma linha ao registo da agenda (fica com as últimas AGENDA_REGISTO_MAX), de forma atómica."""
        if not cfg.get("registo"):
            return
        _, pasta = preparar_cmd({**cfg, "cmd": ["-"]})
        caminho = pasta / cfg["registo"]
        try:
            registo = json.loads(caminho.read_text(encoding="utf-8"))
            registo = registo if isinstance(registo, list) else []
        except (OSError, ValueError):
            registo = []
        tmp = caminho.with_name(caminho.name + ".tmp")
        try:
            tmp.write_text(json.dumps((registo + [linha])[-AGENDA_REGISTO_MAX:], ensure_ascii=False, indent=1),
                           encoding="utf-8")
            for tentativa in range(20):
                try:
                    tmp.replace(caminho)
                    break
                except PermissionError:               # Windows: alguém está a ler o ficheiro nesse instante
                    if tentativa == 19:
                        raise
                    time.sleep(0.05)
        except OSError as e:
            print(f"Agenda: não consegui escrever o registo ({e})", flush=True)

    # ------------------------------------------------------------ página de definições (ex.: do Desporto)
    def definicoes(self, ident):
        """Garante que o servidor da página de definições responde; liga-o se preciso. (ok, erro)

        Corre fora do lock (pode esperar uns segundos). O servidor fica ligado enquanto a página está
        aberta; o comando pede fechar_definicoes() quando voltas a ele.
        """
        entrada = self.atualizaveis.get(ident) or self.raiz_por_id(ident)
        if not entrada or not entrada.get("definicoes"):
            return False, "Sem definições"
        saude = entrada.get("saude")
        if not saude or responde(saude):
            return True, None
        if not entrada.get("arrancar"):
            return False, f"{entrada['nome']} não está a correr"
        with self.lock:
            if not (self.processo_def and self.processo_def.poll() is None):
                cmd, pasta = preparar_cmd(entrada["arrancar"])
                opcoes = {"cwd": str(pasta), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                if NO_WINDOWS:
                    opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                else:
                    opcoes["start_new_session"] = True
                try:
                    self.processo_def = subprocess.Popen(cmd, **opcoes)
                except Exception as e:
                    return False, f"Não consegui arrancar {entrada['nome']}: {e}"
            proc = self.processo_def
            if self.def_limite:
                self.def_limite.cancel()
            self.def_limite = threading.Timer(30 * 60, self.fechar_definicoes)   # se nunca voltares ao comando
            self.def_limite.daemon = True
            self.def_limite.start()
        limite = time.time() + float(entrada.get("espera_max", 60))
        while not responde(saude):
            if proc.poll() is not None:
                return False, f"{entrada['nome']} fechou-se ao arrancar"
            if time.time() > limite:
                self.fechar_definicoes()
                return False, f"{entrada['nome']} não respondeu a tempo"
            time.sleep(0.5)
        return True, None

    def fechar_definicoes(self):
        """Desliga o servidor ligado só para as definições (o de uma app aberta fica)."""
        with self.lock:
            if self.def_limite:
                self.def_limite.cancel()
                self.def_limite = None
            if self.processo_def:
                self._matar(self.processo_def)
                self.processo_def = None

    def raiz_por_id(self, ident):
        return next((a for a in self.raiz if a.get("id") == ident), None)

    def abrir(self, app_id, desbloqueada=False):
        app = self.app(app_id)
        if not app or app.get("em_breve"):
            return False
        self.parar_processo()
        self.grupo = app.get("_grupo")
        self.focar(app_id)
        self.acoes_app = []
        if app.get("pin") and not desbloqueada:
            # App pessoal: primeiro o código, marcado no comando. O código nunca sai do hub.
            self.geracao += 1
            self.ativa = app_id
            self.modo = "pin"
            self.pin = ""
            self.mensagem = ""
            self.emitir_estado()
            return True
        self.geracao += 1
        self.ativa = app_id
        self.modo = "a_carregar"
        self.mensagem = f"A abrir {app['nome']}…"
        self.emitir_estado()
        threading.Thread(target=self._arrancar, args=(app, self.geracao), daemon=True).start()
        return True

    def digito(self, d):
        if self.modo != "pin" or len(d) != 1 or not d.isdigit():
            return False
        app = self.app(self.ativa)
        certo = str(app["pin"])
        if time.time() < self.bloqueado_ate:
            self.mensagem = self._texto_bloqueio()
            self.emitir_estado()
            return True
        self.pin += d
        self.mensagem = ""
        if len(self.pin) < len(certo):
            self.emitir_estado()
            return True
        if hmac.compare_digest(self.pin, certo):
            self.tentativas = 0
            self.bloqueios = 0
            self.pin = ""
            return self.abrir(app["id"], desbloqueada=True)
        self.pin = ""
        self.tentativas += 1
        if self.tentativas >= 5:
            self.tentativas = 0
            self.bloqueado_ate = time.time() + BLOQUEIOS_PIN[min(self.bloqueios, len(BLOQUEIOS_PIN) - 1)]
            self.bloqueios += 1
            self.mensagem = self._texto_bloqueio()
        else:
            self.mensagem = "Código errado"
        self.emitir({"tipo": "pin_errado"})
        self.emitir_estado()
        return True

    def _texto_bloqueio(self):
        """ "Demasiadas tentativas. Espera 15 min." (arredondado para cima: nunca diz 0 min)"""
        minutos = max(1, math.ceil((self.bloqueado_ate - time.time()) / 60))
        return f"Demasiadas tentativas. Espera {'um minuto' if minutos == 1 else f'{minutos} min'}."

    def pode_ler(self, app_id):
        """Os ficheiros de uma app com código só se leem enquanto ela está aberta (depois do código)."""
        app = self.app(app_id)
        if not app or not app.get("pin"):
            return True
        with self.lock:
            return self.modo == "app" and self.ativa == app_id

    def _arrancar(self, app, geracao):
        """Corre fora do lock: arranca o processo (se preciso) e espera que a app responda."""
        if app.get("preparar"):                      # ex.: exportar o resumo das despesas antes de mostrar
            cmd, pasta = preparar_cmd(app["preparar"])
            try:
                r = subprocess.run(cmd, cwd=str(pasta), capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=120, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                   creationflags=subprocess.CREATE_NO_WINDOW if NO_WINDOWS else 0)
                if r.returncode != 0:
                    linhas = (r.stderr or r.stdout).strip().splitlines()
                    return self._falhou(geracao, f"{app['nome']}: {linhas[-1] if linhas else 'falhou a preparar'}")
            except Exception as e:
                return self._falhou(geracao, f"{app['nome']}: {e}")

        saude = app.get("saude")
        with self.lock:
            if self.processo_def and self.processo_def.poll() is None and geracao == self.geracao:
                # o servidor já estava ligado para as definições: passa a ser o desta app (fecha com ela)
                self.processo, self.processo_def = self.processo_def, None
                if self.def_limite:
                    self.def_limite.cancel()
                    self.def_limite = None
        if saude and not responde(saude) and app.get("arrancar"):
            cmd, pasta = preparar_cmd(app["arrancar"])
            try:
                opcoes = {"cwd": str(pasta), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                if NO_WINDOWS:
                    opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                else:
                    opcoes["start_new_session"] = True
                proc = subprocess.Popen(cmd, **opcoes)
            except Exception as e:
                return self._falhou(geracao, f"Não consegui arrancar {app['nome']}: {e}")
            with self.lock:
                if geracao != self.geracao:          # entretanto saíste: não deixes o processo órfão
                    self._matar(proc)
                    return
                self.processo = proc

        limite = time.time() + float(app.get("espera_max", 60))
        while saude and not responde(saude):
            with self.lock:
                if geracao != self.geracao:
                    return
                if self.processo and self.processo.poll() is not None:
                    return self._falhou(geracao, f"{app['nome']} fechou-se ao arrancar.")
            if time.time() > limite:
                return self._falhou(geracao, f"{app['nome']} não respondeu a tempo.")
            time.sleep(0.5)

        with self.lock:
            if geracao != self.geracao:
                return
            self.modo = "app"
            self.mensagem = ""
            self.emitir_estado()

    def _falhou(self, geracao, texto):
        with self.lock:
            if geracao != self.geracao:
                return
            self.parar_processo()
            self.modo = "erro"
            self.mensagem = texto
            self.emitir_estado()

    def fechar(self):
        """Fecha a app e volta ao Início (com o botão Menu, com ↩, ou ao desistir do código ou do loading)."""
        self.acoes_app = []
        if self.grupo:
            anterior, self.grupo = self.grupo, None
            self.focar(anterior)
        self.geracao += 1
        self.pin = ""
        self.parar_processo()
        self.ativa = None
        self.modo = "inicio"
        self.mensagem = ""
        self.emitir_estado()

    def desligar(self):
        self.fechar()
        self.modo = "desligado"
        self.emitir_estado()
        self.correr_gancho("ao_desligar_ecra")

    def ligar(self):
        self.correr_gancho("ao_ligar_ecra")
        self.modo = "inicio"
        self.emitir_estado()

    def correr_gancho(self, nome):
        """Comando opcional do config.json, ex.: apagar o monitor a sério no Linux do mini PC."""
        cmd = self.config.get(nome)
        if cmd:
            try:
                subprocess.Popen(cmd, shell=isinstance(cmd, str))
            except Exception as e:
                print(f"{nome} falhou: {e}", flush=True)

    # ------------------------------------------------------------ processos
    def parar_processo(self):
        if self.processo:
            self._matar(self.processo)
            self.processo = None

    @staticmethod
    def _matar(proc):
        if proc.poll() is not None:
            return
        try:
            if NO_WINDOWS:
                # /T: o python do .venv lança um segundo processo, que também tem de parar
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
        except Exception as e:
            print(f"Não consegui parar o processo {proc.pid}: {e}", flush=True)


HUB = Hub()


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".json": "application/json",
        ".webmanifest": "application/manifest+json",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".woff2": "font/woff2",
    }

    def log_message(self, *args):
        pass                                          # sem uma linha por pedido na consola

    def translate_path(self, path):
        limpo = urlsplit(path).path
        if limpo in ("/", ""):
            limpo = "/ecra.html"
        elif limpo == "/comando":
            limpo = "/comando.html"
        relativo = posixpath.normpath(unquote(limpo)).lstrip("/")
        alvo = (PASTA_WEB / relativo).resolve()
        if alvo != PASTA_WEB and PASTA_WEB not in alvo.parents:
            return str(PASTA_WEB / "__nao_existe__")
        return str(alvo)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        caminho = urlsplit(self.path).path
        if caminho == "/api/estado":
            return self.json(HUB.estado())
        if caminho == "/api/eventos":
            return self.eventos()
        if caminho == "/api/inicio":                # o que o ecrã Início precisa do config (ex.: onde ver o tempo)
            return self.json(HUB.config.get("inicio") or {})
        if caminho in HUB.ficheiros:
            ficheiro, app_id = HUB.ficheiros[caminho]
            if not HUB.pode_ler(app_id):
                return self.send_error(403)
            return self.ficheiro(ficheiro)
        da_pasta = HUB.de_pasta(caminho)
        if da_pasta:
            if not HUB.pode_ler(da_pasta[1]):
                return self.send_error(403)
            return self.ficheiro(da_pasta[0])
        return super().do_GET()

    def do_POST(self):
        caminho = urlsplit(self.path).path
        if caminho not in ("/api/comando", "/api/definicoes", "/api/definicoes/fechar"):
            return self.send_error(404)
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            pedido = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            return self.send_error(400)
        if caminho == "/api/definicoes":            # ⚙ Definições no comando: liga o servidor se preciso e espera
            ok, erro = HUB.definicoes(str(pedido.get("app", "")))
            return self.json({"ok": ok, "erro": erro}, 200 if ok else 503)
        if caminho == "/api/definicoes/fechar":     # o comando voltou a abrir: já não é preciso
            HUB.fechar_definicoes()
            return self.json({"ok": True})
        ok = HUB.comando(str(pedido.get("acao", "")), pedido.get("app"), pedido.get("valor"))
        self.json({"ok": ok}, 200 if ok else 400)

    def ficheiro(self, caminho):
        try:
            corpo = caminho.read_bytes()
        except OSError:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(caminho)))
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def eventos(self):
        """Server-Sent Events: o ecrã e o comando recebem cada mudança na hora."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        fila = queue.Queue()
        with HUB.lock:
            HUB.ouvintes.append(fila)
            fila.put(HUB.estado())
        try:
            while True:
                try:
                    evento = fila.get(timeout=15)
                    linha = "data: " + json.dumps(evento, ensure_ascii=False) + "\n\n"
                except queue.Empty:
                    linha = ": ping\n\n"              # mantém a ligação viva
                self.wfile.write(linha.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with HUB.lock:
                HUB.ouvintes.remove(fila)


def ips_da_rede():
    """Endereços deste PC na rede de casa, para escrever o link do comando."""
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.1.1", 9))             # não envia nada; só escolhe a interface
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def main():
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="MonitorHub")
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = aceita o telemóvel na rede de casa")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    servidor = ThreadingHTTPServer((args.host, args.port), Handler)
    servidor.daemon_threads = True
    print(f"MonitorHub a correr. Ecrã: http://127.0.0.1:{args.port}/")
    HUB.links_comando = [f"http://{ip}:{args.port}/comando" for ip in ips_da_rede()] if args.host != "127.0.0.1" else []
    for link in HUB.links_comando:
        print(f"Comando no telemóvel (mesmo Wi-Fi): {link}")
    if HUB.agendas:
        print(f"Atualização automática (se estiver ligada): {', '.join(a['nome'] for a in HUB.agendas.values())}")
    print("Ctrl+C para parar.", flush=True)
    HUB.arrancar_agendas()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        HUB.parar_processo()
        HUB.fechar_definicoes()
        print("\nHub parado.")


if __name__ == "__main__":
    main()
