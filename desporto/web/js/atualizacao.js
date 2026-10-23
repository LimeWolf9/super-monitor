// Atualizar os dados a pedido (o serve.py já não atualiza sozinho, ver README):
//  - canto: "Dados de hoje 09:12", com a hora da parte do ecrã atual (F1, futebol...); nas cenas de uma competição
//    a hora dela ("futebol:pt" em _atualizado), que pode ter sido atualizada sozinha (atualizar_tudo.py --competicoes);
//  - atualizar: botão "Atualizar" do comando do hub (ação "atualizar") ou tecla U;
//  - barra em baixo durante a atualização: "A atualizar: Futebol (3/8) · 1:12 de ~3:00", e no fim
//    "Atualizado às 09:45" (ou que parte falhou); depois os dados recarregam sozinhos.
import { esc } from './util.js';

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const MOSTRAR_FIM_MS = 8000;

// "hoje 09:12" / "ontem 21:40" / "15 out 21:40"
export function quando(iso) {
  if (!iso) return 'nunca';
  const d = new Date(iso), hoje = new Date();
  const hm = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
  const dia = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dias = Math.round((dia(hoje) - dia(d)) / 86400e3);
  return dias === 0 ? `hoje ${hm}` : dias === 1 ? `ontem ${hm}` : `${d.getDate()} ${MESES[d.getMonth()]} ${hm}`;
}
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

export function iniciarAtualizacao({ getData, recarregar }) {
  const canto = document.getElementById('dados-hora');
  const barra = document.getElementById('atualizacao');
  let estado = null;        // último /api/atualizar/estado
  let tFim = null;
  let parteAtual = null;    // parte do ecrã visível (para o canto)
  let ligaAtual = null;     // e a competição dele (ex.: "pt"), se tiver

  // ----- canto: hora dos dados do ecrã atual
  function atualizarCanto() {
    const at = (getData() || {})._atualizado;
    if (!at) { canto.textContent = ''; return; }   // mock: não há horas
    const iso = (parteAtual && ligaAtual && at[`${parteAtual}:${ligaAtual}`]) || (parteAtual && at[parteAtual]) ||
      Object.values(at).sort().pop();
    canto.textContent = `Dados de ${quando(iso)}`;
  }

  async function comecar() {
    try {
      const r = await fetch('/api/atualizar', { method: 'POST' });
      estado = await r.json();
    } catch (e) {
      barra.hidden = false;
      barra.textContent = 'Não foi possível atualizar: o servidor não responde.';
      setTimeout(() => { barra.hidden = true; }, MOSTRAR_FIM_MS);
      return;
    }
    mostrarBarra();
    perguntar();
  }

  // ----- barra em baixo
  const progresso = (e) => Math.min(0.98, e.estimativa_s ? e.decorrido_s / e.estimativa_s : e.feitos / e.total);
  function textoBarra(e) {
    const atual = (e.passos || []).find((p) => p.estado === 'a_correr');
    const n = Math.min(e.feitos + 1, e.total);
    return `A atualizar: ${esc(atual ? atual.nome : '…')} (${n}/${e.total}) · ${mmss(e.decorrido_s)}` +
      (e.estimativa_s ? ` de ~${mmss(e.estimativa_s)}` : '');
  }
  function mostrarBarra() {
    const e = estado;
    if (!e) return;
    if (e.estado === 'a_correr') {
      barra.hidden = false;
      barra.innerHTML = `<i style="width:${progresso(e) * 100}%"></i><span>${textoBarra(e)}</span>`;
    }
  }
  function mostrarFim(e) {
    const falhas = (e.passos || []).filter((p) => p.estado === 'falhou').map((p) => p.nome);
    const hora = new Date(e.terminado_em || Date.now()).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
    barra.hidden = false;
    barra.classList.toggle('erro', falhas.length > 0);
    barra.innerHTML = `<i style="width:100%"></i><span>${falhas.length
      ? `Atualizado às ${hora}, exceto ${esc(falhas.join(', '))} (ficam os dados anteriores)`
      : `Atualizado às ${hora} (${mmss(e.decorrido_s)})`}</span>`;
    clearTimeout(tFim);
    tFim = setTimeout(() => { barra.hidden = true; barra.classList.remove('erro'); }, MOSTRAR_FIM_MS);
  }

  // ----- perguntar o estado ao servidor: a cada segundo enquanto atualiza, senão a cada 5 s
  let tPergunta = null;
  async function perguntar() {
    clearTimeout(tPergunta);
    const antes = estado;
    try {
      estado = await (await fetch('/api/atualizar/estado', { cache: 'no-store' })).json();
    } catch (e) {
      estado = null;   // sem servidor com a API (ex.: ficheiros estáticos): não há botão de atualizar
    }
    if (estado && estado.estado === 'a_correr') mostrarBarra();
    if (antes && antes.estado === 'a_correr' && estado && estado.estado !== 'a_correr') {   // acabou agora
      await recarregar();
      mostrarFim(estado);
      atualizarCanto();
    }
    tPergunta = setTimeout(perguntar, estado && estado.estado === 'a_correr' ? 1000 : 5000);   // 5 s: também apanha uma atualização feita pelo hub
  }
  perguntar();

  return {
    get aCorrer() { return !!(estado && estado.estado === 'a_correr'); },
    // Botão "Atualizar" do hub (ou tecla U): começa já, se não houver uma a correr; a barra mostra o progresso
    atualizar() { if (!(estado && estado.estado === 'a_correr')) comecar(); },
    aoMudarCena(parte, liga) { parteAtual = parte; ligaAtual = liga || null; atualizarCanto(); },
    atualizarCanto,
  };
}
