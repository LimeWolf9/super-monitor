// Mapa do acompanhamento do Ao vivo (aovivo.js): os estádios dos jogos seguidos num mapa do continente e, a cada
// golo / penálti / vermelho, um voo "à GTA" até ao estádio, com as ruas à volta e um destaque de vidro.
//
// Vista geral   os estádios seguidos enquadrados (com margem); um ponto a pulsar em cada um (azul o FC Porto e
//               Portugal, verde os outros) e um balão de vidro (estádio, emblemas, siglas, resultado, minuto) ligado
//               ao ponto por uma linha. Os balões arrumam-se sozinhos (procura gulosa entre posições candidatas)
//               para não taparem outros balões, os pontos nem saírem do mapa.
// Acontecimento acontecimento(): a largura da vista desce em escala logarítmica (a câmara centra-se no estádio no
//               primeiro quarto da descida), 3,8 s até ~1,1 km; aí aparece o desenho do estádio, posto e rodado sobre
//               o relvado real do OpenStreetMap, com as ruas, linhas, água, parques e prédios à volta; o destaque e o
//               nome do estádio ficam uns segundos e a câmara volta à vista geral em 2,4 s.
// Mapas         web/mapas/<regiao>.json (Natural Earth, ver tools/gerar_mapas.py) e /data/estadios_osm/<id>.json
//               (OpenStreetMap, ver tools/estadios.py). Ambos guardam longitude/latitude: a projeção (Lambert
//               azimutal de áreas iguais, centrada em cada continente) faz-se aqui, em km, com o y para baixo.
import { esc, badge } from './util.js';

const W = 1080, H = 1290;   // tamanho do mapa no ecrã (px)
const R = 6371, GRAU = Math.PI / 180;
// Centro da projeção e largura mínima da vista geral (km), por continente: a vista enquadra só os jogos seguidos
// (só Portugal: Portugal; Inglaterra e França: só esses dois)
export const REGIOES = {
  europa: { centro: [10, 50], minimo: 420 },
  america_norte: { centro: [-96, 39], minimo: 900 },
  america_sul: { centro: [-60, -20], minimo: 900 },
};
// Competições da UEFA (ligas, taças, provas europeias, seleções): são da Europa mesmo com o estádio fora da caixa
const UEFA = new Set(['pt', 'tp', 'tl', 'stp', 'en', 'fa', 'efl', 'es', 'cdr', 'de', 'dfb', 'it', 'cit', 'fr', 'cdf',
  'ucl', 'uel', 'uecl', 'usc', 'unl', 'wcq', 'euq', 'euro']);
const DESCER_MS = 3800, SUBIR_MS = 2400;
const LARGURA_FINAL = 1.1;    // km: o estádio e as ruas à volta
const AREA = { x0: 150, x1: 930, y0: 230, y1: 1060 };   // onde ficam os pontos na vista geral (px)

// Continente de um jogo (pelas coordenadas do estádio; sem elas, pelo desporto/competição), ou null. O Ao vivo só
// pergunta pelos que têm coordenadas (temLugar). A Europa vai até ao Cazaquistão (a caixa de tools/gerar_mapas.py).
export function continente(j) {
  const e = j.estadio;
  if (j.sport !== 'nba' && UEFA.has(j.comp && j.comp.chave)) return 'europa';
  if (e && e.lat != null) {
    if (e.lon > -32 && e.lon < 82 && e.lat > 25 && e.lat < 72) return 'europa';
    if (e.lon < -48 && e.lat > 12) return 'america_norte';
    if (e.lon < -28 && e.lon > -95 && e.lat <= 12 && e.lat > -58) return 'america_sul';
    return null;
  }
  if (j.sport === 'nba') return 'america_norte';
  if (['wcqs', 'ca'].includes(j.comp && j.comp.chave)) return 'america_sul';
  return null;
}
export const temLugar = (j) => !!(j.estadio && j.estadio.lat != null);

function projecao([lon0, lat0]) {
  const l0 = lon0 * GRAU, s0 = Math.sin(lat0 * GRAU), c0 = Math.cos(lat0 * GRAU);
  return (lon, lat) => {
    const l = lon * GRAU - l0, p = lat * GRAU, sp = Math.sin(p), cp = Math.cos(p), cl = Math.cos(l);
    const k = Math.sqrt(2 / (1 + s0 * sp + c0 * cp * cl));
    return [R * k * cp * Math.sin(l), -R * k * (c0 * sp - s0 * cp * cl)];
  };
}

// Uma linha guardada em deltas inteiros ([lon0, lat0, dlon, dlat, ...] / escala) -> "M x y L x y ..." em km.
// base = [lon, lat] somado ao primeiro ponto (o OSM começa no centro do estádio); o = origem a subtrair (km).
function caminho(arr, escala, P, fechar, casas, base = [0, 0], o = [0, 0]) {
  let lon = base[0] * escala, lat = base[1] * escala, d = '';
  for (let i = 0; i < arr.length; i += 2) {
    lon += arr[i]; lat += arr[i + 1];
    const [x, y] = P(lon / escala, lat / escala);
    d += `${i ? 'L' : 'M'}${(x - o[0]).toFixed(casas)} ${(y - o[1]).toFixed(casas)}`;
  }
  return d + (fechar ? 'Z' : '');
}

const cacheMapas = {};
const lerMapa = (regiao) => (cacheMapas[regiao] ||= fetch(`mapas/${regiao}.json`).then((r) => {
  if (!r.ok) throw new Error(`mapa ${regiao}: HTTP ${r.status}`);
  return r.json();
}));
const cacheOsm = {};
const lerOsm = (id) => (cacheOsm[id] ||= fetch(`/data/estadios_osm/${encodeURIComponent(id)}.json`, { cache: 'no-store' })
  .then((r) => (r.ok ? r.json() : null)).catch(() => null));

// Zoom "à GTA": a largura diminui a ritmo constante em escala logarítmica, com arranque e travagem suaves
const suave = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
// a câmara centra-se no estádio no primeiro quarto da descida e depois só desce
const centrar = (f) => { const t = Math.min(1, Math.max(0, f) / 0.25); return t * t * (3 - 2 * t); };
const entre = (a, b, v) => Math.max(a, Math.min(b, v));

// O estádio desenhado (em km, centrado no relvado, comprido ao longo do x): bancadas, cobertura, degraus e o campo
function desenhoEstadio() {
  const s = 0.001;   // 1 m
  const rect = (w, h, r, cls) => `<rect class="${cls}" x="${-w / 2 * s}" y="${-h / 2 * s}" width="${w * s}" height="${h * s}" rx="${r * s}"/>`;
  let d = rect(250, 215, 70, 'bancada') + rect(232, 196, 62, 'cobertura') + rect(205, 168, 45, 'bancada2');
  for (let k = 1; k <= 5; k++) d += rect(205 - k * 14, 168 - k * 14, 45 - k * 6, 'degrau');
  d += rect(110, 73, 2, 'relva');
  const L = (x1, y1, x2, y2) => `<line class="risca" x1="${x1 * s}" y1="${y1 * s}" x2="${x2 * s}" y2="${y2 * s}"/>`;
  d += rect(105, 68, 0, 'risca') + L(0, -34, 0, 34) + `<circle class="risca" r="${9.15 * s}"/>`;
  d += `<rect class="risca" x="${-52.5 * s}" y="${-20.15 * s}" width="${16.5 * s}" height="${40.3 * s}"/>` +
    `<rect class="risca" x="${36 * s}" y="${-20.15 * s}" width="${16.5 * s}" height="${40.3 * s}"/>`;
  return d;
}
const CAMADAS_OSM = ['agua', 'parque', 'edif', 'rio', 'ferro', 'metro', 'menor', 'media', 'maior', 'estadio'];
const FECHADAS = new Set(['agua', 'parque', 'edif', 'estadio']);

// Retângulos: área em comum
const sobrepor = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));

export function criarMapa(host, { dados }) {
  const el = document.createElement('div');
  el.className = 'av-mapa esconde';
  el.innerHTML = `
    <svg class="av-base" preserveAspectRatio="xMidYMid slice">
      <defs><radialGradient id="av-mar" cx="40%" cy="40%" r="80%"><stop offset="0" stop-color="#0d2236"/><stop offset="1" stop-color="#060b14"/></radialGradient></defs>
      <rect x="-30000" y="-30000" width="60000" height="60000" fill="url(#av-mar)"/>
      <g class="terras"></g><g class="detalhe" opacity="0"></g><g class="osm" opacity="0"></g><g class="estadio" opacity="0"></g>
    </svg>
    <svg class="av-grelha"></svg><svg class="av-linhas"></svg>
    <div class="av-sitios"></div><div class="av-camada"></div>
    <div class="av-destaque"></div><div class="av-nome-estadio"></div>
    <div class="av-credito">© OpenStreetMap</div>`;
  host.appendChild(el);
  const $ = (s) => el.querySelector(s);
  const svg = $('.av-base'), gTerras = $('.terras'), gDetalhe = $('.detalhe'), gOsm = $('.osm'), gEstadio = $('.estadio');

  let regiao = null, P = null, mapa = null, comDetalhe = false, sitios = [];
  let jogos = [];                 // os jogos no mapa (com coordenadas)
  const marcas = new Map();       // id -> { ponto, balao, x, y (km), dx, dy (px, do ponto ao balão) }
  let G = { cx: 0, cy: 0, w: 1000 }, V = G;
  let voo = null;                 // o jogo do acontecimento em curso (os balões ficam escondidos)
  let pronto = Promise.resolve();
  let vivo = true;

  // ------------------------------------------------------------ desenhar uma vista
  function aplicar() {
    const escala = V.w / W, hk = H * escala, vb = [V.cx - V.w / 2, V.cy - hk / 2, V.w, hk];
    svg.setAttribute('viewBox', vb.join(' '));
    const ecra = (x, y) => [(x - vb[0]) / escala, (y - vb[1]) / escala];
    const perto = V.w < 2.5;   // muito perto: o ponto dá lugar ao desenho do estádio
    let linhas = '';
    for (const [id, m] of marcas) {
      const [x, y] = ecra(m.x, m.y);
      const fora = x < -400 || x > W + 400 || y < -400 || y > H + 400;
      m.ponto.style.transform = `translate(${x}px, ${y}px)`;
      m.ponto.style.opacity = fora || (perto && voo && voo.id === id) ? 0 : 1;
      m.balao.style.transform = `translate(${x + m.dx}px, ${y + m.dy}px)`;
      if (!voo && m.w) {   // a linha vai do ponto ao lado mais perto do balão
        const bx = entre(x + m.dx, x + m.dx + m.w, x), by = entre(y + m.dy, y + m.dy + m.h, y);
        linhas += `<line x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${bx.toFixed(1)}" y2="${by.toFixed(1)}"/>`;
      }
    }
    $('.av-linhas').innerHTML = linhas;
    // grelha em várias escalas (dá a sensação de descer)
    let g = '';
    for (const passo of [1000, 100, 10, 1, 0.1]) {
      const px = passo / escala;
      if (px < 25 || px > 2500) continue;
      const op = (Math.min(1, (px - 25) / 120) * (px > 1200 ? Math.max(0, (2500 - px) / 1300) : 1)).toFixed(2);
      for (let x = Math.floor(vb[0] / passo) * passo; x < vb[0] + vb[2]; x += passo) { const s = ((x - vb[0]) / escala).toFixed(1); g += `<line x1="${s}" y1="0" x2="${s}" y2="${H}" style="opacity:${op}"/>`; }
      for (let y = Math.floor(vb[1] / passo) * passo; y < vb[1] + vb[3]; y += passo) { const s = ((y - vb[1]) / escala).toFixed(1); g += `<line x1="0" y1="${s}" x2="${W}" y2="${s}" style="opacity:${op}"/>`; }
    }
    $('.av-grelha').innerHTML = g;
    // camadas pela largura da vista: o detalhe (cidades, costa, rios) a meio, o OSM e o estádio no fim
    const eDet = mapa?.detalhe ? entre(0, 1, (600 - V.w) / 400) : 0, eOsm = entre(0, 1, (30 - V.w) / 20), eEst = entre(0, 1, (4 - V.w) / 2.5);
    if (eDet > 0 && !comDetalhe) desenharDetalhe();
    mostrarCamada(gDetalhe, eDet * (1 - eOsm * 0.9));
    mostrarCamada(gOsm, gOsm.childElementCount ? eOsm : 0);
    mostrarCamada(gEstadio, gEstadio.childElementCount ? eEst : 0);
    // os países só se apagam abaixo dos 250 km (uma vista geral apertada, ex.: só Portugal, ainda os mostra)
    gTerras.setAttribute('opacity', 1 - Math.max(eEst, entre(0, 1, (250 - V.w) / 150) * 0.7));
    $('.av-credito').style.opacity = gOsm.childElementCount && eOsm > 0.05 ? 1 : 0;
    // nomes das cidades a meio do zoom (as maiores primeiro, sem se taparem)
    let html = '';
    if (eDet > 0.05 && eOsm < 0.6) {
      const postos = [];
      for (const t of sitios) {
        if (V.w > 150 && t.p < 500_000) continue;
        const [x, y] = ecra(t.x, t.y);
        if (x < 20 || x > W - 200 || y < 140 || y > H - 120) continue;
        const r = { x0: x - 16, x1: x + 24 + t.n.length * 15, y0: y - 22, y1: y + 22 };
        if (postos.some((o) => sobrepor(o, r))) continue;
        postos.push(r);
        html += `<div class="av-sitio" style="transform:translate(${x.toFixed(0)}px,${y.toFixed(0)}px);opacity:${(eDet * (1 - eOsm)).toFixed(2)}">${esc(t.n)}</div>`;
        if (postos.length > 14) break;
      }
    }
    $('.av-sitios').innerHTML = html;
  }

  function mostrarCamada(g, op) {
    g.setAttribute('opacity', op.toFixed(3));
    g.style.display = op > 0.004 ? '' : 'none';   // o que não se vê não se desenha
  }

  function desenharDetalhe() {
    comDetalhe = true;
    const d = mapa.detalhe;
    const junto = (lista, fechar) => lista.map((a) => caminho(a, 1000, P, fechar, 2)).join('');
    gDetalhe.innerHTML = `<path class="urb" d="${junto(d.urb, true)}"/><path class="lago" d="${junto(d.lagos, true)}"/>` +
      `<path class="rio" d="${junto(d.rios, false)}"/><path class="costa" d="${junto(d.costa, false)}"/>`;
  }

  // ------------------------------------------------------------ mapa de base e vista geral
  async function usarRegiao(r) {
    if (r === regiao) return;
    regiao = r;
    P = projecao(REGIOES[r].centro);
    mapa = await lerMapa(r);
    if (regiao !== r) return;
    comDetalhe = false;
    gDetalhe.innerHTML = '';
    gTerras.innerHTML = mapa.paises.map((p) => `<path class="terra${p.n === 'PRT' ? ' pt' : ''}" d="${caminho(p.a, 100, P, true, 1)}"/>`).join('') +
      `<path class="lago" d="${mapa.lagos.map((a) => caminho(a, 100, P, true, 1)).join('')}"/>` +
      (mapa.estados ? `<path class="estados" d="${mapa.estados.map((a) => caminho(a, 100, P, true, 1)).join('')}"/>` : '');
    sitios = (mapa.sitios || []).map((s) => { const [x, y] = P(s.c[0], s.c[1]); return { n: s.n, p: s.p, x, y }; });
  }

  function vistaGeral() {
    const pts = [...marcas.values()];
    if (!pts.length) return { cx: 0, cy: 0, w: REGIOES[regiao].minimo };
    const xs = pts.map((m) => m.x), ys = pts.map((m) => m.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const escala = Math.max((x1 - x0) / (AREA.x1 - AREA.x0), (y1 - y0) / (AREA.y1 - AREA.y0), REGIOES[regiao].minimo / W);
    // o centro da área dos pontos fica no centro dessa área do ecrã
    const meioX = (AREA.x0 + AREA.x1) / 2 - W / 2, meioY = (AREA.y0 + AREA.y1) / 2 - H / 2;
    return { cx: (x0 + x1) / 2 - meioX * escala, cy: (y0 + y1) / 2 - meioY * escala, w: escala * W };
  }

  // Balões: para cada jogo (de cima para baixo), a posição candidata com menos sobreposições
  function arrumarBaloes() {
    const escala = G.w / W, vb0 = G.cx - G.w / 2, vb1 = G.cy - H * escala / 2;
    const lista = [...marcas.values()].map((m) => ({ m, x: (m.x - vb0) / escala, y: (m.y - vb1) / escala }))
      .sort((a, b) => a.y - b.y);
    const ocupado = lista.map((p) => ({ x0: p.x - 34, x1: p.x + 34, y0: p.y - 34, y1: p.y + 34 }));   // os pontos
    const limites = { x0: 16, x1: W - 16, y0: 120, y1: H - 100 };
    for (const p of lista) {
      const w = p.m.balao.offsetWidth, h = p.m.balao.offsetHeight;
      p.m.w = w; p.m.h = h;
      let melhor = null;
      for (const d of [50, 90, 140, 200, 270, 350]) {
        for (let a = 0; a < 360; a += 20) {
          const c = Math.cos(a * GRAU), s = Math.sin(a * GRAU);
          const cx = p.x + c * (d + w / 2), cy = p.y + s * (d + h / 2);
          const r = { x0: cx - w / 2, x1: cx + w / 2, y0: cy - h / 2, y1: cy + h / 2 };
          const fora = w * h - sobrepor(r, limites);
          const tapa = ocupado.reduce((t, o) => t + sobrepor(r, o), 0);
          const custo = tapa * 20 + fora * 40 + d * 6 + (s > 0.3 ? 40 : 0);   // de preferência por cima
          if (!melhor || custo < melhor.custo) melhor = { custo, r };
        }
      }
      ocupado.push(melhor.r);
      p.m.dx = melhor.r.x0 - p.x; p.m.dy = melhor.r.y0 - p.y;
    }
  }

  // ------------------------------------------------------------ jogos
  function balaoHTML(D, j) {
    const res = j.hs == null ? '–' : `${j.hs}–${j.as}`;
    const min = j.estado === 'in' ? `<i></i>${esc(j.tempo)}` : esc(j.tempo);
    return `<div class="comp">${esc(j.estadio.nome)}</div>
      <div class="placar">${badge(D, j.home)}<span class="tn">${esc(j.home)}</span><span class="res">${res}</span><span class="tn">${esc(j.away)}</span>${badge(D, j.away)}</div>
      <div class="min${j.estado === 'in' ? '' : j.estado === 'aquecimento' ? ' aq' : ' fim'}">${min}</div>`;
  }

  // Põe no mapa estes jogos (todos do mesmo continente; os sem coordenadas ficam de fora)
  function atualizar(lista, r) {
    pronto = pronto.then(async () => {
      if (!vivo) return;
      await usarRegiao(r);
      const D = dados();
      jogos = lista.filter(temLugar);
      const ids = new Set(jogos.map((j) => j.id));
      for (const [id, m] of marcas) if (!ids.has(id)) { m.ponto.remove(); m.balao.remove(); marcas.delete(id); }
      const camada = $('.av-camada');
      let mudou = false;
      for (const j of jogos) {
        let m = marcas.get(j.id);
        const [x, y] = P(j.estadio.lon, j.estadio.lat);
        if (!m) {
          m = { ponto: document.createElement('div'), balao: document.createElement('div'), dx: 30, dy: -160 };
          m.ponto.innerHTML = '<i></i><b></b>';
          camada.append(m.ponto, m.balao);
          marcas.set(j.id, m);
          mudou = true;
        }
        if (m.x !== x || m.y !== y) mudou = true;
        m.x = x; m.y = y;
        m.ponto.className = `av-ponto${j.meu ? ' me' : ''}`;
        m.balao.className = `av-pop${j.meu ? ' me' : ''}`;
        const html = balaoHTML(D, j);
        if (m.html !== html) { m.balao.innerHTML = html; m.html = html; }
      }
      if (voo) return;   // durante um acontecimento, a vista geral refaz-se quando a câmara voltar
      const antes = G;
      G = vistaGeral();
      arrumarBaloes();
      if (mudou || Math.abs(antes.w - G.w) > 1) V = G;
      aplicar();
      el.classList.remove('esconde');
    }).catch((e) => console.warn('Mapa:', e));
    return pronto;
  }

  // ------------------------------------------------------------ acontecimentos
  function voar(de, para, ms) {
    return new Promise((ok) => {
      const t0 = performance.now();
      const lw0 = Math.log(de.w), lw1 = Math.log(para.w);
      function passo(agora) {
        if (!vivo) return ok();
        const t = Math.min(1, (agora - t0) / ms), k = suave(t);
        const w = Math.exp(lw0 + (lw1 - lw0) * k);
        // o centro acompanha a escala: chega ao alvo quando a vista já é pequena (ou sai dele logo, ao subir)
        const f = lw0 === lw1 ? k : (lw0 - Math.log(w)) / (lw0 - lw1);
        const c = para.w < de.w ? centrar(f) : 1 - centrar(1 - f);
        V = { w, cx: de.cx + (para.cx - de.cx) * c, cy: de.cy + (para.cy - de.cy) * c };
        aplicar();
        if (t < 1) requestAnimationFrame(passo); else ok();
      }
      requestAnimationFrame(passo);
    });
  }
  const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));

  // Desenha as ruas à volta do estádio e o estádio no relvado. Devolve o ponto (km) do relvado, ou null sem OSM
  async function prepararEstadio(j) {
    gOsm.innerHTML = ''; gEstadio.innerHTML = '';
    const osm = j.estadio.osm ? await lerOsm(j.estadio.id) : null;
    if (!osm || !vivo) return null;
    const campo = osm.campo;
    const centro = campo ? campo.c : osm.centro;
    const o = P(centro[0], centro[1]);
    const camadas = osm.camadas || {};
    gOsm.innerHTML = `<g transform="translate(${o[0]} ${o[1]})">` + CAMADAS_OSM.map((k) =>
      `<path class="${k}" d="${(camadas[k] || []).map((a) => caminho(a, osm.e, P, FECHADAS.has(k), 4, osm.centro, o)).join('')}"/>`).join('') + '</g>';
    if (campo) {
      const a = P(campo.a[0], campo.a[1]), b = P(campo.b[0], campo.b[1]);
      const ang = Math.atan2(b[1] - a[1], b[0] - a[0]) / GRAU;
      gEstadio.innerHTML = `<g transform="translate(${o[0]} ${o[1]}) rotate(${ang.toFixed(2)})">${desenhoEstadio()}</g>`;
    }
    return o;
  }

  // Um acontecimento: voa até ao estádio, mostra o destaque (html, ou uma promessa dele: a cara pode estar a
  // chegar) e o nome do estádio durante "segurar" ms, e volta. Sem o OSM do estádio não há voo: devolve false (e o
  // aovivo.js mostra só o destaque).
  async function acontecimento(j, { destaque, classe = '', segurar = 5000 }) {
    await pronto;
    const m = marcas.get(j.id);
    if (!vivo || !m) return false;
    const alvo = await prepararEstadio(j);
    if (!alvo || !vivo) return false;
    voo = j;
    el.classList.add('esconde');
    const F = { cx: alvo[0], cy: alvo[1] - 0.21, w: LARGURA_FINAL };
    const inicio = { ...G };
    await voar(inicio, F, DESCER_MS);
    const caixa = $('.av-destaque'), nome = $('.av-nome-estadio');
    caixa.className = `av-destaque${classe}`;
    caixa.innerHTML = await destaque;
    if (!vivo) return true;
    const e = j.estadio;
    nome.innerHTML = `${esc(e.nome)}${e.cidade ? `<small>${esc(e.cidade)}</small>` : ''}`;
    caixa.classList.add('on'); nome.classList.add('on');
    await esperar(segurar);
    caixa.classList.remove('on'); nome.classList.remove('on');
    await voar(F, inicio, SUBIR_MS);
    voo = null;
    if (!vivo) return true;
    G = vistaGeral();   // os jogos podem ter mudado durante o voo
    arrumarBaloes();
    V = G;
    aplicar();
    el.classList.remove('esconde');
    return true;
  }

  return {
    el,
    atualizar,
    acontecimento,
    tem: (id) => marcas.has(id),
    destruir() { vivo = false; el.remove(); },
  };
}
