"""Servidor local para o dashboard desportivo.

Uso:  python serve.py            (abre o browser sozinho)
      python serve.py --port 9000 --no-browser   (assim o abre o MonitorHub)

Definições do futebol (que competições seguir): http://<pc>:8000/definicoes, feita para o telemóvel. Lê e grava
data/competicoes.json por GET/POST /api/competicoes (ver tools/competicoes.py).

Ao vivo: GET /api/aovivo[?seguir=id1,id2][&simular=1&desde=<s>] dá os jogos a decorrer agora (tools/aovivo.py, 30 s
de cache); o ecrã ?cat=aovivo pergunta a cada 30 s. Não grava no live.json e nunca descarrega estádios (só lê
data/estadios.json e data/estadios_osm/, preparados antes pelo passo "Estádios" e pelo tools/estadios.py --todos). GET /api/aovivo/cara?pid=&nome=&sigla=
dá a cara de quem marcou. Os mapas de base estão em web/mapas/; o OSM à volta dos estádios em data/estadios_osm/.
Estádios (na página /definicoes): GET /api/estadios dá o progresso do "tools/estadios.py --todos" e o fim do registo;
POST /api/estadios/continuar arranca-o num processo à parte (409 se já estiver a correr).

Os dados só se atualizam quando se pede (no dashboard: o botão "atualizar" do comando, ou a tecla U). O pedido chega por POST /api/atualizar; GET /api/atualizar/estado diz em que passo vai.
É o mesmo código de "python tools/atualizar_tudo.py" (que atualiza sem o servidor, ex.: pelo MonitorHub): os
atualizadores correm em série; o progresso fica em data/atualizacao.json e uma tranca impede duas ao mesmo tempo.

Só usa a biblioteca standard do Python, por isso não há nada para instalar.
"""

import argparse
import json
import posixpath
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

RAIZ = Path(__file__).parent.resolve()
PASTA_WEB = RAIZ / "web"
sys.path.insert(0, str(RAIZ / "tools"))
import atualizar_tudo   # noqa: E402  (o mesmo código do comando "python tools/atualizar_tudo.py")
import competicoes      # noqa: E402  (a lista das competições e a escolha em data/competicoes.json)
import aovivo           # noqa: E402  (os jogos a decorrer: GET /api/aovivo, para o ecrã Ao vivo)
import estadios         # noqa: E402  (o --todos dos estádios do mapa: GET /api/estadios)

def comecar_atualizacao():
    """Arranca uma atualização numa thread. False se já houver uma a correr (aqui ou pelo comando/hub)."""
    if atualizar_tudo.a_correr():
        return False
    threading.Thread(target=atualizar_tudo.atualizar, daemon=True, name="atualizar").start()
    for _ in range(20):   # espera que a tranca exista, para o estado devolvido já dizer "a correr"
        if atualizar_tudo.a_correr():
            break
        time.sleep(0.05)
    return True


def continuar_estadios():
    """Arranca "tools/estadios.py --todos" num processo à parte, que continua mesmo se o servidor parar.
    False se já houver um a correr (a tranca dele)."""
    if estadios.todos_a_correr():
        return False
    flags = 0
    if sys.platform == "win32":   # sem janela e fora do grupo do servidor
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(estadios.REGISTO, "ab") as registo:
        subprocess.Popen([sys.executable, "-u", str(RAIZ / "tools" / "estadios.py"), "--todos"], cwd=RAIZ,
                         stdin=subprocess.DEVNULL, stdout=registo, stderr=subprocess.STDOUT,
                         creationflags=flags, close_fds=True)
    for _ in range(40):   # espera que a tranca exista, para o estado devolvido já dizer "a correr"
        if estadios.todos_a_correr():
            break
        time.sleep(0.1)
    return True


def definicoes():
    """As competições por grupo, com a escolha atual (para a página /definicoes)."""
    escolha, grupos = competicoes.ler(), {}
    for c in competicoes.COMPETICOES:
        grupos.setdefault(c["grupo"], []).append({
            "chave": c["chave"], "nome": c["nome"], "nota": c["nota"],
            "disponivel": c["chave"] in competicoes.POR_DEFEITO, "ligada": escolha.get(c["chave"], False)})
    return {"grupos": [{"nome": g, "itens": itens} for g, itens in grupos.items()]}


def estado_atual():
    # Lido do data/atualizacao.json: também mostra uma atualização feita pelo comando (ex.: pelo hub)
    return atualizar_tudo.estado()


class Handler(SimpleHTTPRequestHandler):
    # No Windows, o registo do sistema por vezes diz que .js é "text/plain",
    # e o browser recusa módulos JavaScript com esse tipo. Fixamos à mão.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }

    def translate_path(self, path):
        """Decide que ficheiro do disco corresponde a um URL.

        /data/...  -> pasta data/ (os dados)
        tudo o resto -> pasta web/ (a apresentação)
        """
        limpo = urlsplit(path).path
        if limpo.rstrip("/") == "/definicoes":
            return str(PASTA_WEB / "definicoes.html")
        base = RAIZ if limpo.startswith("/data/") else PASTA_WEB
        relativo = posixpath.normpath(unquote(limpo)).lstrip("/")
        alvo = (base / relativo).resolve()
        # Segurança: nunca servir ficheiros fora da pasta base (ex.: "../..")
        if alvo != base and base not in alvo.parents:
            return str(base / "__nao_existe__")
        return str(alvo)

    def responder_json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        caminho = urlsplit(self.path).path
        if caminho == "/api/atualizar/estado":
            return self.responder_json(estado_atual())
        if caminho == "/api/competicoes":
            return self.responder_json(definicoes())
        if caminho == "/api/estadios":
            return self.responder_json(estadios.estado_todos())
        if caminho == "/api/aovivo":
            # ?seguir=id1,id2: os jogos seguidos vêm sempre, mesmo acabados; ?simular=1: os de ontem a fingir
            q = parse_qs(urlsplit(self.path).query)
            seguir = [i for i in ",".join(q.get("seguir", [])).split(",") if i][:30]
            try:
                desde = float((q.get("desde") or ["0"])[0] or 0)
                lista = lambda k: [x for x in ",".join(q.get(k, [])).split(",") if x]
                return self.responder_json(aovivo.ao_vivo(seguir, simulado=q.get("simular") == ["1"], desde=desde,
                                                          golo=(q.get("golo") or [None])[0],
                                                          sem_ruas=lista("semruas"), sem_estadio=lista("semestadio")))
            except Exception as e:   # o Ao vivo não pode deitar o servidor abaixo
                return self.responder_json({"erro": str(e), "jogos": [], "proximo": None, "teams": {}}, 502)
        if caminho == "/api/aovivo/cara":
            # a cara de quem marcou (?pid=<id ESPN>&nome=<nome completo>&sigla=<equipa>): {"url": ... ou null}
            q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            try:
                return self.responder_json({"url": aovivo.cara(q.get("pid"), q.get("nome"), q.get("sigla"))})
            except Exception as e:
                return self.responder_json({"url": None, "erro": str(e)})
        return super().do_GET()

    def do_POST(self):
        caminho = urlsplit(self.path).path
        corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if caminho == "/api/competicoes":
            try:
                escolha = json.loads(corpo or b"{}").get("ligadas")
                if not isinstance(escolha, dict):
                    raise ValueError("falta 'ligadas'")
            except (ValueError, AttributeError) as e:
                return self.responder_json({"erro": str(e)}, 400)
            return self.responder_json({"ligadas": competicoes.gravar(escolha)})
        if caminho == "/api/estadios/continuar":
            comecou = continuar_estadios()
            return self.responder_json({"comecou": comecou, **estadios.estado_todos()}, 202 if comecou else 409)
        if caminho != "/api/atualizar":
            return self.send_error(404)
        comecou = comecar_atualizacao()
        # 409 = já havia uma atualização a correr (o estado diz em que passo vai)
        self.responder_json({"comecou": comecou, **estado_atual()}, 202 if comecou else 409)

    def log_message(self, formato, *args):
        # str(): nos erros (send_error) o 1.º argumento é um HTTPStatus, não o pedido
        pedido = str(args[0]) if args else ""
        if "/api/atualizar/estado" not in pedido and "/api/estadios " not in pedido:   # perguntam a cada poucos segundos
            super().log_message(formato, *args)

    def end_headers(self):
        # Sem cache: assim, editar mock.json e recarregar mostra logo a mudança.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def nome_na_rede():
    """IP deste PC na rede de casa (para o link das definições); o nome do PC se não der."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 9))   # UDP: não envia nada, só escolhe a placa de rede
            return s.getsockname()[0]
    except OSError:
        return socket.gethostname()


def main():
    # A consola do Windows nem sempre aceita acentos: em vez de rebentar, troca-os por "?"
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Servidor do dashboard desportivo")
    # 0.0.0.0: o telemóvel chega à página /definicoes pela rede de casa (127.0.0.1 = só este PC)
    parser.add_argument("--host", default="0.0.0.0", help="endereço (por omissão aceita a rede de casa)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="não abrir o browser")
    args = parser.parse_args()

    servidor = ThreadingHTTPServer((args.host, args.port), partial(Handler))
    local = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{local}:{args.port}/?preview=1"
    print(f"Dashboard a correr em {url}")
    if args.host == "0.0.0.0":
        print(f"Definições do futebol (no telemóvel): http://{nome_na_rede()}:{args.port}/definicoes")
    print("Ctrl+C para parar.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")


if __name__ == "__main__":
    main()
