// Peças partilhadas pelas cenas (títulos, logótipos, linhas de tabela, cartão de jogo, caras).
// Não têm cores nem tamanhos: isso vive no CSS.
import { esc, badge, teamName, urlEmblema } from '../util.js';

export { esc, badge, teamName };

// Símbolos das competições (ficheiros em web/img/ligas/), sem placa de fundo.
const LOGOS = ['pt', 'en', 'es', 'ucl', 'uel', 'uecl', 'de', 'fr', 'it', 'f1', 'nba'];
// 'mono' = logótipos que ficariam escuros/vermelhos no fundo: mostram-se como silhueta branca (ver .mono no CSS).
const MONO = ['en', 'es', 'ucl', 'f1', 'fr'];   // fr: o símbolo L1 (2024) é cinzento escuro
const EXT = { f1: 'webp', de: 'png', fr: 'png', it: 'png' };   // os restantes são .svg
const urlLogo = (id) => `img/ligas/${id}.${EXT[id] || 'svg'}`;
// Sem o ficheiro do logótipo (não vêm no repositório: são marcas das competições), o símbolo desaparece.
const logo = (id, nome) => (id ? `<span class="liga-logo logo-${id}${MONO.includes(id) ? ' mono' : ''}"><img src="${urlLogo(id)}" alt="" onerror="this.parentNode.remove()"></span>` : '');

// Carrega logo os símbolos das competições e das equipas, para não aparecerem "a meio" quando a cena entra.
export function precarregarLogos(D) {
  LOGOS.forEach((id) => { new Image().src = urlLogo(id); });
  Object.keys((D && D.teams) || {}).forEach((code) => { new Image().src = urlEmblema(code); });
}

export const titulo = (nome, sub, logoId) =>
  `<h1 class="scene-title">${logo(logoId, nome)}<div class="tt"><span>${esc(nome)}</span>${sub ? `<small>${esc(sub)}</small>` : ''}</div></h1>`;

export const subtitulo = (texto, logoId) => `<h2 class="sub">${logo(logoId, texto)}${esc(texto)}</h2>`;

// Zonas de uma tabela (ex.: 1-8 oitavos, 9-24 play-off): devolve a cor da posição, ou null.
export function corDaZona(zonas, pos) {
  const z = (zonas || []).find((x) => pos <= x.ate);
  return z ? z.cor : null;
}

// Legenda das zonas ("1–8 Oitavos de final", "9–24 Play-off"...), só até à última posição mostrada.
export function legenda(zonas, ultimaPos) {
  if (!zonas || !zonas.length) return '';
  let ini = 1;
  const itens = [];
  for (const z of zonas) {
    if (ini > ultimaPos) break;
    itens.push(`<span><i style="background:${z.cor}"></i>${ini}–${Math.min(z.ate, ultimaPos)} ${esc(z.rotulo)}</span>`);
    ini = z.ate + 1;
  }
  return `<div class="legenda">${itens.join('')}</div>`;
}

// Linha de classificação: posição, distintivo, nome, e colunas numéricas à direita.
export function linhaTabela(D, code, pos, colunas, zonaCor) {
  const eu = code === D.myTeam.code ? ' me' : '';
  const zona = zonaCor ? ` zona" style="--zc:${zonaCor}` : '';
  const nums = colunas.map((c) => `<span class="num ${c.cls || ''}">${esc(c.v)}</span>`).join('');
  return `<div class="row${eu}${zona}"><b class="pos">${pos}</b>${badge(D, code)}<span class="name">${esc(teamName(D, code))}</span>${nums}</div>`;
}

// Cartão de jogo simples: resultado (hs/as), a decorrer (live), adiado, ou dia e hora (when + date).
export function jogo(D, m, simples = false) {
  const [dia, ...hora] = (m.when || '').split(' ');
  const meio = m.live
    ? `<span class="score">${m.hs}<i>–</i>${m.as}</span><span class="ao-vivo">a decorrer${m.clock ? ' · ' + esc(m.clock) : ''}</span>`
    : m.hs != null ? `<span class="score">${m.hs}<i>–</i>${m.as}</span>`
    : m.status === 'adiado' ? '<span class="when adiado">adiado</span>'
    : m.date ? `<span class="when">${esc(dia)} ${esc(m.date)}</span><span class="hora">${esc(hora.join(' '))}</span>`
    : `<span class="when">${esc(m.when)}</span>`;
  const eu = !simples && (m.home === D.myTeam.code || m.away === D.myTeam.code) ? ' me' : '';
  return `<div class="match${eu}">
    <div class="side home"><span class="tn">${esc(teamName(D, m.home))}</span>${badge(D, m.home)}</div>
    <div class="mid">${meio}</div>
    <div class="side away">${badge(D, m.away)}<span class="tn">${esc(teamName(D, m.away))}</span></div>
  </div>`;
}

export const listaJogos = (D, jogos) => `<div class="matches">${jogos.map((m) => jogo(D, m)).join('')}</div>`;

// Cara do jogador (tools/atualizar_fotos.py), a seguir ao emblema. Sem foto: um espaço vazio do mesmo tamanho,
// para as linhas continuarem alinhadas. Se ninguém da lista tiver foto (ex.: no mock), não se reserva espaço.
export function cara(p, comCaras) {
  if (!comCaras) return '';
  return p.photo
    ? `<span class="face"><img src="${esc(p.photo)}" alt="" onerror="this.parentNode.classList.add('vazia');this.remove()"></span>`
    : '<span class="face vazia"></span>';
}
export const temCaras = (lista) => lista.some((p) => p.photo);
