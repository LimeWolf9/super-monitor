// Cenas da Fórmula 1. As que têm "so: 'f1'" só entram em ?cat=f1.
import { targetMs } from '../util.js';
import { esc, badge, teamName, titulo, subtitulo, cara, temCaras } from './base.js';

// Desenho estilizado da pista (SVG) com um ponto a dar voltas.
function pista(t) {
  const [x1, y1, x2, y2] = t.start;
  return `<svg class="track" viewBox="${t.viewBox}" preserveAspectRatio="xMidYMid meet">
    <path id="track-path" d="${t.d}" class="track-base"/>
    <path d="${t.d}" class="track-line"/>
    <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="track-start"/>
    <circle r="4.5" class="track-car"><animateMotion dur="9s" repeatCount="indefinite"><mpath href="#track-path"/></animateMotion></circle>
  </svg>`;
}

// ▲2 / ▼1 / nada: lugares ganhos ou perdidos desde a corrida anterior
const seta = (chg) => (chg > 0 ? `<span class="chg sobe">▲${chg}</span>` : chg < 0 ? `<span class="chg desce">▼${-chg}</span>`
  : '<span class="chg"></span>');

// Data na hora de Portugal: "Sex 23/10" e "18:30"
const LISBOA = 'Europe/Lisbon';
const diaPT = (iso) => {
  const d = new Date(iso);
  const sem = new Intl.DateTimeFormat('pt-PT', { timeZone: LISBOA, weekday: 'short' }).format(d).replace('.', '');
  const dm = new Intl.DateTimeFormat('pt-PT', { timeZone: LISBOA, day: '2-digit', month: '2-digit' }).format(d);
  return `${sem.charAt(0).toUpperCase()}${sem.slice(1, 3)} ${dm}`;
};
const horaPT = (iso) => new Intl.DateTimeFormat('pt-PT', { timeZone: LISBOA, hour: '2-digit', minute: '2-digit' }).format(new Date(iso));

// Cara de um piloto pelo nome (as fotos estão em D.f1.drivers, ver tools/atualizar_fotos.py)
const caraPiloto = (D, nome) => cara((D.f1.drivers || []).find((p) => p.name === nome) || {}, true);
const apelido = (nome) => nome.split(' ').slice(-1)[0];

// Cores dos pneus (as da Pirelli)
const PNEUS = { SOFT: ['#e8002d', 'Macio'], MEDIUM: ['#ffd12e', 'Médio'], HARD: ['#f0f0ec', 'Duro'],
  INTERMEDIATE: ['#43b02a', 'Intermédio'], WET: ['#0067ad', 'Chuva'] };

// Evolução dos pontos: uma cor por piloto (paleta categórica validada para fundo escuro), nunca pela posição
const CORES_SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181'];

function graficoPontos(D) {
  const ev = D.f1.evolution;
  const W = 1000, H = 1850, M = { l: 90, r: 290, t: 30, b: 80 };
  const max = Math.max(...ev.series.flatMap((s) => s.pts), 1);
  const passo = max > 200 ? 100 : 50;
  const topo = Math.ceil(max / passo) * passo;
  const x = (i) => M.l + (i / Math.max(1, ev.rounds.length - 1)) * (W - M.l - M.r);
  const y = (v) => H - M.b - (v / topo) * (H - M.t - M.b);
  // cor fixa por piloto: ordem alfabética dos cinco (não muda quando trocam de lugar entre si)
  const porNome = [...ev.series].map((s) => s.name).sort();
  const cor = (n) => CORES_SERIES[porNome.indexOf(n) % CORES_SERIES.length];
  const grelha = [];
  for (let v = 0; v <= topo; v += passo) {
    grelha.push(`<line x1="${M.l}" x2="${W - M.r}" y1="${y(v)}" y2="${y(v)}" class="gr"/><text x="${M.l - 16}" y="${y(v) + 9}" class="eixo" text-anchor="end">${v}</text>`);
  }
  const rondas = ev.rounds.map((r, i) => (i % 2 === 0 || i === ev.rounds.length - 1)
    ? `<text x="${x(i)}" y="${H - M.b + 46}" class="eixo" text-anchor="middle">${r}</text>` : '').join('');
  // rótulos no fim das linhas, afastados para não se sobreporem
  const fins = ev.series.map((s) => ({ s, y: y(s.pts[s.pts.length - 1]) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < fins.length; i++) fins[i].ly = Math.max(fins[i].y, (fins[i - 1].ly ?? fins[i - 1].y) + 52);
  fins[0] && (fins[0].ly = fins[0].y);
  const linhas = ev.series.map((s) => `<polyline class="ln" style="stroke:${cor(s.name)}" points="${s.pts.map((v, i) => `${x(i)},${y(v)}`).join(' ')}"/>
      <circle cx="${x(s.pts.length - 1)}" cy="${y(s.pts[s.pts.length - 1])}" r="9" style="fill:${cor(s.name)}" class="pt"/>`).join('');
  const rotulos = fins.map((f) => `<text x="${W - M.r + 24}" y="${f.ly + 12}" class="rot"><tspan>${esc(apelido(f.s.name))}</tspan><tspan class="rot-v" dx="12">${f.s.pts[f.s.pts.length - 1]}</tspan></text>`).join('');
  const legenda = ev.series.map((s) => `<span><i style="background:${cor(s.name)}"></i>${esc(s.name)}</span>`).join('');
  return `<svg class="grafico" viewBox="0 0 ${W} ${H}" role="img" aria-label="Pontos acumulados do top 5 ao longo da época">
      ${grelha.join('')}${rondas}<text x="${(M.l + W - M.r) / 2}" y="${H - 6}" class="eixo" text-anchor="middle">Ronda</text>
      ${linhas}${rotulos}</svg><div class="legenda-graf">${legenda}</div>`;
}

// Por esta ordem: primeiro a época inteira, depois o próximo GP, por fim a última corrida
export const CENAS_F1 = [
  {
    id: 'f1', sport: 'f1', league: 'f1', parte: 'f1',
    tem: (D) => (D.f1.drivers || []).length > 0,
    render: (D) => {
      // rosto = cara do piloto (só no campeonato de pilotos); dif = pontos para o líder; chg = lugares ganhos/perdidos
      // desde a corrida anterior (só com dados reais)
      const linha = (i, code, nome, pts, lider, chg, rosto = '') =>
        `<div class="row"><b class="pos">${i + 1}</b>${badge(D, code)}${rosto}<span class="name">${esc(nome)}</span>` +
        `${seta(chg)}<span class="num dif">${i ? `−${lider - pts}` : ''}</span><span class="num pts">${pts}</span></div>`;
      const comCaras = temCaras(D.f1.drivers);
      const lp = (D.f1.drivers[0] || {}).pts, lc = (D.f1.constructors[0] || {}).pts;
      const pil = D.f1.drivers.map((p, i) => linha(i, p.team, p.name, p.pts, lp, p.chg, cara(p, comCaras))).join('');
      const con = D.f1.constructors.map((c, i) => linha(i, c.team, teamName(D, c.team), c.pts, lc, c.chg)).join('');
      return titulo('Fórmula 1', 'Campeonato', 'f1') + subtitulo('Pilotos') + `<div class="table dense">${pil}</div>` +
        subtitulo('Construtores') + `<div class="table dense">${con}</div>`;
    },
  },
  {
    // Duelo entre colegas de equipa: quem ficou à frente na qualificação e na corrida
    id: 'f1-duelos', sport: 'f1', league: 'f1', parte: 'f1', so: 'f1',
    tem: (D) => (D.f1.h2h || []).length > 0,
    render: (D) => {
      const barra = (a, b) => { const t = a + b || 1; return `<div class="duelo-barra"><i style="width:${(a / t) * 100}%"></i></div>`; };
      const linhas = D.f1.h2h.map(({ team, drivers: [a, b] }) => `<div class="duelo">
          <div class="d-lado">${caraPiloto(D, a.name)}<div><b>${esc(apelido(a.name))}</b><small>${a.pts} pts</small></div></div>
          <div class="d-meio">${badge(D, team)}
            <div class="d-linha"><span>${a.q}</span><em>Qual.</em><span>${b.q}</span></div>${barra(a.q, b.q)}
            <div class="d-linha"><span>${a.r}</span><em>Corrida</em><span>${b.r}</span></div>${barra(a.r, b.r)}</div>
          <div class="d-lado dir"><div><b>${esc(apelido(b.name))}</b><small>${b.pts} pts</small></div>${caraPiloto(D, b.name)}</div>
        </div>`).join('');
      return titulo('Fórmula 1', 'Duelos entre colegas', 'f1') + `<section class="block duelos">${linhas}</section>`;
    },
  },
  {
    // Gráfico da evolução dos pontos do top 5
    id: 'f1-pontos', sport: 'f1', league: 'f1', parte: 'f1', so: 'f1',
    tem: (D) => !!(D.f1.evolution && D.f1.evolution.series.length && D.f1.evolution.rounds.length > 1),
    render: (D) => titulo('Fórmula 1', 'Pontos ao longo da época · top 5', 'f1') + `<section class="block graf">${graficoPontos(D)}</section>`,
  },
  {
    id: 'f1-gp', sport: 'f1', league: 'f1', parte: 'f1',
    tem: (D) => !!D.f1.next,
    // A pista ocupa a parte de cima; o contador fica em baixo.
    render: (D) => {
      const n = D.f1.next;
      const caixa = (u, rot) => `<div class="cd-box"><span class="cd-num" data-u="${u}">--</span><span class="cd-lbl">${rot}</span></div>`;
      const dado = (v, l) => `<div class="stat"><span class="v">${esc(v)}</span><span class="l">${l}</span></div>`;
      return titulo('Fórmula 1', 'Próxima corrida', 'f1') +
        `<section class="block track-block">${n.track ? pista(n.track) : ''}
          <div class="pc-stats track-stats">${dado(n.laps, 'voltas')}${dado(n.length, 'pista')}${dado(n.turns, 'curvas')}</div>
        </section>
        <section class="block hero">
          <div class="gp-name">${esc(n.name)}</div>
          <div class="gp-sub">${esc(n.circuit)} · ${esc(n.country)}</div>
          <div class="countdown" data-target="${targetMs(n)}">${caixa('d', 'dias')}${caixa('h', 'horas')}${caixa('m', 'min')}${caixa('s', 'seg')}</div>
        </section>`;
    },
  },
  {
    // Próximo GP: todas as sessões na hora de Portugal e os últimos vencedores no circuito
    id: 'f1-fds', sport: 'f1', league: 'f1', parte: 'f1', so: 'f1',
    tem: (D) => !!(D.f1.weekend && D.f1.weekend.sessions && D.f1.weekend.sessions.length),
    render: (D) => {
      const w = D.f1.weekend;
      const agora = Date.now();
      const proxima = w.sessions.find((x) => Date.parse(x.date) > agora);
      const sess = w.sessions.map((x) => `<div class="row sess${Date.parse(x.date) < agora ? ' feita' : ''}${x === proxima ? ' me' : ''}">
          <span class="name">${esc(x.name)}</span><span class="num dia">${diaPT(x.date)}</span><span class="num pts">${horaPT(x.date)}</span></div>`).join('');
      const venc = (w.winners || []).map((v) => `<div class="row"><b class="pos ano">${v.year}</b>${v.team ? badge(D, v.team) : '<span class="badge vazio"></span>'}
          ${caraPiloto(D, v.name)}<span class="name">${esc(v.name)}</span><span class="num equipa">${esc(v.teamName)}</span></div>`).join('');
      return titulo('Fórmula 1', w.name, 'f1') +
        `<section class="block">${subtitulo('Horário · hora de Portugal')}<div class="table">${sess}</div></section>` +
        (venc ? `<section class="block">${subtitulo('Últimos vencedores aqui')}<div class="table">${venc}</div></section>` : '');
    },
  },
  {
    // Resumo da última corrida
    id: 'f1-ultima', sport: 'f1', league: 'f1', parte: 'f1', so: 'f1',
    tem: (D) => !!(D.f1.last && D.f1.last.podium && D.f1.summary),
    render: (D) => {
      const L = D.f1.last, S = D.f1.summary;
      const lugar = ['1.º', '2.º', '3.º'];
      const podio = L.podium.map((p, i) => `<div class="row podio p${i + 1}"><b class="pos">${lugar[i]}</b>${badge(D, p.team)}${caraPiloto(D, p.name)}
          <span class="name">${esc(p.name)}</span><span class="num">${esc(p.time)}</span></div>`).join('');
      const subidas = (S.gains || []).map((g) => `<div class="row">${badge(D, g.team)}${caraPiloto(D, g.name)}<span class="name">${esc(g.name)}</span>
          <span class="num dia">P${g.grid} → P${g.pos}</span><span class="num pts sobe">+${g.gain}</span></div>`).join('');
      const fora = (S.dnfs || []).map((d) => `<div class="row">${badge(D, d.team)}<span class="name">${esc(d.name)}</span>
          <span class="num dia">${d.status === 'Retired' ? 'desistiu' : esc(d.status)}</span><span class="num">volta ${d.laps}</span></div>`).join('');
      const fp = S.fastestPit;
      return titulo('Fórmula 1', `Resumo · ${L.name}`, 'f1') +
        `<section class="block">${subtitulo('Pódio')}<div class="table">${podio}</div>
          ${L.fastest ? `<div class="nota">⏱ ${esc(L.fastest)}</div>` : ''}</section>` +
        (subidas ? `<section class="block">${subtitulo('Quem mais subiu')}<div class="table">${subidas}</div></section>` : '') +
        (fora ? `<section class="block">${subtitulo('Desistências')}<div class="table">${fora}</div></section>` : '') +
        (fp ? `<section class="block">${subtitulo('Paragem mais rápida')}<div class="table"><div class="row">${fp.team ? badge(D, fp.team) : ''}
          ${caraPiloto(D, fp.name)}<span class="name">${esc(fp.name)}</span><span class="num dia">volta ${fp.lap}</span>
          <span class="num pts">${esc(fp.time.replace('.', ','))} s</span></div></div>
          <div class="nota">Tempo total na via das boxes (entrada → saída).</div></section>` : '');
    },
  },
  {
    // Estratégia de pneus da última corrida (OpenF1): uma barra por piloto, pela ordem de chegada
    id: 'f1-pneus', sport: 'f1', league: 'f1', parte: 'f1', so: 'f1',
    tem: (D) => !!(D.f1.stints && D.f1.stints.drivers && D.f1.stints.drivers.length),
    render: (D) => {
      const S = D.f1.stints;
      const usados = new Set();
      const linhas = S.drivers.map((d) => `<div class="pn-linha"><b class="pos">${esc(d.pos)}</b>${badge(D, d.team)}<span class="pn-cod">${esc(d.code)}</span>
          <div class="pn-barra">${d.stints.map((st) => {
            const [c] = PNEUS[st.c] || ['#777'];
            usados.add(st.c);
            const voltas = st.to - st.from + 1;
            return `<i style="flex:${voltas};background:${c}" class="pn-${st.c.toLowerCase()}">${voltas >= 6 ? voltas : ''}</i>`;
          }).join('')}<span style="flex:${Math.max(0, S.laps - d.stints[d.stints.length - 1].to)}"></span></div></div>`).join('');
      const leg = [...usados].filter((c) => PNEUS[c]).map((c) => `<span><i style="background:${PNEUS[c][0]}"></i>${PNEUS[c][1]}</span>`).join('');
      return titulo('Fórmula 1', `Estratégia de pneus · ${S.name}`, 'f1') +
        `<div class="legenda-graf pn-leg">${leg}<span class="pn-nota">números = voltas com esse pneu · ${S.laps} voltas</span></div>
         <section class="block pneus" style="--n:${S.drivers.length}">${linhas}</section>`;
    },
  },
];
