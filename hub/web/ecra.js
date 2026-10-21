// Ecrã da parede: mostra o que o hub manda (Início, código, loading, app, desligado). Não tem menu: as apps
// escolhem-se no comando do telemóvel.
// e passa as ordens do comando à app aberta. O protocolo está em PROTOCOLO.md.

const corpo = document.body;
const iframe = document.getElementById("app");
const inicio = document.getElementById("inicio");
let estado = { modo: "inicio", apps: [] };
let urlAtual = null;
let appFala = false;          // a app aberta disse "pronto" (usa o protocolo do comando)?
let acoesDaApp = [];

const NOMES = { cima: "▲", baixo: "▼", esquerda: "◀", direita: "▶", ok: "OK", pausa: "⏯ Pausa", voltar: "↩ Voltar" };

// ---------------------------------------------------------------- desenhar o estado
function desenhar() {
  corpo.dataset.modo = estado.modo;

  const app = (estado.atalhos || estado.apps).find(a => a.id === estado.ativa);
  document.getElementById("carregar-icone").textContent = app?.icone || "";
  document.getElementById("carregar-nome").textContent = app?.nome || "";
  document.getElementById("carregar-msg").textContent = estado.mensagem || "";
  document.getElementById("erro-msg").textContent = estado.mensagem || "";
  document.getElementById("pin-nome").textContent = app ? `${app.icone || ""} ${app.nome}` : "";
  document.getElementById("pin-msg").textContent = estado.modo === "pin" ? (estado.mensagem || "") : "";
  const pontos = document.getElementById("pin-pontos");
  pontos.replaceChildren(...Array.from({ length: estado.pin_tamanho || 0 }, (_, i) => {
    const el = document.createElement("i");
    if (i < estado.pin_marcados) el.className = "cheio";
    return el;
  }));

  // Só mexe no iframe quando a app muda: recarregar a cada evento reiniciava a app
  const url = estado.modo === "app" ? estado.url : null;
  if (url !== urlAtual) {
    urlAtual = url;
    appFala = false;
    acoesDaApp = [];
    iframe.src = url || "about:blank";
  }
}

// ---------------------------------------------------------------- avisos
let tAviso;
function aviso(texto) {
  const el = document.getElementById("aviso");
  el.textContent = texto;
  el.classList.add("ver");
  clearTimeout(tAviso);
  tAviso = setTimeout(() => el.classList.remove("ver"), 1600);
}

// ---------------------------------------------------------------- comando -> app
function enviarComando(acao) {
  return fetch("/api/comando", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ acao }) });
}

function ordemParaApp(acao) {
  if (appFala && (acoesDaApp.length === 0 || acoesDaApp.includes(acao))) {
    iframe.contentWindow.postMessage({ monitorhub: 1, tipo: "comando", acao }, "*");
    return;
  }
  // A app não percebe esta ordem: "voltar" leva ao Início, o resto só avisa
  if (acao === "voltar") enviarComando("sair");
  else aviso(appFala ? `Esta app não usa ${NOMES[acao] || acao}` : "Esta app ainda não usa o comando");
}

window.addEventListener("message", (e) => {
  const m = e.data;
  if (!m || m.monitorhub !== 1 || e.source !== iframe.contentWindow) return;
  if (m.tipo === "pronto") {
    appFala = true;
    acoesDaApp = Array.isArray(m.acoes) ? m.acoes : [];
    // O hub passa isto ao comando, que mostra botões extra (ex.: Atualizar) só nesta app
    fetch("/api/comando", { method: "POST", headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ acao: "app_acoes", valor: acoesDaApp }) });
  } else if (m.tipo === "nao_tratado" && m.acao === "voltar") {
    enviarComando("sair");          // a app já está no "início" dela: voltar sai para o Início do hub
  } else if (m.tipo === "aviso" && m.texto) {
    aviso(String(m.texto));
  }
});

// ---------------------------------------------------------------- ligação ao hub
function ligar() {
  const fonte = new EventSource("/api/eventos");
  fonte.onopen = () => corpo.classList.remove("offline");
  fonte.onerror = () => corpo.classList.add("offline");     // o EventSource volta a ligar sozinho
  fonte.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.tipo === "estado") { estado = ev; desenhar(); }
    else if (ev.tipo === "comando" && estado.modo === "app") ordemParaApp(ev.acao);
    else if (ev.tipo === "comando" && estado.modo === "inicio") inicio.contentWindow.postMessage({ monitorhub: 1, tipo: "comando", acao: ev.acao }, "*");
    else if (ev.tipo === "aviso" && ev.texto) aviso(ev.texto);
    else if (ev.tipo === "pin_errado") {
      const p = document.getElementById("pin-pontos");
      p.classList.remove("errado"); void p.offsetWidth; p.classList.add("errado");
    }
  };
}
ligar();

// ---------------------------------------------------------------- teclado (para testar no PC sem telemóvel)
const TECLAS = {
  ArrowUp: "cima", ArrowDown: "baixo", ArrowLeft: "esquerda", ArrowRight: "direita",
  Enter: "ok", Escape: "voltar", Backspace: "voltar", " ": "pausa", m: "menu", e: "energia",
};
document.addEventListener("keydown", (e) => {
  if (estado.modo === "pin" && /^[0-9]$/.test(e.key)) {
    fetch("/api/comando", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ acao: "digito", valor: e.key }) });
    return;
  }
  const acao = TECLAS[e.key];
  if (acao) { e.preventDefault(); enviarComando(acao); }
});
// Depois de abrir uma app, o foco do teclado fica no ecrã do hub e não dentro do iframe
iframe.addEventListener("load", () => window.focus());
