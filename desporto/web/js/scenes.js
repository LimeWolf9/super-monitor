// Monta a rotação. Cada cena é um objeto { id, sport, league, parte, tem(D), render(D, ctx) } que devolve HTML;
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
// cat (parâmetro ?cat= do URL, usado pelo submenu do MonitorHub). As três de agora, cada uma com todos os desportos:
//   ultima  - Última jornada: resultados, 11, classificações, grupos e marcadores do futebol; a última corrida e o
//             campeonato da F1; a noite e as classificações da NBA; o jogador em destaque e as curiosidades
//   aovivo  - Ao vivo: não usa cenas (é o aovivo.js, chamado pelo main.js)
//   proxima - Próxima jornada: os próximos jogos (com o que falta da jornada em curso) e o ranking Elo; o próximo
//             GP e o horário do fim de semana; a corrida ao MVP da NBA
//   sem parâmetro (Dashboard.bat), ou outro valor: a Última jornada e depois a Próxima jornada

// Fase de cada cena da F1, da NBA e das outras (as do futebol vêm de cenasFutebol)
const FASE = {
  f1: 'ultima', 'f1-duelos': 'ultima', 'f1-pontos': 'ultima', 'f1-ultima': 'ultima', 'f1-pneus': 'ultima',
  'f1-gp': 'proxima', 'f1-fds': 'proxima',
  nba: 'ultima', 'nba-noite': 'ultima', 'nba-premios': 'proxima', 'nba-construcao': 'proxima',
  jogador: 'ultima', fun: 'ultima',
};
export const CATEGORIAS_NOVAS = ['ultima', 'aovivo', 'proxima'];

export function construirCenas(D, cat) {
  const reais = D._atualizado;
  const disponivel = (c) => (!reais || reais[c.parte]) && (!c.tem || c.tem(D));
  const [construcao, ...nba] = CENAS_NBA;
  // O ecrã "NBA em construção" só entra enquanto a época regular não começou (sem classificação)
  const outras = [...CENAS_F1, construcao, ...nba, ...CENAS_OUTRAS]
    .filter((c) => c.id !== 'nba-construcao' || !(D.nba && D.nba.east));
  const daFase = (fase) => [...cenasFutebol(D, fase), ...outras.filter((c) => FASE[c.id] === fase)].filter(disponivel);
  if (cat === 'ultima' || cat === 'proxima') return daFase(cat);
  return [...daFase('ultima'), ...daFase('proxima')];
}
