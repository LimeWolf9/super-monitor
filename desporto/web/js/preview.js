// Ajusta o ecrã 1080x2560 à janela do browser.
//  - Modo normal (quiosque): ocupa a janela toda, na proporção certa.
//  - ?preview=1: mais pequeno, para sobrar espaço para a moldura de monitor (CSS em base.css).
const LARGURA = 1080, ALTURA = 2560;

export function ajustar() {
  const preview = document.documentElement.classList.contains('preview');
  const margemX = preview ? 120 : 0;
  const margemY = preview ? 210 : 0;   // moldura + pé do monitor
  const s = Math.min((innerWidth - margemX) / LARGURA, (innerHeight - margemY) / ALTURA);

  const scaler = document.getElementById('scaler');
  scaler.style.width = `${LARGURA * s}px`;
  scaler.style.height = `${ALTURA * s}px`;
  document.getElementById('stage').style.transform = `scale(${s})`;
  window.__scale = s;
}

export function iniciarAjuste() {
  ajustar();
  addEventListener('resize', ajustar);
}
