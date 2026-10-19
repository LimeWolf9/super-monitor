// Funções pequenas partilhadas por vários ficheiros.

// Momento em que a página arrancou. Serve de âncora para "inHours" nos dados fictícios.
export const T0 = Date.now();

// Protege o HTML: se um dia um nome vier da rede com "<" ou "&", não parte a página.
export function esc(valor) {
  return String(valor).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// Escolhe texto claro ou escuro consoante o fundo, para a sigla ser sempre legível.
function corLegivel(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#0b0e14' : '#ffffff';
}

// Símbolo da equipa: mostra o emblema (img/equipas/<sigla>.png). Se o ficheiro não existir,
// aparece o círculo com as cores da equipa + sigla (classe "fail", ver css). Serve para clubes, equipas de F1 e NBA;
// nos jogadores usa-se o símbolo da equipa dele.
// A maioria dos emblemas é PNG; estes vieram em SVG (ex.: Nottingham Forest, que a TheSportsDB não tem).
const EMBLEMAS_SVG = new Set(['NFO']);
export const urlEmblema = (code) => `img/equipas/${code}.${EMBLEMAS_SVG.has(code) ? 'svg' : 'png'}`;

export function badge(D, code, extra = '') {
  const t = D.teams[code] || { c1: '#444444', c2: '#999999' };
  return `<span class="badge crest ${extra}" style="--c1:${t.c1};--c2:${t.c2};--tx:${corLegivel(t.c1)}">` +
    `<img src="${esc(urlEmblema(code))}" alt="" onerror="this.parentNode.classList.add('fail');this.remove()">${esc(code)}</span>`;
}

// Equipas em destaque: a minha (myTeam.code, o FC Porto) e a minha seleção (myTeam.selecao, Portugal)
export function minha(D, code) {
  return code === D.myTeam.code || code === (D.myTeam.selecao || 'PRT');
}
export const temMinha = (D, m) => minha(D, m.home) || minha(D, m.away);

// "Agora" do dashboard: a hora do PC, ou ?hoje=2026-10-05T20:00 (para testar a rotação de outra semana)
const HOJE = new URLSearchParams(location.search).get('hoje');
export const agora = () => (HOJE ? Date.parse(HOJE) : Date.now());

export function teamName(D, code) {
  return (D.teams[code] && D.teams[code].name) || code;
}

// Instante (em ms) da próxima corrida: "date" se existir, senão "inHours" a contar do arranque.
export function targetMs(next) {
  return next.date ? Date.parse(next.date) : T0 + next.inHours * 3600e3;
}

// Atualiza todos os contadores decrescentes visíveis (elementos com data-target).
export function tickCountdowns() {
  document.querySelectorAll('[data-target]').forEach((el) => {
    let s = Math.max(0, Math.floor((Number(el.dataset.target) - Date.now()) / 1000));
    const parts = { d: Math.floor(s / 86400), h: Math.floor(s % 86400 / 3600), m: Math.floor(s % 3600 / 60), s: s % 60 };
    for (const [u, v] of Object.entries(parts)) {
      const alvo = el.querySelector(`[data-u="${u}"]`);
      if (alvo) alvo.textContent = String(v).padStart(2, '0');
    }
  });
}
