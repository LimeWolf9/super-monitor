// Comando: o dashboard obedece ao telemóvel através do MonitorHub (mensagens postMessage, ver o
// PROTOCOLO.md do hub) e também ao teclado (setas, Enter, Esc, Espaço), que ajuda a testar.
//   esquerda / direita  cena anterior / seguinte (a contagem dos segundos recomeça)
//   pausa               fica nesta cena (⏸ no topo); outra vez retoma
//   cima / baixo        muda a notícia com foco (cenas *-proximos); com uma notícia aberta, desliza o texto
//   ok                  com uma notícia em foco (depois de cima/baixo): abre-a por cima da cena (a rotação pausa);
//                       sem notícia em foco não faz nada
//   voltar              fecha a notícia; sem nada aberto, diz ao hub para voltar ao menu
//   atualizar           (botão do hub, ou tecla U) atualiza logo os dados, sem passar pelo menu
//   ir_futebol, ir_f1, ir_nba   (botões do hub, ou teclas 1, 2, 3) salta para o primeiro ecrã desse desporto na
//                       categoria aberta; só se anunciam os desportos que têm ecrãs nela (ver acoes())
import { esc } from './util.js';

// "atualizar": botão próprio no comando do hub (começa logo a atualização, sem menu)
const ACOES = ['esquerda', 'direita', 'cima', 'baixo', 'ok', 'voltar', 'pausa', 'atualizar'];
// Saltos de desporto: ação -> "sport" das cenas
const SALTOS = { ir_futebol: 'football', ir_f1: 'f1', ir_nba: 'nba' };
const TECLAS = {
  ArrowLeft: 'esquerda', ArrowRight: 'direita', ArrowUp: 'cima', ArrowDown: 'baixo',
  Enter: 'ok', Escape: 'voltar', Backspace: 'voltar', ' ': 'pausa', u: 'atualizar', U: 'atualizar',
  1: 'ir_futebol', 2: 'ir_f1', 3: 'ir_nba',
};
const DESLIZAR_PX = 420;   // quanto desce o texto da notícia aberta por cada "baixo"

const emHub = window.parent !== window;   // só fala com o hub quando está dentro do iframe dele
const hub = (m) => { if (emHub) window.parent.postMessage({ monitorhub: 1, ...m }, '*'); };

export function iniciarControlo({ scheduler, getData, dados }) {
  const caixa = document.getElementById('noticia');
  let foco = -1;              // notícia com foco na cena atual (-1 = nenhuma marcada ainda)
  let aberta = false;
  let pausadoAntes = false;   // estado da pausa antes de abrir a notícia, para o repor ao fechar

  const noticias = () => [...(scheduler.cenaAtual?.querySelectorAll('.nt') || [])];

  function marcar() {
    noticias().forEach((el, i) => el.classList.toggle('foco', i === foco));
  }

  function moverFoco(delta) {
    const lista = noticias();
    if (!lista.length) return;
    foco = foco < 0 ? 0 : Math.max(0, Math.min(lista.length - 1, foco + delta));
    marcar();
  }

  function abrir() {
    const lista = noticias();
    if (!lista.length) return;
    const el = lista[Math.max(0, foco)];
    const n = ((getData().news || {})[el.dataset.liga] || [])[+el.dataset.i];
    if (!n) return;
    foco = Math.max(0, foco); marcar();
    const texto = (n.text && n.text.length ? n.text : [n.summary || '']).map((p) => `<p>${esc(p)}</p>`).join('');
    caixa.innerHTML = `<article class="nt-aberta">
      ${n.img ? `<img src="${esc(n.img)}" alt="" onerror="this.remove()">` : ''}
      <h2>${esc(n.title)}</h2>
      <div class="nt-corpo">${texto}</div>
      <footer>${esc(n.source)}${n.url ? ` · ${esc(n.url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0])}` : ''}</footer>
    </article>`;
    caixa.hidden = false;
    aberta = true;
    pausadoAntes = scheduler.pausado;
    scheduler.pausar(true);
  }

  function fechar() {
    caixa.hidden = true;
    caixa.innerHTML = '';
    aberta = false;
    scheduler.pausar(pausadoAntes);
  }

  function alternarPausa() {
    const sim = !scheduler.pausado;
    scheduler.pausar(sim);
    if (aberta) pausadoAntes = sim;
    document.body.classList.toggle('pausado', sim);
    hub({ tipo: 'aviso', texto: sim ? '⏸ Em pausa' : '▶ A rodar' });
  }

  function comando(acao) {
    if (acao === 'atualizar') {
      if (dados.aCorrer) hub({ tipo: 'aviso', texto: 'Já está a atualizar' });
      else dados.atualizar();
      return;
    }
    if (SALTOS[acao]) {
      if (aberta) fechar();
      if (!scheduler.saltar((c) => c.sport === SALTOS[acao])) hub({ tipo: 'aviso', texto: 'Sem ecrãs desse desporto aqui' });
      return;
    }
    switch (acao) {
      case 'esquerda': case 'direita':
        if (aberta) fechar();
        scheduler.mudar(acao === 'direita' ? 1 : -1);
        break;
      case 'cima': case 'baixo': {
        const corpo = aberta && caixa.querySelector('.nt-corpo');
        if (corpo) corpo.scrollBy({ top: acao === 'baixo' ? DESLIZAR_PX : -DESLIZAR_PX, behavior: 'smooth' });
        else moverFoco(acao === 'baixo' ? 1 : -1);
        break;
      }
      case 'ok':
        if (aberta) break;
        if (foco >= 0 && noticias().length) abrir();
        break;
      case 'voltar':
        if (aberta) fechar();
        else hub({ tipo: 'nao_tratado', acao: 'voltar' });
        break;
      case 'pausa': alternarPausa(); break;
      default: hub({ tipo: 'nao_tratado', acao });
    }
  }

  // Cada cena nova começa sem foco marcado (o primeiro cima/baixo marca a 1.ª notícia)
  const aoMudarCena = () => { foco = -1; };

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
  // As ações anunciadas ao hub: as de sempre e um salto por cada desporto que tenha ecrãs na categoria aberta.
  // Volta a anunciar-se quando a lista de cenas muda e os desportos mudam (ex.: a NBA a começar).
  const acoes = () => ACOES.concat(Object.keys(SALTOS).filter((a) => scheduler.cenas.some((c) => c.sport === SALTOS[a])));
  let anunciadas = '';
  function anunciar() {
    const lista = acoes();
    if (lista.join() === anunciadas) return;
    anunciadas = lista.join();
    hub({ tipo: 'pronto', acoes: lista });
  }
  anunciar();

  return { aoMudarCena, anunciar };
}
