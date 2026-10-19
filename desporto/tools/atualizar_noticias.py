"""Vai buscar as notícias de cada liga e grava-as em data/live.json (secção "news").

Uso:
    python tools/atualizar_noticias.py            # atualiza data/live.json
    python tools/atualizar_noticias.py --mostrar  # só mostra o que gravaria

Fontes (sem chave):
- Liga Portugal: RSS do Record (https://www.record.pt/rss), em português. Ficam só as notícias da secção
  "Liga Betclic" (pelo endereço). O Record é creditado na cena.
- As outras competições escolhidas (ligas, taças e seleções; ver competicoes.py): notícias da ESPN para essa
  competição, em inglês, só das que jogam nesta semana (as que entram na rotação). Os vídeos ficam de fora.
Só entram as notícias dos últimos 3 dias. Uma liga sem notícias fica com a lista vazia (os jogos ocupam o ecrã).
Cada notícia leva também o texto completo ("text", até uns 6 parágrafos), para se abrir com o comando: na ESPN vem da
API de artigos; no Record, dos parágrafos da página da notícia. Cada artigo só se vai buscar uma vez (o texto de uma
notícia que já estava no live.json reaproveita-se).
Só usa a biblioteca standard do Python.
"""

import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from comum import gravar, ler_dados, pedir, pedir_json

RSS_RECORD = "https://www.record.pt/rss"
SECCAO_RECORD = "/futebol/futebol-nacional/liga-betclic/"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/news?limit=25"
import competicoes   # noqa: E402

DIAS_ANTES, DIAS_DEPOIS = 4, 7   # a mesma janela da rotação (competicaoAtiva em web/js/cenas/futebol.js)
TIPOS_ESPN = {"HeadlineNews", "Story"}   # "Media" são vídeos
MAX_DIAS = 3
MAX_NOTICIAS = 6
MAX_RESUMO = 160
MAX_PARAGRAFOS = 6
MAX_TEXTO = 1800
ESPN_ARTIGO = "https://content.core.api.espn.com/v1/sports/news/{id}"
# Frases da página do Record que não são da notícia (avisos de login, etc.)
LIXO_RECORD = re.compile(r"efectue o seu registo|efetue o seu registo|deverá efectuar login|deverá efetuar login|"
                         r"cookies|subscrev|assinante", re.I)


def limpar(texto):
    # O Record embrulha os títulos num "<![CDATA[ ... ]]>" escrito como texto: tira-se antes das etiquetas HTML
    texto = re.sub(r"<!\[CDATA\[|\]\]>", "", texto or "")
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = " ".join(texto.split())
    return texto if len(texto) <= MAX_RESUMO else texto[:MAX_RESUMO - 1].rsplit(" ", 1)[0] + "…"


def paragrafos(lista, lixo=None):
    """Limpa os parágrafos e corta o texto em MAX_PARAGRAFOS / MAX_TEXTO caracteres."""
    res, total = [], 0
    for p in lista:
        # etiquetas dentro do parágrafo (<a>, <b>...) saem sem deixar espaço: "Martínez's", não "Martínez 's"
        p = " ".join(html.unescape(re.sub(r"<[^>]+>", "", p)).split())
        if len(p) < 40 or (lixo and lixo.search(p)) or p in res:   # o Record repete o "lead" no fim
            continue
        res.append(p)
        total += len(p)
        if len(res) >= MAX_PARAGRAFOS or total >= MAX_TEXTO:
            break
    return res


def texto_record(url):
    pagina = pedir(url).decode("utf-8", "replace")
    todos = re.findall(r"<p[^>]*>(.*?)</p>", pagina, re.S)
    return paragrafos(todos, LIXO_RECORD)


def texto_espn(artigo_id):
    h = pedir_json(ESPN_ARTIGO.format(id=artigo_id)).get("headlines", [{}])[0]
    story = h.get("story") or ""
    return paragrafos(re.split(r"</p>|\n{2,}", story))


def com_texto(lista, antigas, buscar):
    """Junta o texto completo a cada notícia; reaproveita o das que já existiam (pelo endereço)."""
    ja = {n.get("url"): n.get("text") for n in antigas if n.get("url") and n.get("text")}
    for n in lista:
        if n.get("url") in ja:
            n["text"] = ja[n["url"]]
            continue
        try:
            n["text"] = buscar(n)
        except Exception:   # sem texto: a notícia abre na mesma, só com o resumo
            n["text"] = []
    return lista


def recentes(lista, agora):
    limite = agora - timedelta(days=MAX_DIAS)
    lista = [n for n in lista if datetime.fromisoformat(n["date"]) >= limite]
    return sorted(lista, key=lambda n: n["date"], reverse=True)[:MAX_NOTICIAS]


def record(agora, antigas):
    raiz = ET.fromstring(pedir(RSS_RECORD))
    lista = []
    for it in raiz.iter("item"):
        if SECCAO_RECORD not in (it.findtext("link") or ""):
            continue
        img = it.find("enclosure")
        try:
            quando = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        lista.append({
            "title": limpar(it.findtext("title")),
            "summary": limpar(it.findtext("description")),
            "img": img.attrib.get("url") if img is not None else None,
            "date": quando.isoformat(timespec="seconds"),
            "source": "Record",
            "url": it.findtext("link"),
        })
    return com_texto(recentes(lista, agora), antigas, lambda n: texto_record(n["url"]))


def espn(liga, agora, antigas):
    lista = []
    for a in pedir_json(ESPN.format(liga=liga)).get("articles", []):
        if a.get("type") not in TIPOS_ESPN or not a.get("published"):
            continue
        imagens = [i for i in a.get("images", []) if i.get("url")]
        lista.append({
            "title": limpar(a.get("headline")),
            "summary": limpar(a.get("description")),
            "img": imagens[0]["url"] if imagens else None,
            "date": datetime.fromisoformat(a["published"].replace("Z", "+00:00")).astimezone(timezone.utc)
                    .isoformat(timespec="seconds"),
            "source": "ESPN",
            "url": a.get("links", {}).get("web", {}).get("href"),
            "_id": a.get("id"),
        })
    lista = com_texto(recentes(lista, agora), antigas, lambda n: texto_espn(n["_id"]))
    for n in lista:
        n.pop("_id", None)
    return lista


def ativa(L, agora):
    """A competição joga nesta semana? (sem "janela", dados antigos: sim)"""
    j = (L or {}).get("janela")
    if not j:
        return bool(L)
    data = lambda t: datetime.fromisoformat(t) if t else None
    ultimo, proximo = data(j.get("ultimo")), data(j.get("proximo"))
    return bool(ultimo and agora - ultimo <= timedelta(days=DIAS_ANTES)
                or proximo and proximo - agora <= timedelta(days=DIAS_DEPOIS))


def ligas_espn(dados, agora):
    """Chave -> liga na ESPN das competições com notícias da ESPN: as escolhidas que jogam nesta semana
    (a Liga Portugal vem do Record; os amigáveis não têm notícias próprias)."""
    futebol = dados.get("football") or {}
    return {chave: liga for chave, _, liga, _, _ in competicoes.a_buscar()
            if chave not in ("pt", "amg") and ativa(futebol.get(chave), agora)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    agora = datetime.now(timezone.utc)
    noticias, falhas = {}, []
    # Cada fonte à parte: se uma falhar, as outras entram na mesma e essa liga fica com o que tinha.
    antigas = dados.get("news") or {}
    fontes = {"pt": lambda: record(agora, antigas.get("pt", [])),
              **{k: (lambda k=k, l=l: espn(l, agora, antigas.get(k, []))) for k, l in ligas_espn(dados, agora).items()}}
    # As fontes são independentes: vão em paralelo
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {chave: ex.submit(buscar) for chave, buscar in fontes.items()}
    for chave, f in futuros.items():
        try:
            noticias[chave] = f.result()
        except Exception as e:
            falhas.append(f"{chave} ({e!r})")
            noticias[chave] = (dados.get("news") or {}).get(chave, [])
    if len(falhas) == len(fontes):
        sys.exit(f"Não foi possível atualizar as notícias: {', '.join(falhas)}. O live.json não foi alterado.")

    if args.mostrar:
        print(json.dumps(noticias, ensure_ascii=False, indent=2))
        return
    dados["news"] = noticias
    gravar(dados, "noticias")
    resumo = ", ".join(f"{k} {len(v)}" for k, v in noticias.items())
    print(f"Notícias: {resumo}." + (f" Falharam: {', '.join(falhas)}." if falhas else ""))


if __name__ == "__main__":
    main()
