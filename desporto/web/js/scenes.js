// Monta a rotação. Cada cena é um objeto { id, sport, league, parte, so, tem(D), render(D, ctx) } que devolve HTML;
// as cenas vivem em cenas/ (uma pasta por modalidade). Não têm cores nem tamanhos: isso vive no CSS.
import { cenasFutebol } from './cenas/futebol.js';
import { CENAS_F1 } from './cenas/f1.js';
import { CENAS_NBA } from './cenas/nba.js';
import { CENAS_OUTRAS } from './cenas/outras.js';

export { precarregarLogos } from './cenas/base.js';

// parte = chave em "_atualizado" (live.json) que diz que os dados vieram de uma fonte real;
// tem(D) = há dados para mostrar. Uma cena sem dados reais sai da rotação.
// Com dados reais (live.json, que tem "_atualizado"), uma cena só entra se a sua parte veio de uma fonte real
// e tem dados; assim nunca se mistura o mock com dados reais. Com o mock.json entra tudo.
//
// cat (parâmetro ?cat= do URL, usado pelo submenu do MonitorHub):
//   todos (ou sem parâmetro) - futebol (sem as ligas novas), F1, NBA, jogador, curiosidades
//   futebol - só futebol, com a Bundesliga, a Ligue 1 e a Serie A (só aqui, para a volta de "todos" não crescer)
//   f1      - só as cenas da F1
//   nba     - o ecrã "Em construção"
const CATEGORIAS = {
  todos: (c) => !c.so,
  futebol: (c) => c.sport === 'football',
  f1: (c) => c.sport === 'f1',
  nba: (c) => c.id === 'nba-construcao',
};

export function construirCenas(D, cat = 'todos') {
  const reais = D._atualizado;
  const naCategoria = CATEGORIAS[cat] || CATEGORIAS.todos;
  const disponivel = (c) => naCategoria(c) && (!reais || reais[c.parte]) && (!c.tem || c.tem(D));
  const [construcao, ...nba] = CENAS_NBA;
  return [...cenasFutebol(D, cat), construcao, ...CENAS_F1, ...nba, ...CENAS_OUTRAS].filter(disponivel);
}
