// Cenas da NBA (a categoria de cada uma está em FASE, em scenes.js).
import { esc, badge, titulo, subtitulo, corDaZona, legenda, linhaTabela, listaJogos } from './base.js';

// Corrida a um prémio (MVP, Rookie do Ano): nome, números, barra e percentagem.
function corrida(D, lista) {
  return `<div class="table">${lista.map((p, i) => `
    <div class="row race"><b class="pos">${i + 1}</b>${badge(D, p.team)}
      <div class="rname"><span class="n">${esc(p.name)}</span><span class="l">${esc(p.line)}</span></div>
      <div class="bar"><i style="width:${p.pct}%"></i></div><span class="num pts">${p.pct}%</span></div>`).join('')}</div>`;
}

// Data por extenso: "2026-10-20" -> "20 de outubro"
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
const dataExtenso = (iso) => { const [, m, d] = iso.split('-').map(Number); return `${d} de ${MESES[m - 1]}`; };

export const CENAS_NBA = [
  {
    // Enquanto a época regular não começa (na Próxima jornada): um ecrã com a data de início
    id: 'nba-construcao', sport: 'nba', league: 'nba', parte: 'nba',
    render: (D) => {
      const inicio = D.nba && D.nba.regularStart;
      const dias = inicio ? Math.ceil((Date.parse(`${inicio}T12:00:00`) - Date.now()) / 86400e3) : null;
      return titulo('NBA', 'Em construção', 'nba') + `<section class="block construcao">
        <div class="cons-icone">🏀</div>
        <div class="cons-titulo">A NBA está a chegar</div>
        <div class="cons-texto">Este ecrã ainda está a ser preparado: classificação, jogos da noite e os melhores da época.</div>
        ${inicio ? `<div class="cons-data"><span>Época regular</span><b>${dataExtenso(inicio)}</b>
          ${dias > 0 ? `<small>daqui a ${dias} ${dias === 1 ? 'dia' : 'dias'}</small>` : '<small>já começou</small>'}</div>` : ''}
      </section>`;
    },
  },
  {
    // Classificação de cada conferência até ao último lugar do play-in
    id: 'nba', sport: 'nba', league: 'nba', parte: 'nba',
    tem: (D) => !!(D.nba.east && D.nba.west),
    render: (D) => {
      const conf = (nome, lista) => `<section class="block">${subtitulo(nome)}<div class="table dense">${lista.map((r, i) =>
        linhaTabela(D, r.team, i + 1, [{ v: `${r.w}-${r.l}`, cls: 'pts' }], corDaZona(D.nba.zonas, i + 1))).join('')}</div></section>`;
      return titulo('NBA', 'Classificação por conferência', 'nba') + conf('Conferência Este', D.nba.east) +
        conf('Conferência Oeste', D.nba.west) + legenda(D.nba.zonas, 10);
    },
  },
  {
    id: 'nba-noite', sport: 'nba', league: 'nba', parte: 'nba',
    tem: (D) => (D.nba.lastNight || []).length > 0 || !!D.nba.leaders,
    render: (D) => {
      const lid = Object.entries(D.nba.leaders || {}).map(([cat, lista]) => `
        <section class="block tight">${subtitulo('Líderes · ' + cat)}<div class="table">${lista.map((p, i) => `
          <div class="row"><b class="pos">${i + 1}</b>${badge(D, p.team)}<span class="name">${esc(p.name)}</span><span class="num big">${esc(p.v)}</span></div>`).join('')}</div></section>`).join('');
      const jogos = D.nba.lastNight || [];
      return titulo('NBA', jogos.length ? 'Jogos da noite passada' : 'Líderes da época', 'nba') +
        (jogos.length ? listaJogos(D, jogos) : '') + lid;
    },
  },
  {
    // Os jogos da noite americana que vem, com a hora de Portugal (a maioria já depois da meia-noite)
    id: 'nba-esta-noite', sport: 'nba', league: 'nba', parte: 'nba',
    tem: (D) => (D.nba.tonight || []).length > 0,
    render: (D) => {
      const jogos = D.nba.tonight;
      return titulo('NBA', `Esta noite · ${jogos.length === 1 ? '1 jogo' : `${jogos.length} jogos`} · hora de Portugal`, 'nba') + listaJogos(D, jogos);
    },
  },
  {
    id: 'nba-premios', sport: 'nba', league: 'nba', parte: 'nba',
    tem: (D) => !!(D.nba.mvp && D.nba.roty),
    // Com dados reais, as percentagens vêm das odds das casas de apostas (awardsSource): diz-se no subtítulo.
    render: (D) => titulo('NBA', D.nba.awardsSource ? `Probabilidade segundo as casas de apostas (${D.nba.awardsSource})` : 'Corrida aos prémios', 'nba') +
      `<section class="block">${subtitulo('MVP')}${corrida(D, D.nba.mvp)}</section>` +
      `<section class="block">${subtitulo('Rookie do Ano')}${corrida(D, D.nba.roty)}</section>`,
  },
];
