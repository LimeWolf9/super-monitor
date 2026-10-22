// F1 ao vivo: o ecrã de uma sessão a decorrer. Em direto é uma página do acompanhamento do Ao vivo (aovivo.js monta-o
// com iniciarF1AoVivo({ host, embutido: true }) e desmonta-o com .parar()); os dados vêm de GET /api/f1/aovivo
// (tools/f1_direto.py). Para testar entre corridas, ?cat=aovivo&simular=f1 mostra uma sessão do arquivo
// (tools/f1_aovivo.py), sozinha no ecrã.
//   cabeçalho  GP, país, sessão, volta e o tempo que falta; uma faixa grande quando a pista não está verde
//   mapa       a pista (uma volta limpa do líder) e os carros nas cores das equipas, a deslizar entre amostras
//   torre      posição, cor, piloto, intervalo, pneu e voltas dele, paragens, última volta, ▲▼ desde o início da volta
//   rodapé     as 3 últimas mensagens da direção de prova e o tempo (ar, pista, chuva)
//   avisos     7 s no meio do mapa: partida, novo líder, SC/VSC/vermelha e o fim deles, penalização, desistência,
//              volta mais rápida, xadrez
// Qualificação (e a qualificação sprint; os treinos usam o mesmo ecrã sem zona de eliminação), escolhida pelo tipo
// da sessão: no cabeçalho a parte (Q1/Q2/Q3) e o relógio; a torre ordenada pelo melhor tempo da parte, com a
// diferença para o P1, pneu, voltas, o que o carro está a fazer (box, volta de saída, lançada, lenta) e os setores
// da volta lançada; a linha vermelha da eliminação e os eliminados em baixo, a cinzento; no mapa só os carros em volta
// lançada se destacam. Avisos: começo de cada parte, mais rápido / pole provisória, volta anulada, eliminados, pole.
// Também: a distância para a linha (quem está perto dela), o delta ao vivo da volta lançada contra a melhor volta
// dele e se o pneu é novo (N) ou usado (U).
// Corrida, além disso: as lutas a menos de 1 s (na torre e ligadas no mapa), avisos de paragem (tempo parado) e de
// ultrapassagem no top 5, a paragem mais rápida num canto do mapa e, no rodapé, a rodar a cada 15 s com a direção de
// prova, "o campeonato se acabasse agora" (pilotos e equipas). &rodape=pilotos|equipas fixa essa página (capturas).
// Pergunta a cada segundo. Simulação: GET /api/f1/aovivo?simular=<pasta|1>&inicio=<min desde a partida>|volta=<n>&decorrido=<s>&vel=<x>;
// sem a conta da F1 TV no PC o direto não traz as posições: o mapa mostra só a pista ("sem F1 TV: sem posições").
// No URL da simulação: &arquivo=<pasta de data/f1_gravacoes/arquivo/> (por omissão a corrida mais recente), &inicio=<min> (0 = luzes
// apagadas, ou o início da Q1; negativo = antes), &volta=<n> (salta para o início dessa volta), &parte=Q2 (qualificação:
// salta para o início dessa parte; com &inicio=<min> conta a partir daí), &vel=<x> (1 = tempo real),
// &captura=1 (sem as transições, para as capturas de ecrã: o browser sem janela fotografa a meio delas).
import { esc } from './util.js';
import { fundo } from './backgrounds.js';

const PARAMS = new URLSearchParams(location.search);
const PERGUNTAR_MS = 1000;
const AVISO_MS = 7000;
const RODAPE_MS = 15000;
const T0 = Date.now();
const emHub = window.parent !== window;
const hub = (m) => { if (emHub) window.parent.postMessage({ monitorhub: 1, ...m }, '*'); };

// Cores e letras dos pneus (as da Pirelli, como no ecrã da estratégia; as letras são as da transmissão: S, M, H, I, W)
const PNEUS = { SOFT: ['#e8002d', 'S'], MEDIUM: ['#ffd12e', 'M'], HARD: ['#f0f0ec', 'H'], INTERMEDIATE: ['#43b02a', 'I'], WET: ['#0067ad', 'W'] };
const SESSOES = { Race: 'Corrida', Qualifying: 'Qualificação', Sprint: 'Sprint', 'Sprint Qualifying': 'Qualificação sprint',
  'Practice 1': 'Treino livre 1', 'Practice 2': 'Treino livre 2', 'Practice 3': 'Treino livre 3' };
const PAISES = { Singapore: 'Singapura', 'United States': 'Estados Unidos', Mexico: 'México', Brazil: 'Brasil', 'United Arab Emirates': 'Abu Dhabi',
  Qatar: 'Catar', 'Las Vegas': 'Las Vegas', Australia: 'Austrália', China: 'China', Japan: 'Japão', Bahrain: 'Barém', 'Saudi Arabia': 'Arábia Saudita',
  Italy: 'Itália', Monaco: 'Mónaco', Spain: 'Espanha', Canada: 'Canadá', Austria: 'Áustria', 'Great Britain': 'Grã-Bretanha', Belgium: 'Bélgica',
  Hungary: 'Hungria', Netherlands: 'Países Baixos', Azerbaijan: 'Azerbaijão', Portugal: 'Portugal', Germany: 'Alemanha', France: 'França' };
const FAIXAS = { sc: 'SAFETY CAR', vsc: 'VIRTUAL SAFETY CAR', vsc_fim: 'VSC A TERMINAR', vermelha: 'BANDEIRA VERMELHA', amarela: 'BANDEIRA AMARELA' };

const minutos = (s) => (s == null ? '' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`);
const ESTADOS_Q = { box: ['box', 'BOX'], saida: ['saida', 'VOLTA DE SAÍDA'], lancada: ['lancada', 'VOLTA LANÇADA'], lenta: ['lenta', 'VOLTA LENTA'] };
const relogio = (s) => (s == null ? '' : `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`);
const nomeGP = (r) => (PAISES[r.paisNome] ? `GP ${['Estados Unidos', 'Países Baixos'].includes(PAISES[r.paisNome]) ? 'dos' : 'de'} ${PAISES[r.paisNome]}` : r.gp || 'Fórmula 1');

export function iniciarF1AoVivo({ host, embutido = false }) {
  const SIMULAR = !embutido && PARAMS.get('simular') === 'f1';
  let r = null;               // a última resposta do servidor
  let recebido = 0;           // quando chegou (para deslizar os carros entre as duas amostras)
  let mapaFeito = false, mapaId = null;
  const vistos = new Set();   // acontecimentos já mostrados (ou já passados quando o ecrã abriu)
  const fila = [];
  let aMostrar = false, primeira = true;

  const el = document.createElement('div');
  el.className = `scene scene-f1av sport-f1 league-f1${PARAMS.get('captura') === '1' ? ' captura' : ''}`;
  el.innerHTML = fundo('f1') + `
    <header class="f1av-cab"><span class="f1av-pais"></span><div class="tt"><span class="f1av-gp">Fórmula 1</span><small class="f1av-sub">a ligar…</small></div>
      <div class="f1av-volta"><small>Volta</small><b>–</b></div></header>
    <section class="f1av-mapa"><div class="f1av-faixa" hidden></div><svg viewBox="0 0 1000 640" preserveAspectRatio="xMidYMid meet">
      <g class="f1av-pista"></g><g class="f1av-lutas"></g><g class="f1av-carros"></g></svg><div class="f1av-chip" hidden></div>
      <div class="f1av-nota" hidden>sem F1 TV: sem posições</div>
      <div class="f1av-aviso"></div></section>
    <section class="f1av-torre"></section>
    <footer class="f1av-rodape"><div class="f1av-dir"></div><div class="f1av-tempo"></div></footer>`;
  host.replaceChildren(el);
  const $ = (s) => el.querySelector(s);

  // ---------------------------------------------------------------- cabeçalho e faixa
  function cabecalho() {
    const pais = $('.f1av-pais');
    if (r.bandeira) {
      if (pais.dataset.src !== r.bandeira) {
        pais.dataset.src = r.bandeira;
        pais.className = 'f1av-pais bandeira';
        pais.innerHTML = `<img src="${esc(r.bandeira)}" alt="${esc(r.pais || '')}">`;
      }
    } else {
      pais.className = 'f1av-pais';
      pais.textContent = r.pais || '';
    }
    if ($('.f1av-gp').textContent !== nomeGP(r)) $('.f1av-gp').textContent = nomeGP(r);
    const fim = ['Finished', 'Finalised', 'Ends'].includes(r.estadoSessao);
    if (r.quali) {
      // qualificação / treinos: a parte e o relógio dela
      const q = r.quali, parte = q.parte;
      const final = ['Finalised', 'Ends'].includes(r.estadoSessao) || (fim && !q.vagas && q.modo === 'quali');
      const quando = r.estadoSessao === 'Started' ? (parte ? `${parte} a decorrer` : 'a decorrer')
        : final ? 'Terminada' : fim ? `${parte} terminada` : r.estadoSessao === 'Inactive' && parte ? `${parte} a seguir` : 'Ainda não começou';
      $('.f1av-sub').textContent = [SESSOES[r.sessao] || r.sessao, quando, r.simulado ? 'simulação' : ''].filter(Boolean).join(' · ');
      $('.f1av-volta').innerHTML = `<small>${esc(parte || 'Falta')}</small><b>${r.relogio != null ? minutos(r.relogio) : '–'}</b>`;
    } else {
      const quando = r.estadoSessao === 'Started' ? (r.relogio != null ? `falta ${relogio(r.relogio)}` : '')
        : fim ? 'Terminada' : 'Ainda não começou';
      $('.f1av-sub').textContent = [SESSOES[r.sessao] || r.sessao, quando, r.simulado ? 'simulação' : ''].filter(Boolean).join(' · ');
      $('.f1av-volta').innerHTML = `<small>Volta</small><b>${r.volta ?? '–'}</b><i>/${r.voltas ?? '–'}</i>`;
    }
    caber($('.f1av-gp'), 84, 56);
    caber($('.f1av-sub'), 36, 26);
    const f = $('.f1av-faixa');
    const st = r.pista.estado;
    f.hidden = !FAIXAS[st];
    f.className = `f1av-faixa ${st}`;
    if (FAIXAS[st]) f.textContent = st === 'amarela' && r.pista.amarelas.length
      ? `${FAIXAS[st]} · SETOR ${r.pista.amarelas.join(', ')}` : FAIXAS[st];
  }

  // A letra encolhe (de máx até mín) até o texto caber na largura, sem reticências
  function caber(no, max, min) {
    let tam = max;
    no.style.fontSize = `${tam}px`;
    while (tam > min && no.scrollWidth > no.clientWidth + 1) {
      tam -= 2;
      no.style.fontSize = `${tam}px`;
    }
  }

  // ---------------------------------------------------------------- mapa
  function desenharPista(m) {
    if (!m) { $('.f1av-pista').innerHTML = ''; return; }
    const [px, py] = m.partida || [0, 0];
    $('.f1av-pista').innerHTML = `<path d="${m.d}" class="f1av-base"/><path d="${m.d}" class="f1av-linha"/>
      <circle cx="${px}" cy="${py}" r="9" class="f1av-partida"/>`;
    mapaFeito = true;
  }

  function carrosNoMapa() {
    const g = $('.f1av-carros');
    const lider = r.quali ? null : r.carros.find((c) => c.pos === 1 && c.estado !== 'abd');
    // os de trás primeiro, para o líder ficar por cima; na qualificação só os que vão em volta lançada se destacam
    const apagado = (c) => (r.quali && c.estado !== 'lancada' ? ' apagado' : '');
    const carros = [...r.carros].filter((c) => c.xy).reverse();
    if (r.quali) carros.sort((a, b) => (a.estado === 'lancada') - (b.estado === 'lancada'));
    $('.f1av-lutas').innerHTML = (r.lutas || []).map(([a, b]) => `<line data-a="${a}" data-b="${b}"/>`).join('');
    const chip = $('.f1av-chip');
    chip.hidden = !r.paragemRapida;
    if (r.paragemRapida) chip.innerHTML = `<small>Paragem mais rápida</small><b>${esc(r.paragemRapida.texto)}</b>`;
    g.innerHTML = carros.map((c) => `<g class="f1av-carro${c.estado ? ' ' + c.estado : ''}${apagado(c)}${c.luta ? ' luta' : ''}${c === lider ? ' lider' : ''}" data-n="${c.num}">
      ${c === lider ? '<circle r="22" class="anel"/>' : ''}<circle r="13" style="fill:${c.cor}"/><text y="-22">${esc(c.tla)}</text></g>`).join('');
    mover();
  }

  // Entre duas respostas, cada carro desliza da posição em t para a de t + 1 s
  function mover() {
    if (!r) return;
    const f = Math.min(1, (Date.now() - recebido) / PERGUNTAR_MS);
    const onde = {};
    for (const g of el.querySelectorAll('.f1av-carro')) {
      const c = r.carros.find((x) => x.num === g.dataset.n);
      if (!c || !c.xy) continue;
      const [x0, y0, x1, y1] = c.xy;
      onde[c.num] = [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f];
      g.setAttribute('transform', `translate(${onde[c.num][0].toFixed(1)} ${onde[c.num][1].toFixed(1)})`);
    }
    // a linha entre os dois carros de cada luta
    for (const ln of el.querySelectorAll('.f1av-lutas line')) {
      const a = onde[ln.dataset.a], b = onde[ln.dataset.b];
      if (!a || !b) { ln.setAttribute('visibility', 'hidden'); continue; }
      ln.removeAttribute('visibility');
      ln.setAttribute('x1', a[0].toFixed(1)); ln.setAttribute('y1', a[1].toFixed(1));
      ln.setAttribute('x2', b[0].toFixed(1)); ln.setAttribute('y2', b[1].toFixed(1));
    }
  }
  const animar = () => { if (!ativo) return; mover(); requestAnimationFrame(animar); };

  // ---------------------------------------------------------------- torre
  function intervalo(c) {
    if (c.estado === 'abd') return '<span class="f1av-tag abd">ABD</span>';
    if (c.estado === 'box') return '<span class="f1av-tag box">BOX</span>';
    if (c.pos === 1) return '<span class="lider">Líder</span>';
    return esc(c.int || c.gap || '');
  }
  const pneu = (c) => {
    if (!PNEUS[c.pneu]) return '<span class="f1av-pneu"></span>';
    const [cor, letra] = PNEUS[c.pneu];
    // quantas voltas tem o pneu; na qualificação, um jogo novo acabado de montar (volta de saída e a lançada) diz "novo"
    const info = r && r.quali && c.novo && (c.idade ?? 0) <= 2 ? '<em class="novo">novo</em>' : `<em>${c.idade ?? 0} v</em>`;
    return `<span class="f1av-pneu"><i style="--pc:${cor}">${letra}</i>${info}</span>`;
  };
  const delta = (c) => (c.estado === 'abd' || !c.delta ? '<span class="f1av-d"></span>'
    : c.delta > 0 ? `<span class="f1av-d sobe">▲${c.delta}</span>` : `<span class="f1av-d desce">▼${-c.delta}</span>`);

  // Qualificação: melhor tempo da parte, diferença para o P1, pneu, voltas, o que está a fazer e os setores da volta lançada
  function torreQuali() {
    const q = r.quali;
    const ativos = r.carros.filter((c) => c.estado !== 'fora').length;
    const linhas = r.carros.map((c, i) => {
      const fora = c.estado === 'fora';
      // a linha vermelha: por baixo do último que passa, enquanto há quem possa cair
      const corte = !fora && q.vagas && i + 1 === q.vagas && ativos > q.vagas ? ' corte' : '';
      const zona = !fora && q.vagas && i + 1 > q.vagas ? ' zona' : '';
      const [classe, texto] = ESTADOS_Q[c.estado] || ['', ''];
      const setores = `<span class="f1av-set">${(c.setores || []).map((s) => `<i class="${s || 'nada'}"></i>`).join('')}</span>`;
      const gap = fora ? `<span class="f1av-fora">Fora na ${esc(c.fora)}</span>`
        : c.corte ? `<span class="f1av-corte ${c.corte.lado}"><b>${esc(c.corte.v)}</b><small>${esc(c.corte.txt)}</small></span>`
        : i === 0 && c.melhorVolta ? '<span class="lider">P1</span>' : esc(c.gap || '');
      const dv = c.deltaVolta;
      const deltaV = dv == null ? '' : `<b class="f1av-dv ${dv < 0 ? 'ganha' : 'perde'}">${dv < 0 ? '−' : '+'}${Math.abs(dv).toFixed(2)}</b>`;
      return `<div class="f1av-l q${fora ? ' fora' : ''}${corte}${zona}${c.estado === 'box' ? ' box' : ''}">
        <b class="pos">${i + 1}</b><i class="cor" style="background:${c.cor}"></i><span class="tla">${esc(c.tla)}</span>
        <span class="mv">${esc(c.melhorVolta || '')}</span><span class="int">${gap}</span>${fora ? '' : `${pneu(c)}<span class="par">${c.voltas || ''}</span>`}
        <span class="eq">${texto ? `<span class="f1av-tag ${classe}">${deltaV && classe === 'lancada' ? 'LANÇADA' : texto}</span>` : ''}${deltaV}</span>${setores}</div>`;
    }).join('');
    $('.f1av-torre').innerHTML = `<div class="f1av-l q head"><b class="pos"></b><i class="cor"></i><span class="tla">Piloto</span>
      <span class="mv">Melhor</span><span class="int">Dif.</span><span class="f1av-pneu">Pneu</span><span class="par">Vts</span>
      <span class="eq">Em pista</span><span class="f1av-set">Set.</span></div>${linhas}`;
  }

  function torre() {
    if (r.quali) return torreQuali();
    const linhas = r.carros.map((c) => `<div class="f1av-l${c.estado ? ' ' + c.estado : ''}${c.luta ? ' luta ' + c.luta : ''}">
      <b class="pos">${c.estado === 'abd' ? '' : c.pos}</b><i class="cor" style="background:${c.cor}"></i>
      <span class="tla">${esc(c.tla)}</span><span class="int">${intervalo(c)}</span>${pneu(c)}
      <span class="par">${c.paragens || ''}</span>
      <span class="ult${c.roxo ? ' roxo' : c.verde ? ' verde' : ''}">${esc(c.ultima)}</span>${delta(c)}</div>`).join('');
    $('.f1av-torre').innerHTML = `<div class="f1av-l head"><b class="pos"></b><i class="cor"></i><span class="tla">Piloto</span>
      <span class="int">Intervalo</span><span class="f1av-pneu">Pneu</span><span class="par">Par.</span><span class="ult">Última volta</span>
      <span class="f1av-d"></span></div>${linhas}`;
  }

  // ---------------------------------------------------------------- rodapé
  // "O campeonato se acabasse agora": 6 linhas em duas colunas (lugar, ▲▼, nome, pontos e quantos ganha hoje)
  function campeonatoHTML(tipo) {
    const lista = r.campeonato[tipo] || [];
    const sobe = (x) => (x.sobe > 0 ? `<em class="sobe">▲${x.sobe}</em>` : x.sobe < 0 ? `<em class="desce">▼${-x.sobe}</em>` : '<em></em>');
    return `<h2 class="sub">Campeonato se acabasse agora · ${tipo === 'pilotos' ? 'Pilotos' : 'Equipas'}</h2><div class="f1av-camp ${tipo}">${lista.map((x) =>
      `<div><b>${x.pos}</b>${sobe(x)}<i style="background:${x.cor}"></i><span>${esc(x.nome)}</span><strong>${x.pontos}</strong><small>${x.ganha ? `+${x.ganha}` : ''}</small></div>`).join('')}</div>`;
  }

  function rodape() {
    const paginas = r.campeonato ? ['direcao', 'pilotos', 'equipas'] : ['direcao'];
    const fixa = PARAMS.get('rodape');
    const pagina = paginas.includes(fixa) ? fixa : paginas[Math.floor((Date.now() - T0) / RODAPE_MS) % paginas.length];
    $('.f1av-dir').innerHTML = pagina !== 'direcao' ? campeonatoHTML(pagina) : `<h2 class="sub">Direção de prova</h2>` + (r.direcao.length ? r.direcao.map((m) =>
      `<div class="f1av-msg${m.flag ? ' flag-' + esc(String(m.flag).toLowerCase().replace(/\s+/g, '-')) : ''}"><b>${m.volta ? `V${m.volta}` : ''}</b><span>${esc(m.texto || '')}</span></div>`).join('')
      : '<div class="f1av-msg"><span>Sem mensagens</span></div>');
    const t = r.tempo || {};
    const num = (v) => (v == null ? '–' : `${String(v).replace('.', ',')}°`);
    $('.f1av-tempo').innerHTML = `<h2 class="sub">Tempo</h2><div><small>Ar</small><b>${num(t.ar)}</b></div><div><small>Pista</small><b>${num(t.pista)}</b></div>
      <div><small>Chuva</small><b class="${t.chuva ? 'chove' : ''}">${t.chuva ? 'Sim' : 'Não'}</b></div>`;
  }

  // ---------------------------------------------------------------- avisos (7 s)
  const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));
  async function correrFila() {
    if (aMostrar) return;
    aMostrar = true;
    const caixa = $('.f1av-aviso');
    while (fila.length) {
      const ev = fila.shift();
      const c = ev.num && r ? r.carros.find((x) => x.num === ev.num) : null;
      caixa.className = `f1av-aviso ${ev.tipo}`;
      caixa.innerHTML = `<div class="tipo">${esc(ev.titulo)}</div>
        <div class="quem">${c ? `<i style="background:${c.cor}"></i>` : ''}${esc(ev.tipo === 'penalizacao' ? ev.texto.slice(0, 90) : ev.texto)}</div>`;
      requestAnimationFrame(() => caixa.classList.add('on'));
      await esperar(fila.length > 2 ? AVISO_MS / 2 : AVISO_MS);
      caixa.classList.remove('on');
      await esperar(500);
    }
    aMostrar = false;
  }
  function acontecimentos() {
    for (const ev of r.eventos || []) {
      if (vistos.has(ev.id)) continue;
      vistos.add(ev.id);
      // ao abrir, só os que aconteceram há menos de 7 s
      if (primeira && r.t - ev.t > AVISO_MS / 1000) continue;
      fila.push(ev);
    }
    primeira = false;
    correrFila();
  }

  // ---------------------------------------------------------------- dados
  async function perguntar() {
    const q = SIMULAR ? new URLSearchParams({ simular: PARAMS.get('arquivo') || '1', decorrido: String((Date.now() - T0) / 1000) })
      : new URLSearchParams();
    if (SIMULAR) for (const k of ['inicio', 'volta', 'parte', 'vel']) if (PARAMS.get(k)) q.set(k, PARAMS.get(k));
    if (!mapaFeito) q.set('mapa', '1');
    try {
      const resp = await fetch(`/api/f1/aovivo?${q}`, { cache: 'no-store' });
      const novo = await resp.json();
      if (novo.erro) throw new Error(novo.erro);
      if (novo.semDados) {   // em direto, antes de chegar o retrato da sessão
        $('.f1av-sub').textContent = novo.ligado ? 'À espera dos dados da sessão…' : 'A ligar ao live timing da F1…';
        if (novo.mapa && !mapaFeito) { desenharPista(novo.mapa); mapaId = novo.mapaId; }
        return;
      }
      r = novo;
      recebido = Date.now();
    } catch (e) {
      $('.f1av-sub').textContent = `Sem dados (${e.message})`;
      return;
    }
    // o traçado pode mudar em direto (o do OpenStreetMap até haver uma volta limpa da sessão)
    if (mapaFeito && r.mapaId !== undefined && r.mapaId !== mapaId) { mapaFeito = false; return; }
    if (!mapaFeito) { desenharPista(r.mapa); mapaId = r.mapaId; }
    $('.f1av-nota').hidden = !r.semPosicoes;
    cabecalho();
    carrosNoMapa();
    torre();
    rodape();
    acontecimentos();
  }

  // Comando: aqui só o "voltar" (vai para o menu do hub); embutido no Ao vivo, é o Ao vivo que trata do comando
  if (!embutido) {
    hub({ tipo: 'pronto', acoes: ['voltar'] });
    window.addEventListener('message', (e) => {
      const m = e.data;
      if (emHub && m && m.monitorhub === 1 && m.tipo === 'comando') hub({ tipo: 'nao_tratado', acao: m.acao });
    });
  }

  let ativo = true;
  perguntar();
  const intervaloId = setInterval(perguntar, PERGUNTAR_MS);
  requestAnimationFrame(animar);
  const parar = () => { ativo = false; clearInterval(intervaloId); };
  window.addEventListener('pagehide', parar);
  return { parar, ativo: () => ativo };
}
