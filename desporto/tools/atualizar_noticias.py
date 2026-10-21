"""Vai buscar as notícias de cada liga e grava-as em data/live.json (secção "news").

Uso:
    python tools/atualizar_noticias.py            # atualiza data/live.json
    python tools/atualizar_noticias.py --mostrar  # só mostra o que gravaria

Fontes (sem chave):
- Liga Portugal: RSS do Record (https://www.record.pt/rss), em português. Ficam só as notícias da secção
  "Liga Betclic" (pelo endereço). O Record é creditado na cena.
- As outras competições escolhidas (ligas, taças e seleções; ver competicoes.py): notícias da ESPN para essa
  competição, em inglês, só das que jogam nesta semana (as que entram na rotação). Os vídeos ficam de fora.
- Feeds RSS gerais: A Bola, Maisfutebol, BBC Sport (futebol) e Marca (LaLiga). Cada notícia vai para a competição de
  que fala (o nome da competição e os nomes das suas equipas; ver atribuir()), só entre as que estão na rotação.
  Só se usa o que vem no feed: título, resumo e imagem (a BBC proíbe extrair conteúdo das páginas).
  O Jogo não entra: o robots.txt proíbe o acesso automático.
Cada fonte liga-se e desliga-se em /definicoes (n_record, n_espn, n_abola... em data/competicoes.json).
As notícias repetidas entre fontes saem (o mesmo endereço, ou mais de metade das palavras do título iguais).
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
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from comum import gravar, ler_dados, pedir, pedir_json, registar_fonte

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


# ---------- Feeds RSS gerais (A Bola, Maisfutebol, BBC, Marca) ----------
# Não são de uma competição: cada notícia vai para a competição de que fala (palavras-chave e nomes das equipas).
# Só se usa o que vem no feed (título, resumo, imagem); as páginas das notícias não se vão buscar.
# O Jogo fica de fora: o robots.txt proíbe o acesso automático.
# chave em competicoes.json -> (nome, endereço, competição de quem empata, idioma)
FEEDS = {
    "n_abola": ("A Bola", "https://www.abola.pt/rss-articles.xml", "pt"),
    "n_maisfutebol": ("Maisfutebol", "https://maisfutebol.iol.pt/rss", "pt"),
    "n_bbc": ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/rss.xml", "en"),
    "n_marca": ("Marca", "https://e00-marca.uecdn.es/rss/futbol/primera-division.xml", "es"),
}
MEDIA = "{http://search.yahoo.com/mrss/}"
# Nomes de cada competição nas notícias (português, inglês e espanhol)
PALAVRAS = {
    "pt": ["liga portugal", "liga betclic", "i liga"], "tp": ["taca de portugal"], "tl": ["taca da liga", "allianz cup"],
    "en": ["premier league"], "fa": ["fa cup", "taca de inglaterra"], "efl": ["carabao cup", "league cup"],
    "es": ["laliga", "la liga", "primera division"], "cdr": ["copa del rey", "taca do rei"],
    "de": ["bundesliga"], "dfb": ["dfb pokal", "taca da alemanha"], "it": ["serie a"], "cit": ["coppa italia"],
    "fr": ["ligue 1"], "cdf": ["coupe de france"],
    "ucl": ["champions league", "liga dos campeoes", "champions"], "uel": ["europa league", "liga europa"],
    "uecl": ["conference league", "liga conferencia"], "usc": ["supertaca europeia", "super cup"],
    "unl": ["liga das nacoes", "nations league"], "wcq": ["qualificacao para o mundial", "world cup qualif"],
    "euq": ["qualificacao para o europeu", "euro qualif"], "wc": ["mundial", "world cup"], "euro": ["europeu", "euro 20"],
    "ca": ["copa america"], "amg": ["amigavel", "friendly"],
}
NOMES_CURTOS = 4   # nomes de equipa mais curtos do que isto não contam (ex.: "AVS", "Inter" conta)
MIN_PONTOS = 2     # uma notícia só entra se falar da competição (3) ou de duas equipas dela (1 + 1)


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return " " + " ".join(re.sub(r"[^a-z0-9 ]", " ", texto).split()) + " "


def rss(nome, url, agora):
    raiz = ET.fromstring(pedir(url))
    lista = []
    for it in raiz.iter("item"):
        try:
            quando = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        descricao = it.findtext("description") or ""
        img = (it.find(f"{MEDIA}content") if it.find(f"{MEDIA}content") is not None else it.find(f"{MEDIA}thumbnail"))
        img = img.attrib.get("url") if img is not None else None
        if not img:   # o Maisfutebol põe a imagem dentro da descrição
            m = re.search(r'<img[^>]+src="([^"]+)"', descricao)
            img = m.group(1) if m else None
        resumo = limpar(descricao)
        lista.append({"title": limpar(it.findtext("title")), "summary": resumo, "img": img,
                      "date": quando.isoformat(timespec="seconds"), "source": nome, "url": it.findtext("link"),
                      "text": [resumo] if resumo else []})
    limite = agora - timedelta(days=MAX_DIAS)
    return [n for n in lista if datetime.fromisoformat(n["date"]) >= limite]


def palavras_das_competicoes(dados, chaves):
    """chave -> [(texto normalizado, peso)]: o nome da competição vale 3, o de cada equipa dela vale 1."""
    futebol, teams = dados.get("football") or {}, dados.get("teams") or {}
    res = {}
    for chave in chaves:
        L = futebol.get(chave) or {}
        codes = {r["team"] for r in L.get("table", [])} | {m[k] for m in L.get("results", []) + L.get("next", [])
                                                         for k in ("home", "away") if m.get(k)}
        nomes = {n for c in codes for n in (teams.get(c, {}).get("name"), teams.get(c, {}).get("espnName"))
                 if n and len(n) >= NOMES_CURTOS}
        res[chave] = [(normalizar(p), 3) for p in PALAVRAS.get(chave, []) + [L.get("name", "")] if p] + \
                     [(normalizar(n), 1) for n in nomes]
    return res


def atribuir(noticia, palavras, preferida):
    """A competição de que a notícia fala (a de mais pontos, pelo menos MIN_PONTOS), ou None.
    Empate: a do feed (ex.: a Liga Portugal n'A Bola), senão a 1.ª da lista."""
    texto = normalizar(f"{noticia['title']} {noticia['summary']}")
    pontos = {c: sum(peso for p, peso in lista if p in texto) for c, lista in palavras.items()}
    melhor = max(pontos.values(), default=0)
    if melhor < MIN_PONTOS:
        return None
    empatadas = [c for c, v in pontos.items() if v == melhor]
    return preferida if preferida in empatadas else empatadas[0]


def chave_titulo(n):
    return {p for p in normalizar(n["title"]).split() if len(p) >= 4}


def sem_duplicados(lista):
    """Tira as notícias repetidas entre fontes (o mesmo endereço, ou títulos com mais de metade das palavras iguais).
    Fica a primeira, por isso a lista deve vir pela ordem de preferência das fontes."""
    vistas, res = [], []
    for n in lista:
        k = chave_titulo(n)
        if any(n.get("url") and n.get("url") == v.get("url") or (k and len(k & kv) / len(k | kv) > 0.5)
               for v, kv in vistas):
            continue
        vistas.append((n, k))
        res.append(n)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostrar", action="store_true", help="só mostra o resultado, não grava")
    args = ap.parse_args()

    dados = ler_dados()
    agora = datetime.now(timezone.utc)
    escolha = competicoes.ler()
    falhas = []
    # Cada fonte à parte: se uma falhar, as outras entram na mesma e essa liga fica com o que tinha.
    antigas = dados.get("news") or {}
    ativas = [c for c, *_ in competicoes.a_buscar(escolha) if ativa((dados.get("football") or {}).get(c), agora)]
    if escolha.get("tl") and ativa((dados.get("football") or {}).get("tl"), agora):   # vem de outro passo
        ativas.append("tl")
    fontes = {}
    if escolha.get("n_record") and "pt" in ativas:
        fontes["pt"] = lambda: record(agora, antigas.get("pt", []))
    if escolha.get("n_espn"):
        fontes.update({k: (lambda k=k, l=l: espn(l, agora, antigas.get(k, []))) for k, l in ligas_espn(dados, agora).items()})
    fontes.update({k: (lambda n=n, u=u: rss(n, u, agora)) for k, (n, u, _) in FEEDS.items() if escolha.get(k)})
    # As fontes são independentes: vão em paralelo
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {chave: ex.submit(buscar) for chave, buscar in fontes.items()}
    porComp, dosFeeds = {}, []
    nomes = {c["chave"]: c["nome"] for c in competicoes.COMPETICOES}
    for chave, f in futuros.items():
        # Nome da fonte em data/fontes.json: "RSS A Bola", "RSS Record", "ESPN Notícias Premier League"...
        nome = f"RSS {FEEDS[chave][0]}" if chave in FEEDS else "RSS Record" if chave == "pt" else f"ESPN Notícias {nomes.get(chave, chave)}"
        try:
            res = f.result()
            # Um feed geral sem nenhuma notícia recente é estranho; numa liga da ESPN pode ser só uma semana calma
            registar_fonte(nome, itens=len(res), esperado=chave in FEEDS or chave == "pt")
        except Exception as e:
            registar_fonte(nome, erro=e)
            falhas.append(f"{chave} ({e!r})")
            res = antigas.get(chave, []) if chave not in FEEDS else []
        if chave in FEEDS:
            dosFeeds += [(n, FEEDS[chave][2]) for n in res]
        else:
            porComp.setdefault(chave, []).extend(res)
    if fontes and len(falhas) == len(fontes):
        sys.exit(f"Não foi possível atualizar as notícias: {', '.join(falhas)}. O live.json não foi alterado.")
    # Cada notícia dos feeds gerais vai para a competição de que fala (das que estão na rotação)
    palavras = palavras_das_competicoes(dados, ativas)
    for n, preferida in dosFeeds:
        chave = atribuir(n, palavras, preferida)
        if chave:
            porComp.setdefault(chave, []).append(n)
    # Sem repetidas (as das fontes da competição primeiro), as mais recentes primeiro, até MAX_NOTICIAS
    noticias = {}
    for chave, lista in porComp.items():
        lista = sem_duplicados(lista)
        noticias[chave] = sorted(lista, key=lambda n: n["date"], reverse=True)[:MAX_NOTICIAS]

    if args.mostrar:
        print(json.dumps(noticias, ensure_ascii=False, indent=2))
        return
    dados["news"] = noticias
    gravar(dados, "noticias")
    resumo = ", ".join(f"{k} {len(v)}" for k, v in noticias.items())
    print(f"Notícias: {resumo}." + (f" Falharam: {', '.join(falhas)}." if falhas else ""))


if __name__ == "__main__":
    main()
