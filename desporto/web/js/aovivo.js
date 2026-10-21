// Ao vivo (?cat=aovivo): o "presente". Em vez da rotação de cenas, duas vistas comandadas pelo telemóvel:
//   lista          os jogos a decorrer agora nas competições ligadas (GET /api/aovivo, ver tools/aovivo.py),
//                  por competição. ▲▼ mudam o foco, OK marca/desmarca "seguir", ▶ (ou OK em "Acompanhar") abre
//                  o acompanhamento; ↩ volta ao menu do hub. Os jogos do FC Porto e de Portugal vêm marcados.
//   acompanhamento os jogos seguidos em cartões grandes (até 4 por ecrã; ◀▶ mudam de página), com os acontecimentos.
//                  Quando um resultado muda aparece um destaque ("⚽ GOLO · FC Porto 1–0 · Samu 34'"). ↩ volta à lista.
// Pergunta ao servidor a cada 30 s, só enquanto está aberto (o hub fecha o iframe ao sair). Não mexe no live.json.
// ?simular=1: os jogos de ontem a fingir que estão a decorrer (para testar sem jogos ao vivo).
import { esc, badge, teamName } from './util.js';
import { titulo, subtitulo } from './cenas/base.js';
import { evento } from './cenas/futebol.js';
import { fundo } from './backgrounds.js';

const PERGUNTAR_MS = 30_000;
const POR_PAGINA = 4;
const DESTAQUE_MS = 7000;
const GUARDAR = 'aovivo.seguir';   // jogos seguidos e desmarcados (só neste browser; serve para não os perder ao recarregar)
const SIMULAR = new URLSearchParams(location.search).get('simular') === '1';
const TECLAS = { ArrowUp: 'cima', ArrowDown: 'baixo', ArrowLeft: 'esquerda', ArrowRight: 'direita', Enter: 'ok', Escape: 'voltar', Backspace: 'voltar' };
const ACOES = { lista: ['cima', 'baixo', 'ok', 'direita', 'voltar'], seguir: ['esquerda', 'direita', 'voltar'] };

const emHub = window.parent !== window;
const hub = (m) => { if (emHub) window.parent.postMessage({ monitorhub: 1, ...m }, '*'); };

function ler() {
  try { return JSON.parse(localStorage.getItem(GUARDAR)) || {}; } catch { return {}; }
}
function guardar(seguidos, desmarcados) {
  try { localStorage.setItem(GUARDAR, JSON.stringify({ seguidos: [...seguidos], desmarcados: [...desmarcados] })); } catch { /* sem armazenamento: fica só nesta sessão */ }
}

export function iniciarAoVivo({ host, getData }) {
  const guardado = ler();
  const seguidos = new Set(guardado.seguidos || []);
  const desmarcados = new Set(guardado.desmarcados || []);   // jogos "meus" que se desmarcaram (não voltam a marcar-se)
  let resposta = { jogos: [], proximo: null, teams: {} };
  let vista = 'lista', foco = 0, pagina = 0;
  const anteriores = {};   // id -> "hs-as" da última resposta (para dar pelos golos)
  let tDestaque = null;

  // Os emblemas e os nomes: os do live.json, mais os das equipas que só aparecem no Ao vivo
  const D = () => { const d = getData(); return { ...d, teams: { ...resposta.teams, ...d.teams } }; };
  const jogos = () => resposta.jogos || [];
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
  const minuto = (j) => j.estado === 'in'
    ? `<span class="av-min${j.tempo === 'Intervalo' ? ' pausa' : ''}"><i></i>${esc(j.tempo)}</span>`
    : `<span class="av-min fim">${esc(j.tempo)}</span>`;
  const resultado = (j) => (j.hs == null ? '<span class="av-res">–</span>' : `<span class="av-res">${j.hs}<i>–</i>${j.as}</span>`);

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
    el.innerHTML = fundo('football') + titulo('Ao vivo', `${lista.length === 1 ? '1 jogo' : `${lista.length} jogos`} a decorrer · OK marca, ▶ acompanha`) + `<section class="av-lista">${html}</section>`;
    el.querySelector('.av-linha.foco, .av-acompanhar.foco')?.scrollIntoView({ block: 'nearest' });
  }

  function cartao(dd, j) {
    const lado = (s) => (j.ev || []).filter((e) => e.s === s).sort((a, b) => parseInt(a.m, 10) - parseInt(b.m, 10));
    const evs = (lista) => `<div class="av-evs">${lista.map(evento).join('')}</div>`;
    return `<article class="av-cartao${j.meu ? ' me' : ''}${j.estado === 'post' ? ' terminado' : ''}">
      <div class="av-comp">${esc(j.comp.nome)}</div>
      <div class="av-placar">
        <div class="av-eq casa">${badge(dd, j.home)}<span class="tn">${esc(teamName(dd, j.home))}</span></div>
        <div class="av-meio">${resultado(j)}${minuto(j)}</div>
        <div class="av-eq fora">${badge(dd, j.away)}<span class="tn">${esc(teamName(dd, j.away))}</span></div>
      </div>
      ${(j.ev || []).length ? `<div class="av-acont">${evs(lado('h'))}<span></span>${evs(lado('a'))}</div>` : ''}
    </article>`;
  }

  function desenharSeguir() {
    const dd = D();
    const lista = listaSeguidos();
    const paginas = Math.max(1, Math.ceil(lista.length / POR_PAGINA));
    pagina = Math.min(pagina, paginas - 1);
    const estes = lista.slice(pagina * POR_PAGINA, (pagina + 1) * POR_PAGINA);
    const sub = `A acompanhar ${lista.length === 1 ? '1 jogo' : `${lista.length} jogos`}${paginas > 1 ? ` · ${pagina + 1}/${paginas} (◀▶)` : ''} · ↩ lista`;
    el.innerHTML = fundo('football') + titulo('Ao vivo', sub) +
      (estes.length ? `<section class="av-cartoes n${estes.length}">${estes.map((j) => cartao(dd, j)).join('')}</section>`
        : '<section class="block construcao"><div class="cons-titulo">Nenhum jogo seguido</div><div class="cons-texto">Volta à lista (↩) e marca jogos com OK.</div></section>');
  }

  const desenhar = () => (vista === 'lista' ? desenharLista() : desenharSeguir());

  // ---------------------------------------------------------------- golos
  function destacar(j) {
    const dd = D();
    const golos = (j.ev || []).filter((e) => !['red', 'pen_miss'].includes(e.t));
    const ultimo = golos.sort((a, b) => parseInt(b.m, 10) - parseInt(a.m, 10))[0];
    const quem = ultimo ? ` · ${esc(ultimo.p)} ${esc(ultimo.m)}'` : '';
    caixaDestaque.innerHTML = `<div class="golo-caixa${j.meu ? ' me' : ''}"><b>${j.sport === 'nba' ? '🏀' : '⚽ GOLO'}</b>
      <span>${esc(teamName(dd, j.home))} ${j.hs}–${j.as} ${esc(teamName(dd, j.away))}${quem}</span></div>`;
    caixaDestaque.hidden = false;
    clearTimeout(tDestaque);
    tDestaque = setTimeout(() => { caixaDestaque.hidden = true; }, DESTAQUE_MS);
  }

  // ---------------------------------------------------------------- dados
  async function perguntar() {
    try {
      const q = new URLSearchParams({ seguir: [...seguidos].join(',') });
      if (SIMULAR) q.set('simular', '1');
      const r = await fetch(`/api/aovivo?${q}`, { cache: 'no-store' });
      resposta = await r.json();
    } catch (e) {
      resposta = { ...resposta, erro: `Sem ligação ao servidor (${e.message})` };
    }
    // Os jogos do FC Porto e de Portugal entram marcados (a não ser que já se tenham desmarcado)
    let mudou = false;
    for (const j of jogos()) {
      if (j.meu && !desmarcados.has(j.id) && !seguidos.has(j.id)) { seguidos.add(j.id); mudou = true; }
      // NBA: o resultado muda a toda a hora; só os golos do futebol têm destaque
      const agora = `${j.hs}-${j.as}`;
      if (j.sport === 'football' && seguidos.has(j.id) && anteriores[j.id] && anteriores[j.id] !== agora && j.hs != null) destacar(j);
      anteriores[j.id] = agora;
    }
    if (mudou) guardar(seguidos, desmarcados);
    foco = Math.min(foco, itens().length - 1);
    desenhar();
  }

  // ---------------------------------------------------------------- comando
  function anunciar() { hub({ tipo: 'pronto', acoes: ACOES[vista] }); }
  function irPara(v) { vista = v; pagina = 0; anunciar(); desenhar(); }

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
        const paginas = Math.max(1, Math.ceil(listaSeguidos().length / POR_PAGINA));
        pagina = (pagina + (acao === 'direita' ? 1 : -1) + paginas) % paginas;
        desenhar();
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
  const intervalo = setInterval(perguntar, PERGUNTAR_MS);
  window.addEventListener('pagehide', () => clearInterval(intervalo));   // ao sair do Ao vivo, deixa de perguntar
}
