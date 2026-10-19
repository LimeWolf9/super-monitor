// Fundos ilustrados (SVG) para o layout Liquid Glass.
// Cada cena leva: (1) um fade de cor vertical (a cor da competição) e
// (2) um desenho da modalidade em traço fino (campo de futebol, linhas de velocidade, campo de basquetebol).
// As cores vêm do CSS da cena (--accent e --tint), por isso mudam com a competição.

const TINT = 'var(--tint, color-mix(in srgb, var(--accent) 40%, #05060a))';

// Fade vertical na cor da competição: forte no topo, a desaparecer por volta dos 75% do ecrã.
const FADE = `
  <defs>
    <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0"    style="stop-color:color-mix(in srgb, ${TINT} 82%, var(--accent))"/>
      <stop offset=".35"  style="stop-color:${TINT};stop-opacity:.85"/>
      <stop offset=".75"  style="stop-color:${TINT};stop-opacity:0"/>
    </linearGradient>
  </defs>
  <rect width="1080" height="2560" fill="url(#fade)"/>`;

const CAMPO = `
  <g fill="none" stroke="#fff" stroke-opacity=".17" stroke-width="6">
    <rect x="90" y="330" width="900" height="1900" rx="6"/>
    <line x1="90" y1="1280" x2="990" y2="1280"/>
    <circle cx="540" cy="1280" r="170"/>
    <rect x="290" y="330" width="500" height="300"/><rect x="400" y="330" width="280" height="120"/>
    <path d="M 440 630 A 110 110 0 0 0 640 630"/>
    <rect x="290" y="1930" width="500" height="300"/><rect x="400" y="2110" width="280" height="120"/>
    <path d="M 440 1930 A 110 110 0 0 1 640 1930"/>
  </g>
  <circle cx="540" cy="1280" r="9" fill="#fff" fill-opacity=".22"/>`;

const F1 = `
  <g stroke="#fff" stroke-opacity=".13" stroke-width="10" stroke-linecap="round">
    <line x1="-60" y1="420" x2="520" y2="150"/><line x1="200" y1="640" x2="900" y2="320"/>
    <line x1="-100" y1="900" x2="380" y2="690"/><line x1="480" y1="980" x2="1140" y2="700"/>
    <line x1="60" y1="1300" x2="700" y2="1020"/><line x1="620" y1="1500" x2="1160" y2="1280"/>
    <line x1="-80" y1="1720" x2="420" y2="1500"/><line x1="300" y1="1900" x2="960" y2="1620"/>
  </g>`;

const BASQUETE = `
  <g fill="none" stroke="#fff" stroke-opacity=".17" stroke-width="6">
    <rect x="90" y="330" width="900" height="1900" rx="6"/>
    <line x1="90" y1="1280" x2="990" y2="1280"/><circle cx="540" cy="1280" r="150"/>
    <rect x="390" y="330" width="300" height="440"/><circle cx="540" cy="770" r="130"/>
    <path d="M 170 330 L 170 660 A 470 470 0 0 0 910 660 L 910 330"/>
    <circle cx="540" cy="420" r="28"/><line x1="490" y1="380" x2="590" y2="380"/>
    <rect x="390" y="1790" width="300" height="440"/><circle cx="540" cy="1790" r="130"/>
    <path d="M 170 2230 L 170 1900 A 470 470 0 0 1 910 1900 L 910 2230"/>
    <circle cx="540" cy="2140" r="28"/><line x1="490" y1="2180" x2="590" y2="2180"/>
  </g>`;

const ANEIS = `
  <g fill="none" stroke="#fff" stroke-opacity=".12" stroke-width="5">
    <circle cx="920" cy="420" r="200"/><circle cx="920" cy="420" r="330"/><circle cx="920" cy="420" r="470"/>
    <circle cx="160" cy="2100" r="200"/><circle cx="160" cy="2100" r="330"/><circle cx="160" cy="2100" r="470"/>
  </g>`;

const MOTIVOS = { football: CAMPO, f1: F1, nba: BASQUETE };

export function fundo(sport) {
  return `<svg class="bg" viewBox="0 0 1080 2560" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <rect width="1080" height="2560" fill="#05060a"/>${FADE}${MOTIVOS[sport] || ANEIS}</svg>`;
}
