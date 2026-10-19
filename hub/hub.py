"""MonitorHub: transforma o monitor da parede numa "TV" com apps, comandada pelo telemóvel.

Uso:  python hub.py                 (porto 8080, aceita ligações da rede de casa)
      python hub.py --port 9000
      python hub.py --host 127.0.0.1 (só este PC; o telemóvel deixa de chegar cá)

Páginas:
  /          ecrã da parede (menu, loading e a app escolhida)
  /comando   comando para o telemóvel

Cada app está em apps.json. Uma app com "arrancar" só corre enquanto está escolhida:
o hub arranca-a ao abrir e para-a ao sair (só se foi ele a arrancá-la).

Só usa a biblioteca standard do Python, por isso não há nada para instalar.
"""

import argparse
import hmac
import json
import os
import posixpath
import queue
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
# apps.local.json (fora do git) tem a configuração deste PC, ex.: o PIN; sem ele usa-se o apps.json de exemplo
FICHEIRO_APPS = RAIZ / "apps.local.json" if (RAIZ / "apps.local.json").exists() else RAIZ / "apps.json"
FICHEIRO_CONFIG = RAIZ / "config.json"
NO_WINDOWS = os.name == "nt"

# Ações que o comando envia. As de navegação vão para o menu ou para a app ativa.
# "sair" fecha a app e volta ao menu de onde ela foi aberta (o ecrã manda-a quando a app não trata o "voltar").
# "atualizar" só faz sentido numa app que o anuncie (o comando só mostra o botão nesse caso).
ACOES = {"cima", "baixo", "esquerda", "direita", "ok", "voltar", "pausa", "menu", "energia", "sair", "atualizar"}
CAMPOS_MENU = ("id", "nome", "icone", "descricao", "em_breve", "etiqueta")


def ler_json(caminho, omissao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return omissao


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
        self.config = ler_json(FICHEIRO_CONFIG, {})
        # O menu tem dois níveis: uma entrada com "apps" é um grupo (ex.: Desporto -> Futebol, F1...).
        # Os filhos herdam do grupo o que não definirem (ex.: o "arrancar" do servidor do desporto).
        self.raiz = []
        self.folhas = {}            # id -> app que se abre (com "_grupo" se estiver dentro de um)
        for item in ler_json(FICHEIRO_APPS, []):
            if item.get("escondida"):
                continue
            if item.get("apps"):
                comum = {k: v for k, v in item.items() if k not in CAMPOS_MENU + ("apps", "escondida", "atualizar")}
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
        self.grupo = None           # id do grupo cujo submenu está no ecrã (None = menu inicial)
        self.modo = "menu"          # menu | pin | a_carregar | app | erro | desligado
        self.pin = ""               # dígitos já marcados no ecrã do código
        self.tentativas = 0         # códigos errados seguidos
        self.bloqueado_ate = 0.0    # depois de 5 errados, espera um minuto
        self.foco = 0               # índice da app com foco no menu
        self.ativa = None           # id da app aberta (ou a carregar)
        self.mensagem = ""          # texto do loading / do erro
        self.processo = None        # processo arrancado por nós (para o parar ao sair)
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

    # ------------------------------------------------------------ eventos para os ecrãs
    def estado(self):
        with self.lock:
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
                "atalhos": [{**{k: a.get(k) for k in CAMPOS_MENU}, "nome": a.get("atalho") or a["nome"]}
                            for a in self.folhas.values()],
                # Dados que se podem atualizar sem abrir a app, e como está cada atualização
                "atualizacoes": [{"id": i, "nome": a["nome"], "icone": a.get("icone"), **self.atualizacoes.get(i, {})}
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

    # ------------------------------------------------------------ comandos
    def comando(self, acao, app_id=None, valor=None):
        with self.lock:
            if acao == "digito":
                return self.digito(str(valor or ""))
            if acao == "app_acoes":                   # o ecrã conta o que a app anunciou no "pronto"
                if self.modo == "app" and isinstance(valor, list):
                    self.acoes_app = [str(a) for a in valor if str(a) in ACOES]
                    self.emitir_estado()
                return True
            if acao == "atualizar" and app_id:        # botão "Atualizar" de uma entrada, sem abrir a app
                return self.atualizar(app_id)
            if acao == "abrir" and app_id:
                if self.modo == "desligado":
                    self.correr_gancho("ao_ligar_ecra")
                return self.abrir(app_id)
            if acao not in ACOES:
                return False

            if acao == "energia":
                if self.modo == "desligado":
                    self.ligar()
                else:
                    self.desligar()
                return True
            if self.modo == "desligado":
                return True                       # ecrã apagado: só o botão de energia acorda

            if acao == "menu":
                self.fechar(inicio=True)
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

            if self.modo == "menu":
                itens = self.itens()
                n = len(itens)
                passo = -1 if acao in ("cima", "esquerda") else 1 if acao in ("baixo", "direita") else 0
                if passo and n:
                    for _ in range(n):                # salta as apps "em breve"
                        self.foco = (self.foco + passo) % n
                        if not itens[self.foco].get("em_breve"):
                            break
                elif acao == "ok" and n:
                    item = itens[self.foco]
                    if item.get("apps"):               # grupo: entra no submenu
                        self.grupo = item["id"]
                        self.focar()
                    else:
                        return self.abrir(item["id"])
                elif acao == "voltar" and self.grupo:  # sai do submenu
                    anterior, self.grupo = self.grupo, None
                    self.focar(anterior)
                self.emitir_estado()
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

    def _correr_atualizacao(self, ident, entrada):
        cmd, pasta = preparar_cmd(entrada["atualizar"])
        try:
            proc = subprocess.Popen(cmd, cwd=str(pasta), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                    creationflags=subprocess.CREATE_NO_WINDOW if NO_WINDOWS else 0)
        except Exception as e:
            return self._fim_atualizacao(ident, entrada, "falhou", str(e))
        inicio = time.time()
        while proc.poll() is None:
            self._acompanhar(ident, entrada, inicio)
            time.sleep(1)
        erro = (proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
        codigo = proc.returncode
        if codigo == 2:
            # Já havia uma a correr (ex.: começada dentro do dashboard): acompanha-a pelo ficheiro
            limite = time.time() + 1800
            while time.time() < limite:
                p = self._acompanhar(ident, entrada, inicio)
                if not p or p.get("estado") != "a_correr":
                    break
                time.sleep(1)
            final = self._ler_progresso(entrada) or {}
            return self._fim_atualizacao(ident, entrada, "ok" if final.get("estado") == "ok" else "falhou",
                                         final.get("erro"))
        self._fim_atualizacao(ident, entrada, "ok" if codigo == 0 else "falhou", erro[-1] if erro and codigo else None)

    def _acompanhar(self, ident, entrada, inicio):
        p = self._ler_progresso(entrada)
        with self.lock:
            novo = {**(p or {}), "estado": "a_correr", "inicio": inicio}
            novo.setdefault("decorrido_s", round(time.time() - inicio))
            if novo != self.atualizacoes.get(ident):
                self.atualizacoes[ident] = novo
                self.emitir_estado()
        return p

    def _fim_atualizacao(self, ident, entrada, resultado, erro=None):
        with self.lock:
            final = {**(self._ler_progresso(entrada) or {}), "estado": resultado}
            final.setdefault("terminado_em", datetime.now().isoformat(timespec="seconds"))
            if erro:
                final["erro"] = erro
            self.atualizacoes[ident] = final
            texto = f"{entrada['nome']} atualizado" if resultado == "ok" else f"{entrada['nome']}: a atualização falhou"
            self.emitir({"tipo": "aviso", "texto": texto})
            self.emitir_estado()

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
            self.emitir_estado()
            return True
        self.pin += d
        self.mensagem = ""
        if len(self.pin) < len(certo):
            self.emitir_estado()
            return True
        if hmac.compare_digest(self.pin, certo):
            self.tentativas = 0
            self.pin = ""
            return self.abrir(app["id"], desbloqueada=True)
        self.pin = ""
        self.tentativas += 1
        if self.tentativas >= 5:
            self.tentativas = 0
            self.bloqueado_ate = time.time() + 60
            self.mensagem = "Demasiadas tentativas. Espera um minuto."
        else:
            self.mensagem = "Código errado"
        self.emitir({"tipo": "pin_errado"})
        self.emitir_estado()
        return True

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

    def fechar(self, inicio=False):
        """Fecha a app e volta ao menu de onde foi aberta (ou ao inicial, com o botão Menu)."""
        self.acoes_app = []
        if inicio and self.grupo:
            anterior, self.grupo = self.grupo, None
            self.focar(anterior)
        self.geracao += 1
        self.pin = ""
        self.parar_processo()
        self.ativa = None
        self.modo = "menu"
        self.mensagem = ""
        self.emitir_estado()

    def desligar(self):
        self.fechar(inicio=True)
        self.modo = "desligado"
        self.emitir_estado()
        self.correr_gancho("ao_desligar_ecra")

    def ligar(self):
        self.correr_gancho("ao_ligar_ecra")
        self.modo = "menu"
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
        if caminho in HUB.ficheiros:
            ficheiro, app_id = HUB.ficheiros[caminho]
            if not HUB.pode_ler(app_id):
                return self.send_error(403)
            return self.ficheiro(ficheiro)
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/comando":
            return self.send_error(404)
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            pedido = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            return self.send_error(400)
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
    print("Ctrl+C para parar.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        HUB.parar_processo()
        print("\nHub parado.")


if __name__ == "__main__":
    main()
