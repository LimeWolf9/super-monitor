# MonitorHub

Transforma o monitor da parede numa "TV" com apps (desporto, despesas, e o que vier),
comandada pelo telemóvel. Cada app só corre enquanto está escolhida.

## Ligar (no PC)

Duplo clique em **`MonitorHub.bat`**. Arranca o hub e abre o Edge em ecrã inteiro no
monitor vertical, no ecrã **Início** (ver abaixo). Para sair: `Alt+F4` no ecrã (fecha a app aberta e o hub).

Sem o .bat: `python hub.py` e abrir `http://127.0.0.1:8080/`.

Da primeira vez o Windows pergunta se o Python pode usar a rede: diz que sim em
**redes privadas**, senão o telemóvel não chega cá.

## Comando no telemóvel

O endereço aparece no fundo do Início (ex.: `http://192.168.1.50:8080/comando`).
Abre-o no telemóvel, no mesmo Wi-Fi, e "Adicionar ao ecrã principal" para ficar como app.

**As apps escolhem-se no comando**: no topo estão todas, agrupadas como no `apps.json` (Desporto:
Última jornada, Ao vivo, Próxima jornada; depois as outras). Carregar numa abre-a logo no monitor.
A parede não tem menu: mostra o Início, o código, o loading ou a app.

| Botão | No Início | Dentro de uma app |
|---|---|---|
| ◀ ▶ | mudam a página das notícias | o que a app quiser (ex.: mudar de cena) |
| ▲ ▼ OK | — | o que a app quiser (ex.: abrir notícia) |
| Voltar | — | volta atrás na app, ou ao Início |
| Pausa | — | pausa a app |
| ⌂ Início | — | fecha a app e volta ao Início |
| ⏻ | apaga o ecrã | fecha a app e apaga o ecrã |

Manter uma seta carregada repete. No PC também dá com o teclado: setas, Enter,
Esc, Espaço (pausa), `m` (Início), `e` (energia).

## Início

O ecrã da parede quando não há nenhuma app aberta (`web/apps/inicio.html`), no mesmo estilo Liquid Glass
dos ecrãs do desporto. De cima para baixo:

- a hora, o dia, a saudação e o nascer e o pôr do sol;
- o tempo: agora, um gráfico das próximas 12 horas (temperatura e chuva) e os 5 dias seguintes, da
  [Open-Meteo](https://open-meteo.com/), sem chave, atualizado a cada 30 min;
- **Hoje no desporto**: os jogos de hoje das competições seguidas (até 4, os do FC Porto e de Portugal
  primeiro), com a hora, o resultado se já acabou ou "AO VIVO" pela hora de início, e o aviso para abrir o
  Ao vivo no comando quando há jogos a decorrer;
- o FC Porto, compacto (próximo jogo com contagem, último resultado e a posição na liga com o lugar acima e
  o de baixo) ao lado da F1 (o desenho da pista, a contagem e, num fim de semana de GP, as próximas sessões);
- Portugal, só se jogar nos próximos 14 dias;
- as notícias do FC Porto e da Liga, com imagem, tantas quantas couberem e a mudar a cada 20 s (◀ ▶ no comando);
  quando sobra espaço, o jogador em destaque e as curiosidades;
- no rodapé, uma curiosidade "Neste dia", a hora dos dados do desporto e o endereço do comando.

As despesas nunca aparecem aqui.

- Os dados do desporto vêm do `live.json` pelos `ficheiros` do Desporto no `apps.json` (não é preciso
  o servidor do desporto a correr, nem se vai à rede). O estilo e as peças (emblemas, tabela, pista, fundos)
  são os do desporto: o hub serve o `desporto/web` em `/apps/desporto/` (as `pastas` do apps.json).
- O sítio do tempo está em `config.json` → `"inicio"` → `"tempo"` (o exemplo é o Porto). Para o teu,
  põe-no no `config.local.json` (fora do git), que o hub aplica por cima do `config.json`:

  ```json
  { "inicio": { "tempo": { "nome": "Porto", "latitude": 41.1496, "longitude": -8.611 } } }
  ```
- `inicio.html?mock=1` mostra-o com os dados fictícios do desporto e um tempo inventado (sem rede).

## Apps

Estão em `apps.json` (vai para o git). O que for só do teu PC (o PIN, um caminho diferente) vai em
`apps.local.json`, que o git ignora, **só com o que muda**: o hub lê sempre o `apps.json` e aplica-lhe
este por cima, campo a campo (pelo `id` da app ou do grupo; os filhos de um grupo também valem):

```json
{
  "despesas": { "pin": "1234" },
  "desporto": { "arrancar": { "pasta": "../desporto", "cmd": [".venv/Scripts/python.exe", "serve.py", "--no-browser"] } }
}
```

Cada campo substitui o do `apps.json` inteiro (ex.: o `arrancar` acima leva a pasta e o comando).
Uma chave começada por `_` é um comentário. Um `apps.local.json` antigo, com a lista das apps
toda, continua a funcionar como antes (usa-se esse em vez do `apps.json`).

```json
{
  "id": "desporto", "nome": "Desporto", "icone": "⚽", "descricao": "Futebol, F1 e NBA",
  "url": "http://127.0.0.1:8000/",          // o que o ecrã mostra
  "saude": "http://127.0.0.1:8000/",        // o hub espera que isto responda (ecrã de loading)
  "arrancar": { "pasta": "../desporto",
                "cmd": [".venv/Scripts/python.exe", "serve.py", "--no-browser"] },
  "espera_max": 60                          // segundos até desistir
}
```

- Com `arrancar`, o hub arranca a app ao abrir e para-a ao sair. Se já estiver a correr
  (ex.: abriste o `Dashboard.bat`), usa-a e não a para.
- Sem `arrancar` (ex.: o Relógio), é só uma página.
- Uma entrada com `"apps": [...]` é um **grupo**: no comando, as apps dele aparecem juntas (o Desporto tem
  Última jornada, Ao vivo e Próxima jornada). Os filhos herdam do grupo o que não definirem, como o
  `arrancar` do servidor. `atalho` é o nome no comando.
- `preparar` corre um comando antes de mostrar a app, durante o loading (as Despesas
  exportam o resumo do mês). `"python"` quer dizer o mesmo Python que corre o hub.
- `ficheiros` deixa a app ler um ficheiro de outra pasta por um endereço do hub, ex.:
  `"/dados/despesas.json": "../../despesas-casal/data/monitor.json"`.
  Um a um, de propósito: nunca a pasta inteira (a base de dados das despesas não sai do PC).
- `pastas` é como os `ficheiros`, mas para uma pasta de páginas, ex.: `"/apps/desporto/": "../desporto/web"`.
  Só serve código e imagens (`.js`, `.css`, `.png`, `.svg`, `.webp`, `.jpg`, `.woff2`), nunca dados nem nada
  fora da pasta. O Início usa-a para ter o estilo e as peças do desporto.
- `atualizar` diz como atualizar os dados sem abrir a app (o Desporto tem). Aparece no
  comando em "Atualizar dados", com o progresso ("Atualizado há 2 h") e, se falhar,
  as fontes que falharam. Formato no **PROTOCOLO.md**.
- `"pin": "1234"` pede esse código antes de abrir (as Despesas têm). Marca-se no teclado
  que aparece no comando; o código só existe no `apps.json` e nunca vai para o telemóvel
  nem para o ecrã. 5 erros seguidos bloqueiam um minuto; os 5 seguintes, 5 min; depois 15 e a partir
  daí 60 min de cada vez. Só volta a 1 min depois de um código certo (ou de reiniciar o hub). O ecrã diz
  quantos minutos faltam. Enquanto a app não está aberta,
  os seus `ficheiros` também ficam fechados na rede.
- **Despesas (demo)** é a mesma página com dados inventados (`web/apps/despesas-demo.json`)
  e sem código, para mostrar a quem vem cá a casa.
- `"em_breve": true` mostra-a no comando mas não deixa abrir.
- `"escondida": true` tira-a do comando.

Para uma app obedecer às setas, OK e pausa, ver **PROTOCOLO.md**.

## Ecrã desligado

No PC, ⏻ põe o ecrã a preto (não desliga o monitor a sério: no Windows isso apagava
também o teu monitor principal). No mini PC, onde o monitor é o único ecrã, o
`config.json` liga isto ao sistema:

```json
{ "ao_desligar_ecra": "wlr-randr --output HDMI-A-1 --off",
  "ao_ligar_ecra":    "wlr-randr --output HDMI-A-1 --on" }
```

(o comando exato depende de como o Linux do M80q mostrar o ecrã; vê-se na altura)

## Plano

1. ✅ Hub, Início, loading, comando no telemóvel (onde se escolhem as apps), ecrã apagado.
2. Dashboard de desporto a obedecer ao comando (pausa, setas, abrir notícia).
3. ✅ Página de despesas para a parede: o mês do último extracto (total, entrou/sobrou,
   categorias vs. o normal) e os últimos meses com os objetivos. Só totais, nunca
   movimentos nem o saldo em conta.
4. No M80q: cada app num container Docker, o `arrancar` passa a `docker compose start`;
   Home Assistant manda as mesmas ordens (`POST /api/comando`).

## API (para o Home Assistant e afins)

- `GET /api/estado` — o que está no ecrã.
- `POST /api/comando` com `{"acao": "ok"}` ou `{"acao": "abrir", "app": "desporto"}`.
- `GET /api/eventos` — cada mudança, em direto (Server-Sent Events).

Sem palavra-passe: só para a rede de casa (e Tailscale). Não abras o porto no router.
