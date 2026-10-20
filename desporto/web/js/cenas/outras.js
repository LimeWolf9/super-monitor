// Cenas que não são de uma modalidade: jogador em destaque e curiosidades.
import { esc, badge, titulo, subtitulo } from './base.js';

export const CENAS_OUTRAS = [
  {
    id: 'jogador', sport: 'player', parte: 'destaques',
    tem: (D) => (D.players || []).length > 0,
    render: (D) => titulo('Jogador em destaque', 'Os números da semana') + D.players.map((p) => `
      <section class="player-card sport-${p.sport}">
        <div class="pc-head">${badge(D, p.team)}<div><div class="pc-name">${esc(p.name)}</div><div class="pc-tag">${esc(p.tag)}</div></div></div>
        <div class="pc-stats">${p.stats.map((s) => `<div class="stat"><span class="v">${esc(s.value)}</span><span class="l">${esc(s.label)}</span></div>`).join('')}</div>
        <div class="pc-blurb">${esc(p.blurb)}</div>
      </section>`).join(''),
  },
  {
    id: 'fun', sport: 'fun', parte: 'curiosidades',
    tem: (D) => ['onThisDay', 'records', 'comparisons'].some((k) => (D.fun[k] || []).length),
    // ctx.pass = quantas voltas completas já foram dadas; roda os itens para não repetir sempre os mesmos.
    render: (D, ctx) => {
      const dois = (lista) => [0, 1].slice(0, Math.min(2, lista.length)).map((k) => lista[(ctx.pass * 2 + k) % lista.length]);
      const bloco = (nome, lista = [], comAno) => !lista.length ? '' : `<section class="block fun-block">${subtitulo(nome)}${dois(lista).map((it) => `
        <p class="fun-item">${comAno ? `<b class="year">${it.year}</b>` : ''}${esc(it.text)}</p>`).join('')}</section>`;
      return titulo('Curiosidades') +
        bloco('Neste dia na história', D.fun.onThisDay, true) +
        bloco('Recordes curiosos', D.fun.records) +
        bloco('Comparações absurdas', D.fun.comparisons);
    },
  },
];

// ?cat=aovivo: por agora, um ecrã só, "Em construção"
export const CENA_AO_VIVO = {
  id: 'aovivo-construcao', sport: 'live', parte: 'futebol',
  render: () => titulo('Ao vivo', 'Em construção') + `<section class="block construcao">
    <div class="cons-icone">📡</div>
    <div class="cons-titulo">Os jogos a decorrer vão aparecer aqui</div>
    <div class="cons-texto">Resultados ao minuto dos jogos das competições que segues, da F1 e da NBA. Ainda está a ser preparado.</div>
  </section>`,
};
