// Cenas de futebol: resultados com eventos, melhor 11, classificação, próximos jogos com notícias, marcadores;
// e, nas taças e nas seleções, um ecrã com a fase (resultados e jogos seguintes) e as tabelas dos grupos.
import { esc, badge, teamName, titulo, subtitulo, corDaZona, legenda, linhaTabela, jogo, cara, temCaras, minha, temMinha } from './base.js';
import { agora } from '../util.js';

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
  const eu = temMinha(D, m) ? ' me' : '';
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

// Jogos grandes: os das equipas em destaque (myTeam: o FC Porto e Portugal) e aqueles em que as duas equipas estão no top da tabela
// (top 6 nas ligas, top 8 nas competições europeias).
const TOP_DESTAQUE = { pt: 6, en: 6, es: 6, de: 6, fr: 6, it: 6, ucl: 8, uel: 8, uecl: 8 };
function eDestaque(D, chave, m) {
  if (temMinha(D, m)) return true;
  const L = D.football[chave];
  if (!(L.table || []).some((r) => r.j > 0)) return false;   // antes da 1.ª jornada a tabela não diz nada
  const top = new Set((L.table || []).slice(0, TOP_DESTAQUE[chave] || 6).map((r) => r.team));
  return top.has(m.home) && top.has(m.away);
}

// Jogos da jornada dos resultados que ainda estão por jogar (aparecem nos resultados e também nos próximos jogos)
export const pendentes = (L) => (L.results || []).filter((m) => m.hs == null && m.status !== 'adiado');

// Próximos jogos por ordem: primeiro o que falta da jornada em curso, depois os seguintes; em cada parte os
// destaques primeiro e depois os restantes (pela ordem de calendário).
function proximosOrdenados(D, chave) {
  const L = D.football[chave];
  const parte = (lista, atual) => {
    const xs = lista.map((m) => ({ m, d: eDestaque(D, chave, m), atual }));
    return xs.filter((x) => x.d).concat(xs.filter((x) => !x.d));
  };
  return parte(pendentes(L), true).concat(parte(L.next || [], false));
}

// ---------- Próximos jogos (2 por linha) + notícias da liga no espaço que sobra ----------

// Medidas (px). Têm de bater certo com .pj e .nt no base.css.
const LINHA_PJ = 162;            // cartão compacto (150) + espaço entre linhas
const ALTURA_NOTICIA = 172;      // uma notícia (imagem 150) + espaço
const CABECALHO_NOTICIAS = 76;   // subtítulo "Notícias"
const MIN_NOTICIAS = 3;          // se houver notícias, mostram-se pelo menos estas
const MAX_NOTICIAS = 6;

// ---------- Probabilidades do ClubElo (tools/atualizar_elo.py) ----------
// As previsões do ClubElo, quando as há; senão, calculadas a partir do Elo: o resultado esperado da casa
// (We = 1 / (1 + 10^(-(Elo casa + FATOR_CASA - Elo fora) / 400))) e o empate pela curva que mais se aproxima das
// previsões do ClubElo (29% entre equipas iguais, menos quando uma é muito melhor).
const FATOR_CASA = 60;   // pontos de Elo de jogar em casa
export function probabilidades(D, m) {
  const E = D.elo;
  if (!E) return null;
  const dele = (E.previsoes || {})[`${m.home}-${m.away}`];
  if (dele) return { p: dele, fonte: 'ClubElo' };
  const a = (E.porSigla || {})[m.home], b = (E.porSigla || {})[m.away];
  if (a == null || b == null) return null;
  const we = 1 / (1 + 10 ** (-(a + FATOR_CASA - b) / 400));
  const pX = 0.29 * (1 - (2 * we - 1) ** 2);
  const p1 = Math.max(0, we - pX / 2);
  return { p: [p1 * 100, pX * 100, Math.max(0, 100 - p1 * 100 - pX * 100)], fonte: 'Elo' };
}

// Percentagens inteiras que somam sempre 100: normaliza (as do ClubElo vêm a somar 99,9 a 100,1) e arredonda
// pelo maior resto (arredondar cada uma à parte dava 99 ou 101 num jogo em cada cinco).
export function inteirosAte100(valores) {
  const total = valores.reduce((t, v) => t + v, 0) || 1;
  const exatos = valores.map((v) => (v * 100) / total);
  const base = exatos.map(Math.floor);
  let falta = 100 - base.reduce((t, v) => t + v, 0);
  exatos.map((v, i) => [v - base[i], i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (falta-- > 0) base[i] += 1; });
  return base;
}

// Barra das probabilidades por baixo das equipas, só com as percentagens, pela ordem dos nomes no cartão: a da casa
// (em cima) à esquerda, o empate ao meio (cor neutra) e a de fora à direita. Cada parte tem a largura exata da sua
// percentagem; a do favorito vai em destaque. Se o número não couber na parte, fica fora, colado à barra
// (à esquerda o da casa, à direita o de fora).
const LARGURA_BARRA = 440;   // px de uma barra num cartão de meia largura
const PX_LETRA = 10;         // px por letra (16 px de letra) + margens
const cabe = (texto, v) => texto.length * PX_LETRA + 12 <= (v / 100) * LARGURA_BARRA;
function barraProb(D, m, pr) {
  if (!pr) return '';
  const [p1, pX, p2] = inteirosAte100(pr.p);
  const fav = Math.max(p1, p2) > pX ? (p1 >= p2 ? 0 : 2) : 1;
  const nomes = [teamName(D, m.home), 'Empate', teamName(D, m.away)];
  const parte = (v, i) => `<span class="pb${i === 1 ? ' empate' : ''}${i === fav ? ' fav' : ''}" style="flex:${v} 1 0" title="${esc(nomes[i])} ${v}%">${cabe(`${v}%`, v) || i === 1 ? `${v}%` : ''}</span>`;
  const fora = (v, i) => (cabe(`${v}%`, v) ? '' : `<span class="pb-fora${i === fav ? ' fav' : ''}">${v}%</span>`);
  return `<div class="pj-prob">${fora(p1, 0)}<div class="pb-barra">${parte(p1, 0)}${parte(pX, 1)}${parte(p2, 2)}</div>${fora(p2, 2)}</div>`;
}

// Nota com a fonte das probabilidades, por baixo dos próximos jogos
function notaProb(D, jogos) {
  const fontes = new Set(jogos.map((m) => (probabilidades(D, m) || {}).fonte).filter(Boolean));
  if (!fontes.size) return '';
  return `<div class="nota prob-nota">Probabilidades (casa · empate · fora): ${fontes.has('ClubElo') ? 'previsões do ClubElo' : ''}${fontes.size > 1 ? '; ' : ''}${fontes.has('Elo') ? 'calculadas a partir do Elo do ClubElo' : ''}</div>`;
}

// Cartão compacto: as duas equipas em linhas, o dia e a hora à direita e, se houver Elo, a barra 1 X 2 por baixo.
function jogoCompacto(D, m, destaque) {
  const eu = temMinha(D, m) ? ' me' : '';
  const [dia, ...hora] = (m.when || '').split(' ');
  const equipa = (code) => `<div class="pj-eq">${badge(D, code)}<span class="tn">${esc(teamName(D, code))}</span></div>`;
  const prob = m.hs == null && m.status !== 'adiado' ? barraProb(D, m, probabilidades(D, m)) : '';
  // "Destaque" numa fita no canto de cima (por baixo da hora ficava colada à barra 1 X 2)
  return `<div class="pj${eu}${destaque ? ' destaque' : ''}${prob ? ' com-prob' : ''}">${destaque ? '<span class="tag destaque fita">Destaque</span>' : ''}${equipa(m.home)}${equipa(m.away)}
    <div class="pj-quando"><span class="dia">${esc(dia)}${m.date ? ' ' + esc(m.date) : ''}</span><span class="hora">${esc(hora.join(' '))}</span></div>${prob}</div>`;
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
// Com uma jornada a meio (ex.: a Champions entre terça e quarta), o que falta dela vem primeiro, com um subtítulo
// próprio ("Jornada 3 · faltam 9 jogos"), e só depois a jornada seguinte. O que falta da jornada mostra-se sempre todo;
// se não couber tudo, é a seguinte que fica com o "+N jogos".
const CABECALHO_PARTE = 76;      // subtítulo de cada parte (o mesmo tamanho do das notícias)
function cenaProximos(D, chave) {
  const L = D.football[chave];
  const jogos = proximosOrdenados(D, chave);
  const atuais = jogos.filter((x) => x.atual), seguintes = jogos.filter((x) => !x.atual);
  const partes = atuais.length && seguintes.length;
  const noticias = noticiasDaLiga(D, chave);
  const reserva = (noticias.length ? CABECALHO_NOTICIAS + Math.min(MIN_NOTICIAS, noticias.length) * ALTURA_NOTICIA : 0)
    + (partes ? 2 * CABECALHO_PARTE : 0);
  const maxLinhas = Math.max(1, Math.floor((ALTURA_JOGOS - reserva) / LINHA_PJ));
  // Linhas para a jornada seguinte, depois de pôr todos os que faltam da atual
  const linhasAtuais = Math.ceil(atuais.length / 2);
  const cabemSeguintes = Math.max(partes ? 1 : 0, maxLinhas - linhasAtuais) * 2;
  let mostrarSeg = seguintes;
  let resto = 0;
  if (seguintes.length > cabemSeguintes) {
    mostrarSeg = seguintes.slice(0, cabemSeguintes - 1);   // o último lugar fica para o "+N jogos"
    resto = seguintes.length - mostrarSeg.length;
  }
  const mostrar = atuais.concat(mostrarSeg);
  const linhas = linhasAtuais + Math.ceil((mostrarSeg.length + (resto ? 1 : 0)) / 2);
  const livre = ALTURA_JOGOS - linhas * LINHA_PJ - CABECALHO_NOTICIAS - (partes ? 2 * CABECALHO_PARTE : 0);
  const nNoticias = Math.min(MAX_NOTICIAS, noticias.length, Math.max(0, Math.floor(livre / ALTURA_NOTICIA)));
  const grelha = (xs, comResto) => `<div class="pjs">${xs.map((x) => jogoCompacto(D, x.m, x.d)).join('')}` +
    `${comResto && resto ? `<div class="pj mais">+${resto} jogos</div>` : ''}</div>`;
  const ehJornada = L.round && L.round.startsWith('Jornada');
  // Com o que falta da jornada em curso e a seguinte misturados nos próximos, não se diz o número da jornada
  const nomeSeguinte = !L.nextMixed && ehJornada ? nomeJornadaSeguinte(L.round) : 'A seguir';
  let corpo;
  if (partes) {
    const falta = `${ehJornada ? L.round : 'Esta jornada'} · ${atuais.length === 1 ? 'falta 1 jogo' : `faltam ${atuais.length} jogos`}`;
    corpo = subtitulo(falta) + grelha(atuais, false) + subtitulo(nomeSeguinte) + grelha(mostrarSeg, true);
  } else {
    corpo = grelha(mostrar, true);
  }
  const jornada = !partes && !atuais.length && nomeSeguinte !== 'A seguir' ? ' · ' + nomeSeguinte : '';
  return titulo(L.name, `Próximos jogos${jornada}`, chave) + corpo +
    notaProb(D, mostrar.map((x) => x.m)) + blocoNoticias(noticias.slice(0, nNoticias), chave);
}

// "Jornada 8" (a última terminada) -> "Jornada 9"
const nomeJornadaSeguinte = (round) => `Jornada ${parseInt(round.replace(/\D/g, ''), 10) + 1}`;

function marcadores(D, lista) {
  const comCaras = temCaras(lista);
  return `<div class="table">${lista.map((s, i) => `
    <div class="row${minha(D, s.team) ? ' me' : ''}"><b class="pos">${i + 1}</b>${badge(D, s.team)}${cara(s, comCaras)}
      <span class="name">${esc(s.name)}</span><span class="num big">${s.goals}</span></div>`).join('')}</div>`;
}

// ---------- Taças e seleções (tipo "taca" / "selecoes", de tools/atualizar_futebol.py) ----------

// Resultado compacto (2 por linha, quando a ronda tem muitos jogos): cada equipa na sua linha com os golos à
// direita; quem perdeu fica mais apagado. Por jogar: o dia e a hora; a decorrer: "ao vivo".
function resultadoCompacto(D, m) {
  const eu = temMinha(D, m) ? ' me' : '';
  if (m.hs == null) {   // ainda por jogar (ou adiado) nesta ronda
    if (m.status === 'adiado') return `<div class="pj${eu}">${eqCompacta(D, m.home)}${eqCompacta(D, m.away)}<div class="pj-quando"><span class="dia">adiado</span></div></div>`;
    return jogoCompacto(D, m, false);
  }
  // Vencedor: pelo resultado ou, empatado, pelos penáltis ("g.p. 6-5")
  const pen = /g\.p\. (\d+)-(\d+)/.exec(m.nota || '');
  const [ph, pa] = pen ? [Number(pen[1]), Number(pen[2])] : [m.hs, m.as];
  const perdeu = (lado) => !m.live && (lado === 'h' ? (m.hs < m.as || (m.hs === m.as && ph < pa)) : (m.as < m.hs || (m.hs === m.as && pa < ph)));
  const linha = (code, golos, lado) => `<div class="pr-eq${perdeu(lado) ? ' perdeu' : ''}">${badge(D, code)}<span class="tn">${esc(teamName(D, code))}</span><b>${golos}</b></div>`;
  const nota = m.live ? `<span class="pr-nota ao-vivo">ao vivo${m.clock ? ' · ' + esc(m.clock) : ''}</span>`
    : m.nota ? `<span class="pr-nota">${esc(m.nota)}</span>` : '';
  return `<div class="pr${eu}">${linha(m.home, m.hs, 'h')}${linha(m.away, m.as, 'a')}${nota}</div>`;
}
const eqCompacta = (D, code) => `<div class="pj-eq">${badge(D, code)}<span class="tn">${esc(teamName(D, code))}</span></div>`;

// Os jogos das equipas em destaque primeiro, os outros pela ordem do calendário
const destaquesPrimeiro = (D, lista) => lista.filter((m) => temMinha(D, m)).concat(lista.filter((m) => !temMinha(D, m)));

const ALTURA_DETALHE = 190;   // px mínimos de um resultado com os marcadores (senão passa a compacto, 2 por linha)
const MAX_PROXIMOS_TACA = 8;  // jogos seguintes no ecrã da fase (o resto fica em "+N jogos")

// Páginas do ecrã da fase. Os resultados compactos (2 por linha) encolhem até ALTURA_MIN_CARTAO para caberem
// num só ecrã (os 27 jogos da 3.ª eliminatória da Taça cabem); só se nem assim couberem é que se parte, em
// páginas iguais. Os jogos seguintes vão na 1.ª página e as notícias da competição no espaço que sobrar de
// cada página (notícias diferentes em cada uma).
const ALTURA_MIN_CARTAO = 128;   // px: abaixo disto os nomes deixam de se ler bem a 2-3 metros
const ESPACO_CARTOES = 12;       // px entre linhas (o "gap" do .pjs)
function alturaCartao(linhas, livre) {
  return Math.min(LINHA_PJ - ESPACO_CARTOES, Math.floor((livre - (linhas - 1) * ESPACO_CARTOES) / Math.max(1, linhas)));
}

// modo: "resultados" (a ronda toda, os jogos por jogar no seu lugar), "proximos" (o que falta da ronda e a ronda
// seguinte) ou nada (as duas coisas no mesmo ecrã)
function paginasTaca(D, L, chave, modo) {
  const res = modo === 'proximos' ? [] : destaquesPrimeiro(D, L.results || []);
  // O que falta da eliminatória em curso primeiro, e só depois a seguinte (cada parte com os destaques primeiro)
  const prox = modo === 'resultados' ? [] : destaquesPrimeiro(D, modo === 'proximos' ? pendentes(L) : []).concat(destaquesPrimeiro(D, L.next || []));
  const maxProx = res.length ? MAX_PROXIMOS_TACA : 2 * Math.floor(ALTURA_JOGOS / LINHA_PJ);
  const nProx = prox.length > maxProx ? maxProx - 1 : prox.length;
  const altProx = prox.length ? (res.length ? CABECALHO_NOTICIAS : 0) + Math.ceil((nProx + (prox.length > nProx ? 1 : 0)) / 2) * LINHA_PJ : 0;
  const livre1 = ALTURA_JOGOS - altProx;
  let paginas;
  if (!res.length) {
    paginas = [{ res: [], prox, nProx, usado: altProx }];
  } else if (res.length * ALTURA_DETALHE <= livre1) {
    const fatia = Math.min(ALTURA_MAX_JOGO, Math.floor(livre1 / res.length));
    paginas = [{ res, prox, nProx, detalhe: fatia, usado: fatia * res.length + altProx }];
  } else {
    const linhas = Math.ceil(res.length / 2);
    const h1 = alturaCartao(linhas, livre1);
    if (h1 >= ALTURA_MIN_CARTAO) {   // cabe tudo num ecrã
      paginas = [{ res, prox, nProx, cartao: h1, usado: linhas * (h1 + ESPACO_CARTOES) + altProx }];
    } else {   // páginas iguais (os jogos seguintes vão na 1.ª)
      const porPag = 2 * Math.floor((ALTURA_JOGOS + ESPACO_CARTOES) / (ALTURA_MIN_CARTAO + ESPACO_CARTOES));
      const n = Math.ceil((res.length + (prox.length ? Math.ceil(altProx / LINHA_PJ) * 2 : 0)) / porPag);
      const tam = 2 * Math.ceil(res.length / n / 2);
      paginas = [];
      for (let i = 0; i < res.length; i += tam) {
        const r = res.slice(i, i + tam), primeira = i === 0;
        const livre = primeira ? livre1 : ALTURA_JOGOS;
        const h = Math.max(ALTURA_MIN_CARTAO, alturaCartao(Math.ceil(tam / 2), livre));
        paginas.push({ res: r, prox: primeira ? prox : [], nProx: primeira ? nProx : 0, cartao: h,
                       usado: Math.ceil(r.length / 2) * (h + ESPACO_CARTOES) + (primeira ? altProx : 0) });
      }
    }
  }
  // Notícias: no espaço que sobrar de cada página, sem repetir
  const noticias = noticiasDaLiga(D, chave);
  let usadas = 0;
  for (const pg of paginas) {
    const cabem = Math.floor((ALTURA_JOGOS - pg.usado - CABECALHO_NOTICIAS) / ALTURA_NOTICIA);
    const n = Math.max(0, Math.min(MAX_NOTICIAS, noticias.length - usadas, cabem));
    pg.noticias = noticias.slice(usadas, usadas + n);
    usadas += n;
  }
  return paginas;
}

function cenaTaca(D, chave, k, modo) {
  const L = D.football[chave];
  const paginas = paginasTaca(D, L, chave, modo);
  const p = paginas[k] || paginas[0];
  const emCurso = L.partial ? ` · ${L.partial.done} de ${L.partial.total} jogos` : '';
  // nos próximos jogos: a fase do que falta da ronda em curso, a da ronda seguinte, ou nenhuma se forem as duas
  const falta = modo === 'proximos' && pendentes(L).length;
  const faseProx = falta ? ((L.next || []).length ? '' : L.fase) : L.proxFase;
  const sub = p.res.length ? `Resultados · ${L.fase || ''}${emCurso}` : `Próximos jogos${faseProx ? ' · ' + faseProx : ''}`;
  let html = titulo(L.name, sub + sufixoPagina(k, paginas.length), chave);
  if (p.detalhe) {
    html += `<div class="mresults" style="--n:${p.res.length};--slot:${p.detalhe}px">${p.res.map((m) => jogoDetalhe(D, m, p.detalhe)).join('')}</div>`;
  } else if (p.res.length) {
    html += `<div class="pjs${p.cartao < LINHA_PJ - ESPACO_CARTOES ? ' denso' : ''}" style="grid-auto-rows:${p.cartao}px">${p.res.map((m) => resultadoCompacto(D, m)).join('')}</div>`;
  }
  if (p.prox.length) {
    const mostrar = p.prox.slice(0, p.nProx);
    const resto = p.prox.length - mostrar.length;
    const titulo2 = p.res.length ? subtitulo(`Próximos jogos${faseProx ? ' · ' + faseProx : ''}`) : '';
    html += `<section class="taca-prox">${titulo2}<div class="pjs">${mostrar.map((m) => jogoCompacto(D, m, temMinha(D, m))).join('')}` +
      `${resto ? `<div class="pj mais">+${resto} jogos</div>` : ''}</div>${notaProb(D, mostrar)}</section>`;
  }
  if (p.noticias.length) html += blocoNoticias(p.noticias, chave);
  return html;
}

// Tabelas dos grupos (Liga das Nações: Liga A; qualificações; fases finais): 2 por linha, o de Portugal primeiro
const GRUPOS_POR_PAGINA = 8;
function paginasGrupos(L) {
  const g = L.grupos || [];
  const paginas = [];
  for (let i = 0; i < g.length; i += GRUPOS_POR_PAGINA) paginas.push(g.slice(i, i + GRUPOS_POR_PAGINA));
  return paginas;
}

function cenaGrupos(D, chave, k) {
  const L = D.football[chave];
  const paginas = paginasGrupos(L);
  const fase = (L.fase || L.proxFase || '').split(' · ')[0];
  const cab = '<div class="row head"><b class="pos"></b><span class="name"></span><span class="num">J</span><span class="num">DG</span><span class="num pts">PTS</span></div>';
  const grupo = (g) => `<section class="block tight grupo">${subtitulo(g.name)}<div class="table">${cab}${g.table.map((r, i) =>
    linhaTabela(D, r.team, i + 1, [{ v: r.j }, { v: r.dg > 0 ? '+' + r.dg : r.dg }, { v: r.pts, cls: 'pts' }])).join('')}</div></section>`;
  return titulo(L.name, `Classificação${fase ? ' · ' + fase : ''}${sufixoPagina(k, paginas.length)}`, chave) +
    `<div class="grupos-grelha">${(paginas[k] || []).map(grupo).join('')}</div>`;
}

// ---------- Que competições entram na rotação ----------

// Só as que jogam nesta semana: com um jogo acabado (ou a decorrer) nos últimos 4 dias, ou um jogo nos próximos 7.
// As datas vêm de "janela" (atualizar_futebol.py); sem ela (mock.json) entra sempre.
// Por categoria: na "Última jornada" entram as que tiveram jogos nos últimos 7 dias; na "Próxima jornada" as que
// têm jogos nos próximos 7. Sem categoria, qualquer das duas.
const DIAS_DEPOIS = 7, DIAS_ULTIMA = 7;
export function competicaoAtiva(L, fase) {
  if (!L || !L.janela) return !!L;
  const t = agora(), dia = 86400e3;
  const { ultimo, proximo } = L.janela;
  const antes = (dias) => ultimo != null && t - Date.parse(ultimo) <= dias * dia && Date.parse(ultimo) <= t + dia;
  const depois = proximo != null && Date.parse(proximo) - t <= DIAS_DEPOIS * dia && Date.parse(proximo) >= t - dia;
  if (fase === 'ultima') return antes(DIAS_ULTIMA);
  if (fase === 'proxima') return depois;   // (o que falta da jornada em curso também conta: está em proximo)
  return antes(DIAS_ULTIMA) || depois;
}

const eLiga = (L) => !L.tipo || L.tipo === 'liga';
const ativas = (D, fase) => Object.keys(D.football || {}).filter((k) => competicaoAtiva(D.football[k], fase));

// Marcadores: as ligas da rotação, 2 por linha, top 3 de cada uma
const comMarcadores = (D, fase) => ativas(D, fase).filter((k) => eLiga(D.football[k]) && (D.football[k].scorers || []).length);
function cenaMarcadores(D, fase) {
  const com = comMarcadores(D, fase);
  return titulo('Marcadores', 'Golos esta época') +
    `<div class="golos-grelha" style="--linhas:${Math.ceil(com.length / 2)}">` +
    com.map((k) =>
      `<section class="block tight league-${k}">${subtitulo(D.football[k].name, k)}${marcadores(D, D.football[k].scorers)}</section>`).join('') +
    '</div>';
}

// ---------- Ranking Elo da Europa (ClubElo): o top 10 e, por baixo, os clubes portugueses ----------
const NOMES_PAISES = { ENG: 'Inglaterra', ESP: 'Espanha', GER: 'Alemanha', ITA: 'Itália', FRA: 'França', POR: 'Portugal',
  NED: 'Países Baixos', BEL: 'Bélgica', TUR: 'Turquia', SCO: 'Escócia', AUT: 'Áustria', GRE: 'Grécia', CZE: 'Chéquia' };
function cenaElo(D) {
  const E = D.elo;
  const [a, m, d] = (E.data || '').split('-');
  const linha = (c) => {
    const nome = c.sigla ? teamName(D, c.sigla) : c.club;
    return `<div class="row${c.sigla && minha(D, c.sigla) ? ' me' : ''}"><b class="pos">${c.posEuropa}</b>${c.sigla ? badge(D, c.sigla) : '<span class="badge vazio"></span>'}
      <span class="name">${esc(nome)}<small class="pais">${esc(NOMES_PAISES[c.country] || c.country)}</small></span><span class="num pts">${c.elo}</span></div>`;
  };
  const top = E.ranking.filter((c) => c.posEuropa <= 10), pt = E.ranking.filter((c) => c.posEuropa > 10);
  return titulo('Ranking Elo', `Europa · ClubElo${d ? ` · ${d}/${m}` : ''}`) +
    `<div class="table elo">${top.map(linha).join('')}</div>` +
    (pt.length ? `${subtitulo('Portugal')}<div class="table elo">${pt.map(linha).join('')}</div>` : '') +
    `<div class="nota">Força dos clubes pelo sistema Elo (clubelo.com): sobe com as vitórias, mais contra adversários fortes. Posição entre os clubes europeus.</div>`;
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

// Todas as cenas de futebol, pela ordem da rotação (a ordem das competições no live.json, que é a de
// tools/competicoes.py), só das competições que jogam nesta semana (competicaoAtiva).
// fase "ultima" (Última jornada): por competição, os resultados (a jornada toda), o 11, a classificação e os grupos;
//   no fim, os marcadores.
// fase "proxima" (Próxima jornada): os próximos jogos (com o que falta da jornada em curso); no fim, o ranking Elo.
// Sem fase: tudo junto (as duas).
export function cenasFutebol(D, fase) {
  const cenas = [];
  const add = (id, chave, render) => cenas.push({ id, sport: 'football', league: chave, parte: 'futebol', render });
  const ultima = fase !== 'proxima', proxima = fase !== 'ultima';
  // soTabela: a Liga Europa e a Conferência não mostram os resultados nem os próximos jogos por agora (a fase de
  // liga tem 18 jogos e pouco interesse); voltam a ser avaliadas nas eliminatórias.
  const liga = (chave, soTabela) => {
    const L = D.football[chave];
    if (ultima && !soTabela && (L.results || []).length) {
      const nj = paginarJogos(L.results).length;
      for (let k = 0; k < nj; k++) add(`${chave}-jogos${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaJogos(d, chave, k));
      if (L.onze && (L.onze.players || []).length === 11) add(`${chave}-onze`, chave, (d) => cenaOnze(d, chave));
    }
    if (ultima && (L.table || []).length) {
      const nt = paginasTabela(L).length;
      for (let k = 0; k < nt; k++) add(`${chave}-tabela${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaTabela(d, chave, k));
    }
    if (proxima && !soTabela && (pendentes(L).length || (L.next || []).length)) add(`${chave}-proximos`, chave, (d) => cenaProximos(d, chave));
  };
  const taca = (chave) => {
    const L = D.football[chave];
    // Sem fase: o ecrã com as duas coisas. Com fase: os resultados ou os próximos jogos
    const modo = fase === 'ultima' ? 'resultados' : fase === 'proxima' ? 'proximos' : undefined;
    const temJogos = modo === 'resultados' ? (L.results || []).length
      : modo === 'proximos' ? pendentes(L).length + (L.next || []).length : (L.results || []).length + (L.next || []).length;
    if (temJogos) {
      const sufixo = modo === 'proximos' ? '-proximos' : '-jogos';
      const np = paginasTaca(D, L, chave, modo).length;
      for (let k = 0; k < np; k++) add(`${chave}${sufixo}${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaTaca(d, chave, k, modo));
    }
    if (ultima) {
      const ng = paginasGrupos(L).length;
      for (let k = 0; k < ng; k++) add(`${chave}-grupos${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaGrupos(d, chave, k));
    }
  };
  for (const chave of ativas(D, fase)) {
    if (eLiga(D.football[chave])) liga(chave, chave === 'uel' || chave === 'uecl');
    else taca(chave);
  }
  if (ultima) cenas.push({ id: 'golos', sport: 'football', parte: 'futebol', tem: (d) => comMarcadores(d, fase).length > 0, render: (d) => cenaMarcadores(d, fase) });
  if (proxima) cenas.push({ id: 'elo', sport: 'football', league: 'elo', parte: 'elo', tem: (d) => !!(d.elo && (d.elo.ranking || []).length), render: (d) => cenaElo(d) });
  return cenas;
}
