# Alterações

## Depois da 2.0 (2026-10-23)

### Atualizar por partes
- `atualizar_tudo.py --passos noticias,fotos` corre só esses passos; `--competicoes pt` só essas competições no
  futebol e no 11 da jornada (as outras ficam como estavam).
- Na página `/definicoes`, a secção "Atualizar só uma parte": um botão por parte (futebol, Taça da Liga, F1, NBA,
  notícias, ClubElo, fotos, curiosidades, estádios) com a hora da última vez, e uma competição sozinha. Mostra o
  progresso e, no fim, as fontes que falharam. Pelo `POST /api/atualizar` com `{"passos", "competicoes"}`; sem
  corpo continua a atualizar tudo (a tecla U e o botão do hub não mudam).
- O canto "Dados de hoje 09:12" mostra a hora de cada competição, por isso não mente depois de uma atualização parcial.

### Atualização automática (desligada por omissão)
- O MonitorHub atualiza sozinho, se a ligares em `/definicoes` ("Atualização automática"): às 07:00 tudo, notícias
  de 30 em 30 min, cada competição de futebol 2h05 depois do início dos jogos (e mais até 3 vezes se o jogo ainda
  não acabou), a F1 1 h e 3 h depois de cada sessão e a NBA às 18:00. Entre a 01:00 e as 07:00 não corre nada.
- As regras estão em `desporto/tools/agenda.py`; o hub só corre o que está na hora (entrada `"agenda"` no
  `apps.json`, ver `hub/PROTOCOLO.md`) e regista cada execução, que a página mostra.

### Dados sempre frescos no ecrã
- Uma cena em pausa (ou fixa) redesenha-se quando chegam dados novos; se nada mudou, o ecrã não mexe.
- O Início do hub vê a cada minuto se houve uma atualização e redesenha logo; o tempo a cada 15 min (era 30).

### Outros
- O User-Agent dos pedidos leva o link do projeto, como a Wikipédia, a Wikidata e o OpenStreetMap pedem.
- No Windows, gravar o progresso da atualização já não falha (`WinError 5`) quando alguém o está a ler ao mesmo tempo.

## 2.0 (2026-10-22)

### Ao vivo
- **Mapa do continente** por cima dos cartões, quando os jogos seguidos são todos na Europa (até ao Cazaquistão),
  na América do Sul ou, na NBA, nos EUA (dividido por estados). Um ponto a pulsar em cada estádio e um balão com os
  emblemas, o resultado e o minuto. A vista enquadra só os jogos seguidos.
- **Acontecimentos no mapa:** em cada golo, penálti, autogolo, penálti falhado ou vermelho, o mapa voa até ao
  estádio, com as ruas, linhas, água e prédios à volta, mostra a cara e o nome de quem foi, o minuto e o resultado,
  e volta. Vários seguidos entram numa fila.
- **Aquecimento:** os jogos entram na lista 10 min antes da hora, sem resultado.
- Os marcadores cabem sempre no cartão (a letra encolhe e, se for preciso, passam a duas colunas), e o resultado
  já não fica atrás dos golos quando a ESPN demora a atualizá-lo.

### Estádios do mapa
- Coordenadas da Wikidata, confirmadas pela cidade, e o OpenStreetMap à volta de cada estádio de futebol, guardados
  no PC (fora do git). Correções à mão em `desporto/tools/estadios_correcoes.json`.
- Preparam-se antes, nunca durante o jogo: no passo "Estádios" da atualização (os jogos dos próximos 30 dias que
  faltam) ou de uma vez para a época toda (`estadios.py --todos`, que continua sozinho por uma tarefa agendada).
- Pedidos com calma: um de cada vez, 3 servidores do Overpass, no máximo 40 por dia e uma pausa de 24 h depois de 3
  falhas seguidas. Opções `--testar`, `--refazer`, `--corrigir` e `--seco`.
- Na página `/definicoes`: o estado, o botão "Continuar download" e os estádios dos próximos jogos que ainda faltam.

### F1 ao vivo
- Durante as sessões do fim de semana, a sessão aparece no Ao vivo e tem um ecrã próprio: corrida (intervalos,
  paragens, lutas, ultrapassagens, o campeonato se acabasse agora), qualificação (Q1/Q2/Q3 e a linha de eliminação)
  ou treinos, com o mapa da pista e avisos por cima (partida, novo líder, safety car, eliminados, pole).
- Fonte: o live timing da F1. O token da F1 TV é opcional (junta as posições dos carros) e fica só no PC.
- Cada sessão é gravada no PC para se poder rever; `f1_arquivo.py` descarrega sessões passadas para testar.

### Hub e comando
- O ⚙ Definições do comando abre sempre: se o servidor do desporto estiver desligado, o hub liga-o e volta a
  desligá-lo no fim.
- Início: as notícias nunca ficam cortadas. NBA "Esta noite": os resultados alinhados e tudo cabe no ecrã.

### Limpeza
- A verificação antes de cada commit diz "ok" quando passa e os acentos aparecem bem no Windows.
- Código que já não se usava retirado.

## 1.0 (2026-10-21)

A primeira versão fechada do ecrã:

- **Hub:** na parede só o Início, o código, o loading e a app aberta; as apps escolhem-se no comando do telemóvel.
  Estilo "Liquid Glass".
- **Desporto:** Última jornada, Ao vivo e Próxima jornada, com futebol das competições escolhidas, Fórmula 1 e NBA.
- **Despesas:** totais do mês e objetivos, com PIN, e uma versão demo.
- **Fontes e definições:** em `/definicoes` escolhem-se as competições e vê-se como correu cada fonte.
