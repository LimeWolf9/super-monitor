// Ecrã da parede: mostra o que o hub manda (menu, loading, app, desligado)
// e passa as ordens do comando à app aberta. O protocolo está em PROTOCOLO.md.

const corpo = document.body;
const iframe = document.getElementById("app");
let estado = { modo: "menu", apps: [] };
let urlAtual = null;
let appFala = false;          // a app aberta disse "pronto" (usa o protocolo do comando)?
let acoesDaApp = [];

const NOMES = { cima: "▲", baixo: "▼", esquerda: "◀", direita: "▶", ok: "OK", pausa: "⏯ Pausa", voltar: "↩ Voltar" };

// ---------------------------------------------------------------- relógio do menu
function relogio() {
  const agora = new Date();
  document.getElementById("hora").textContent = agora.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  const data = agora.toLocaleDateString("pt-PT", { weekday: "long", day: "numeric", month: "long" });
  document.getElementById("data").textContent = data.charAt(0).toUpperCase() + data.slice(1);
}
relogio();
setInterval(relogio, 1000);

// ---------------------------------------------------------------- desenhar o estado
function desenhar() {
  corpo.dataset.modo = estado.modo;

  const lista = document.getElementById("lista");
  lista.replaceChildren(...estado.apps.map((a, i) => {
    const li = document.createElement("li");
    li.className = (i === estado.foco ? "foco " : "") + (a.em_breve ? "em-breve" : "");
    li.innerHTML = `<span class="icone"></span><div><div class="nome"></div><div class="desc"></div></div>`;
    li.querySelector(".icone").textContent = a.icone || "▪";
    li.querySelector(".nome").textContent = a.nome;
    li.querySelector(".desc").textContent = textoAtualizacao(a.id) || a.descricao || "";
    if (a.em_breve) {
      const et = document.createElement("span");
      et.className = "etiqueta";
      et.textContent = a.etiqueta || "Em breve";
      li.append(et);
    } else if (a.submenu) {
      const seta = document.createElement("span");
      seta.className = "seta";
      seta.textContent = "›";
      li.append(seta);
    }
    return li;
  }));
  document.getElementById("titulo-menu").textContent = estado.grupo
    ? `${estado.grupo.icone || ""} ${estado.grupo.nome}` : "O que queres ver?";
  corpo.classList.toggle("submenu", !!estado.grupo);
  document.getElementById("links").textContent = (estado.links_comando || []).join("  ·  ") || "abre /comando neste PC";

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

// ---------------------------------------------------------------- atualização dos dados (sem abrir a app)
function haQuanto(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (!(min >= 0)) return "";
  if (min < 1) return "agora mesmo";
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  return h < 48 ? `há ${h} h` : `há ${Math.round(h / 24)} dias`;
}
function textoAtualizacao(id) {
  const u = (estado.atualizacoes || []).find((x) => x.id === id);
  if (!u || !u.estado) return "";
  if (u.estado === "a_correr") {
    const n = u.total ? ` ${u.feitos || 0}/${u.total}` : "";
    return `⟳ A atualizar…${n}${u.passo ? " · " + u.passo : ""}`;
  }
  // erro do atualizacao.json: as fontes que falharam ("Falharam: RSS Marca, ESPN NBA"); cortado para caber na linha
  if (u.estado === "falhou") {
    const quando = u.terminado_em ? " · " + haQuanto(u.terminado_em) : "";
    const erro = u.erro && u.erro.length > 48 ? u.erro.slice(0, 47) + "…" : u.erro;
    return erro ? `⚠ ${erro}${quando}` : `⚠ A última atualização falhou${u.terminado_em ? " " + haQuanto(u.terminado_em) : ""}`;
  }
  return u.terminado_em ? `Atualizado ${haQuanto(u.terminado_em)}` : "";
}
setInterval(() => estado.modo === "menu" && desenhar(), 60000);   // o "há X min" envelhece

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
  // A app não percebe esta ordem: "voltar" leva ao menu, o resto só avisa
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
    enviarComando("sair");          // a app já está no "início": voltar sai para o menu de onde veio
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
