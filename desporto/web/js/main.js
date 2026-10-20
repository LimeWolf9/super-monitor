// Ponto de entrada: lê o URL, carrega os dados e liga as peças.
import { construirCenas, precarregarLogos } from './scenes.js';
import { createScheduler } from './scheduler.js';
import { tickClock, aplicarCorMinhaEquipa } from './header.js';
import { iniciarAjuste } from './preview.js';
import { tickCountdowns } from './util.js';
import { iniciarControlo } from './controlo.js';
import { iniciarAtualizacao } from './atualizacao.js';

const SEGUNDOS_POR_CENA = 10;
const REFRESCAR_DADOS_MS = 60_000;
const params = new URLSearchParams(location.search);
// ?cat=ultima | aovivo | proxima (submenu do MonitorHub);
// sem parâmetro: a Última jornada e depois a Próxima jornada (ver scenes.js)
const CATEGORIA = params.get('cat') || null;

let dados = null;

// Dados reais em live.json (gravado pelos tools/atualizar_*.py); se ainda não existir, usa o mock.
// ?mock=1 força os dados fictícios.
const FICHEIROS = params.get('mock') === '1' ? ['mock.json'] : ['live.json', 'mock.json'];

async function carregarDados() {
  let resp;
  for (const f of FICHEIROS) {
    resp = await fetch(`/data/${f}`, { cache: 'no-store' });
    if (resp.ok) break;
  }
  if (!resp.ok) throw new Error(`dados: HTTP ${resp.status}`);
  dados = await resp.json();
  aplicarCorMinhaEquipa(dados);
}

// Canto de baixo, à esquerda: em que desporto estamos e em que ecrã dele ("Futebol 3/24")
const NOMES_SECOES = { football: 'Futebol', f1: 'Fórmula 1', nba: 'NBA', player: 'Destaque', fun: 'Curiosidades', live: 'Ao vivo' };
let scheduler = null;
function mostrarSecao(cena) {
  const el = document.getElementById('secao');
  if (!el || !scheduler) return;
  const mesmas = scheduler.cenas.filter((c) => c.sport === cena.sport);
  const pos = mesmas.indexOf(cena) + 1;
  el.textContent = `${NOMES_SECOES[cena.sport] || ''}${mesmas.length > 1 && pos ? ` ${pos}/${mesmas.length}` : ''}`;
}

async function arrancar() {
  iniciarAjuste();
  await carregarDados();
  precarregarLogos(dados);

  let controlo = null, dadosUI = null;
  scheduler = createScheduler({
    host: document.getElementById('scene-host'),
    bar: document.getElementById('progress-bar'),
    scenes: construirCenas(dados, CATEGORIA),
    getData: () => dados,
    seconds: SEGUNDOS_POR_CENA,
    fixedId: params.get('scene'),
    aoMudar: (el, cena) => {
      if (controlo) controlo.aoMudarCena(el);
      mostrarSecao(cena);
      if (dadosUI) dadosUI.aoMudarCena(cena.parte);
    },
  });
  // Recarregar depois de uma atualização pedida no menu "Atualizar dados" (atualizacao.js)
  const recarregar = async () => {
    try { await carregarDados(); scheduler.setScenes(construirCenas(dados, CATEGORIA)); scheduler.refresh(); if (controlo) controlo.anunciar(); }
    catch (e) { console.warn('Falha a recarregar dados:', e); }
  };
  dadosUI = iniciarAtualizacao({ getData: () => dados, recarregar });
  // Comando do telemóvel (dentro do MonitorHub) e teclado: ver controlo.js
  controlo = iniciarControlo({ scheduler, getData: () => dados, dados: dadosUI });
  scheduler.start();

  // Todos os segundos: relógio e contagens decrescentes.
  tickClock();
  setInterval(() => { tickClock(); tickCountdowns(); }, 1000);

  // Periodicamente volta a ler os dados. Se a rede falhar, mantém os antigos.
  setInterval(async () => {
    try { await carregarDados(); scheduler.setScenes(construirCenas(dados, CATEGORIA)); scheduler.refresh(); if (controlo) controlo.anunciar(); }
    catch (e) { console.warn('Falha a atualizar dados:', e); }
  }, REFRESCAR_DADOS_MS);
}

arrancar().catch((e) => {
  document.getElementById('scene-host').innerHTML = `<div class="scene"><h1 class="scene-title"><span>Erro</span><small>${e.message}</small></h1></div>`;
  console.error(e);
});
