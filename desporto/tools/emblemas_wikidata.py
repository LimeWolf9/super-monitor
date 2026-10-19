"""Emblemas que a ESPN não tem (sobretudo os clubes amadores das taças), pelo Wikidata.

Como se procura:
1. Wikidata (CLUBES_FIXOS, ou a pesquisa com haswbstatement): o nome do clube, em português, só entre os clubes de futebol
   (P31 = Q476028) do país certo (P17; ex.: Q45 Portugal). Só se aceita uma correspondência clara (ver
   entidade()); senão, fica a sigla.
2. O logótipo (P154), descarregado do Wikimedia Commons em PNG (Special:FilePath com ?width=).
3. Se não houver P154 (é o normal: os emblemas destes clubes não são livres e não estão no Commons), a imagem
   principal do artigo da Wikipédia em português ligado a essa entidade, só se for PNG ou SVG (as fotos, em JPG,
   ficam de fora).

Cada procura fica em data/emblemas_wikidata.json (o que se encontrou e o que não), para não voltar a procurar:
uma procura falhada só se repete ao fim de DIAS_REPETIR dias. São marcas dos clubes, só para uso pessoal.
Só usa a biblioteca standard do Python.
"""

import json
import re
import threading
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone

from comum import RAIZ, pedir

MAPA = RAIZ / "data" / "emblemas_wikidata.json"
# A Wikimedia pede um User-Agent com contacto: o do projeto, sem dados pessoais
USER_AGENT = "dashboard-desportivo/1.0 (https://github.com/LimeWolf9/super-monitor)"
WIKIDATA = "https://www.wikidata.org/w/api.php?"
WIKIPEDIA = "https://pt.wikipedia.org/w/api.php?"
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/{ficheiro}?width=200"
CLUBE_FUTEBOL = "Q476028"
DIAS_REPETIR = 30
TAMANHO = 200   # px

# Clubes que a pesquisa não acerta sozinha (nome em português -> entidade do Wikidata)
CLUBES_FIXOS = {"Salgueiros": "Q1754163", "Atlético CP": "Q757422"}

_tranca = threading.Lock()   # as competições correm em paralelo e partilham o mapa
_mapa = None


def _json(base, params):
    return json.loads(pedir(base + urllib.parse.urlencode({**params, "format": "json"}), ua=USER_AGENT))


def normalizar(nome):
    """Sem acentos nem pontuação, em minúsculas: "União de Leiria" -> "uniao de leiria"."""
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", nome).split())


def ler_mapa():
    global _mapa
    with _tranca:
        if _mapa is None:
            try:
                _mapa = json.loads(MAPA.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _mapa = {}
        return _mapa


def gravar_mapa():
    with _tranca:
        if _mapa is not None:
            tmp = MAPA.with_suffix(".tmp")
            tmp.write_text(json.dumps(_mapa, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(MAPA)


def _valores(entidade, prop):
    return [c["mainsnak"].get("datavalue", {}).get("value") for c in entidade.get("claims", {}).get(prop, [])]


def _ids(entidade, prop):
    return {v.get("id") for v in _valores(entidade, prop) if isinstance(v, dict)}


# Palavras genéricas dos nomes dos clubes: não contam para comparar "Leça" com "Leça Futebol Clube"
GENERICAS = {"clube", "club", "futebol", "football", "sport", "sporting", "desportivo", "desportiva", "desportos",
             "associacao", "grupo", "sociedade", "recreativo", "recreativa", "cultural", "uniao", "de", "da", "do",
             "dos", "das", "e", "fc", "cf", "sc", "cd", "gd", "ad", "ud", "acdr", "cdr", "us", "os", "sad"}


def palavras(nome):
    return set(normalizar(nome).split()) - GENERICAS


def entidade(nome, pais, tipo=CLUBE_FUTEBOL):
    """A entidade do Wikidata para este nome, ou None se não houver uma correspondência clara.

    A pesquisa já só devolve entidades do tipo e do país certos (haswbstatement). Ficam as que têm no nome todas
    as palavras do nome procurado; se ainda houver mais do que uma, só se aceita uma que tenha exatamente essas
    palavras e cujo nome comece pelo nome procurado (ex.: "Leça" -> "Leça Futebol Clube", e não
    "Desportivo de Leça do Balio"). Senão, nenhuma.
    """
    procura = _json(WIKIDATA, {"action": "query", "list": "search", "srlimit": 8,
                               "srsearch": f"{nome} haswbstatement:P31={tipo} haswbstatement:P17={pais}"})
    ids = [r["title"] for r in procura.get("query", {}).get("search", [])]
    if not ids:
        return None
    dados = _json(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|sitelinks",
                             "languages": "pt"})["entities"]
    alvo = palavras(nome) or set(normalizar(nome).split())
    rotulo = lambda e: e.get("labels", {}).get("pt", {}).get("value", "")
    certas = [dados[i] for i in ids if alvo <= palavras(rotulo(dados[i]))]
    if len(certas) > 1:
        certas = [e for e in certas if palavras(rotulo(e)) == alvo
                  and normalizar(rotulo(e)).startswith(normalizar(nome))]
    return certas[0] if len(certas) == 1 else None


def logotipo(e):
    """(url, fonte) do logótipo da entidade, ou (None, None)."""
    ficheiros = [v for v in _valores(e, "P154") if isinstance(v, str)]
    if ficheiros:
        return COMMONS.format(ficheiro=urllib.parse.quote(ficheiros[0].replace(" ", "_"))), "commons"
    titulo = e.get("sitelinks", {}).get("ptwiki", {}).get("title")
    if not titulo:
        return None, None
    d = _json(WIKIPEDIA, {"action": "query", "titles": titulo, "prop": "pageimages", "piprop": "thumbnail|name",
                          "pithumbsize": TAMANHO, "pilicense": "any"})
    pagina = next(iter(d.get("query", {}).get("pages", {}).values()), {})
    imagem, miniatura = pagina.get("pageimage") or "", (pagina.get("thumbnail") or {}).get("source")
    if miniatura and imagem.lower().endswith((".png", ".svg")):
        return miniatura, "ptwiki"
    return None, None


def por_id(qid):
    return _json(WIKIDATA, {"action": "wbgetentities", "ids": qid, "props": "claims|labels|sitelinks",
                            "languages": "pt"})["entities"][qid]


def emblema(chave_mapa, nomes, pais, destino, tipo=CLUBE_FUTEBOL):
    """Procura e grava o emblema em destino (PNG). Devolve True se ficou com emblema.

    chave_mapa: o que identifica o clube no mapa (ex.: "espn:22399"); nomes: os nomes a experimentar, por ordem
    (o nome em português e o da ESPN).
    """
    nome = nomes[0]
    mapa = ler_mapa()
    antes = mapa.get(chave_mapa)
    if antes and not antes.get("url"):   # já se procurou e não havia: só se repete passado algum tempo
        quando = datetime.fromisoformat(antes.get("procurado", "2000-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - quando < timedelta(days=DIAS_REPETIR):
            return False
    try:
        if antes and antes.get("url"):
            url, fonte, qid = antes["url"], antes.get("fonte"), antes.get("qid")
        else:
            fixo = next((CLUBES_FIXOS[n] for n in nomes if n in CLUBES_FIXOS), None)
            e = por_id(fixo) if fixo else None
            for n in ([] if e else dict.fromkeys(nomes)):
                e = entidade(n, pais, tipo)
                if e:
                    break
            qid = e["id"] if e else None
            url, fonte = logotipo(e) if e else (None, None)
        png = pedir(url, ua=USER_AGENT) if url else b""
        ok = png.startswith(b"\x89PNG")
        if ok:
            destino.write_bytes(png)
    except Exception as ex:   # sem rede, API em baixo: tenta-se na próxima atualização
        print(f"Aviso: Wikidata, {nome}: {ex!r}")
        return False
    with _tranca:
        mapa[chave_mapa] = {"nome": nome, "qid": qid, "fonte": fonte if ok else None, "url": url if ok else None,
                            "procurado": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    gravar_mapa()
    return ok
