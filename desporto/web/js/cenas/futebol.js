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
  const eu = temMinha(D, m) ? ' me' : '';
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

// Páginas do ecrã da fase: a 1.ª tem os jogos seguintes por baixo dos resultados; as outras, só resultados.
function paginasTaca(D, L) {
  const res = destaquesPrimeiro(D, L.results || []);
  const prox = destaquesPrimeiro(D, L.next || []);
  const nProx = prox.length > MAX_PROXIMOS_TACA ? MAX_PROXIMOS_TACA - 1 : prox.length;
  const altProx = prox.length ? CABECALHO_NOTICIAS + Math.ceil((nProx + (prox.length > nProx ? 1 : 0)) / 2) * LINHA_PJ : 0;
  const livre1 = ALTURA_JOGOS - altProx;
  if (!res.length) return [{ res: [], prox, nProx, livre: livre1 }];
  if (res.length * ALTURA_DETALHE <= livre1) return [{ res, prox, nProx, detalhe: true, livre: livre1 }];
  // Quantas páginas são precisas e, depois, os jogos repartidos por igual (27 jogos: 14 + 13, e não 26 + 1)
  const porPag1 = Math.max(2, Math.floor(livre1 / LINHA_PJ) * 2);
  const porPag = Math.floor(ALTURA_JOGOS / LINHA_PJ) * 2;
  const n = 1 + Math.ceil(Math.max(0, res.length - porPag1) / porPag);
  const tam = Math.min(porPag1, Math.ceil(res.length / n));
  const paginas = [{ res: res.slice(0, tam), prox, nProx, livre: livre1 }];
  const tamOutras = Math.ceil((res.length - tam) / Math.max(1, n - 1));
  for (let i = tam; i < res.length; i += tamOutras) paginas.push({ res: res.slice(i, i + tamOutras), prox: [], nProx: 0, livre: ALTURA_JOGOS });
  return paginas;
}

function cenaTaca(D, chave, k) {
  const L = D.football[chave];
  const paginas = paginasTaca(D, L);
  const p = paginas[k] || paginas[0];
  const emCurso = L.partial ? ` · ${L.partial.done} de ${L.partial.total} jogos` : '';
  const sub = p.res.length ? `Resultados · ${L.fase || ''}${emCurso}` : `Próximos jogos${L.proxFase ? ' · ' + L.proxFase : ''}`;
  let html = titulo(L.name, sub + sufixoPagina(k, paginas.length), chave);
  let usado = 0;
  if (p.detalhe) {
    const fatia = Math.min(ALTURA_MAX_JOGO, Math.floor(p.livre / p.res.length));
    html += `<div class="mresults" style="--n:${p.res.length};--slot:${fatia}px">${p.res.map((m) => jogoDetalhe(D, m, fatia)).join('')}</div>`;
    usado = fatia * p.res.length;
  } else if (p.res.length) {
    html += `<div class="pjs">${p.res.map((m) => resultadoCompacto(D, m)).join('')}</div>`;
    usado = Math.ceil(p.res.length / 2) * LINHA_PJ;
  }
  if (p.prox.length) {
    const mostrar = p.prox.slice(0, p.nProx);
    const resto = p.prox.length - mostrar.length;
    const titulo2 = p.res.length ? subtitulo(`Próximos jogos${L.proxFase ? ' · ' + L.proxFase : ''}`) : '';
    html += `<section class="taca-prox">${titulo2}<div class="pjs">${mostrar.map((m) => jogoCompacto(D, m, temMinha(D, m))).join('')}` +
      `${resto ? `<div class="pj mais">+${resto} jogos</div>` : ''}</div></section>`;
    usado += (p.res.length ? CABECALHO_NOTICIAS : 0) + Math.ceil((mostrar.length + (resto ? 1 : 0)) / 2) * LINHA_PJ;
  }
  // Notícias da competição no espaço que sobra (só na 1.ª página)
  if (k === 0) {
    const n = Math.min(MAX_NOTICIAS, noticiasDaLiga(D, chave).length, Math.floor((ALTURA_JOGOS - usado - CABECALHO_NOTICIAS) / ALTURA_NOTICIA));
    if (n > 0) html += blocoNoticias(noticiasDaLiga(D, chave).slice(0, n), chave);
  }
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
const DIAS_ANTES = 4, DIAS_DEPOIS = 7;
export function competicaoAtiva(L) {
  if (!L || !L.janela) return !!L;
  const t = agora(), dia = 86400e3;
  const { ultimo, proximo } = L.janela;
  return (ultimo != null && t - Date.parse(ultimo) <= DIAS_ANTES * dia && Date.parse(ultimo) <= t + dia)
    || (proximo != null && Date.parse(proximo) - t <= DIAS_DEPOIS * dia && Date.parse(proximo) >= t - dia);
}

const eLiga = (L) => !L.tipo || L.tipo === 'liga';
const ativas = (D) => Object.keys(D.football || {}).filter((k) => competicaoAtiva(D.football[k]));

// Marcadores: as ligas da rotação, 2 por linha, top 3 de cada uma
const comMarcadores = (D) => ativas(D).filter((k) => eLiga(D.football[k]) && (D.football[k].scorers || []).length);
function cenaMarcadores(D) {
  const com = comMarcadores(D);
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

// Todas as cenas de futebol, pela ordem da rotação (a ordem das competições no live.json, que é a de
// tools/competicoes.py), só das competições que jogam nesta semana (competicaoAtiva).
// Ligas: resultados (várias páginas), melhor 11, classificação e próximos jogos. Taças e seleções: o ecrã da fase
// e as tabelas dos grupos. No fim, os marcadores.
export function cenasFutebol(D) {
  const cenas = [];
  const add = (id, chave, render) => cenas.push({ id, sport: 'football', league: chave, parte: 'futebol', render });
  // soTabela: a Liga Europa e a Conferência não mostram os resultados nem os próximos jogos por agora (a fase de
  // liga tem 18 jogos e pouco interesse); voltam a ser avaliadas nas eliminatórias.
  const liga = (chave, soTabela) => {
    const L = D.football[chave];
    if (!soTabela && (L.results || []).length) {
      const nj = paginarJogos(L.results).length;
      for (let k = 0; k < nj; k++) add(`${chave}-jogos${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaJogos(d, chave, k));
      if (L.onze && (L.onze.players || []).length === 11) add(`${chave}-onze`, chave, (d) => cenaOnze(d, chave));
    }
    if ((L.table || []).length) {
      const nt = paginasTabela(L).length;
      for (let k = 0; k < nt; k++) add(`${chave}-tabela${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaTabela(d, chave, k));
    }
    if (!soTabela && (L.next || []).length) add(`${chave}-proximos`, chave, (d) => cenaProximos(d, chave));
  };
  const taca = (chave) => {
    const L = D.football[chave];
    if ((L.results || []).length || (L.next || []).length) {
      const np = paginasTaca(D, L).length;
      for (let k = 0; k < np; k++) add(`${chave}-jogos${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaTaca(d, chave, k));
    }
    const ng = paginasGrupos(L).length;
    for (let k = 0; k < ng; k++) add(`${chave}-grupos${k ? '-' + (k + 1) : ''}`, chave, (d) => cenaGrupos(d, chave, k));
  };
  for (const chave of ativas(D)) {
    if (eLiga(D.football[chave])) liga(chave, chave === 'uel' || chave === 'uecl');
    else taca(chave);
  }
  cenas.push({ id: 'golos', sport: 'football', parte: 'futebol', tem: (d) => comMarcadores(d).length > 0, render: (d) => cenaMarcadores(d) });
  return cenas;
}
