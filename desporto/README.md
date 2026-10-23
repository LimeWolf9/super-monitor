# Dashboard desportivo vertical (1080x2560)

Dashboard para um monitor na parede em modo retrato. Os dados vêm de `data/live.json` (reais, gravado pelos atualizadores em `tools/`) e, enquanto esse ficheiro não existir, de `data/mock.json` (fictícios).

## Arrancar

```powershell
.venv\Scripts\python serve.py
```

Abre o browser em `http://127.0.0.1:8000/?preview=1`. Parar: `Ctrl+C`.
Opções: `--port 9000`, `--no-browser`, `--host 127.0.0.1` (só este PC; por omissão aceita a rede de casa, para o telemóvel chegar às definições). Ao arrancar mostra o link das definições, com o IP do PC.

## Ligar e desligar no monitor da parede

Duplo clique em **`Dashboard.bat`**: arranca o servidor e abre o Edge em ecrã inteiro no monitor que estiver na vertical. Para desligar: **Alt+F4** no dashboard; o servidor para sozinho.

- O monitor (LG 34UB67, 2560 × 1080) tem de estar em **Retrato** (Definições > Sistema > Ecrã > Orientação), o que dá exatamente os 1080 × 2560 do dashboard. O pé não roda: precisa de um suporte VESA de parede.
- O Edge do dashboard usa um perfil próprio (`%LOCALAPPDATA%\dashboard-desportivo\edge`), por isso não mexe nas tuas janelas do Edge.
- O script está em `tools/iniciar_dashboard.ps1`.

## Categorias (`?cat=`)

Três categorias, cada uma com todos os desportos (`construirCenas` em `web/js/scenes.js`):

| `?cat=` | Nome | O que tem |
|---|---|---|
| `ultima` | Última jornada | Futebol: os resultados da última jornada ou eliminatória de cada competição (a jornada toda: os jogos por jogar ficam no seu lugar, com o dia e a hora), o 11 da jornada, as classificações, os grupos e os marcadores. F1: a última corrida, os pneus, os duelos, a evolução dos pontos e o campeonato. NBA: a noite passada e as classificações. No fim, o jogador em destaque e as curiosidades |
| `aovivo` | Ao vivo | O "presente", com atualização contínua (ver abaixo): a lista dos jogos a decorrer agora e o acompanhamento dos que escolheres |
| `proxima` | Próxima jornada | Futebol: tudo o que está por jogar até ao fim da próxima jornada, incluindo o que falta da jornada em curso (esses jogos aparecem nas duas categorias; na Próxima vêm primeiro, com o subtítulo "Jornada 3 · faltam 9 jogos", e depois a jornada seguinte), com a barra das probabilidades e as notícias; o ranking Elo. F1: o próximo GP e o horário do fim de semana. NBA: os jogos desta noite com a hora de Portugal ("NBA · Esta noite") e a corrida ao MVP (e o "Em construção" até a época começar) |
| (sem parâmetro) | | A Última jornada e depois a Próxima jornada (é o que o `Dashboard.bat` mostra) |

- O futebol são as competições escolhidas em `/definicoes`: na Última jornada as que tiveram jogos nos últimos 7 dias, na Próxima as que têm jogos nos próximos 7.
- **Ao vivo** (`web/js/aovivo.js` e `tools/aovivo.py`): o passado e o futuro só mudam quando se atualiza; o Ao vivo
  pergunta ao servidor a cada 30 s enquanto está aberto (`GET /api/aovivo`, com 30 s de cache), e não grava no `live.json`.
  Vai à ESPN só nas competições ligadas que jogam hoje (segundo o `live.json`), à Liga Portugal quando há jogo da Taça da
  Liga e à NBA. A lista mostra os jogos a decorrer, por competição, com o resultado e o minuto (10 min antes da hora o jogo entra
  em "Aquecimento", sem resultado, e passa a decorrer quando a ESPN o dá como começado); os do FC Porto e de
  Portugal vêm marcados. ▲▼ foco, OK marca/desmarca, ▶ (ou "Acompanhar") abre o acompanhamento (ver "Mapa do Ao
  vivo" abaixo): o mapa dos estádios em cima e os cartões por baixo, 2 por linha e até 6 por página (com mais jogos as
  páginas trocam sozinhas a cada 10 s; ◀▶ também trocam), com os golos, penáltis e vermelhos; um jogo que acabe fica
  com "Terminado". ↩ volta à lista, e na lista ao menu do hub. Sem jogos: "Sem jogos ao vivo" e o próximo jogo (ou a
  próxima sessão da F1, se vier antes). Durante as sessões da F1 a sessão também está na lista (ver "F1 ao vivo").
  Para testar sem jogos a decorrer: `?cat=aovivo&simular=1` (os jogos de ontem, futebol e NBA, a fingir que estão a
  decorrer: começam no minuto 55 e andam 1 minuto a cada 2 s; aos 10 s entra um golo inventado num jogo seguido).
  Só com o `simular=1`: `&seguir=futebol6,nba2` (segue os primeiros N de cada desporto, ou ids), `&vista=seguir` (abre
  logo o acompanhamento) e `&golo=LIV` (a equipa do golo inventado).
- As jornadas agrupam-se pelas datas dos jogos: mais de 40 h sem jogos separa duas jornadas (assim uma jornada de fim de semana e a de meio da semana a seguir ficam separadas). Nas taças e seleções conta a fase de cada jogo.

O comando funciona igual em todas. Com as 25 fontes por defeito (só as ligadas em `/definicoes`: as desligadas não se pedem), o `atualizar_futebol.py` demora ~12 s (vão 8 em paralelo). Uma atualização completa demora ~55 s (na primeira vez mais,  porque descarrega os emblemas dos clubes e as bandeiras).

## Competições do futebol (`/definicoes`)

O futebol está organizado à volta das competições que se seguem, e **só entram na rotação as que jogam nesta semana**: com um jogo acabado (ou a decorrer) nos últimos 4 dias, ou um jogo marcado para os próximos 7 (`competicaoAtiva` em `web/js/cenas/futebol.js`; as datas vêm de `janela` no `live.json`). Ex.: no fim de semana da Taça de Portugal aparece a Taça em vez da Liga; numa paragem para as seleções aparece a Liga das Nações.

**Escolher**: no telemóvel, `http://<IP do PC>:8000/definicoes` (o `serve.py` mostra o link ao arrancar). Caixas por grupo (a do grupo liga e desliga tudo), **Gravar** ou **Gravar e atualizar já**. Grava em `data/competicoes.json` (fora do git: cada PC tem a sua escolha); o que lá faltar fica com o valor por defeito. As mudanças entram na atualização seguinte (as desligadas saem do `live.json`). A lista, os grupos e os valores por defeito estão em `tools/competicoes.py`.

Por defeito, tudo ligado:

| Grupo | Competições |
|---|---|
| Portugal | Liga Portugal, Taça de Portugal. A **Taça da Liga** é opcional e vem desligada (ver "Taça da Liga (opcional)"). **A Supertaça não tem fonte grátis e sem chave** (não está na ESPN nem na API da Liga Portugal, porque é da FPF): aparece na página, mas não se pode ligar |
| Inglaterra, Espanha, Alemanha, Itália, França | a liga, e as taças (Taça de Inglaterra, Taça da Liga inglesa, Taça do Rei, Taça da Alemanha, Taça de Itália, Taça de França) **só a partir dos oitavos** |
| Europa | Liga dos Campeões, Liga Europa, Liga Conferência, Supertaça Europeia |
| Seleções | **Portugal**: todos os jogos, com os amigáveis. **Brasil** e **Argentina**: só os oficiais (Mundial, qualificação sul-americana, Copa América). **Liga das Nações**: só a Liga A. **Qualificação do Mundial** (Europa) e **do Europeu**: todos os jogos. **Mundial** e **Europeu** (fase final): todos os jogos |

Desligar uma competição de seleções não esconde os jogos de Portugal (ou do Brasil e da Argentina) nessa competição: esses dependem das caixas das seleções.

**Ecrãs**:
- Ligas: como sempre (resultados, 11 da jornada, tabela, próximos jogos com notícias; a Liga Europa e a Conferência só a tabela) e os marcadores no fim.
- Taças e seleções (`<chave>-jogos`): os resultados da ronda e, por baixo, os jogos da ronda seguinte, com a fase no subtítulo ("3.ª eliminatória", "Oitavos de final", "Fase de liga · Jornada 4", "Meias-finais · 2.ª mão"). Com poucos jogos, cada resultado leva os marcadores; com muitos (ex.: 27 na 3.ª eliminatória da Taça), passam a cartões compactos, 2 por linha, em páginas iguais. Prolongamento e penáltis: "a.p." e "g.p. 6-5". Os jogos do FC Porto e de Portugal vão para o topo, com a cor de destaque. Notícias da ESPN no espaço que sobrar, se houver.
- Grupos (`<chave>-grupos`): as tabelas dos grupos (J, DG, PTS), 2 por linha, o de Portugal primeiro. Liga das Nações: os 4 grupos da Liga A. Qualificações e fases finais: os grupos que a ESPN tiver para os jogos deste período.
- Como nas ligas, a ronda aparece logo que acaba o primeiro jogo, e um ecrã sem dados sai da rotação.

Chaves (para `?scene=`): `tp` Taça de Portugal, `fa`, `efl`, `cdr`, `dfb`, `cit`, `cdf` (taças estrangeiras), `usc` Supertaça Europeia, `unl` Liga das Nações, `wcq` / `euq` qualificações do Mundial (Europa) e do Europeu, `wc` / `euro` fases finais, `ca` Copa América, `wcqs` qualificação sul-americana, `amg` amigáveis de Portugal.

## Comando (MonitorHub e teclado)

Dentro do MonitorHub (pasta `hub/` deste repositório), o dashboard obedece ao comando do telemóvel. O hub abre-o num iframe e manda as ordens por `postMessage` (ver o `PROTOCOLO.md` do hub). O protocolo só se liga dentro de um iframe: pelo `Dashboard.bat` tudo funciona como antes. As teclas fazem o mesmo, o que ajuda a testar sem o hub.

| Botão | Tecla | O que faz |
|---|---|---|
| ◀ ▶ | setas ← → | cena anterior / seguinte (a contagem do tempo da cena recomeça; em pausa, muda e continua em pausa) |
| Pausa | Espaço | fica nesta cena, com um ⏸ no topo (e um aviso no hub); outra vez retoma |
| Futebol / F1 / NBA | 1 / 2 / 3 | salta para o primeiro ecrã desse desporto na categoria aberta (ações `ir_futebol`, `ir_f1`, `ir_nba`; o dashboard só anuncia ao hub as dos desportos que têm ecrãs nessa categoria). No canto de baixo, à esquerda, aparece onde estás: "Futebol 3/24" |
| ▲ ▼ | setas ↑ ↓ | nas cenas `*-proximos`, muda a notícia com foco (contorno); com uma notícia aberta, desliza o texto |
| OK | Enter | abre a notícia com foco por cima da cena: imagem grande, título, texto completo e fonte. A rotação pausa enquanto estiver aberta |
| Voltar | Esc | fecha a notícia; sem nada aberto, volta ao menu do hub |

Código: `web/js/controlo.js`. O texto completo das notícias vem do `atualizar_noticias.py` (ESPN: API de artigos; Record: página da notícia), e cada artigo só se vai buscar uma vez.

## Parâmetros do URL (combináveis)

| Parâmetro | O que faz |
|---|---|
| `?preview=1` | Mostra o ecrã em retrato dentro de uma moldura, para caber num monitor horizontal |
| `?scene=f1-gp` | Fixa uma cena em vez de rodar |
| `?mock=1` | Usa sempre os dados fictícios do `mock.json` |
| `?cat=ultima` / `aovivo` / `proxima` | Só uma categoria (é o que o submenu do MonitorHub usa). Sem parâmetro: a Última jornada e depois a Próxima |
| `?hoje=2026-10-06T22:00` | Faz de conta que é esse dia, para ver que competições entram na rotação nessa semana (os dados são os mesmos) |

Ids das cenas (também `de-*`, `fr-*`, `it-*`, e `tp-jogos`, `unl-jogos`, `unl-grupos`... das taças e seleções, `nba-construcao`): `pt-jogos`, `pt-tabela`, `pt-proximos`, `en-jogos`, `en-tabela`, `en-proximos`, `es-jogos`, `es-tabela`, `es-proximos`, `ucl-jogos`, `pt-onze` (e `en-onze`, `es-onze`, `ucl-onze`...), `ucl-tabela`, `ucl-proximos`, `uel-tabela`, `uecl-tabela`, `golos`, `elo`, `f1`, `f1-gp`, `nba`, `nba-noite`, `nba-premios`, `jogador`, `fun`.

Exemplo: `http://127.0.0.1:8000/?preview=1&scene=golos`

Se uma lista não cabe num ecrã, divide-se em páginas (ex.: `ucl-jogos`, `ucl-jogos-2`, `ucl-tabela`, `ucl-tabela-2`). Cada ecrã de resultados é dividido em fatias iguais, uma por jogo, com os marcadores por baixo (se forem muitos, passam a duas colunas e, no limite, aparece "+N"). A Liga Europa e a Conferência mostram só a classificação (os próximos jogos voltam a ser avaliados nas eliminatórias); a NBA mostra a classificação até ao play-in.

A classificação e os próximos jogos estão em ecrãs separados (`*-tabela` e `*-proximos`). Os próximos jogos ocupam uma só página, 2 por linha, e o espaço que sobra fica com as **notícias da liga** (se não couberem os jogos todos e 3 notícias, aparece "+N jogos"). Os **jogos grandes** vão para o topo, com a etiqueta "Destaque": os da equipa em destaque (`myTeam`) e aqueles em que as duas equipas estão no top 6 da tabela (top 8 nas competições europeias; ver `TOP_DESTAQUE` em `web/js/cenas/futebol.js`).

## Onde mexer

- **Dados** → `data/live.json`, ou `data/mock.json` se o live não existir (recarrega sozinho a cada 60 s; ou F5).
- **Que dados aparecem em cada cena** → `web/js/cenas/` (um ficheiro por modalidade: `futebol.js`, `f1.js`, `nba.js`, `outras.js`; as peças comuns em `base.js`). A ordem da rotação e as categorias estão em `web/js/scenes.js`.
- **Aspeto** → `web/css/base.css` (estrutura e tamanhos; no fim, o aspeto Liquid Glass), cores das competições em `leagues.css`, fundos ilustrados em `web/js/backgrounds.js`.
- **Segundos por cena** → `duracaoCena` em `web/js/main.js`: 5 s + 0,5 s por linha visível (jogos, linhas de tabela, notícias, itens; seletores em `LINHAS`), entre 6 e 20 s. Uma cena com `segundos` próprio (número ou função) manda. A barra de progresso usa a mesma duração.
- **Equipa em destaque** → `myTeam.code` em `live.json` (e no `mock.json`, de onde o live é criado) (FCP).
- **Nome na saudação do topo** → `utilizador` em `live.json` e `mock.json` ("Bom dia/Boa tarde/Boa noite, Diogo").

## Dados reais

Tudo vem de fontes reais e gratuitas, sem chave: Fórmula 1, futebol, NBA, jogador em destaque e curiosidades.

**Os dados só se atualizam quando se pede** (o `serve.py` não atualiza sozinho), ou pela **atualização automática** do MonitorHub, se estiver ligada (ver abaixo):

- Botão **Atualizar** do comando do MonitorHub (ação `atualizar`; no teclado, tecla **U**): começa logo a atualização. Se já estiver a atualizar, o hub mostra "Já está a atualizar".
- Durante a atualização aparece uma barra em baixo: "A atualizar: Futebol (2/8) · 0:18 de ~0:38". A estimativa vem do que cada passo demorou da última vez (`data/duracoes.json`). No fim aparece "Atualizado às 10:52" durante uns segundos (ou que parte falhou, que fica com os dados anteriores), e o ecrã recarrega os dados sozinho.
- Em todos os ecrãs, no canto de baixo: "Dados de hoje 09:12", com a hora da parte desse ecrã (F1, futebol...).
- Os passos, em série: F1 → futebol → Taça da Liga → 11 da jornada → ClubElo → NBA → notícias → fotos → destaques → curiosidades → estádios (do mapa do Ao vivo). Um que falhe não para os outros; o resultado aparece no terminal.
- Por baixo: `POST /api/atualizar` começa (recusa com 409 se já houver uma a correr) e `GET /api/atualizar/estado` diz o passo, os feitos de N, o tempo decorrido e o estimado.

**Atualizar sem abrir o dashboard** (ex.: pelo MonitorHub): `.venv\Scripts\python.exe tools\atualizar_tudo.py`, na pasta do projeto. É o mesmo código do botão do dashboard.

- Mostra `[2/8] Futebol...` em cada passo; `--json` dá uma linha JSON por mudança; `--estado` só mostra o estado e sai.
- **Por partes**: `--passos noticias,fotos` corre só esses passos (pela ordem de sempre). Os nomes: `f1`, `futebol`, `taca_liga`, `onze`, `elo`, `nba`, `noticias`, `fotos`, `destaques`, `curiosidades`, `estadios`. A tranca, o progresso e as fontes funcionam igual; o `atualizacao.json` só mostra os passos que correram e o `duracoes.json` só muda nesses. `--competicoes pt,en` (as chaves de `tools/competicoes.py`) passa para o futebol e para o 11 da jornada: só essas competições mudam, as outras ficam como estavam no `live.json` (ex.: `--passos futebol,onze --competicoes pt`). Também dá direto: `python tools/atualizar_futebol.py --competicoes pt`. Sem opções corre tudo, como o botão **Atualizar** e o MonitorHub.
- O canto "Dados de hoje 09:12" não mente depois de uma atualização parcial: cada competição atualizada regista a sua hora em `_atualizado` (`"futebol:pt"`, e `"futebol:tl"` para a Taça da Liga) e as cenas dela mostram essa; a hora `"futebol"` (a das cenas sem competição, como os marcadores) só muda numa atualização completa do futebol.
- Saída: **0** tudo bem; **1** algum passo ou fonte falhou (última linha do stderr, com as fontes: "Falharam: RSS Marca, ESPN NBA"); **2** já havia uma atualização a correr (do comando ou do dashboard).
- Progresso em `data/atualizacao.json` (escrita atómica, atualizado a cada segundo), o mesmo formato do `GET /api/atualizar/estado`:
  `estado` ("a_correr" / "ok" / "falhou" / "nunca"), `passo`, `feitos`, `total`, `decorrido_s`, `estimativa_s`, `inicio_em`, `terminado_em`, `erro`, `passos` (detalhe).
- **Que fonte falhou**: cada atualizador regista em `data/fontes.json` como correu cada fonte que usa (`registar_fonte` em `tools/comum.py`, escrita atómica): por fonte ("ESPN Liga Portugal", "Jolpica F1", "RSS A Bola", "ClubElo API"...) `estado` ("ok" / "aviso" se respondeu sem dados onde se esperavam / "falhou"), `ok`, `ultima_ok`, `ultima_tentativa`, `itens`, `erro` e `passo` (o atualizador). Aparece no fim de `/definicoes` (secção "Fontes"), e o `erro` do `atualizacao.json` diz as fontes que falharam (é o que o menu do MonitorHub mostra).
- `data/atualizacao.lock` impede duas atualizações ao mesmo tempo (uma tranca com mais de 20 min sem sinal de vida é ignorada). Se o dashboard estiver aberto, mostra a barra de progresso de uma atualização feita assim.

**Atualização automática** (desligada por defeito): liga-se em `/definicoes`, secção "Atualização automática" (grava em `data/agenda_config.json`, fora do git). Quem corre é o **MonitorHub** (tem de estar a correr: é o processo que está sempre ligado); o `tools/agenda.py` diz o que está na hora e o hub corre `tools/atualizar_tudo.py` com os `--passos`/`--competicoes` de cada tarefa, uma de cada vez, com o progresso no comando como uma atualização normal (mas sem aviso no ecrã da parede). As regras, na hora deste PC:

- Entre a **01:00 e as 07:00** não corre nada. Às **07:00** atualiza tudo (o que acabou de noite fica para aqui).
- **Notícias** de 30 em 30 min, das 08:00 às 00:30. **NBA** às 18:00.
- **Futebol**, por competição (as ligadas, com a Taça da Liga): **2h05 depois do início** de cada jogo, só essa competição (`--passos futebol,onze,destaques --competicoes pt`; a Taça da Liga com o passo `taca_liga`). Jogos da mesma competição que acabam até 30 min uns dos outros vão juntos. Se nos dados novos o jogo ainda não acabou (prolongamento, penáltis, atrasos), tenta outra vez 20 min depois, no máximo 3 vezes.
- **F1**: 1 h e 3 h depois do fim de cada sessão (o `live.json` só tem o início: treinos, qualificações e sprint contam 1 h, a corrida 2 h). As sessões ficam lembradas em `data/agenda_memoria.json`, porque o `live.json` passa para o GP seguinte mal a corrida começa.
- Depois de cada parte correm os **destaques** (as mesmas partes do "Atualizar só uma parte": `PARTES` em `tools/atualizar_tudo.py`).
- Se já estava a correr uma atualização (saída 2), tenta 5 min depois. Se uma parte falha 3 vezes seguidas, espera 30 min, depois 1 h, depois 2 h.
- Ao ligar não corre o que ficou para trás: só conta o que estava marcado depois disso. De cada tarefa que se repete só fica a mais recente que falta.
- Cada execução fica em `data/agenda_registo.json` (as últimas 200: hora, o quê, resultado, erro, segundos); a página mostra as próximas 5 (uma por parte) e as últimas 10.
- Ver sem esperar: `python tools/agenda.py --proximas` (JSON com tudo o que vem nos próximos 2 dias; `--agora 2026-10-24T22:00` faz de conta que é essa hora), `--estado` (o que a página mostra), `--ligar` / `--desligar`. Para testar o hub, o `agenda_config.json` aceita `"testes": [{"em": "2026-10-23T09:15", "passos": "noticias"}]` (uma tarefa de uma vez a essa hora; só corre se estiver ligada).
- Por baixo: `GET /api/agenda` e `POST /api/agenda` com `{"ligada": true}` no `serve.py`; no hub, a entrada `"agenda"` do `hub/apps.json` (formato no `hub/PROTOCOLO.md`).

Também se podem correr à mão (todos aceitam `--mostrar`, que só mostra e não grava):

```powershell
.venv\Scripts\python tools\atualizar_f1.py
.venv\Scripts\python tools\atualizar_futebol.py
.venv\Scripts\python tools\atualizar_nba.py
.venv\Scripts\python tools\atualizar_noticias.py
.venv\Scripts\python tools\atualizar_destaques.py      # usa os dados dos três de cima
.venv\Scripts\python tools\atualizar_curiosidades.py   # idem
```

- O `live.json` é criado a partir do `mock.json` na primeira vez (é por isso que o mock guarda os nomes e as cores das equipas e as zonas das tabelas: num PC novo, como o mini PC, é daí que tudo arranca); depois cada atualizador só troca a sua parte e regista a hora em `_atualizado`. Quando as cinco partes já vieram de fontes reais, o aviso de "DADOS FICTÍCIOS" sai do ficheiro.
- Se um atualizador falhar (sem rede, API em baixo, formato mudou), o `live.json` fica como estava. A gravação é atómica (`live.tmp` e depois troca).
- **Uma cena sem dados reais sai da rotação** em vez de mostrar o mock (ver `construirCenas` em `scenes.js`): só entra se a sua parte estiver em `_atualizado` e tiver dados. Ex.: a NBA antes de a época começar, a Liga Conferência antes da 1.ª jornada. Com `?mock=1` aparece a amostra do mock (Liga Portugal, F1, NBA, um destaque e uma curiosidade).
- A lista de cenas é refeita sempre que os dados são relidos (a cada 60 s): as cenas novas entram sozinhas.
- Código partilhado pelos atualizadores novos: `tools/comum.py`.

### Fórmula 1 (`atualizar_f1.py`)

- Fonte: API Jolpica (continuação da Ergast).
- Classificações de pilotos e construtores, próxima corrida (data real, pista desenhada, voltas e comprimento) e última corrida (pódio e volta mais rápida).
- Os traçados vêm de `data/circuitos/f1-circuits.geojson` (descarregado sozinho da primeira vez). O número de curvas está numa tabela no início do script (`CURVAS`), porque a API não o tem.

### Melhor 11 da jornada (`atualizar_onze.py`)

- Um ecrã por competição com resultados (`<liga>-onze`), logo a seguir aos resultados: um 4-3-3 sobre o relvado, com o emblema, o nome e o motivo ("2 golos", "baliza a zeros").
- Não há uma fonte aberta com o 11 oficial, por isso é **calculado pelo dashboard** (o ecrã diz isso): a ESPN dá, para cada jogo, o onze de cada equipa, as posições e as estatísticas. Cada jogador soma pontos por golos (5), assistências (3), ser titular (1), vitória (2) ou empate (0,5), baliza a zeros (GR 4, defesas 3, médios 1), defesas do GR (0,7 cada) e perde por golos sofridos, cartões e autogolos (tabela `PONTOS` no script).
- As estatísticas de cada jogo só se pedem uma vez (cache em `data/cache_onze.json`, fora do git): a primeira vez demora ~1 min, depois só os jogos novos.
- A Liga Europa e a Conferência não têm (não mostram resultados). Sem dados, o ecrã sai da rotação.

Marcadores: um só ecrã com todas as competições da rotação, pela mesma ordem, 2 por linha e o top 3 de cada uma.

### Cenas da F1

Pensada para os dias sem corrida, por esta ordem: primeiro a época inteira, depois o próximo GP, por fim a última corrida. Tudo vem de corridas já feitas (o direto está em "F1 ao vivo", no Ao vivo). O `atualizar_f1.py` prepara cada parte à parte; se uma falhar, fica a `null` e esse ecrã sai da rotação (nunca se inventa). ~15 s por atualização.

| Cena | O que mostra | Fonte |
|---|---|---|
| `f1` | Campeonato de pilotos e construtores, com a diferença para o líder e ▲▼ desde a corrida anterior | Jolpica |
| `f1-duelos` | Duelo entre colegas das 11 equipas: quem ficou à frente na qualificação e na corrida, e os pontos | Jolpica |
| `f1-pontos` | Gráfico da evolução dos pontos do top 5, ronda a ronda (cada piloto com a sua cor, fixa) | Jolpica |
| `f1-gp` | Próxima corrida: pista, voltas, comprimento, contagem | Jolpica + traçados |
| `f1-fds` | Horário de todas as sessões do fim de semana, na hora de Portugal, e os 5 últimos vencedores no circuito | Jolpica |
| `f1-ultima` | Resumo da última corrida: pódio, volta mais rápida, quem mais subiu, desistências, paragem mais rápida (tempo na via das boxes) | Jolpica |
| `f1-pneus` | Estratégia de pneus da última corrida: uma barra por piloto, pela ordem de chegada | OpenF1 (histórico, sem chave) |

Na Última jornada entram o campeonato, os duelos, os pontos, a última corrida e os pneus; na Próxima jornada, o próximo GP e o horário do fim de semana.

### Futebol (`atualizar_futebol.py`)

- Fonte: API pública da ESPN (`site.api.espn.com`). Não é oficial: se mudar, o script falha sem estragar nada.
- As competições escolhidas em `data/competicoes.json` (ver "Competições do futebol"). Nas ligas, 5 pedidos por competição; nas taças e seleções, 3 (os jogos de três meses) e mais 1 para as tabelas dos grupos. Vão 8 em paralelo (~12 s no total). Uma competição que falhe fica com os dados anteriores; as outras atualizam na mesma.
- Taças e seleções: a fase vem de cada jogo (`season.slug` da ESPN: `3rd-round`, `round-of-16`, `group-stage`, `league-phase`...). As rondas são a fase mais a jornada (fase de grupos: o n.º do jogo de cada equipa) ou a mão (eliminatórias a duas mãos); nos amigáveis, cada janela de jogos. "Só a partir dos oitavos" vai pelo nome da fase (`round-of-16` em diante; na FA Cup a `fifth-round` e na Taça da Liga inglesa a `fourth-round`). A Liga A da Liga das Nações são as seleções dos grupos "Group A1" a "A4" da classificação da ESPN.
- Seleções e clubes amadores das taças: ficam com a sigla da ESPN (sem aviso) e o nome em português das seleções está em `NOMES_SELECOES`. Portugal é `PRT` (`POR` já era dos Portland Trail Blazers). As bandeiras e os emblemas vêm da ESPN; os clubes que a ESPN não tem ficam com o círculo e a sigla. Os símbolos das competições novas também se descarregam da ESPN (`web/img/ligas/<chave>.png`).
- Classificação, resultados da última jornada terminada (golos, penáltis, penáltis falhados, autogolos e vermelhos), jogos da jornada seguinte (hora deste PC, ex.: "Dom 20:30") e os 3 melhores marcadores. Os nomes das competições e as zonas da tabela ficam como estão.
- A ESPN não diz a jornada de cada jogo: os jogos são agrupados pelas datas (mais de 40 h de intervalo = jornada nova) e o número da jornada é o número de jogos que a maioria das equipas já fez. Os jogos em atraso, isolados, não aparecem.
- Equipas: o mapa `EQUIPAS` no início do script liga o id da ESPN à sigla (a dos emblemas). As siglas da própria ESPN não servem (para ela "SLB" é o Slovan Bratislava). Uma equipa que não esteja em `teams` é acrescentada com as cores da ESPN, e o emblema que faltar é descarregado da ESPN para `web/img/equipas/`. Um id desconhecido (ex.: equipa promovida na próxima época) dá um aviso: acrescenta-o a `EQUIPAS` e `NOVAS`.
- Nas taças europeias só está tratada a fase de liga. A partir de fevereiro (eliminatórias), a tabela continua a ser a da fase de liga.

### NBA (`atualizar_nba.py`)

- Fonte: API pública da ESPN.
- Classificação da época regular por conferência (até ao 10.º, com as zonas de play-off e play-in), jogos da noite passada (dia anterior em Nova Iorque; a pré-época não conta) e líderes da época em pontos, ressaltos e assistências.
- Antes de a época regular começar não há classificação nem líderes: ficam a `null` e as cenas `nba` e `nba-noite` saem da rotação até haver dados.
- Corrida ao MVP e ao Rookie do Ano (cena `nba-premios`): odds "futures" das casas de apostas que a ESPN publica (DraftKings), sem chave. As odds passam a probabilidade implícita, normalizada entre os 5 favoritos, e o subtítulo da cena diz a fonte. Antes da época, a linha de cada jogador mostra as odds (ex.: "Odds +210"); depois, as médias da época.
- Guarda também o melhor marcador da noite (box score de cada jogo), para o jogador em destaque.

### Taça da Liga (opcional, `atualizar_taca_liga.py`)

- Mostra a Taça da Liga (Allianz Cup) como as outras taças: os resultados da ronda, os jogos seguintes, a fase no subtítulo e o FC Porto em destaque.
- A ESPN não a tem: os dados vêm da **API pública do site da Liga Portugal** (`ligaportugal.pt/api/v1/competition/...`, sem chave). A época calcula-se sozinha (a partir de julho, a nova).
- **Vem desligada.** Os termos de utilização da Liga Portugal só permitem uso pessoal e não comercial: quem a ligar deve lê-los e respeitá-los (`ligaportugal.pt/pages/termos-e-condicoes`).
- **Ligar**: em `/definicoes`, grupo Portugal, caixa "Taça da Liga", e **Gravar e atualizar já**.
- Nada do que vem desta API vai para o git: os resultados ficam no `data/live.json` e os emblemas em `web/img/`, ambos fora do git. Este repositório não tem nenhuma cópia desses dados.
- É um passo próprio da atualização: se falhar, fica o que estava; desligada, sai do `live.json`.

### ClubElo (`atualizar_elo.py`)

- Fonte: [ClubElo](http://clubelo.com), grátis e sem chave. O ranking vem da API (`api.clubelo.com/AAAA-MM-DD`, CSV); quando a API está em baixo (acontece), da página `clubelo.com/Ranking` (os ~750 primeiros do mundo).
- **Probabilidades nos próximos jogos** (barra 1 X 2 por baixo de cada jogo, o favorito em destaque): as previsões do ClubElo da página `clubelo.com/Fixtures` (a API das previsões foi desativada; a página só tem os jogos dos próximos dias de algumas ligas). Os outros jogos calculam-se no dashboard a partir do Elo (`probabilidades()` em `web/js/cenas/futebol.js`: 60 pontos de Elo por jogar em casa, e o empate pela curva que mais se aproxima das previsões do ClubElo). A nota por baixo dos jogos diz qual das duas foi usada. Sem Elo de uma das equipas, o jogo fica sem barra.
- **Ecrã `elo`**: o top 10 da Europa e os clubes portugueses que estiverem no ranking, com a posição entre os europeus.
- Os nomes do ClubElo ligam-se às siglas pelos nomes das equipas (só no mesmo país); os que não batem certo vão em `NOMES`. ~2 s.

### Understat (xG): não

O robots.txt do Understat proíbe tudo (`Disallow: /`), por isso o xG não entra.

### Jogador em destaque (`atualizar_destaques.py`)

Calculado a partir do `live.json`, sem pedidos à rede:
- Futebol: quem marcou mais golos na última jornada (Liga Portugal, Champions, Premier League, La Liga, Liga Europa). Num empate ganha um jogador da equipa em destaque (`myTeam`).
- NBA: o melhor marcador da noite passada.
- F1: o vencedor do último GP, com a posição e os pontos no campeonato.

### Curiosidades (`atualizar_curiosidades.py`)

- **Neste dia na história**: API REST da Wikipédia em português. Primeiro os acontecimentos desportivos do dia; como são raros, completa com os desportistas que nasceram neste dia (portugueses primeiro, depois os mais conhecidos); em último caso, os acontecimentos desportivos da Wikipédia em inglês.
- **Recordes curiosos**: não há API; vêm de `data/recordes.json` (24 recordes reais) e cada dia começam num diferente. Podes acrescentar mais, desde que sejam factos confirmados.
- **Comparações absurdas**: calculadas com os dados reais (ex.: os golos do melhor marcador contra os de equipas inteiras, os pontos do líder contra os últimos juntos, os quilómetros do próximo GP contra Lisboa–Porto).

### Notícias (`atualizar_noticias.py`)

- Liga Portugal: RSS do **Record** (`record.pt/rss`), em português, só as notícias da secção Liga Betclic.
- Feeds gerais, que não são de uma competição: **A Bola** (`abola.pt/rss-articles.xml`, só títulos), **Maisfutebol** (`maisfutebol.iol.pt/rss`), **BBC Sport** (`feeds.bbci.co.uk/sport/football/rss.xml`, em inglês) e **Marca** (o feed da Primera División, em espanhol). Cada notícia vai para a competição de que fala, entre as que estão na rotação: o nome da competição vale 3 pontos e o de cada equipa dela 1; entra a de mais pontos, com pelo menos 2 (`atribuir()`). Num empate fica a do feed (A Bola e Maisfutebol: Liga Portugal; BBC: Premier League; Marca: LaLiga). Destes só se usa o que vem no feed (título, resumo, imagem): a BBC proíbe extrair conteúdo das páginas.
- **O Jogo** não entra: o robots.txt proíbe o acesso automático.
- As notícias repetidas entre fontes saem (o mesmo endereço, ou mais de metade das palavras do título iguais).
- Cada fonte liga-se e desliga-se em `/definicoes` (grupo "Notícias").
- As outras competições escolhidas que jogam nesta semana (ligas, taças e seleções): notícias da ESPN para essa competição, em inglês (sem vídeos). Nas taças pequenas a ESPN quase nunca tem.
- Só as dos últimos 3 dias, até 6 por liga. A cena mostra a fonte ("Notícias: Record"). Se uma liga não tiver notícias, os jogos ficam com o ecrã todo.
- O código das notícias está separado do dos jogos (`blocoNoticias` em `web/js/cenas/futebol.js`): se um dia passarem para uma página "Notícias" própria, basta usá-lo noutra cena.

## Mapa do Ao vivo

No acompanhamento, quando todos os jogos seguidos são no mesmo continente (Europa, América do Norte para a NBA, ou
América do Sul para o Brasil e a Argentina), aparece em cima um mapa (`web/js/mapa.js`) com um ponto a pulsar em cada
estádio (azul o FC Porto e Portugal, verde os outros) e um balão de vidro com o estádio, os emblemas, o resultado e o
minuto; os balões arrumam-se sozinhos para não se taparem. Continentes misturados: só os cartões. Um jogo cujo estádio
ainda não tem coordenadas fica fora do mapa, mas com o cartão.

- **Acontecimentos** (só no futebol): a cada resposta comparam-se os golos, penáltis, autogolos, penáltis falhados e
  vermelhos de cada jogo seguido com os da resposta anterior. Os novos entram numa fila, pela ordem em que chegam. Cada
  um: voo "à GTA" até ao estádio (3,8 s, zoom logarítmico até ~1,1 km), o desenho do estádio posto sobre o relvado real
  com as ruas, linhas de comboio e metro, água, parques e prédios à volta (OpenStreetMap), o destaque (tipo, cara e nome
  de quem foi, minuto, emblemas e resultado com o lado que mudou a cor) e o nome do estádio durante 5 s (3 s se houver
  mais de 3 à espera), e o voo de volta (2,4 s). O cartão do jogo brilha entretanto. Sem mapa, só o destaque.
- **NBA**: mapa dos EUA (e do Canadá, para Toronto) com os pontos e o resultado/período; sem zoom nem destaques.
- **Estádios** (`tools/estadios.py`): o estádio de cada jogo vem da ESPN (o mesmo scoreboard); as coordenadas da
  Wikidata (pesquisa pelo nome, P625, confirmada pela cidade; senão a cidade, com o aviso "só cidade"), em
  `data/estadios.json`. As que a Wikidata erra corrigem-se à mão em `tools/estadios_correcoes.json` (no git; nunca
  são substituídas). No futebol, o OpenStreetMap à volta (Overpass: ruas, linhas, água e parques num raio de 2,5 km,
  as estradas grandes até 8 km, prédios a 250 m, o estádio e o relvado, que dá o centro e o ângulo do desenho), já
  simplificado, em `data/estadios_osm/<id>.json`. Ambos são cache local (fora do git).
- **Preparam-se antes, nunca durante o jogo**: o Ao vivo só lê o cache. Sem o OSM, o jogo fica no mapa sem o zoom
  das ruas (só o destaque); sem coordenadas, só o cartão. Os pedidos vão um de cada vez, com pausa e User-Agent
  próprio, no máximo 40 descarregamentos do OSM por dia; ao fim de 3 estádios seguidos com erro de rede o Overpass
  fica 24 h em pausa (3 servidores, e um que falhe fica 10 min de parte).
  - Passo "Estádios" da atualização à mão (`tools/atualizar_estadios.py`): só os estádios dos jogos dos próximos 30
    dias que faltam, até 7 minutos; sem nada em falta não liga a ninguém. `--seco` só diz o que falta.
  - `python tools/estadios.py --todos` prepara de uma vez os estádios da época: os de todos os jogos marcados nos
    próximos 8 meses (competições ligadas e NBA, pelos scoreboards da ESPN mês a mês). Primeiro as coordenadas de
    todos (~1 pedido por segundo), depois o OpenStreetMap de cada estádio de futebol (o do jogo mais próximo
    primeiro, 30 s entre pedidos). Grava a cada estádio: se parar, corre-se outra vez e continua; os erros de rede
    repetem-se ao fim de 15, 30 e 60 minutos. Demora dias, pelo limite diário; o progresso fica em
    `data/estadios_todos.json` (formato do `data/atualizacao.json`). `--retomar` (com `pythonw`, numa tarefa
    agendada do Windows) continua-o se não acabou nem está a correr. Cada chave da ESPN descarrega-se uma vez; no
    fim, o registo lista os que parecem o mesmo com chaves diferentes (o ponto de um dentro do contorno do outro).
  - `--testar <nome>` tenta já o OSM desse estádio (mesmo com o Overpass em pausa; se vier, segue como o
    `--retomar`), `--refazer <id>` marca um para voltar a descarregar, `--corrigir` aplica as correções à mão, `--seco` só mostra.
  - Na página `/definicoes` (secção "Estádios do mapa") vê-se o estado, feitos/total, a pausa do Overpass, os
    estádios dos próximos jogos sem coordenadas ou sem ruas e o fim do registo; o botão "Continuar download" arranca
    o `--todos` num processo à parte se não estiver a correr (`GET /api/estadios`, `POST /api/estadios/continuar`;
    a tranca `data/estadios_todos.lock` impede dois ao mesmo tempo).
- **Mapas de base**: `web/mapas/europa.json`, `america_norte.json`, `america_sul.json` (países a 50 m; cidades, costa,
  rios e lagos a 10 m para o meio do zoom; o da América do Norte, da NBA, só tem os países e os estados dos EUA), gerados por `tools/gerar_mapas.py` a partir do Natural Earth. Guardam
  longitude/latitude; a projeção (Lambert azimutal de áreas iguais, centrada em cada continente) faz-se no browser.
- **Caras**: `GET /api/aovivo/cara` procura na cache das fotos (`web/img/jogadores/`), no facepack (pelo id em
  `data/facepack_ids.json`) e na ESPN pelo id do atleta; sem cara, aparece o emblema da equipa.

**Créditos**: mapas de base do [Natural Earth](https://www.naturalearthdata.com/) (domínio público). Ruas e estádios
© [contribuidores do OpenStreetMap](https://www.openstreetmap.org/copyright) (licença ODbL; o mapa mostra
"© OpenStreetMap" enquanto está perto). Coordenadas dos estádios da [Wikidata](https://www.wikidata.org/) (CC0).

## F1 ao vivo

Durante as sessões do fim de semana (treinos, qualificações, sprint e corrida, com as horas do `live.json`), o Ao
vivo mostra a sessão como um item da lista, com a bandeira do país, e vem marcada. No acompanhamento é a primeira
página: o ecrã da F1 inteiro (`web/js/f1aovivo.js`), 20 s antes de passar aos cartões dos jogos (se for a única
coisa seguida, fica nela); o atalho `ir_f1` (tecla 2) volta a ela. O ecrã escolhe-se pelo tipo da sessão: corrida
(volta, intervalos, paragens, lutas a menos de 1 s, ultrapassagens no top 5, o campeonato se acabasse agora),
qualificação (Q1/Q2/Q3 com a linha de eliminação, a distância para ela, o delta da volta lançada, pneus novos) ou
treinos (pelo melhor tempo, sem eliminação). O mapa mostra a pista e os carros, e por cima os avisos de 7 s.

- **Fonte:** o live timing da F1 (`livetiming.formula1.com`), o mesmo feed não oficial que a app usa, só para uso
  pessoal; quem o usa tem de respeitar os termos da Formula 1 e da F1 TV. O cliente (`tools/f1_direto.py`) só está
  ligado enquanto o Ao vivo ou o ecrã da F1 perguntam (desliga-se 90 s depois do último pedido) e religa sozinho se
  a ligação cair. Cada sessão fica gravada em `data/f1_gravacoes/` (fora do git) para se poder rever.
- **Token da F1 TV (opcional):** sem ele vem tudo menos as posições dos carros (o mapa mostra só a pista, com a nota
  "sem F1 TV: sem posições"). Com uma conta F1 TV, o valor do cookie `login-session` do formula1.com num ficheiro
  `data/f1tv_token.txt` (local e no `.gitignore`; nunca é escrito noutro sítio) junta as posições. A página
  `/definicoes` mostra a fonte "F1 ao vivo (live timing)" com ✓ ou o aviso de que falta o token.
- **Traçado do mapa:** o de uma volta limpa (o carro sempre em pista, sem saltos nas posições) guardado por circuito em
  `data/f1_gravacoes/pistas/`; num circuito novo, o desenho do OpenStreetMap (ver "Pista da F1") até haver uma volta limpa.
- **Bandeiras:** de [flagcdn.com](https://flagcdn.com) (domínio público), descarregadas uma vez para `web/img/bandeiras/`.
- **Testar entre corridas** (só para quem desenvolve; nunca aparece sem estes parâmetros):
  `?cat=aovivo&simular=f1&arquivo=<pasta>` mostra uma sessão de `data/f1_gravacoes/arquivo/` (descarregada com
  `tools/f1_arquivo.py`, que precisa do token) com `&inicio=<min>`, `&volta=<n>`, `&parte=Q2`, `&vel=<x>`;
  e `F1_DIRETO_REPLAY=<pasta>[,<vel>[,<min>]]` no ambiente do `serve.py` faz o cliente em direto receber essa sessão
  do arquivo em vez do feed (o Ao vivo mostra-a como se estivesse a decorrer).

## Pista da F1

O desenho da pista da cena `f1-gp` é feito pelo `atualizar_f1.py` a partir do traçado real do circuito (`data/circuitos/f1-circuits.geojson`, convertido em SVG por `tools/gerar_pista.py`). Os traçados são de https://github.com/bacinger/f1-circuits (dados do OpenStreetMap, licença ODbL); são medidos em mapa, por isso podem diferir ligeiramente da versão oficial.

## Emblemas das equipas

```powershell
.venv\Scripts\python tools\baixar_emblemas.py            # descarrega os que faltam
.venv\Scripts\python tools\baixar_emblemas.py MCI ARS    # só estes
.venv\Scripts\python tools\baixar_emblemas.py --refazer  # tudo de novo
```

No dia a dia não é preciso: os atualizadores de futebol e NBA descarregam sozinhos o emblema de uma equipa nova (da ESPN).

**Clubes que a ESPN não tem** (sobretudo os amadores das taças): `tools/emblemas_wikidata.py` procura-os no Wikidata, só entre os clubes de futebol do país dessa taça (`PAIS_WIKIDATA` em `atualizar_futebol.py`), e só aceita uma correspondência clara (se houver dois clubes com o mesmo nome, como as duas Lusitânias, fica a sigla). O emblema vem do logótipo do Wikidata (P154, no Commons) ou, como é o normal nestes clubes, da imagem do artigo da Wikipédia em português ligado a essa entidade, só se for PNG ou SVG. Cada procura fica em `data/emblemas_wikidata.json` (o que se encontrou e o que não): só se procura o que falta, e uma procura falhada só se repete passados 30 dias. Os que a pesquisa não acerta vão em `CLUBES_FIXOS` (nome -> entidade). Na 3.ª eliminatória da Taça de 2026/27 ficaram 21 dos 31 clubes; a primeira vez demora mais ~80 s. Os nomes sem acentos da ESPN ("Uniao Leiria") corrigem-se em `NOMES_PT`.

**Símbolos das competições**: vêm da ESPN (a versão para fundo escuro), para `web/img/ligas/<chave>.png`. A Taça de Portugal não tem na ESPN: usa-se o desenho do troféu do Commons (`SIMBOLOS_COMMONS`). O script serve para repor um emblema estragado. Futebol e NBA vêm da ESPN; as equipas de F1 do site oficial da F1 (`F1_OFICIAL` no script), já sem margens, e as que têm logótipo preto (Mercedes, Aston Martin, Audi, Cadillac) usam a versão branca. O `NFO.svg` (Nottingham Forest) é da Wikipédia. São marcas dos clubes, só para uso pessoal.

## Caras dos jogadores

`tools/atualizar_fotos.py` (corre com os outros quando se atualiza) põe a cara do jogador a seguir ao emblema, nos melhores marcadores (cena `golos`) e no campeonato de pilotos (cena `f1`).

- Futebol, por esta ordem:
  1. **Facepack do Football Manager** (megapack "cut out" da sortitoutsi), se existir. A pasta vai em `config.local.json` na raiz (fora do git, cada máquina tem o seu), ou na variável de ambiente `FACEPACK_DIR`:
     ```json
     { "FACEPACK_DIR": "D:/facepack/faces" }
     ```
     Os ficheiros do pack são `face_<id FM>.png`, sem nomes. O id de cada marcador procura-se uma vez no site da sortitoutsi (confirmando o clube) e fica em `data/facepack_ids.json`. Se a pesquisa falhar (ex.: há muitos "João Pedro"), acrescenta-se à mão: `"João Pedro|CHE": 19371552`. A cara é copiada para `web/img/jogadores/`, por isso continua a aparecer mesmo sem o pack (ex.: no mini PC). Se a pasta não existir, este passo é saltado.
  2. A foto da ESPN pelo id do atleta (a mesma fonte dos marcadores).
- F1: fotos oficiais do site da F1, recortadas à cara pelo próprio site.
- As fotos ficam em `web/img/jogadores/` (fora do git), com uma cache (`_cache.json`): só se procuram as dos jogadores que estão nas listas nesse momento (3 marcadores por liga e os pilotos), e cada uma só se descarrega uma vez. Uma tentativa falhada (sem foto, ou um site sem resposta) fica registada e só se repete no dia seguinte.
- Sem foto, fica um espaço vazio do mesmo tamanho (as linhas continuam alinhadas). São fotos de jogadores, só para uso pessoal.

## Mais tarde: Raspberry Pi

`python serve.py` + Chromium em quiosque, por exemplo:
`chromium-browser --kiosk "http://localhost:8000/"`.
Não há dependências para instalar (`requirements.txt` está vazio de propósito).

## Notas

- Equipas: emblemas em `web/img/equipas/<sigla>.png` (clubes, equipas de F1 e NBA). Se faltar algum, aparece o círculo com as cores e a sigla. Nos jogadores usa-se o emblema da equipa.
- Competições: os símbolos (`web/img/ligas/`) foram descarregados da Wikimedia/Wikipédia e recortados (só o símbolo, sem texto). São marcas dos respetivos donos, só para uso pessoal neste dashboard; não os redistribuas.
- Os textos de "Neste dia" no mock não correspondem à data de hoje; são só exemplos. Os do live.json são os do dia.
