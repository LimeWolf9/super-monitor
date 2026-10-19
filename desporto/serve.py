"""Servidor local para o dashboard desportivo.

Uso:  python serve.py            (abre o browser sozinho)
      python serve.py --port 9000 --no-browser   (assim o abre o MonitorHub)

Os dados só se atualizam quando se pede (no dashboard: o botão "atualizar" do comando, ou a tecla U). O pedido chega por POST /api/atualizar; GET /api/atualizar/estado diz em que passo vai.
É o mesmo código de "python tools/atualizar_tudo.py" (que atualiza sem o servidor, ex.: pelo MonitorHub): os
atualizadores correm em série; o progresso fica em data/atualizacao.json e uma tranca impede duas ao mesmo tempo.

Só usa a biblioteca standard do Python, por isso não há nada para instalar.
"""

import argparse
import json
import posixpath
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

RAIZ = Path(__file__).parent.resolve()
PASTA_WEB = RAIZ / "web"
sys.path.insert(0, str(RAIZ / "tools"))
import atualizar_tudo   # noqa: E402  (o mesmo código do comando "python tools/atualizar_tudo.py")

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
        if urlsplit(self.path).path == "/api/atualizar/estado":
            return self.responder_json(estado_atual())
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/atualizar":
            return self.send_error(404)
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        comecou = comecar_atualizacao()
        # 409 = já havia uma atualização a correr (o estado diz em que passo vai)
        self.responder_json({"comecou": comecou, **estado_atual()}, 202 if comecou else 409)

    def log_message(self, formato, *args):
        if "/api/atualizar/estado" not in (args[0] if args else ""):   # o dashboard pergunta a cada segundo
            super().log_message(formato, *args)

    def end_headers(self):
        # Sem cache: assim, editar mock.json e recarregar mostra logo a mudança.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    # A consola do Windows nem sempre aceita acentos: em vez de rebentar, troca-os por "?"
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Servidor do dashboard desportivo")
    parser.add_argument("--host", default="127.0.0.1", help="endereço (por omissão só este PC)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="não abrir o browser")
    args = parser.parse_args()

    servidor = ThreadingHTTPServer((args.host, args.port), partial(Handler))
    url = f"http://{args.host}:{args.port}/?preview=1"
    print(f"Dashboard a correr em {url}\nCtrl+C para parar.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")


if __name__ == "__main__":
    main()
