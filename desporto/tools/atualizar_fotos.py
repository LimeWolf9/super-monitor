"""Põe a cara dos jogadores nos melhores marcadores (cena "golos") e no campeonato de pilotos (cena "f1").

Uso:
    python tools/atualizar_fotos.py            # descarrega as fotos que faltam e grava o caminho no live.json
    python tools/atualizar_fotos.py --mostrar  # só mostra o que encontraria, não grava

Corre depois de atualizar_futebol.py e atualizar_f1.py (que reescrevem as listas).
- Futebol, por esta ordem:
  1. o facepack do Football Manager (megapack "cut out" da sortitoutsi), se a pasta existir. A pasta vem de
     FACEPACK_DIR, em config.local.json (na raiz, fora do git) ou numa variável de ambiente. Os ficheiros do
     pack são face_<id FM>.png; o id de cada jogador procura-se uma vez no site da sortitoutsi (confirmando o
     clube) e fica em data/facepack_ids.json, que também se pode editar à mão.
  2. a foto da ESPN pelo id do atleta (a mesma fonte dos marcadores, sem risco de homónimos).
- F1: fotos oficiais do site da F1, já recortadas à cara pela própria Cloudinary do site (g_face).
As fotos ficam em web/img/jogadores/ (cache local, fora do git). Só se procuram as dos jogadores que estão nas
listas nesse momento, e cada uma só se descarrega uma vez. Uma tentativa falhada também fica registada, com a
data, e só se repete no dia seguinte.
Num jogador sem foto não aparece nada (a cena guarda o espaço). Fotos de jogadores, só para uso pessoal.
Só usa a biblioteca standard do Python.
"""

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

from baixar_emblemas import EPOCA_F1, F1_OFICIAL
from comum import RAIZ, gravar, ler_dados, pedir

PASTA = RAIZ / "web" / "img" / "jogadores"
CACHE = PASTA / "_cache.json"   # jogador -> ficheiro, ou null (falhou; volta a tentar no dia seguinte)
DIAS_PARA_REPETIR = 1
ESPN_FOTO = "https://a.espncdn.com/combiner/i?img=/i/headshots/soccer/players/full/{id}.png&w=200"
F1_FOTO = ("https://media.formula1.com/image/upload/c_thumb,g_face,w_200,h_200/f_png/q_auto/v1740000000/"
           "common/f1/{ano}/{equipa}/{codigo}/{ano}{equipa}{codigo}right.webp")
# Sigla da equipa de F1 -> nome no site da F1 (o mesmo dos logótipos, em baixar_emblemas.py)
EQUIPAS_F1 = {sigla: equipa for sigla, (equipa, _) in F1_OFICIAL.items()}
LIGAS = ["pt", "en", "es", "de", "fr", "it", "ucl", "uel", "uecl"]   # as da cena "golos"

# Facepack do Football Manager
CONFIG_LOCAL = RAIZ / "config.local.json"   # {"FACEPACK_DIR": "..."} (fora do git: cada máquina tem o seu)
IDS_FM = RAIZ / "data" / "facepack_ids.json"   # "Nome|SIGLA" -> id FM (editável à mão)
PESQUISA_FM = "https://sortitoutsi.net/search/database?search={nome}&type=person"
PAUSA_FM = 2.0


def pasta_facepack():
    """Pasta do facepack (variável de ambiente FACEPACK_DIR ou config.local.json), ou None se não existir."""
    valor = os.environ.get("FACEPACK_DIR")
    if not valor:
        try:
            valor = json.loads(CONFIG_LOCAL.read_text(encoding="utf-8")).get("FACEPACK_DIR")
        except (OSError, ValueError):
            valor = None
    if not valor:
        return None
    pasta = Path(valor).expanduser()
    return pasta if pasta.is_dir() else None   # ex.: no mini PC, sem o pack, salta-se sem erro


def simples(texto):
    """"Nicolò Tresoldi" -> "nicolo tresoldi" (sem acentos nem pontuação)."""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", texto).split()


def ficheiro(prefixo, nome):
    return f"{prefixo}-{'-'.join(simples(nome))}.png"


def ler_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ler_ids_fm():
    try:
        return json.loads(IDS_FM.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clube_bate(palavras_clube, texto):
    """Alguma palavra do clube aparece no texto (ou começa da mesma forma: "ferencvaros" ~ "ferencvarosi")."""
    for w in simples(texto):
        for c in palavras_clube:
            if w == c or (min(len(w), len(c)) >= 5 and (w.startswith(c) or c.startswith(w))):
                return True
    return False


def id_fm(nome, sigla, clube, ids):
    """Id FM do jogador: do data/facepack_ids.json ou, se não estiver lá, da pesquisa no site da sortitoutsi.
    clube = nomes do clube (o nosso e o da ESPN). Só se aceita um resultado com o mesmo nome e o clube certo (ex.: "Sport Lisboa e Benfica" para SLB)."""
    chave = f"{nome}|{sigla}"
    if chave in ids:
        return ids[chave]
    pagina = pedir(PESQUISA_FM.format(nome=urllib.parse.quote_plus(nome)), pausa=PAUSA_FM).decode("utf-8", "replace")
    nomes_clube = list(clube)
    palavras_clube = {w for n in nomes_clube for w in simples(n)} - {"fc", "cf", "sc", "cd", "ac", "sl", "club", "de", "the"}
    achado = None
    # Cada resultado: ".../person/<id>/<nome> ... Nome person (<id>) País » Liga » Clube Game Guides"
    for m in re.finditer(r'football-manager/person/(\d+)/', pagina):
        texto = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", pagina[m.start():m.start() + 3000])))
        fim = texto.find("Game Guides")
        texto = texto[:fim] if fim > 0 else texto[:400]
        if simples(nome) == simples(texto.split(" person (")[0].split(">")[-1].strip()) or \
                " ".join(simples(nome)) in " ".join(simples(texto)):
            if clube_bate(palavras_clube, texto.split(")", 1)[-1]):
                achado = int(m.group(1))
                break
    if achado:
        ids[chave] = achado
        IDS_FM.write_text(json.dumps(ids, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return achado


def foto_facepack(nome, sigla, clube, pasta, ids):
    """Copia a cara do facepack para a cache do dashboard (para funcionar sem o pack). None se não houver."""
    fid = id_fm(nome, sigla, clube, ids)
    origem = pasta / f"face_{fid}.png" if fid else None
    if not origem or not origem.is_file():
        return None
    nome_ficheiro = ficheiro("fm", nome)
    shutil.copyfile(origem, PASTA / nome_ficheiro)
    return nome_ficheiro


def foto_espn(nome, espn_id):
    """Foto da ESPN pelo id do atleta, ou None (a ESPN só tem foto de alguns jogadores)."""
    if not espn_id:
        return None
    try:
        png = pedir(ESPN_FOTO.format(id=espn_id), pausa=0.3)
    except Exception:   # 404: sem foto
        return None
    if not png.startswith(b"\x89PNG"):
        return None
    nome_ficheiro = ficheiro("espn", nome)
    (PASTA / nome_ficheiro).write_bytes(png)
    return nome_ficheiro


def foto_futebol(nome, sigla, clube, espn_id=None, facepack=None, ids=None):
    """Caminho da foto do jogador, ou None: primeiro o facepack (se houver), depois a ESPN."""
    if facepack:
        try:
            no_pack = foto_facepack(nome, sigla, clube, facepack, ids)
        except Exception as e:   # site da sortitoutsi sem resposta: passa às outras fontes
            print(f"Aviso: facepack, {nome}: {e!r}")
            no_pack = None
        if no_pack:
            return no_pack
    return foto_espn(nome, espn_id)


def foto_f1(nome, equipa):
    """No site da F1 o piloto é <3 letras do nome><3 do apelido>01 (ex.: Max Verstappen -> maxver01)."""
    partes = simples(nome)
    if equipa not in EQUIPAS_F1 or len(partes) < 2:
        return None
    codigo = f"{partes[0][:3]}{partes[-1][:3]}01"
    url = F1_FOTO.format(ano=EPOCA_F1, equipa=EQUIPAS_F1[equipa], codigo=codigo)
    try:
        png = pedir(url, pausa=0.3)
    except Exception:
        return None
    if not png.startswith(b"\x89PNG"):
        return None
    nome_ficheiro = ficheiro("f1", nome)
    (PASTA / nome_ficheiro).write_bytes(png)
    return nome_ficheiro


def com_cache(cache, chave, buscar, mostrar):
    """Usa a cache; se não houver (ou o "não encontrado" já tiver mais de 7 dias), vai buscar."""
    agora = time.time()
    if chave in cache:
        c = cache[chave]
        if c.get("file") and (PASTA / c["file"]).exists():
            return c["file"]
        if not c.get("file") and agora - c.get("t", 0) < DIAS_PARA_REPETIR * 86400:
            return None
    if mostrar:
        return None
    try:
        f = buscar()
    except Exception as e:   # API sem resposta: regista-se como falha e volta a tentar no dia seguinte
        print(f"Aviso: {chave.split('|')[1]}: {e!r}")
        f = None
    cache[chave] = {"file": f, "t": agora}
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o que já está em cache, não descarrega nem grava")
    args = ap.parse_args()

    PASTA.mkdir(parents=True, exist_ok=True)
    dados = ler_dados()
    cache = ler_cache()
    facepack, ids = pasta_facepack(), ler_ids_fm()
    teams = dados.get("teams", {})
    com, sem = [], []
    try:
        for liga in LIGAS:
            for s in ((dados.get("football") or {}).get(liga) or {}).get("scorers", []):
                equipa = teams.get(s["team"], {})
                clube = equipa.get("name", s["team"])
                nomes = [n for n in (clube, equipa.get("espnName")) if n]
                f = com_cache(cache, f"fut|{s['name']}|{s['team']}", lambda: foto_futebol(s["name"], s["team"], nomes, s.get("id"), facepack, ids), args.mostrar)
                s["photo"] = f"img/jogadores/{f}" if f else None
                (com if f else sem).append(s["name"])
        for p in (dados.get("f1") or {}).get("drivers", []):
            f = com_cache(cache, f"f1|{p['name']}|{p['team']}", lambda: foto_f1(p["name"], p["team"]), args.mostrar)
            p["photo"] = f"img/jogadores/{f}" if f else None
            (com if f else sem).append(p["name"])
    except Exception as e:
        sys.exit(f"Não foi possível atualizar as fotos ({e!r}). O live.json não foi alterado.")
    finally:
        if not args.mostrar:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.mostrar:
        print(f"Com foto em cache: {len(com)}; sem: {', '.join(sem) or 'nenhum'}")
        return
    gravar(dados, "fotos")
    print(f"Fotos: {len(com)} com foto, {len(sem)} sem" + (f" ({', '.join(sem)})." if sem else "."))


if __name__ == "__main__":
    main()
