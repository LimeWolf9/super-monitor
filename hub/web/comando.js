// Comando do telemóvel: cada botão manda uma ação ao hub; o estado chega por eventos.

const NOMES_MODO = { menu: "Menu", a_carregar: "A abrir…", erro: "Erro", desligado: "Ecrã desligado" };
let estado = null;

function enviar(corpo) {
  if (navigator.vibrate) navigator.vibrate(12);
  fetch("/api/comando", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) })
    .catch(() => {});
}

// Botões com data-acao. Manter carregado numa seta repete (para descer listas compridas).
document.querySelectorAll("button[data-acao]").forEach((b) => {
  const acao = b.dataset.acao;
  const repete = ["cima", "baixo", "esquerda", "direita"].includes(acao);
  let t1, t2;
  const parar = () => { clearTimeout(t1); clearInterval(t2); b.classList.remove("carregado"); };
  b.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    b.classList.add("carregado");
    enviar({ acao });
    if (repete) t1 = setTimeout(() => { t2 = setInterval(() => enviar({ acao }), 180); }, 450);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => b.addEventListener(ev, parar));
  b.addEventListener("contextmenu", (e) => e.preventDefault());
});

// Teclado do código: cada dígito vai direto ao hub (o telemóvel não sabe o código)
document.querySelectorAll("button[data-digito]").forEach((b) => {
  b.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    b.classList.add("carregado");
    enviar({ acao: "digito", valor: b.dataset.digito });
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => b.addEventListener(ev, () => b.classList.remove("carregado")));
});

function desenhar() {
  const app = (estado.atalhos || estado.apps).find((a) => a.id === estado.ativa);
  let texto = NOMES_MODO[estado.modo] || "";
  if (estado.modo === "app" && app) texto = `${app.icone || ""} ${app.nome}`;
  if (estado.modo === "a_carregar" && app) texto = `A abrir ${app.nome}…`;
  document.body.classList.toggle("desligado", estado.modo === "desligado");
  document.body.classList.toggle("pin", estado.modo === "pin");
  document.body.classList.toggle("pode-atualizar", (estado.acoes_app || []).includes("atualizar"));
  if (estado.modo === "pin") {
    texto = `🔒 ${app ? app.nome : ""}`;
    document.getElementById("pin-titulo").textContent = estado.mensagem
      || `Código: ${"●".repeat(estado.pin_marcados)}${"○".repeat(Math.max(0, estado.pin_tamanho - estado.pin_marcados))}`;
  }
  document.getElementById("estado").textContent = texto;

  const caixa = document.getElementById("apps");
  caixa.replaceChildren(...(estado.atalhos || estado.apps).map((a) => {
    const b = document.createElement("button");
    b.innerHTML = `<span class="ic"></span><span class="n"></span>`;
    b.querySelector(".ic").textContent = a.icone || "▪";
    b.querySelector(".n").textContent = a.em_breve ? `${a.nome} (${(a.etiqueta || "em breve").toLowerCase()})` : a.nome;
    b.disabled = !!a.em_breve;
    b.classList.toggle("ativa", a.id === estado.ativa);
    b.addEventListener("click", () => enviar({ acao: "abrir", app: a.id }));
    return b;
  }));
}

// ---------------------------------------------------------------- atualizar dados sem abrir a app
function haQuanto(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (!(min >= 0)) return "";
  if (min < 1) return "agora mesmo";
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  return h < 48 ? `há ${h} h` : `há ${Math.round(h / 24)} dias`;
}
function desenharDados() {
  const lista = estado.atualizacoes || [];
  document.getElementById("dados-bloco").classList.toggle("vazio", lista.length === 0);
  document.getElementById("dados").replaceChildren(...lista.map((u) => {
    const el = document.createElement("div");
    el.className = "dado";
    el.innerHTML = `<span class="ic"></span><div class="txt"><div class="n"></div><div class="s"></div></div><button>⟳ Atualizar</button>`;
    el.querySelector(".ic").textContent = u.icone || "▪";
    el.querySelector(".n").textContent = u.nome;
    const s = el.querySelector(".s");
    const b = el.querySelector("button");
    if (u.estado === "a_correr") {
      s.textContent = `${u.passo || "A atualizar…"}${u.total ? ` · ${u.feitos || 0}/${u.total}` : ""}`
        + (u.estimativa_s ? ` · faltam ~${Math.max(1, Math.round((u.estimativa_s - (u.decorrido_s || 0)) / 60))} min` : "");
      const barra = document.createElement("div");
      barra.className = "barra";
      barra.innerHTML = `<i style="width:${u.total ? Math.round(100 * (u.feitos || 0) / u.total) : 10}%"></i>`;
      el.querySelector(".txt").append(barra);
      b.disabled = true;
      b.textContent = "A atualizar";
    } else if (u.estado === "falhou") {
      s.textContent = `Falhou ${u.terminado_em ? haQuanto(u.terminado_em) : ""}${u.erro ? ": " + u.erro : ""}`;
      s.classList.add("falhou");
    } else {
      s.textContent = u.terminado_em ? `Atualizado ${haQuanto(u.terminado_em)}` : "Ainda sem atualizações";
    }
    b.addEventListener("click", () => enviar({ acao: "atualizar", app: u.id }));
    return el;
  }));
}
setInterval(() => estado && desenharDados(), 60000);

const fonte = new EventSource("/api/eventos");
fonte.onopen = () => document.body.classList.remove("offline");
fonte.onerror = () => {
  document.body.classList.add("offline");
  document.getElementById("estado").textContent = "Sem ligação ao hub…";
};
fonte.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  if (ev.tipo === "estado") { estado = ev; desenhar(); desenharDados(); }
};
