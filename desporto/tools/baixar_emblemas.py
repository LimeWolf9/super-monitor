"""Volta a descarregar emblemas para web/img/equipas/<sigla>.png.

Uso:
    python tools/baixar_emblemas.py              # descarrega os que faltam
    python tools/baixar_emblemas.py MCI ARS      # só estas siglas
    python tools/baixar_emblemas.py --refazer    # volta a descarregar todos

No dia a dia não é preciso: os atualizadores de futebol e NBA descarregam sozinhos o emblema de uma equipa nova.
Serve para repor um emblema estragado ou trocado.
- Futebol e NBA: o emblema da ESPN (as mesmas fontes de atualizar_futebol.py e atualizar_nba.py).
- Fórmula 1: os logótipos do site oficial da F1 (F1_OFICIAL), já sem margens e sem texto de patrocinadores.
  Os que são pretos usam a versão branca, para se verem no fundo escuro.
Se uma equipa falhar, o dashboard usa o círculo com as cores e a sigla.
Os emblemas são marcas dos respetivos clubes: só para uso pessoal, não redistribuir.
"""

import argparse

import atualizar_futebol as futebol
import atualizar_nba as nba
from comum import EMBLEMAS, baixar_emblema, ler_dados

# Fórmula 1: sigla -> (equipa no site da F1, variante). "logowhite" para os logótipos pretos.
# O site serve as imagens pela Cloudinary: e_trim tira as margens, f_png devolve PNG.
# Também o usa o atualizar_fotos.py, para as fotos dos pilotos.
F1_OFICIAL = {
    "MCL": ("mclaren", "logo"), "FER": ("ferrari", "logo"), "RBR": ("redbullracing", "logo"),
    "MER": ("mercedes", "logowhite"), "AMR": ("astonmartin", "logowhite"), "ALP": ("alpine", "logo"),
    "HAA": ("haas", "logo"), "VRB": ("racingbulls", "logo"), "WIL": ("williams", "logo"),
    "AUD": ("audi", "logowhite"), "CAD": ("cadillac", "logowhite"),
}
EPOCA_F1 = 2026
URL_F1 = ("https://media.formula1.com/image/upload/e_trim/c_fit,w_240,h_160/f_png/q_auto/v1740000000/"
          "common/f1/{ano}/{equipa}/{ano}{equipa}{variante}.webp")


def enderecos():
    """Sigla -> endereço do emblema, para todas as equipas que o dashboard conhece."""
    urls = {}
    for espn_id, sigla in futebol.EQUIPAS.items():
        urls[sigla] = futebol.URL_EMBLEMA.format(id=espn_id)
    # equipas de futebol acrescentadas pelo atualizador (guardam o id da ESPN em "teams")
    for sigla, t in ler_dados().get("teams", {}).items():
        if t.get("_espn") and sigla not in urls:
            urls[sigla] = futebol.URL_EMBLEMA.format(id=t["_espn"])
    for sigla in nba.EQUIPAS.values():
        urls[sigla] = nba.URL_EMBLEMA.format(abrev=nba.EMBLEMA_ESPN.get(sigla, sigla.lower()))
    for sigla, (equipa, variante) in F1_OFICIAL.items():
        urls[sigla] = URL_F1.format(ano=EPOCA_F1, equipa=equipa, variante=variante)
    return urls


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("siglas", nargs="*", help="só estas equipas (por omissão, todas)")
    ap.add_argument("--refazer", action="store_true", help="descarrega também os que já existem")
    args = ap.parse_args()

    EMBLEMAS.mkdir(parents=True, exist_ok=True)
    urls = enderecos()
    siglas = args.siglas or sorted(urls)
    falhas = []
    for s in siglas:
        if s not in urls:
            print(f"{s}: sigla desconhecida")
            falhas.append(s)
            continue
        if not args.refazer and (EMBLEMAS / f"{s}.png").exists():
            continue
        if baixar_emblema(s, urls[s]):
            print(f"{s}: ok", flush=True)
        else:
            falhas.append(s)
    print("Falharam:", ", ".join(falhas) if falhas else "nenhuma")


if __name__ == "__main__":
    main()
