"""Testes da agenda da atualização automática (tools/agenda.py).

Correr (na pasta desporto):  python -m unittest discover -s tests
Usam ficheiros falsos numa pasta temporária: não tocam no data/ a sério. Só biblioteca standard.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import agenda        # noqa: E402
import competicoes   # noqa: E402


def local(*args):
    """Uma hora deste PC (com o fuso), como as que a agenda usa."""
    return datetime(*args).astimezone()


class TestAgenda(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.antes = {n: getattr(agenda, n) for n in ("LIVE", "CONFIG", "REGISTO", "MEMORIA")}
        self.competicoes_antes = competicoes.FICHEIRO
        for n in self.antes:
            setattr(agenda, n, self.pasta / f"{n.lower()}.json")
        competicoes.FICHEIRO = self.pasta / "competicoes.json"   # não existe: as competições por defeito (a Liga ligada)
        self.gravar("CONFIG", {"ligada": True, "ligada_em": local(2026, 10, 21, 8, 0).isoformat()})
        # Um jogo da Liga às 20:00, ainda sem resultado nos dados
        self.gravar("LIVE", {"football": {"pt": {"name": "Liga Portugal", "results": [
            {"iso": local(2026, 10, 21, 20, 0).isoformat(), "home": "FCP", "away": "SLB"}]}}})
        self.gravar("REGISTO", [])

    def tearDown(self):
        for n, v in self.antes.items():
            setattr(agenda, n, v)
        competicoes.FICHEIRO = self.competicoes_antes

    def gravar(self, nome, dados):
        getattr(agenda, nome).write_text(json.dumps(dados), encoding="utf-8")

    def na_hora(self, agora):
        return [t for t in agenda.proximas(agora)["tarefas"] if t["na_hora"]]

    def test_jogo_atualiza_2h05_depois_do_inicio(self):
        self.assertNotIn("futebol:pt", [t["chave"] for t in self.na_hora(local(2026, 10, 21, 22, 0))])
        self.assertIn("futebol:pt", [t["chave"] for t in self.na_hora(local(2026, 10, 21, 22, 10))])

    def test_jogo_desiste_depois_de_4_tentativas(self):
        self.gravar("REGISTO", [{"em": (local(2026, 10, 21, 22, 5) + timedelta(minutes=20 * i)).isoformat(), "id": f"futebol:pt#{i}",
                                 "chave": "futebol:pt", "resultado": "ok"} for i in range(4)])
        self.assertNotIn("futebol:pt", [t["chave"] for t in self.na_hora(local(2026, 10, 21, 23, 50))])

    def test_de_noite_nao_corre_nada(self):
        self.assertEqual(self.na_hora(local(2026, 10, 22, 3, 0)), [])

    def test_desligada_nao_corre_nada(self):
        self.gravar("CONFIG", {"ligada": False})
        self.assertEqual(self.na_hora(local(2026, 10, 21, 22, 10)), [])


if __name__ == "__main__":
    unittest.main()
