// Ao vivo (?cat=aovivo): o "presente". Em vez da rotação de cenas, duas vistas comandadas pelo telemóvel:
//   lista          os jogos a decorrer agora nas competições ligadas e os que começam daqui a 10 min ou menos
//                  ("Aquecimento", sem resultado; passam a ao vivo quando a ESPN os der como começados) (GET /api/aovivo, ver tools/aovivo.py),
//                  por competição. ▲▼ mudam o foco, OK marca/desmarca "seguir", ▶ (ou OK em "Acompanhar") abre
//                  o acompanhamento; ↩ volta ao menu do hub. Os jogos do FC Porto e de Portugal vêm marcados.
//   acompanhamento os jogos seguidos: em cima o mapa do continente com os estádios (mapa.js), quando estão todos no
//                  mesmo (Europa, América do Norte ou do Sul); por baixo os cartões, 2 por linha e até 6 por página.
//                  Com mais jogos, as páginas trocam sozinhas a cada 10 s (◀▶ também trocam). ↩ volta à lista.
// Acontecimentos: a cada resposta comparam-se os acontecimentos de cada jogo de futebol seguido com os da anterior
// (golos, penáltis, autogolos, penáltis falhados, vermelhos). Os novos entram numa fila, pela ordem em que chegam,
// sem preferência por equipa. Cada um: com mapa e o OSM do estádio, o voo até ao estádio e o destaque
// (mapa.acontecimento); sem mapa ou sem o OSM, só o destaque, sem zoom. O cartão do jogo brilha entretanto.
// Estádios: só os que já estão preparados (o Ao vivo nunca descarrega nada). Um jogo sem coordenadas fica só no
// cartão e não conta para o continente do mapa; sem nenhum com coordenadas, só cartões. O que falta vê-se na
// página /definicoes, não aqui. Com mais de 3 à espera, cada um fica menos tempo.
// Pergunta ao servidor a cada 30 s, só enquanto está aberto (o hub fecha o iframe ao sair). Não mexe no live.json.
// ?simular=1: os jogos de ontem a fingir que estão a decorrer (ver tools/aovivo.py), perguntando a cada 10 s.
//   Só com ele: &seguir=futebol6,nba (os primeiros 6 de futebol e todos da NBA; ou ids), &vista=seguir (abre logo o
//   acompanhamento), &aquecimento=<siglas> (esses jogos em "Aquecimento", que começam aos 40 s; por omissão, o
//   primeiro de futebol), &golo=<sigla> (a equipa do golo inventado aos 10 s) e &semruas= / &semestadio=<siglas> (esses
//   jogos como se o estádio não tivesse o OSM / as coordenadas).
import { esc, badge, teamName } from './util.js';
import { titulo, subtitulo } from './cenas/base.js';
import { evento } from './cenas/futebol.js';
import { fundo } from './backgrounds.js';
import { criarMapa, continente, temLugar } from './mapa.js';

const PARAMS = new URLSearchParams(location.search);
const SIMULAR = PARAMS.get('simular') === '1';
const PERGUNTAR_MS = SIMULAR ? 10_000 : 30_000;
const POR_PAGINA = 6;
const PAGINA_MS = 10_000;
const SEGURAR_MS = 5000, SEGURAR_CURTO_MS = 3000, FILA_LONGA = 3;   // destaque: 5 s, ou 3 s com mais de 3 à espera
const GUARDAR = 'aovivo.seguir';   // jogos seguidos e desmarcados (só neste browser; serve para não os perder ao recarregar)
const TECLAS = { ArrowUp: 'cima', ArrowDown: 'baixo', ArrowLeft: 'esquerda', ArrowRight: 'direita', Enter: 'ok', Escape: 'voltar', Backspace: 'voltar' };
const ACOES = { lista: ['cima', 'baixo', 'ok', 'direita', 'voltar'], seguir: ['esquerda', 'direita', 'voltar'] };
const TIPOS = { golo: '⚽ GOLO', pen: '⚽ PENÁLTI', og: '⚽ AUTOGOLO', pen_miss: '❌ PENÁLTI FALHADO', red: '🟥 VERMELHO' };
const NO_SUB = { golo: 'Golo', pen: 'Penálti', og: 'Autogolo', pen_miss: 'Penálti falhado', red: 'Vermelho' };

const emHub = window.parent !== window;
const hub = (m) => { if (emHub) window.parent.postMessage({ monitorhub: 1, ...m }, '*'); };
const T0 = Date.now();

function ler() {
  try { return JSON.parse(localStorage.getItem(GUARDAR)) || {}; } catch { return {}; }
}
function guardar(seguidos, desmarcados) {
  if (SIMULAR && PARAMS.get('seguir')) return;   // escolha do URL de teste: não fica guardada
  try { localStorage.setItem(GUARDAR, JSON.stringify({ seguidos: [...seguidos], desmarcados: [...desmarcados] })); } catch { /* sem armazenamento: fica só nesta sessão */ }
}

// "45+2" -> 45.02 (para ordenar os acontecimentos)
const minutoNum = (m) => { const [a, b] = String(m).split('+'); return (parseInt(a, 10) || 0) + (parseInt(b, 10) || 0) / 100; };
const tipo = (e) => e.t || 'golo';
const chaveEv = (e) => `${tipo(e)}|${e.s}|${e.m}|${e.pid || e.p}`;
const conta = (e) => ['golo', 'pen', 'og'].includes(tipo(e));

// O resultado logo depois deste acontecimento (os golos até ele, inclusive)
function placarAte(j, ev) {
  const ord = [...(j.ev || [])].sort((a, b) => minutoNum(a.m) - minutoNum(b.m));
  const ate = ord.slice(0, ord.indexOf(ev) + 1).filter(conta);
  const para = (e) => (tipo(e) === 'og' ? (e.s === 'h' ? 'a' : 'h') : e.s);
  return { hs: ate.filter((e) => para(e) === 'h').length, as: ate.filter((e) => para(e) === 'a').length };
}

// A cara de quem foi (o servidor procura na cache das fotos, no facepack e na ESPN); null se não houver
async function cara(j, ev) {
  if (!ev.pn && !ev.pid) return null;
  try {
    const q = new URLSearchParams({ pid: ev.pid || '', nome: ev.pn || ev.p, sigla: ev.s === 'h' ? j.home : j.away });
    const r = await fetch(`/api/aovivo/cara?${q}`, { cache: 'no-store' });
    const url = (await r.json()).url;
    if (!url) return null;
    await new Promise((ok) => { const img = new Image(); img.onload = img.onerror = ok; img.src = url; });   // já carregada quando aparece
    return url;
  } catch { return null; }
}

export function iniciarAoVivo({ host, getData }) {
  const guardado = ler();
  const seguidos = new Set(guardado.seguidos || []);
  const desmarcados = new Set(guardado.desmarcados || []);   // jogos "meus" que se desmarcaram (não voltam a marcar-se)
  let resposta = { jogos: [], proximo: null, teams: {} };
  let vista = SIMULAR && PARAMS.get('vista') === 'seguir' ? 'seguir' : 'lista';
  let foco = 0, pagina = 0, primeira = true;
  const vistos = {};       // id -> chaves dos acontecimentos já vistos (para dar pelos novos)
  const fila = [];         // acontecimentos à espera: { id, ev }
  let atual = null;        // o acontecimento a mostrar agora: { id, ev }
  let ui = null;           // o acompanhamento montado: { regiao, mapa, grelha }
  let tPagina = null;

  // Os emblemas e os nomes: os do live.json, mais os das equipas que só aparecem no Ao vivo
  const D = () => { const d = getData(); return { ...d, teams: { ...resposta.teams, ...d.teams } }; };
  const jogos = () => resposta.jogos || [];
  const jogo = (id) => jogos().find((j) => j.id === id);
  const listaSeguidos = () => jogos().filter((j) => seguidos.has(j.id));
  // Itens da lista: os jogos e, no fim, "Acompanhar"
  const itens = () => [...jogos().map((j) => j.id), 'acompanhar'];

  const el = document.createElement('div');
  el.className = 'scene scene-aovivo sport-football';
  host.replaceChildren(el);
  const caixaDestaque = document.createElement('div');
  caixaDestaque.id = 'golo';
  caixaDestaque.hidden = true;
  host.appendChild(caixaDestaque);

  // ---------------------------------------------------------------- desenhar
  // Aquecimento (começa daqui a 10 min ou menos): a hora no lugar do resultado; no cartão, também quanto falta
  // (a hora já passou e a ESPN ainda não o deu como começado: "atrasado")
  const falta = (j) => {
    const min = Math.round((new Date(j.iso) - Date.now()) / 60_000);
    return min >= 1 ? `em ${min} min` : min >= -1 ? 'a começar' : 'atrasado';
  };
  const hora = (j) => new Date(j.iso).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
  const minuto = (j, comFalta = false) => j.estado === 'in'
    ? `<span class="av-min${j.tempo === 'Intervalo' ? ' pausa' : ''}"><i></i>${esc(j.tempo)}</span>`
    : j.estado === 'aquecimento' ? `<span class="av-min aq">Aquecimento${comFalta ? ` · ${falta(j)}` : ''}</span>`
    : `<span class="av-min fim">${esc(j.tempo)}</span>`;
  const resultado = (j) => (j.estado === 'aquecimento' ? `<span class="av-res av-aq">${hora(j)}</span>`
    : j.hs == null ? '<span class="av-res">–</span>' : `<span class="av-res">${j.hs}<i>–</i>${j.as}</span>`);

  function linha(dd, j, i) {
    const marcado = seguidos.has(j.id);
    return `<div class="av-linha${i === foco ? ' foco' : ''}${marcado ? ' seguido' : ''}${j.meu ? ' me' : ''}">
      <span class="av-check">${marcado ? '✓' : ''}</span>
      <span class="av-eq casa"><span class="tn">${esc(teamName(dd, j.home))}</span>${badge(dd, j.home)}</span>
      <span class="av-meio">${resultado(j)}${minuto(j)}</span>
      <span class="av-eq fora">${badge(dd, j.away)}<span class="tn">${esc(teamName(dd, j.away))}</span></span>
    </div>`;
  }

  function desenharLista() {
    desmontar();
    const dd = D();
    const lista = jogos();
    if (!lista.length) {
      const p = resposta.proximo;
      const quando = p && p.iso ? new Date(p.iso) : null;
      const hora = quando ? quando.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' }) : '';
      const dia = quando ? quando.toLocaleDateString('pt-PT', { weekday: 'long', day: 'numeric', month: 'long' }) : '';
      el.innerHTML = fundo('football') + titulo('Ao vivo', 'Jogos a decorrer agora') + `<section class="block construcao">
        <div class="cons-icone">📡</div>
        <div class="cons-titulo">Sem jogos ao vivo</div>
        ${p ? `<div class="cons-data"><span>Próximo jogo · ${esc(p.comp && p.comp.nome || '')}</span>
          <b>${esc(teamName(dd, p.home))} – ${esc(teamName(dd, p.away))}</b>
          <small>${esc(dia)}${hora ? ' · ' + hora : ''}</small></div>` : '<div class="cons-texto">Não há jogos marcados nas competições escolhidas.</div>'}
        ${resposta.erro ? `<div class="cons-texto">${esc(resposta.erro)}</div>` : ''}
      </section>`;
      return;
    }
    // Por competição, pela ordem em que vêm (o servidor ordena por competição e hora)
    let html = '', i = 0, comp = null;
    for (const j of lista) {
      if (j.comp.nome !== comp) {
        if (comp !== null) html += '</div>';
        comp = j.comp.nome;
        html += subtitulo(comp, j.comp.chave) + '<div class="av-grupo">';
      }
      html += linha(dd, j, i++);
    }
    html += '</div>';
    const n = listaSeguidos().length;
    html += `<div class="av-acompanhar${foco === lista.length ? ' foco' : ''}${n ? '' : ' vazio'}">
      ${n ? `Acompanhar ${n === 1 ? '1 jogo' : `${n} jogos`} ▶` : 'Marca jogos com OK para os acompanhar'}</div>`;
    const aq = lista.filter((j) => j.estado === 'aquecimento').length;
    const contagem = aq === lista.length ? `${aq === 1 ? '1 jogo' : `${aq} jogos`} em aquecimento`
      : `${lista.length - aq === 1 ? '1 jogo' : `${lista.length - aq} jogos`} a decorrer${aq ? ` · ${aq} em aquecimento` : ''}`;
    el.innerHTML = fundo('football') + titulo('Ao vivo', `${contagem} · OK marca, ▶ acompanha`) + `<section class="av-lista">${html}</section>`;
    el.querySelector('.av-linha.foco, .av-acompanhar.foco')?.scrollIntoView({ block: 'nearest' });
  }

  function cartao(dd, j) {
    const lado = (s) => (j.ev || []).filter((e) => e.s === s).sort((a, b) => minutoNum(a.m) - minutoNum(b.m));
    const evs = (lista) => `<div class="av-evs">${lista.map(evento).join('')}</div>`;
    const flash = atual && atual.id === j.id ? ' flash' : '';
    return `<article class="av-c${j.sport === 'nba' ? ' nba' : ''}${j.meu ? ' me' : ''}${j.estado === 'post' ? ' terminado' : ''}${j.estado === 'aquecimento' ? ' aquecimento' : ''}${flash}">
      <div class="cab"><b>${esc((j.estadio && j.estadio.nome) || j.comp.nome)}</b>${minuto(j, true)}</div>
      <div class="placar">
        <div class="eq">${badge(dd, j.home)}<span class="tn">${esc(teamName(dd, j.home))}</span></div>
        ${resultado(j)}
        <div class="eq">${badge(dd, j.away)}<span class="tn">${esc(teamName(dd, j.away))}</span></div>
      </div>
      ${(j.ev || []).length ? `<div class="av-acont">${evs(lado('h'))}<span></span>${evs(lado('a'))}</div>` : ''}
    </article>`;
  }

  // O continente do mapa, se todos os jogos seguidos com coordenadas estiverem no mesmo; senão null (só cartões).
  // Os sem coordenadas ficam só nos cartões e não contam.
  function regiaoDoMapa(lista) {
    const regioes = new Set(lista.filter(temLugar).map(continente));
    return regioes.size === 1 && !regioes.has(null) ? [...regioes][0] : null;
  }

  function subSeguir(lista) {
    if (atual) {
      const j = jogo(atual.id);
      return `${NO_SUB[tipo(atual.ev)]} · ${j ? `${teamName(D(), j.home)} – ${teamName(D(), j.away)}` : ''}`;
    }
    const comps = [...new Set(lista.map((j) => j.comp.nome))];
    return `A acompanhar ${lista.length === 1 ? '1 jogo' : `${lista.length} jogos`}${comps.length <= 2 ? ` · ${comps.join(', ')}` : ''}`;
  }

  function desmontar() {
    if (ui && ui.mapa) ui.mapa.destruir();
    ui = null;
  }

  function desenharSeguir() {
    const dd = D();
    const lista = listaSeguidos();
    if (!lista.length) {
      desmontar();
      el.innerHTML = fundo('football') + titulo('Ao vivo', 'A acompanhar · ↩ lista') +
        '<section class="block construcao"><div class="cons-titulo">Nenhum jogo seguido</div><div class="cons-texto">Volta à lista (↩) e marca jogos com OK.</div></section>';
      return;
    }
    const regiao = regiaoDoMapa(lista);
    // Monta o ecrã (mapa + cartões) só quando muda entre "com mapa" e "sem mapa"; durante um acontecimento espera
    if (!ui || (!!ui.regiao !== !!regiao && !atual)) {
      desmontar();
      el.innerHTML = fundo('football') + titulo('Ao vivo', subSeguir(lista)) +
        `<section class="av-grelha-cartoes${regiao ? '' : ' sem-mapa'}"></section>`;
      ui = { regiao, grelha: el.querySelector('.av-grelha-cartoes'), mapa: regiao ? criarMapa(el, { dados: D }) : null };
    }
    if (ui.mapa && regiao) { ui.regiao = regiao; ui.mapa.atualizar(lista, regiao); }
    const sub = el.querySelector('.scene-title small');
    if (sub) sub.textContent = subSeguir(lista);
    const paginas = Math.max(1, Math.ceil(lista.length / POR_PAGINA));
    pagina = ((pagina % paginas) + paginas) % paginas;
    ui.grelha.innerHTML = lista.slice(pagina * POR_PAGINA, (pagina + 1) * POR_PAGINA).map((j) => cartao(dd, j)).join('');
  }

  const desenhar = () => (vista === 'lista' ? desenharLista() : desenharSeguir());

  // As páginas dos cartões trocam sozinhas (a não ser durante um acontecimento: fica a do jogo)
  function reiniciarPaginas() {
    clearInterval(tPagina);
    tPagina = setInterval(() => {
      if (vista !== 'seguir' || atual || listaSeguidos().length <= POR_PAGINA) return;
      pagina++;
      desenharSeguir();
    }, PAGINA_MS);
  }

  // ---------------------------------------------------------------- acontecimentos
  function destaqueHTML(dd, j, ev, foto) {
    const t = tipo(ev);
    const equipa = ev.s === 'h' ? j.home : j.away;
    const quem = foto ? `<img class="cara" src="${esc(foto)}" alt="">` : `<span class="cara sem-cara">${badge(dd, equipa)}</span>`;
    const mudou = t === 'og' ? (ev.s === 'h' ? 'a' : 'h') : conta(ev) ? ev.s : null;
    const p = placarAte(j, ev);
    const n = (lado, v) => (lado === mudou ? `<u>${v}</u>` : v);
    return `<div class="tipo">${TIPOS[t]}</div><div class="quem">${quem}${esc(ev.p)} ${esc(ev.m)}'</div>
      <div class="placar">${badge(dd, j.home)}<span class="res">${n('h', p.hs)}–${n('a', p.as)}</span>${badge(dd, j.away)}</div>`;
  }

  const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));

  async function mostrarAcontecimento({ id, ev }) {
    const j = jogo(id);
    if (!j) return;
    const segurar = fila.length >= FILA_LONGA ? SEGURAR_CURTO_MS : SEGURAR_MS;
    const vermelho = tipo(ev) === 'red' ? ' vermelho' : '';
    const html = cara(j, ev).then((foto) => destaqueHTML(D(), jogo(id) || j, ev, foto));
    // o cartão do jogo brilha (e fica à vista: vai-se para a página dele)
    const lista = listaSeguidos();
    const i = lista.findIndex((x) => x.id === id);
    if (i >= 0) pagina = Math.floor(i / POR_PAGINA);
    if (vista === 'seguir') desenharSeguir();
    // o voo até às ruas só com o OSM do estádio (mapa.acontecimento devolve false sem ele)
    if (vista === 'seguir' && ui && ui.mapa && ui.mapa.tem(id) && j.estadio && j.estadio.osm
        && await ui.mapa.acontecimento(j, { destaque: html, classe: vermelho, segurar })) return;
    // sem mapa, sem o OSM do estádio (ou este jogo não está no mapa): só o destaque, sem o zoom
    caixaDestaque.innerHTML = `<div class="av-destaque${vermelho}">${await html}</div>`;
    caixaDestaque.hidden = false;
    requestAnimationFrame(() => caixaDestaque.firstElementChild?.classList.add('on'));
    await esperar(segurar);
    caixaDestaque.firstElementChild?.classList.remove('on');
    await esperar(500);
    caixaDestaque.hidden = true;
  }

  async function correrFila() {
    if (atual) return;
    while (fila.length) {
      atual = fila.shift();
      try { await mostrarAcontecimento(atual); } catch (e) { console.warn('Acontecimento:', e); }
      atual = null;
      if (vista === 'seguir') desenharSeguir();
    }
  }

  // Os acontecimentos novos de cada jogo de futebol seguido (a primeira vez que se vê um jogo, só se registam)
  function procurarNovos() {
    for (const j of listaSeguidos()) {
      if (j.sport !== 'football') continue;   // NBA: o resultado muda a toda a hora; não há destaques
      const evs = (j.ev || []).filter((e) => TIPOS[tipo(e)]);
      if (!vistos[j.id]) { vistos[j.id] = new Set(evs.map(chaveEv)); continue; }
      const novos = evs.filter((e) => !vistos[j.id].has(chaveEv(e))).sort((a, b) => minutoNum(a.m) - minutoNum(b.m));
      for (const e of novos) { vistos[j.id].add(chaveEv(e)); fila.push({ id: j.id, ev: e }); }
    }
    correrFila();
  }

  // ---------------------------------------------------------------- dados
  async function perguntar() {
    try {
      const q = new URLSearchParams({ seguir: [...seguidos].join(',') });
      if (SIMULAR) {
        q.set('simular', '1');
        q.set('desde', String(Math.round((Date.now() - T0) / 1000)));
        for (const k of ['golo', 'semruas', 'semestadio', 'aquecimento']) if (PARAMS.get(k)) q.set(k, PARAMS.get(k));
      }
      const r = await fetch(`/api/aovivo?${q}`, { cache: 'no-store' });
      resposta = await r.json();
    } catch (e) {
      resposta = { ...resposta, erro: `Sem ligação ao servidor (${e.message})` };
    }
    let mudou = false;
    if (primeira && SIMULAR && PARAMS.get('seguir')) {
      // teste: &seguir=futebol6,nba2 (os primeiros N de cada desporto), ou ids
      seguidos.clear();
      for (const pedido of PARAMS.get('seguir').split(',')) {
        const m = pedido.match(/^(futebol|nba)(\d*)$/);
        const estes = m ? jogos().filter((j) => j.sport === (m[1] === 'nba' ? 'nba' : 'football')).slice(0, m[2] ? +m[2] : undefined) : jogos().filter((j) => j.id === pedido);
        estes.forEach((j) => seguidos.add(j.id));
      }
      primeira = false;
      perguntar();   // outra vez, já com os seguidos (o golo inventado só entra num jogo seguido)
      return;
    }
    primeira = false;
    // Os jogos do FC Porto e de Portugal entram marcados (a não ser que já se tenham desmarcado)
    if (!(SIMULAR && PARAMS.get('seguir'))) {
      for (const j of jogos()) {
        if (j.meu && !desmarcados.has(j.id) && !seguidos.has(j.id)) { seguidos.add(j.id); mudou = true; }
      }
    }
    if (mudou) guardar(seguidos, desmarcados);
    foco = Math.min(foco, itens().length - 1);
    desenhar();
    procurarNovos();
  }

  // ---------------------------------------------------------------- comando
  function anunciar() { hub({ tipo: 'pronto', acoes: ACOES[vista] }); }
  function irPara(v) { vista = v; pagina = 0; anunciar(); desenhar(); reiniciarPaginas(); }

  function alternar(id) {
    if (seguidos.has(id)) { seguidos.delete(id); desmarcados.add(id); }
    else { seguidos.add(id); desmarcados.delete(id); }
    guardar(seguidos, desmarcados);
  }

  function comando(acao) {
    if (vista === 'lista') {
      const n = itens().length;
      if (acao === 'cima' || acao === 'baixo') { foco = (foco + (acao === 'baixo' ? 1 : -1) + n) % n; desenhar(); return; }
      if (acao === 'ok') {
        const id = itens()[foco];
        if (id === 'acompanhar') { if (listaSeguidos().length) irPara('seguir'); return; }
        if (id) { alternar(id); desenhar(); }
        return;
      }
      if (acao === 'direita') { if (listaSeguidos().length) irPara('seguir'); else hub({ tipo: 'aviso', texto: 'Marca um jogo com OK' }); return; }
      if (acao === 'voltar') { hub({ tipo: 'nao_tratado', acao: 'voltar' }); return; }
    } else {
      if (acao === 'esquerda' || acao === 'direita') {
        pagina += acao === 'direita' ? 1 : -1;
        desenharSeguir();
        reiniciarPaginas();
        return;
      }
      if (acao === 'voltar') { irPara('lista'); return; }
    }
    hub({ tipo: 'nao_tratado', acao });
  }

  window.addEventListener('message', (e) => {
    const m = e.data;
    if (emHub && m && m.monitorhub === 1 && m.tipo === 'comando') comando(m.acao);
  });
  window.addEventListener('keydown', (e) => {
    const acao = TECLAS[e.key];
    if (!acao || e.ctrlKey || e.altKey || e.metaKey) return;
    e.preventDefault();
    comando(acao);
  });

  anunciar();
  desenhar();
  perguntar();
  reiniciarPaginas();
  const intervalo = setInterval(perguntar, PERGUNTAR_MS);
  window.addEventListener('pagehide', () => { clearInterval(intervalo); clearInterval(tPagina); });   // ao sair do Ao vivo, deixa de perguntar
}
