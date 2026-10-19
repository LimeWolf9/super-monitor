// Barra de topo ao estilo do iPhone: hora e data à esquerda, saudação ao centro.

const capitalizar = (s) => s.charAt(0).toUpperCase() + s.slice(1);
let nome = '';

function saudacao(hora) {
  const t = hora >= 6 && hora < 12 ? 'Bom dia' : hora >= 12 && hora < 20 ? 'Boa tarde' : 'Boa noite';
  return nome ? `${t}, ${nome}` : t;
}

export function tickClock() {
  const agora = new Date();
  const hh = String(agora.getHours()).padStart(2, '0');
  const mm = String(agora.getMinutes()).padStart(2, '0');
  // Os ":" piscam a cada segundo (span próprio para poder animar só eles).
  document.getElementById('clock').innerHTML = `${hh}<span class="colon">:</span>${mm}`;
  const dia = capitalizar(agora.toLocaleDateString('pt-PT', { weekday: 'short' }).replace('.', '').slice(0, 3));
  const dd = String(agora.getDate()).padStart(2, '0');
  const mes = String(agora.getMonth() + 1).padStart(2, '0');
  document.getElementById('date').textContent = `${dia} ${dd}/${mes}`;
  document.getElementById('greeting').textContent = saudacao(agora.getHours());
}

// Dados que vêm do mock.json: nome do utilizador e cor de destaque da minha equipa (usada nas tabelas e jogos).
export function aplicarCorMinhaEquipa(D) {
  nome = D.utilizador || '';
  document.documentElement.style.setProperty('--me', D.teams[D.myTeam.code].c1);
}
