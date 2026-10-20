# Protocolo do comando (para quem faz uma app)

Uma app do MonitorHub é uma página web que o ecrã da parede abre num `iframe`.
Para obedecer ao comando do telemóvel, a app só precisa de trocar mensagens
`postMessage` com o hub. Uma app que ignore isto continua a funcionar: só não
reage às setas, e "Voltar" leva ao menu.

Todas as mensagens têm `monitorhub: 1`.

## Hub → app

```js
{ monitorhub: 1, tipo: "comando", acao: "direita" }
```

`acao` é uma de: `cima`, `baixo`, `esquerda`, `direita`, `ok`, `voltar`, `pausa`, `atualizar`.

Atalhos `ir_<sítio>` (ex.: `ir_futebol`, `ir_f1`, `ir_nba`): a app anuncia-os nas
`acoes` do `pronto` e o comando mostra um botão por cada um (Futebol, F1, NBA, ou o
nome do sítio). Carregar envia `{ tipo: "comando", acao: "ir_f1" }` à app, que salta
para o primeiro ecrã desse sítio. A app pode voltar a mandar `pronto` com outra lista
quando o que faz sentido mudar (ex.: sem `ir_nba` no Ao vivo).

`atualizar` vem de um botão próprio do comando ("⟳ Atualizar dados"), que só aparece
quando a app aberta inclui `"atualizar"` nas `acoes` do `pronto`. A app decide o que
fazer (ex.: o desporto chama o seu `POST /api/atualizar` e mostra o progresso); pode
responder com um `aviso` (ex.: "Já está a atualizar").
(`menu` e `energia` são tratadas pelo próprio hub e nunca chegam à app.)

## App → hub

| Mensagem | Quando |
|---|---|
| `{ monitorhub: 1, tipo: "pronto", acoes: [...] }` | Ao arrancar. `acoes` diz que botões a app usa; os outros mostram um aviso no ecrã. Lista vazia = todos. |
| `{ monitorhub: 1, tipo: "nao_tratado", acao: "voltar" }` | A app já está no "início" e "Voltar" deve sair para o menu. |
| `{ monitorhub: 1, tipo: "aviso", texto: "⏸ Em pausa" }` | Mostra uma mensagem curta em baixo no ecrã. |

## Exemplo mínimo

```js
const hub = (m) => parent !== window && parent.postMessage({ monitorhub: 1, ...m }, "*");

window.addEventListener("message", (e) => {
  const m = e.data;
  if (!m || m.monitorhub !== 1 || m.tipo !== "comando") return;
  if (m.acao === "direita") proximaCena();
  else if (m.acao === "pausa") alternarPausa();
  else hub({ tipo: "nao_tratado", acao: m.acao });
});

hub({ tipo: "pronto", acoes: ["esquerda", "direita", "pausa", "ok", "voltar"] });
```

A app completa de exemplo é `web/apps/relogio.html`.

## Sugestão para o dashboard de desporto (fase 2)

- `esquerda` / `direita`: cena anterior / seguinte (e recomeça a contagem dos 10 s)
- `pausa`: fixa a cena atual (mostrar um ⏸ discreto)
- `cima` / `baixo`: mover o foco entre notícias ou jogos da cena
- `ok`: abrir a notícia com foco (por cima da cena); `voltar` fecha-a
- `voltar` sem nada aberto: `nao_tratado` → menu
- `atualizar`: anunciar em `pronto` e correr a atualização dos dados

## Atualizar dados sem abrir a app

Uma entrada do `apps.json` (app ou grupo) pode ter:

```json
"atualizar": {
  "pasta": "../desporto",
  "cmd": [".venv/Scripts/python.exe", "tools/atualizar_tudo.py"],
  "progresso": "data/atualizacao.json"
}
```

O comando aparece em "Atualizar dados" no telemóvel, e o botão "⟳ Atualizar dados"
também o usa quando a app aberta (ou o seu grupo) não anuncia `atualizar` no `pronto`.
O hub corre o `cmd` na `pasta` (`"python"` = o Python do hub) e lê o `progresso` a
cada segundo enquanto corre.

**Saída do comando:** `0` = ok, `1` = algum passo falhou (a última linha do stderr
aparece como erro), `2` = já havia uma atualização a correr (o hub acompanha-a pelo
ficheiro até acabar).

**Ficheiro de progresso** (JSON, escrito de uma vez, ex.: `.tmp` + rename). Todos os
campos são opcionais; o hub usa estes:

```json
{
  "estado": "a_correr",          // "a_correr" | "ok" | "falhou"
  "passo": "Futebol",            // o que está a fazer agora (texto curto)
  "feitos": 3, "total": 7,       // passos acabados de N (barra de progresso)
  "decorrido_s": 42,             // segundos desde o início
  "estimativa_s": 120,           // duração total estimada, em segundos
  "terminado_em": "2026-10-19T10:00:00",   // quando acabou (para o "atualizado há 2 h")
  "erro": "texto"                // se falhou, porquê
}
```
