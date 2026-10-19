// Cenas de futebol: resultados com eventos, melhor 11, classificação, próximos jogos com notícias, marcadores.
import { esc, badge, teamName, titulo, subtitulo, corDaZona, legenda, linhaTabela, jogo, cara, temCaras } from './base.js';

// Um evento do jogo (golo, penálti, penálti falhado, autogolo, vermelho).
// O nome vai num <span class="p"> próprio: se não couber, é cortado com reticências e o minuto fica sempre visível.
function evento(e) {
  const nome = `<span class="p">${esc(e.p)}</span>`;
  const min = `<span class="min">${esc(e.m)}'</span>`;
  const bola = '<i class="ball"></i>';
  switch (e.t) {
    case 'red':      return `<span class="ev-i ev-red"><i class="card-red"></i>${nome}${min}</span>`;
    case 'pen':      return `<span class="ev-i">${bola}${nome}${min}<span class="tag pen">P</span></span>`;
    case 'pen_miss': return `<span class="ev-i"><i class="goal-red"></i>${nome}${min}</span>`;
    case 'og':       return `<span class="ev-i">${bola}${nome}${min}<span class="tag og">AG</span></span>`;
    default:         return `<span class="ev-i">${bola}${nome}${min}</span>`;
  }
}

// Medidas dos eventos (px). Têm de bater certo com .evs no base.css.
const ALTURA_CARTAO = 96;               // cartão do jogo (84) + margens
const LINHA_EV = { 1: 37, 2: 32 };      // altura de uma linha: letra normal (30) ou mais pequena (24)

// Resultado com detalhe: cartão do jogo + eventos de cada equipa por baixo.
// Cabem tantas linhas quantas a fatia deixar (--slot muda com o número de jogos na página): primeiro numa
// coluna; se não chegar, numa coluna com letra mais pequena; depois em duas equilibradas (ex.: 3 + 3); se nem
// assim, os primeiros e um "+N". Cada lado fica sempre na sua metade, por baixo da sua equipa (nunca por baixo do resultado).
function jogoDetalhe(D, m, fatia) {
  const lado = (s) => (m.ev || [])
    .filter((e) => e.s === s)
    .sort((a, b) => parseInt(a.m, 10) - parseInt(b.m, 10));
  const h = lado('h'), a = lado('a');
  const espaco = Math.max(0, fatia - ALTURA_CARTAO);
  const linhasNormal = Math.max(1, Math.floor(espaco / LINHA_EV[1]));
  const linhasPequena = Math.max(1, Math.floor(espaco / LINHA_EV[2]));
  const bloco = (lista, cls) => {
    const pequena = lista.length > linhasNormal;          // letra mais pequena
    const colunas = lista.length > linhasPequena ? 2 : 1;  // e só depois duas colunas
    // duas colunas equilibradas: 6 eventos -> 3 + 3 (e não 4 + 2)
    const linhas = colunas === 2 ? Math.min(linhasPequena, Math.ceil(lista.length / 2)) : pequena ? linhasPequena : linhasNormal;
    const cabem = colunas * linhas;
    const itens = lista.length > cabem
      ? lista.slice(0, cabem - 1).map(evento).concat(`<span class="ev-i mais">+${lista.length - cabem + 1}</span>`)
      : lista.map(evento);
    return `<div class="evs ${cls}${pequena ? ' pequena' : ''}${colunas === 2 ? ' many' : ''}" style="--linhas:${Math.min(linhas, itens.length)}">${itens.join('')}</div>`;
  };
  const eu = (m.home === D.myTeam.code || m.away === D.myTeam.code) ? ' me' : '';
  return `<div class="mres${eu}">${jogo(D, m, true)}
    ${h.length || a.length ? `<div class="mres-ev">${bloco(h, 'home')}<span></span>${bloco(a, 'away')}</div>` : ''}</div>`;
}

// ---------- Páginas: quando a lista não cabe num ecrã, divide-se em várias cenas ----------

const MAX_JOGOS_PAGINA = 10;   // jogos por ecrã: o ecrã é dividido em partes iguais, uma por jogo
const ALTURA_JOGOS = 2150;     // px disponíveis para os cartões de resultados
const ALTURA_MAX_JOGO = 250;   // px máximos de cada jogo (quando há poucos jogos na página)
const MAX_LINHAS_TABELA = 28;  // linhas por página: a 1.ª página enche o ecrã e o resto passa para a seguinte

// Reparte os jogos por páginas do mesmo tamanho (ex.: 18 jogos -> 2 páginas de 9).
function paginarJogos(lista) {
  const n = Math.max(1, Math.ceil(lista.length / MAX_JOGOS_PAGINA));
  const tam = Math.ceil(lista.length / n);
  return Array.from({ length: n }, (_, i) => lista.slice(i * tam, (i + 1) * tam));
}

const sufixoPagina = (k, total) => (total > 1 ? ` · ${k + 1}/${total}` : '');

// Resultados de TODOS os jogos da jornada (página k). Cada jogo ocupa uma fatia de altura fixa.
function cenaJogos(D, chave, k) {
  const L = D.football[chave];
  const paginas = paginarJogos(L.results);
  const pag = paginas[k] || [];
  const fatia = Math.min(ALTURA_MAX_JOGO, Math.floor(ALTURA_JOGOS / Math.max(1, pag.length)));
  // Jornada ainda em curso (ex.: falta o jogo de segunda): "9 de 10 jogos"
  const emCurso = L.partial ? ` · ${L.partial.done} de ${L.partial.total} jogos` : '';
  return titulo(L.name, `Resultados · ${L.round}${emCurso}${sufixoPagina(k, paginas.length)}`, chave) +
    `<div class="mresults" style="--n:${pag.length};--slot:${fatia}px">${pag.map((m) => jogoDetalhe(D, m, fatia)).join('')}</div>`;
}

// Classificação (página k). Os próximos jogos têm cena própria (cenaProximos).
function paginasTabela(L) {
  const paginas = [];
  for (let i = 0; i < L.table.length; i += MAX_LINHAS_TABELA) paginas.push(L.table.slice(i, i + MAX_LINHAS_TABELA));
  return paginas.length ? paginas : [[]];
}

function cenaTabela(D, chave, k) {
  const L = D.football[chave];
  const paginas = paginasTabela(L);
  const linhasPag = paginas[k] || [];
  const inicio = paginas.slice(0, k).reduce((t, p) => t + p.length, 0);
  const cab = `<div class="row head"><b class="pos"></b><span class="name"></span><span class="num">J</span><span class="num pts">PTS</span></div>`;
  const linhas = linhasPag.map((r, i) => {
    const pos = inicio + i + 1;
    return linhaTabela(D, r.team, pos, [{ v: r.j }, { v: r.pts, cls: 'pts' }], corDaZona(L.zonas, pos));
  }).join('');
  return titulo(L.name, `Classificação · ${L.round}${sufixoPagina(k, paginas.length)}`, chave) +
    `<div class="table dense">${cab}${linhas}</div>` + legenda(L.zonas, inicio + linhasPag.length);
}

// Jogos grandes: os da equipa em destaque (myTeam) e aqueles em que as duas equipas estão no top da tabela
// (top 6 nas ligas, top 8 nas competições europeias).
const TOP_DESTAQUE = { pt: 6, en: 6, es: 6, de: 6, fr: 6, it: 6, ucl: 8, uel: 8, uecl: 8 };
function eDestaque(D, chave, m) {
  const eu = D.myTeam.code;
  if (m.home === eu || m.away === eu) return true;
  const L = D.football[chave];
  if (!(L.table || []).some((r) => r.j > 0)) return false;   // antes da 1.ª jornada a tabela não diz nada
  const top = new Set((L.table || []).slice(0, TOP_DESTAQUE[chave] || 6).map((r) => r.team));
  return top.has(m.home) && top.has(m.away);
}

// Próximos jogos por ordem: primeiro os destaques, depois os restantes (cada grupo pela ordem de calendário).
function proximosOrdenados(D, chave) {
  const lista = (D.football[chave].next || []).map((m) => ({ m, d: eDestaque(D, chave, m) }));
  return lista.filter((x) => x.d).concat(lista.filter((x) => !x.d));
}

// ---------- Próximos jogos (2 por linha) + notícias da liga no espaço que sobra ----------

// Medidas (px). Têm de bater certo com .pj e .nt no base.css.
const LINHA_PJ = 162;            // cartão compacto (150) + espaço entre linhas
const ALTURA_NOTICIA = 172;      // uma notícia (imagem 150) + espaço
const CABECALHO_NOTICIAS = 76;   // subtítulo "Notícias"
const MIN_NOTICIAS = 3;          // se houver notícias, mostram-se pelo menos estas
const MAX_NOTICIAS = 6;

// Cartão compacto: as duas equipas em linhas, o dia e a hora à direita.
function jogoCompacto(D, m, destaque) {
  const eu = (m.home === D.myTeam.code || m.away === D.myTeam.code) ? ' me' : '';
  const [dia, ...hora] = (m.when || '').split(' ');
  const equipa = (code) => `<div class="pj-eq">${badge(D, code)}<span class="tn">${esc(teamName(D, code))}</span></div>`;
  return `<div class="pj${eu}${destaque ? ' destaque' : ''}">${equipa(m.home)}${equipa(m.away)}
    <div class="pj-quando"><span class="dia">${esc(dia)}${m.date ? ' ' + esc(m.date) : ''}</span><span class="hora">${esc(hora.join(' '))}</span>
    ${destaque ? '<span class="tag destaque">Destaque</span>' : ''}</div></div>`;
}

// Notícias da liga (D.news[chave], de tools/atualizar_noticias.py). Independente dos jogos: se um dia passarem
// para uma cena própria, basta chamar esta função noutra cena.
function noticiasDaLiga(D, chave) {
  return (D.news && D.news[chave]) || [];
}

function haQuanto(iso) {
  const min = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  return h < 24 ? `há ${h} h` : `há ${Math.round(h / 24)} d`;
}

// data-liga / data-i: dizem ao comando (controlo.js) que notícia abrir com OK
function blocoNoticias(lista, chave) {
  if (!lista.length) return '';
  const fontes = [...new Set(lista.map((n) => n.source))].join(', ');
  return `<section class="noticias">${subtitulo('Notícias')}${lista.map((n, i) => `
    <div class="nt" data-liga="${chave}" data-i="${i}">${n.img ? `<img src="${esc(n.img)}" alt="" onerror="this.remove()">` : ''}
      <div class="nt-txt"><b>${esc(n.title)}</b>${n.summary ? `<span class="nt-res">${esc(n.summary)}</span>` : ''}
      <span class="nt-meta">${esc(n.source)} · ${haQuanto(n.date)}</span></div></div>`).join('')}
    <div class="nt-fonte">Notícias: ${esc(fontes)}</div></section>`;
}

// Jogos da jornada seguinte em grelha de 2 por linha (destaques primeiro) e, por baixo, as notícias da liga.
// Se não couberem os jogos todos e as notícias mínimas, mostram-se os primeiros e um "+N jogos".
function cenaProximos(D, chave) {
  const L = D.football[chave];
  const jogos = proximosOrdenados(D, chave);
  const noticias = noticiasDaLiga(D, chave);
  const reserva = noticias.length ? CABECALHO_NOTICIAS + Math.min(MIN_NOTICIAS, noticias.length) * ALTURA_NOTICIA : 0;
  const maxLinhas = Math.max(1, Math.floor((ALTURA_JOGOS - reserva) / LINHA_PJ));
  let mostrar = jogos;
  let resto = 0;
  if (Math.ceil(jogos.length / 2) > maxLinhas) {
    mostrar = jogos.slice(0, maxLinhas * 2 - 1);   // o último lugar fica para o "+N jogos"
    resto = jogos.length - mostrar.length;
  }
  const linhas = Math.ceil((mostrar.length + (resto ? 1 : 0)) / 2);
  const livre = ALTURA_JOGOS - linhas * LINHA_PJ - CABECALHO_NOTICIAS;
  const nNoticias = Math.min(MAX_NOTICIAS, noticias.length, Math.max(0, Math.floor(livre / ALTURA_NOTICIA)));
  // Com o que falta da jornada em curso e a seguinte misturados, não se diz o número da jornada
  const jornada = !L.nextMixed && L.round && L.round.startsWith('Jornada') ? ' · ' + nomeJornadaSeguinte(L.round) : '';
  return titulo(L.name, `Próximos jogos${jornada}`, chave) +
    `<div class="pjs">${mostrar.map((x) => jogoCompacto(D, x.m, x.d)).join('')}${resto ? `<div class="pj mais">+${resto} jogos</div>` : ''}</div>` +
    blocoNoticias(noticias.slice(0, nNoticias), chave);
}

// "Jornada 8" (a última terminada) -> "Jornada 9"
const nomeJornadaSeguinte = (round) => `Jornada ${parseInt(round.replace(/\D/g, ''), 10) + 1}`;

function marcadores(D, lista) {
  const comCaras = temCaras(lista);
  return `<div class="table">${lista.map((s, i) => `
    <div class="row${s.team === D.myTeam.code ? ' me' : ''}"><b class="pos">${i + 1}</b>${badge(D, s.team)}${cara(s, comCaras)}
      <span class="name">${esc(s.name)}</span><span class="num big">${s.goals}</span></div>`).join('')}</div>`;
}

// Ordem das competições na rotação (a Bundesliga, a Ligue 1 e a Serie A só em ?cat=futebol)
const ORDEM_LIGAS = { todos: ['pt', 'en', 'es', 'ucl', 'uel', 'uecl'], futebol: ['pt', 'en', 'es', 'de', 'fr', 'it', 'ucl', 'uel', 'uecl'] };

// Marcadores: todas as competições da rotação, 2 por linha, top 3 de cada uma
const comMarcadores = (D, ligas) => ligas.filter((k) => D.football[k] && (D.football[k].scorers || []).length);
function cenaMarcadores(D, ligas) {
  const com = comMarcadores(D, ligas);
  return titulo('Marcadores', 'Golos esta época') +
    `<div class="golos-grelha" style="--linhas:${Math.ceil(com.length / 2)}">` +
    com.map((k) =>
      `<section class="block tight league-${k}">${subtitulo(D.football[k].name, k)}${marcadores(D, D.football[k].scorers)}</section>`).join('') +
    '</div>';
}

// ---------- Melhor 11 da jornada (tools/atualizar_onze.py): 4-3-3 sobre o relvado ----------
function cenaOnze(D, chave) {
  const L = D.football[chave], O = L.onze;
  const linha = (nome) => O.players.filter((p) => p.line === nome);
  const jogador = (p) => `<div class="o-jog">${badge(D, p.team)}<b>${esc(p.short || p.name)}</b>${p.why ? `<small>${esc(p.why)}</small>` : ''}</div>`;
  const fila = (nome) => `<div class="o-fila">${linha(nome).map(jogador).join('')}</div>`;
  return titulo(L.name, `Melhor 11 · ${O.round || L.round}`, chave) +
    `<section class="block onze">${fila('AV')}${fila('MED')}${fila('DEF')}${fila('GR')}</section>
     <div class="nota onze-nota">Calculado pelo dashboard a partir das estatísticas da ESPN (golos, assistências, balizas a zeros, defesas, resultado). Não é o 11 oficial.</div>`;
}

// Todas as cenas de futebol, pela ordem da rotação: por liga, resultados (várias páginas), melhor 11,
// classificação e próximos jogos; no fim, os marcadores.
export function cenasFutebol(D, cat) {
  const cenas = [];
  const ligas = ORDEM_LIGAS[cat] || ORDEM_LIGAS.todos;
  // soTabela: Liga Europa/Conferência não mostram os resultados, só a classificação e os próximos jogos.
  // comProximos: a Liga Europa e a Conferência não mostram os próximos jogos por agora (a fase de liga tem
  // 18 jogos e pouco interesse); voltam a ser avaliadas nas eliminatórias.
  const liga = (chave, league, soTabela = false, comProximos = true) => {
    const L = D.football[chave];
    if (!L) return;
    if (!soTabela && (L.results || []).length) {
      const nj = paginarJogos(L.results).length;
      for (let k = 0; k < nj; k++) {
        cenas.push({ id: `${chave}-jogos${k ? '-' + (k + 1) : ''}`, sport: 'football', league, parte: 'futebol', render: (d) => cenaJogos(d, chave, k) });
      }
      if (L.onze && (L.onze.players || []).length === 11) {
        cenas.push({ id: `${chave}-onze`, sport: 'football', league, parte: 'futebol', render: (d) => cenaOnze(d, chave) });
      }
    }
    if ((L.table || []).length) {
      const nt = paginasTabela(L).length;
      for (let k = 0; k < nt; k++) {
        cenas.push({ id: `${chave}-tabela${k ? '-' + (k + 1) : ''}`, sport: 'football', league, parte: 'futebol', render: (d) => cenaTabela(d, chave, k) });
      }
    }
    if (comProximos && (L.next || []).length) {
      cenas.push({ id: `${chave}-proximos`, sport: 'football', league, parte: 'futebol', render: (d) => cenaProximos(d, chave) });
    }
  };
  liga('pt', 'pt'); liga('en', 'en'); liga('es', 'es');
  if (cat === 'futebol') { liga('de', 'de'); liga('fr', 'fr'); liga('it', 'it'); }
  liga('ucl', 'ucl');
  liga('uel', 'uel', true, false); liga('uecl', 'uecl', true, false);
  cenas.push({
    id: 'golos', sport: 'football', parte: 'futebol',
    tem: (d) => comMarcadores(d, ligas).length > 0,
    render: (d) => cenaMarcadores(d, ligas),
  });
  return cenas;
}
