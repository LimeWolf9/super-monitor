// Trata da rotação das cenas, das transições e da barra de progresso.
// Também obedece ao comando (ver controlo.js): cena anterior/seguinte e pausa.
import { tickCountdowns } from './util.js';
import { fundo } from './backgrounds.js';

export function createScheduler({ host, bar, scenes, getData, seconds, fixedId, aoMudar = () => {} }) {
  let index = -1;
  let pass = 0;          // voltas completas ao ciclo (usado na cena "fun")
  let atual = null;      // elemento da cena visível
  let timer = null;
  let pausado = false;

  const fixa = fixedId ? scenes.find((s) => s.id === fixedId) : null;
  if (fixedId && !fixa) console.warn(`Cena "${fixedId}" não existe. Ids válidos:`, scenes.map((s) => s.id).join(', '));

  function montar(cena, animar) {
    const el = document.createElement('div');
    el.className = `scene scene-${cena.id} sport-${cena.sport}` + (cena.league ? ` league-${cena.league}` : '') + (animar ? ' enter' : '');
    el.innerHTML = fundo(cena.sport) + cena.render(getData(), { pass });
    host.appendChild(el);
    if (animar) {
      el.getBoundingClientRect();        // força o browser a "ver" o estado inicial
      el.classList.remove('enter');      // ...e só depois anima para o estado final
    }
    if (atual) {
      const velha = atual;
      velha.classList.add('leave');
      setTimeout(() => velha.remove(), 900);
    }
    atual = el;
    tickCountdowns();
    aoMudar(el, cena);
  }

  function reiniciarBarra() {
    bar.style.animation = 'none';
    bar.getBoundingClientRect();
    bar.style.animation = pausado ? 'none' : `progress ${seconds}s linear forwards`;
  }

  // Agenda a cena seguinte daqui a "seconds" (a contagem recomeça sempre que se muda de cena à mão)
  function agendar() {
    clearTimeout(timer);
    if (!pausado && !fixa) timer = setTimeout(() => ir(1), seconds * 1000);
    reiniciarBarra();
  }

  function ir(delta) {
    if (!scenes.length) { timer = setTimeout(() => ir(1), seconds * 1000); return; }   // sem cenas: espera por dados
    const antes = index;
    index = ((index + delta) % scenes.length + scenes.length) % scenes.length;
    // Uma só cena (ex.: ?cat=nba): não a volta a desenhar a cada volta, só reagenda
    if (scenes.length === 1 && atual && antes === index) { agendar(); return; }
    if (delta > 0 && index < antes && atual) pass++;
    montar(scenes[index], true);
    agendar();
  }

  return {
    start() {
      if (fixa) {
        document.body.classList.add('fixed');
        montar(fixa, false);
      } else {
        ir(1);
      }
    },
    // Comando: cena anterior (-1) ou seguinte (+1). Com uma cena fixa (?scene=) não faz nada.
    mudar(delta) {
      if (!fixa) ir(delta);
    },
    // Comando: pausa (fica nesta cena) ou retoma (a contagem dos segundos recomeça do zero)
    pausar(sim) {
      pausado = sim;
      agendar();
    },
    get pausado() { return pausado; },
    get cenaAtual() { return atual; },
    // Dados novos podem trazer ou tirar cenas (ex.: uma jornada com mais jogos, a NBA a começar).
    setScenes(novas) {
      scenes = novas;
      if (index >= scenes.length) index = -1;
    },
    // Chamado quando chegam dados novos: só redesenha se a cena estiver fixa.
    refresh() {
      if (!fixa) return;
      atual.remove(); atual = null;
      montar(fixa, false);
    },
  };
}
